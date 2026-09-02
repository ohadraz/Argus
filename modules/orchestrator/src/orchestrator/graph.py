from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, Protocol

from agent_codefix import propose_fix
from agent_communicator import post_update as _post_update
from agent_communicator import raise_page as _raise_page
from agent_investigator import Findings
from agent_investigator import investigate as _investigate
from agent_mitigation import Action, Outcome, Verdict, propose_action, take_action
from agent_mitigation.tools import fetch_recent_flag_changes, utc_now
from agent_postmortem import PostmortemDocument
from argus_core.config import get_settings
from argus_core.db import connect
from argus_core.events import (
    ActionTaken,
    AgentInvoked,
    FlagChangesRetrieved,
    Publisher,
    StatusChanged,
    VerdictReached,
    nobody,
    publish,
)
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus, status_after
from argus_core.models.reading import Reading

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both.
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing
from argus_core.timestamps import to_iso
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from orchestrator.postmortem import write_postmortem_for
from orchestrator.publishing import record_call, record_event
from orchestrator.repository import actions, hypotheses, incidents, postmortems


class Investigate(Protocol):
    def __call__(
        self,
        alert: Alert,
        incident_id: str,
        # Keyword-only, because the real `investigate` carries its retrieval
        # seams between these and `incident_id`. A protocol that allowed them
        # positionally would be describing a call nothing can make.
        *,
        already_read: Sequence[Reading] | None = None,
        already_refuted: Sequence[Attempt] | None = None,
        publisher: Publisher = nobody,
        recorder: Recorder = records_nothing,
    ) -> Findings: ...


class RecordHypothesis(Protocol):
    # Positional-only: the hypothesis is all this is called with, so any
    # single-argument callable is one, whatever it named its parameter.
    def __call__(self, hypothesis: Hypothesis, /) -> None: ...


class RecordOutcome(Protocol):
    def __call__(self, hypothesis_id: str, tested: bool, result: str) -> None: ...


class PostUpdate(Protocol):
    def __call__(self, incident_id: str, message: str) -> None: ...


class RaisePage(Protocol):
    def __call__(self, incident_id: str, message: str) -> None: ...


class FetchFlagChanges(Protocol):
    def __call__(self) -> list[FlagChange]: ...


class TakeAction(Protocol):
    # The action is positional, so any callable naming it whatever it likes is
    # one. The incident and the publisher are keyword-only and defaulted: they
    # are what the action narrates itself against, and a caller with neither
    # takes the same action and tells nobody about it.
    def __call__(
        self,
        action: Action,
        /,
        *,
        incident_id: str | None = None,
        publisher: Publisher = nobody,
    ) -> Outcome: ...


class RecordAction(Protocol):
    def __call__(
        self,
        incident_id: str,
        hypothesis_id: str,
        action_type: str,
        outcome: str,
        undo_descriptor: dict[str, Any],
    ) -> None: ...


class TransitionIncident(Protocol):
    def __call__(
        self,
        incident_id: str,
        to_status: IncidentStatus,
        actor: Actor,
        action: str,
        result: str | None = None,
        confidence: float | None = None,
    ) -> None: ...


class WritePostmortem(Protocol):
    # Positional-only: the incident is all this is called with, and the real
    # one carries a recorder behind it that a stand-in has no use for.
    def __call__(self, incident_id: str, /) -> PostmortemDocument: ...


class RecordPostmortem(Protocol):
    def __call__(self, incident_id: str, document: PostmortemDocument, /) -> None: ...


class RecordNote(Protocol):
    # The same narration a transition carries, minus the one thing that makes a
    # transition one. A node that has something to say and moved nothing says it
    # through here.
    def __call__(
        self,
        incident_id: str,
        actor: Actor,
        action: str,
        result: str | None = None,
        confidence: float | None = None,
    ) -> None: ...


def _record_hypothesis(hypothesis: Hypothesis) -> None:
    with connect() as conn:
        hypotheses.record(conn, hypothesis)


def _record_outcome(hypothesis_id: str, tested: bool, result: str) -> None:
    with connect() as conn:
        hypotheses.record_outcome(conn, hypothesis_id, tested=tested, result=result)


def _transition_incident(
    incident_id: str,
    to_status: IncidentStatus,
    actor: Actor,
    action: str,
    result: str | None = None,
    confidence: float | None = None,
) -> None:
    with connect() as conn:
        incidents.transition(
            conn, incident_id, to_status, actor=actor, action=action,
            result=result, confidence=confidence,
        )


def _record_note(
    incident_id: str,
    actor: Actor,
    action: str,
    result: str | None = None,
    confidence: float | None = None,
) -> None:
    with connect() as conn:
        incidents.record_note(
            conn, incident_id, actor=actor, action=action,
            result=result, confidence=confidence,
        )


def _record_action(
    incident_id: str,
    hypothesis_id: str,
    action_type: str,
    outcome: str,
    undo_descriptor: dict[str, Any],
) -> None:
    with connect() as conn:
        actions.record(
            conn,
            incident_id,
            hypothesis_id=hypothesis_id,
            action_type=action_type,
            outcome=outcome,
            undo_descriptor=undo_descriptor,
        )


def _record_postmortem(incident_id: str, document: PostmortemDocument) -> None:
    with connect() as conn:
        postmortems.record(conn, incident_id, document.model_dump(mode="json"))


class Narration(BaseModel):
    """What a node says it just did, on its way past.

    Three of these are the `timeline_event` columns a human reads the incident
    from. `detail` is what the published `StatusChanged` carries, which is not
    always the same sentence: the Investigator's event names what the
    investigation did, while Mitigation's names what came back from the action.
    Defaulting it to `action` keeps the ordinary case to one field.

    A node returns this alongside its work and never writes it anywhere. Nothing
    about narration is a node's to decide except the words.
    """

    action: str
    result: str | None = None
    confidence: float | None = None
    detail: str | None = None

    def published_detail(self) -> str:
        return self.detail if self.detail is not None else self.action


def with_status(
    node: Callable[[IncidentState], dict[str, Any]],
    actor: Actor,
    max_rounds: int,
    transition_incident: TransitionIncident = _transition_incident,
    record_note: RecordNote = _record_note,
    publisher: Publisher = nobody,
) -> Callable[..., dict[str, Any]]:
    """Wraps a node so that the status it implies is derived, written and
    published in one place (spec §7.1, §10).

    The return type is `Callable[...]` rather than the exact one-argument
    signature, because that is what LangGraph's `add_node` overloads accept -
    the same shape `functools.partial` produced when nodes were registered
    directly.

    Applied at registration time rather than called inside each node, because
    the guarantee wanted here - a status is written only when the incident
    enters it - is not one five nodes can be trusted to remember. They forgot it
    twice: a refuted action wrote `fixing` and was overwritten one node later,
    and an exhausted walk wrote `escalated` on its way into Code-Fix.

    The three inputs to a row come from three places that actually know them.
    The status comes from `status_after`, which is the state machine. The words
    come from the node, which is the only thing that knows what it just did. The
    actor comes from this call, because which agent a node belongs to is fixed
    when the graph is built and was being repeated inside every node as a
    constant.

    `narration` is popped rather than passed on. Left in the updates it would
    become a field of `IncidentState`, checkpointed with the incident forever,
    describing whichever node happened to run last.
    """
    def run(state: IncidentState) -> dict[str, Any]:
        updates = dict(node(state))
        narration = updates.pop("narration", None)
        next_status = status_after(state.model_copy(update=updates), max_rounds)

        if next_status == state.status:
            if narration is not None:
                record_note(
                    state.incident_id,
                    actor=actor,
                    action=narration.action,
                    result=narration.result,
                    confidence=narration.confidence,
                )

            return updates

        # A node that can move the incident has to say why: a transition with no
        # account of itself is a row a human cannot read the incident from.
        if narration is None:
            raise ValueError(
                f"node moved incident [{state.incident_id}] to [{next_status}] "
                f"without narrating it"
            )

        transition_incident(
            state.incident_id,
            next_status,
            actor=actor,
            action=narration.action,
            result=narration.result,
            confidence=narration.confidence,
        )
        publish(
            StatusChanged(
                incident_id=state.incident_id,
                to_status=next_status,
                detail=narration.published_detail(),
            ),
            publisher,
        )

        return {**updates, "status": next_status}

    return run


def mitigation_proposal_node(
    state: IncidentState,
    fetch_flag_changes: FetchFlagChanges = fetch_recent_flag_changes,
    publisher: Publisher = nobody,
) -> dict[str, Any]:
    """Chooses the reversible action that answers the hypothesis, and stops
    there (spec §7.3).

    Nothing here changes anything: it reads what the provider recorded as
    having changed and asks Mitigation which action follows, deterministically
    and without a model. Separating this from the node that acts is what leaves
    somewhere for the gate to stand - a gate the acting code could skip is not
    a gate.

    A provider that cannot be read proposes nothing rather than raising. "I
    could not find out what changed" and "nothing changed" lead to the same
    place - no action, and a human - and neither is a reason to fail the graph.
    """
    if state.hypothesis is None:
        return {"proposed_action": None}

    try:
        flag_changes = fetch_flag_changes()
    except Exception:
        # Deliberately unpublished. An empty history here would state that
        # nothing had changed, where what happened is that nobody could say -
        # and the two look identical on a page while meaning opposite things.
        return {"proposed_action": None}

    # The whole basis of the action about to be proposed: which flag moved,
    # which way, and when. Published from the node that reads it, because by
    # the time an action exists this history has already been reduced to a
    # single decision about a single flag.
    publish(
        FlagChangesRetrieved(incident_id=state.incident_id, changes=list(flag_changes)),
        publisher,
    )

    return {"proposed_action": propose_action(state.hypothesis, flag_changes)}


def tier_gate_node(
    state: IncidentState,
    record_outcome: RecordOutcome = _record_outcome,
) -> dict[str, Any]:
    """Refuses to let a reversible action reach its call without a way back
    (spec §13).

    The one check, and the reason it lives here rather than inside the agent
    that performs the write: a guarantee enforced by the code it constrains is
    a convention, not a guarantee. An action with no undo descriptor is not
    reversible however it is labelled, and an incident with no action at all
    has nothing for this stage to admit.

    A rejection is recorded and the walk moves on, rather than ending the
    incident. The gate is judging *this* action, and the explanations after it
    on the list may be perfectly reversible - stopping here would let one
    unreversible proposal spend the whole of Argus's autonomy. Where nothing
    follows, the node that decides that says so.

    It moves the incident nowhere - a rejection is the end of this attempt, not
    of the incident, so the status is `mitigating` before and after. The
    narration is the whole point of the return: this is the only place that
    knows what was refused and why, and the rejection clears the action on the
    way out.

    Silently passing an ungated action would be the failure this node exists to
    make impossible; silently dropping it would leave an incident that simply
    stopped.
    """
    reason = _why_the_action_cannot_proceed(state.proposed_action)

    if reason is None:
        return {}

    # The candidate's own row says it was never put to the question, and why.
    if state.hypothesis is not None:
        record_outcome(state.hypothesis.id, tested=False, result=reason)

    return {
        "proposed_action": None,
        "narration": Narration(action="action rejected at the tier gate", result=reason),
    }


def _why_the_action_cannot_proceed(action: Action | None) -> str | None:
    """The timeline's account of a rejection, or `None` when there is none to
    give. Two rejections reach the same status for different reasons, and a
    human reading the incident needs to know which: nothing to do at all, or
    something to do that could not be undone."""
    if action is None:
        return "no reversible action was proposed for this cause"

    if not action.undo_descriptor:
        return (
            f"the proposed action [{action.action_type}] on [{action.flag}] "
            f"carries no undo descriptor, so it is not reversible"
        )

    return None


def route_after_gate(state: IncidentState) -> str:
    """Where the gate sends an incident: on to the action, or on to whatever
    comes after an action that will not be taken.

    A rejected action clears `proposed_action`, which is what distinguishes the
    two - the status is `mitigating` either way, because a rejection at the gate
    is not the end of the incident, only the end of this attempt.
    """
    return "mitigating" if state.proposed_action is not None else "next_candidate"


def investigator_node(
    state: IncidentState,
    investigate: Investigate = _investigate,
    record_hypothesis: RecordHypothesis = _record_hypothesis,
    publisher: Publisher = nobody,
    recorder: Recorder = records_nothing,
) -> dict[str, Any]:
    """Forms a hypothesis, records every candidate it considered, and reports
    whether any of them is worth acting on (spec §7.2, §10).

    It does not decide the incident's status. What it reports -
    `nothing_worth_trying`, the candidate list, the index of the one to try - is
    what the status is derived from, one place further out.

    `investigate`/`record_hypothesis` default to the real investigation call and
    repository write, injectable so this node's logic can be unit tested without
    a live Target Service or database - mirroring the seams
    `agent_investigator.investigate()` establishes for its own retrieval and
    model calls."""
    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.INVESTIGATOR), publisher)

    findings = investigate(
        alert=state.alert,
        incident_id=state.incident_id,
        # Handed down rather than left to the agent's own default, so the
        # Investigator's account of what it read and this node's account of
        # what it did are one narration instead of two.
        publisher=publisher,
        # The same handing-down for the receipts. The agent's own default
        # records nowhere, which is right for a unit test and wrong for a run
        # nobody can afford to repeat.
        recorder=recorder,
        # Both empty on a first round. On a later one they are what makes the
        # round worth paying for: what earlier rounds already read, and what has
        # already been tried and did not help.
        already_read=state.already_read,
        already_refuted=state.attempts,
    )
    # Routing reads the best answer, as it always has. The rest are what the
    # walk moves on to when this one is refuted.
    # The best answer this round has that the walk has not already disproved.
    # On a first round that is simply the best answer; on a later one it matters,
    # because a re-investigation is free to reach the same conclusion as the one
    # that was just refuted, and acting on it again would change the same flag
    # back and forth until the round budget ran out.
    next_up = _the_next_worth_trying(findings.candidates, state.attempts, start=0)
    hypothesis = next_up[1] if next_up is not None else findings.candidates[0]
    # A named cause is enough to start the walk. Confidence used to gate this,
    # and gating it here was answering the wrong question: a mitigation that is
    # taken alone, confirmed against the service and put back when it does not
    # help costs two minutes, so what admits it is whether there is anything to
    # try - not how sure the model is that this one is right. An ambiguous
    # incident is exactly the case that produced middling confidence and no
    # action at all, which is the case the walk exists for.
    #
    # Reported rather than acted on. That this round found nothing worth trying
    # is what the investigation learned, and it is the one thing that tells an
    # investigation with nothing to offer apart from a walk that has worked
    # through everything it was offered - the two leave the same list behind.
    nothing_worth_trying = next_up is None
    # Every candidate, not only the one about to be tried. The incident's
    # record should say what was considered as well as what was acted on - a
    # runner-up that never reached the table is a finding a human picking the
    # incident up cannot see Argus ever having had.
    for candidate in findings.candidates:
        record_hypothesis(candidate)

    return {
        "hypothesis": hypothesis,
        "candidates": findings.candidates,
        "candidate_index": next_up[0] if next_up is not None else 0,
        # Everything read across this incident, not only this round's, so a
        # third round is told about the first as well as the second.
        "already_read": [*state.already_read, *findings.already_read],
        "rounds": state.rounds + 1,
        "confidence": hypothesis.confidence,
        "nothing_worth_trying": nothing_worth_trying,
        "narration": Narration(
            action=_what_the_investigation_did(hypothesis),
            result=hypothesis.summary,
            confidence=hypothesis.confidence,
        ),
    }


def _what_the_investigation_did(hypothesis: Hypothesis) -> str:
    """What the timeline records the Investigator as having done (spec §11.2).

    Two escalations reach this line for different reasons, and the timeline is
    where a human finds out which. A named cause below the threshold means a
    hypothesis was formed and is on file to be doubted; no cause at all means
    the loop read everything it was allowed to and still had nothing - the
    next step there is more evidence, not a second opinion on the first.
    """
    return "hypothesis formed" if hypothesis.cause_type is not None else "insufficient evidence"


def route_after_investigation(state: IncidentState) -> str:
    return "mitigating" if state.status == IncidentStatus.MITIGATING else "escalated"


def mitigation_node(
    state: IncidentState,
    take: TakeAction = take_action,
    record_action: RecordAction = _record_action,
    record_outcome: RecordOutcome = _record_outcome,
    publisher: Publisher = nobody,
) -> dict[str, Any]:
    """Performs the action the gate admitted, and records what came of it
    (spec §7.3, §11.1).

    Reached only through the gate, so the action is known to exist and to carry
    a way back. The verdict it returns is the strongest evidence anything in
    this graph has - it was measured against re-queried metrics - and it is
    reported here rather than turned into a status, because turning it into one
    was how `refuted` came to mean two different things in two places.

    The row records the descriptor the *write tier returned* rather than the
    one proposed, since that is the account of what actually changed.
    """
    # Both, because an action is taken *for* a candidate: one without the other
    # is not an attempt this node can account for, and recording it would leave
    # a row nothing can attribute. The gate guarantees both are here; this says
    # so in a way the type checker can read.
    if state.proposed_action is None or state.hypothesis is None:
        return _nothing_to_act_on()

    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.MITIGATION), publisher)
    # Published from here rather than from inside Mitigation, which is not
    # incident-scoped: neither `take_action` nor `Action` carries an incident,
    # and threading one through an agent purely so it can narrate would put a
    # field in the domain for the account's benefit.
    publish(
        ActionTaken(
            incident_id=state.incident_id,
            hypothesis_id=state.hypothesis.id,
            action_type=state.proposed_action.action_type,
            subject=state.hypothesis.subject,
            enabled=state.proposed_action.enabled,
        ),
        publisher,
    )

    # The incident and the publisher travel with the action, so the wait for
    # the service to answer - the longest silence in an incident - is narrated
    # from inside Mitigation, where the looking actually happens.
    result = take(state.proposed_action, incident_id=state.incident_id, publisher=publisher)
    outcome = str(result.verdict)

    publish(
        VerdictReached(
            incident_id=state.incident_id,
            hypothesis_id=state.hypothesis.id,
            outcome=outcome,
        ),
        publisher,
    )

    record_action(
        state.incident_id,
        # The candidate this attempt is about, named while it is still in hand.
        # Recovering it later means matching the flag the action and the
        # hypothesis happen to share, which the walk makes unambiguous only by
        # refusing to act on one subject twice - a rule about not retrying a
        # move, not about identity.
        hypothesis_id=state.hypothesis.id,
        action_type=state.proposed_action.action_type,
        outcome=outcome,
        undo_descriptor=result.undo_descriptor,
    )
    # This candidate was genuinely tested: an action was taken and the service
    # was measured afterwards. The verdict is the answer it was tested for, so
    # it belongs on the candidate's own row and not only on the timeline - a
    # list of explanations with no sign of which one the walk was on is a list
    # nobody can read the incident from.
    if state.hypothesis is not None:
        record_outcome(state.hypothesis.id, tested=True, result=outcome)

    return {
        "action_outcome": outcome,
        "narration": Narration(
            action="mitigation attempted", result=result.detail, detail=result.detail
        ),
    }


def _nothing_to_act_on() -> dict[str, Any]:
    """The unreachable case, handled rather than assumed away.

    The gate escalates an unproposed action, so nothing should arrive here
    without one. A node that indexed into `None` on the day that stopped being
    true would fail inside a state-changing step, which is the worst place to
    discover it.
    """
    return {
        "action_outcome": str(Verdict.ESCALATED),
        "narration": Narration(
            action="mitigation attempted", result="no action reached the mitigation step"
        ),
    }


def next_candidate_node(
    state: IncidentState,
    post_update: PostUpdate = _post_update,
) -> dict[str, Any]:
    """Decides what happens after an attempt settled nothing (spec §7.3).

    Reached two ways - the gate refusing an action, and the service refusing to
    recover after one - because "what now" has a single answer and splitting it
    across two nodes would be two chances to get it wrong.

    Three outcomes, in the order they are worth having. Another candidate above
    the mitigate threshold is tried, because the second explanation of a
    correlated change is usually still on the list. Failing that, another
    investigation is bought - and what buys it is the refutation, not a wider
    window: Argus changed production and the service did not answer, which is
    evidence no amount of re-reading produces and which the model has never
    seen. Gating that on leftover widening budget shut the door at exactly the
    wrong moment, since a hard incident spends its whole schedule reaching a
    confident first answer. Failing both, there are no moves left and a human is
    needed.

    What was just tried is remembered on the way past. That record is the one
    thing a later round knows that the first could not, and it belongs here,
    attached to the attempt that produced it, rather than being reconstructed
    later from a timeline.
    """
    attempts = [*state.attempts, *_what_was_just_tried(state)]
    next_up = _the_next_worth_trying(
        state.candidates, attempts, start=state.candidate_index + 1
    )
    next_index = next_up[0] if next_up is not None else len(state.candidates)
    next_candidate = next_up[1] if next_up is not None else None

    if next_candidate is not None:
        post_update(
            state.incident_id,
            f"{_what_the_attempt_did(state)}. Trying next: {next_candidate.summary}",
        )
        # Narration, and no transition behind it: the incident was mitigating
        # before this and is mitigating after. Moving to the next candidate is
        # progress through a phase, not out of one.
        return {
            "attempts": attempts,
            "candidate_index": next_index,
            "hypothesis": next_candidate,
            "confidence": next_candidate.confidence,
            "narration": Narration(
                action="moving on to the next candidate",
                result=next_candidate.summary,
                confidence=next_candidate.confidence,
            ),
        }

    if state.rounds < get_settings().investigation_max_rounds:
        # The most confusing moment to leave unannounced: Argus goes quiet
        # while it buys a wider look, and silence is what a stuck agent and a
        # thinking one have in common.
        post_update(
            state.incident_id,
            f"{_what_the_attempt_did(state)}. No explanation left in this round, "
            f"investigating further back",
        )
        return {
            "attempts": attempts,
            "candidate_index": next_index,
            "narration": Narration(
                action="every explanation was refuted, investigating again"
            ),
        }

    # Nothing reversible is left, and what remains is a permanent fix - which is
    # the one thing `fixing` means. Reported, not decided: the index past the end
    # of the list and a spent round budget are what say so.
    return {
        "attempts": attempts,
        "candidate_index": next_index,
        "narration": Narration(
            action="no explanation left to try",
            result=(
                f"{len(attempts)} action(s) were taken and undone, and the evidence "
                f"offers nothing further to try"
            ),
        ),
    }


def _what_the_attempt_did(state: IncidentState) -> str:
    """The war room's account of the attempt that just settled nothing.

    Two things end an attempt without an answer, and a human deciding whether
    to step in needs to know which: a change that was made and did not help, or
    a change that was never allowed to happen. Named here rather than in the
    Communicator, which has no way to tell them apart.

    The end of the walk is deliberately not phrased here - that one is the
    page's to announce, and no update precedes it.
    """
    action = state.proposed_action

    if action is None:
        return "The action for this explanation could not be taken"

    return (
        f"Set [{action.flag}] {'on' if action.enabled else 'off'}; "
        f"the service did not recover, so it was put back"
    )


def _the_next_worth_trying(
    candidates: list[Hypothesis], attempts: list[Attempt], start: int
) -> tuple[int, Hypothesis] | None:
    """The first candidate from `start` onwards that is worth an experiment,
    with the index it sits at - or `None` when the list is spent.

    Every explanation that names a cause is worth one, however far down the list
    it sits: the list is ordered by confidence, so a later candidate is only
    ever reached once the ones the model believed more have been tried and
    refuted, and by then the ranking has already been proved wrong about the
    ones above it.

    Two things disqualify a candidate. One names no cause: there is nothing to
    change on its account, which is a different answer from being unsure. The
    other has already been tried - the same subject was changed earlier in this
    incident and the service did not recover - and doing it again would be
    Argus running the same experiment expecting a different world. That can
    happen across rounds, where a later investigation is free to reach the same
    conclusion as the first: the refutation is offered to it as evidence, but
    nothing obliges it to change its mind, and nothing should oblige the walk to
    keep acting on it either.
    """
    already_tried = {attempt.subject for attempt in attempts}

    for index in range(start, len(candidates)):
        candidate = candidates[index]

        if candidate.is_actionable() and candidate.subject not in already_tried:
            return index, candidate

    return None


def _what_was_just_tried(state: IncidentState) -> list[Attempt]:
    """The attempt this node is reacting to, if production was actually changed.

    An action the gate refused never ran, so there is nothing to remember and
    nothing a later round could learn from it. Only a change that was made -
    and undone - is evidence about the cause it was made on.
    """
    action = state.proposed_action

    if action is None or not action.undo_descriptor:
        return []

    return [
        Attempt(
            subject=action.flag,
            enabled=action.enabled,
            occurred_at=to_iso(utc_now()),
        )
    ]


def route_after_next_candidate(state: IncidentState) -> str:
    if state.status == IncidentStatus.MITIGATING:
        return "mitigating"

    if state.status == IncidentStatus.INVESTIGATING:
        return "investigating"

    return "fixing"


def route_after_mitigation(state: IncidentState) -> str:
    """A confirmed action resolves; anything else that left the world intact
    hands over to the walk.

    A refuted action stays in `mitigating` and goes to the node that decides
    whether another explanation is left to try. Code-Fix is reached only once
    there is not, which is what "Argus is out of reversible moves" means.

    An `escalated` outcome still ends things immediately: the action could not
    be taken at all, so nothing was changed and nothing was measured, and a
    further experiment would run against a world Argus cannot describe.
    """
    if state.status == IncidentStatus.RESOLVED:
        return "resolved"
    if state.status == IncidentStatus.MITIGATING:
        return "next_candidate"
    return "escalated"


def codefix_node(state: IncidentState) -> dict[str, Any]:
    """Looks for a permanent fix, once no reversible action is left (spec §7.4).

    Still a stub, and the return value is the honest part of it: reporting that
    no fix was found is a real answer, and it is what carries the incident on to
    a human. Leaving it silent was how an incident could reach the end of the
    graph still marked `fixing`, which is a status nothing was working on.
    """
    propose_fix(state.hypothesis.summary if state.hypothesis else "")

    return {
        "fix_found": False,
        "narration": Narration(
            action="no code-level fix found",
            result="the incident is being handed to a human",
        ),
    }


def route_after_codefix(state: IncidentState) -> str:
    return "resolved" if state.status == IncidentStatus.RESOLVED else "escalated"


def communicator_node(
    state: IncidentState, raise_page: RaisePage = _raise_page
) -> dict[str, Any]:
    """Raises the one page an incident gets (spec §7.5, §10).

    Every way an incident can end without a fix arrives here - an investigation
    that named nothing, an action that could not be taken, a walk that tried
    everything it had - which is what makes "exactly one page" a property of
    the graph's shape rather than a rule this node has to enforce. The updates
    along the way were the Communicator's other register; this is the one that
    interrupts someone.
    """
    raise_page(state.incident_id, _why_a_human_is_needed(state))
    return {}


def _why_a_human_is_needed(state: IncidentState) -> str:
    """What the page says, which is the last thing Argus gets to say.

    A walk that tried things and a walk that never got started are different
    incidents to be woken for, and the count is the difference: it tells the
    reader whether production has been changed and put back, or never touched.
    """
    if state.attempts:
        return (
            f"{len(state.attempts)} explanation(s) were tried and undone, and "
            f"nothing further is left to try"
        )

    return "escalating: there was no action Argus could take on this incident"


def postmortem_node(
    state: IncidentState,
    write: WritePostmortem = write_postmortem_for,
    record: RecordPostmortem = _record_postmortem,
) -> dict[str, Any]:
    """Writes the incident up, and stores whatever was written (spec §7.6).

    The last node, and the only one whose work nothing downstream reads - which
    is why it stores a partial document rather than discarding one. A page
    finding nothing where a postmortem should be cannot tell "never written"
    from "lost", and the incident is over either way.

    Both collaborators are injected for the usual reason: what a postmortem
    says belongs to the agent and how a row is stored belongs to the
    repository, so this node's own logic - that the two are joined at all - can
    be tested without a database or a model.
    """
    record(state.incident_id, write(state.incident_id))

    return {}



# One attempt is four traversals - proposal, gate, mitigation, next_candidate -
# and an incident nobody could fix ends in three more: codefix, communicator,
# postmortem. Named constants rather than a number in the arithmetic below,
# because they are facts about the graph a few lines further down, and the day
# one of them changes is the day this stops being right silently.
_NODES_PER_ATTEMPT = 4
_NODES_ENDING_A_WALK = 3


def recursion_limit(max_rounds: int, max_candidates: int) -> int:
    """How many traversals the longest walk these settings allow will take.

    LangGraph stops a graph after a fixed number of super-steps, defaulting to
    25 - a number chosen to catch a runaway loop, and one this graph's walk
    passes legitimately: three rounds of four candidates is fifty-four. Hitting
    it raises mid-incident, with production already changed and no postmortem
    written, which is the one failure a limit meant to protect the system would
    cause by itself.

    Derived from the two settings that actually bound the walk rather than set
    to a generous constant, so that widening the iteration budget or the
    candidate budget cannot leave the graph unable to spend it.
    """
    a_full_round = 1 + _NODES_PER_ATTEMPT * max_candidates

    return max_rounds * a_full_round + _NODES_ENDING_A_WALK


def build_graph(checkpointer: BaseCheckpointSaver[Any]) -> CompiledStateGraph[IncidentState]:
    """Assembles spec §10's incident FSM as a LangGraph `StateGraph` (§7.1) -
    every sub-agent and the tier-gate node are present, and every edge from
    §10's diagram is wired, even though this change's happy path only
    drives `investigating -> mitigating -> resolved`."""
    graph: StateGraph[IncidentState] = StateGraph(IncidentState)
    # The subscriber is bound here rather than defaulted on the nodes. A node's
    # collaborators default to the real thing because a caller that wants the
    # real thing is the ordinary case; publishing is the exception, since the
    # ordinary case for a node called on its own - in a test - is that nobody
    # is listening. Wiring it where the graph is assembled keeps a unit test
    # away from the database without every one of them having to say so.
    #
    # Every node is wrapped so the status its work implies is derived, written
    # and published in one place. The actor is supplied here because which agent
    # a node belongs to is a fact about the graph, not about the node.
    max_rounds = get_settings().investigation_max_rounds
    deciding_status = partial(
        with_status, max_rounds=max_rounds, publisher=record_event
    )

    graph.add_node(
        "investigator",
        deciding_status(
            partial(investigator_node, publisher=record_event, recorder=record_call),
            Actor.INVESTIGATOR
        ),
    )
    graph.add_node(
        "mitigation_proposal",
        deciding_status(
            partial(mitigation_proposal_node, publisher=record_event), Actor.MITIGATION
        ),
    )
    graph.add_node("tier_gate", deciding_status(tier_gate_node, Actor.MITIGATION))
    graph.add_node(
        "mitigation",
        deciding_status(partial(mitigation_node, publisher=record_event), Actor.MITIGATION),
    )
    graph.add_node("next_candidate", deciding_status(next_candidate_node, Actor.MITIGATION))
    graph.add_node("codefix", deciding_status(codefix_node, Actor.CODEFIX))
    graph.add_node("communicator", deciding_status(communicator_node, Actor.COMMUNICATOR))
    graph.add_node("postmortem", deciding_status(postmortem_node, Actor.POSTMORTEM))

    graph.add_edge(START, "investigator")
    graph.add_conditional_edges(
        "investigator",
        route_after_investigation,
        {"mitigating": "mitigation_proposal", "escalated": "communicator"},
    )
    # The gate stands between the proposal and the call that performs it
    # (spec §13) - not at the start of the graph, where it would guard nothing
    # because no action exists yet to be judged.
    graph.add_edge("mitigation_proposal", "tier_gate")
    graph.add_conditional_edges(
        "tier_gate",
        route_after_gate,
        {"mitigating": "mitigation", "next_candidate": "next_candidate"},
    )
    graph.add_conditional_edges(
        "mitigation",
        route_after_mitigation,
        {
            "resolved": "postmortem",
            "next_candidate": "next_candidate",
            "escalated": "communicator",
        },
    )
    # The loop. An attempt that settled nothing goes back to the proposal node
    # for the next explanation, or back to the Investigator for a wider look -
    # and Code-Fix is reached only once neither is left, which is what "Argus is
    # out of moves" actually means.
    graph.add_conditional_edges(
        "next_candidate",
        route_after_next_candidate,
        {
            "mitigating": "mitigation_proposal",
            "investigating": "investigator",
            "fixing": "codefix",
        },
    )
    graph.add_conditional_edges(
        "codefix",
        route_after_codefix,
        {"resolved": "postmortem", "escalated": "communicator"},
    )
    graph.add_edge("communicator", "postmortem")
    graph.add_edge("postmortem", END)

    return graph.compile(checkpointer=checkpointer)
