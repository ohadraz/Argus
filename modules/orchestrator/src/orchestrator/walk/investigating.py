"""One round of investigation: what it found, and its account of finding it.

The round also reads the flag provider, which the node that proposes an action
used to do. It has to: what memory demotes, and what the walk skips, is the
action a candidate would be answered with - and that question cannot be asked
before the history is in hand. Read once here and carried, so that the round
that chose a candidate and the node that acts on it reason about one account of
the provider rather than two.
"""

from __future__ import annotations

from argus_core.events import (
    AgentInvoked,
    CandidatesReordered,
    FlagChangesRetrieved,
    Publisher,
    nobody,
    publish,
)
from argus_core.models import Actor, FlagChange, Hypothesis, IncidentStatus

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both.
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing
from incident_memory.describing import what_it_looked_like
from incident_memory.ordering import demoting_what_was_refuted

from orchestrator.walk.candidates import the_next_worth_trying, what_each_would_do
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import (
    FetchFlagChanges,
    Investigate,
    RecallSimilar,
    RecordHypothesis,
)
from orchestrator.walk.routes import ESCALATED_ROUTE, MITIGATING_ROUTE
from orchestrator.walk.state import IncidentState


def investigator_node(
    state: IncidentState,
    record_hypothesis: RecordHypothesis,
    investigate: Investigate,
    recall_similar: RecallSimilar,
    fetch_flag_changes: FetchFlagChanges,
    publisher: Publisher = nobody,
    recorder: Recorder = records_nothing,
) -> StateDelta:
    """Forms a hypothesis, records every candidate it considered, and reports
    whether any of them is worth acting on (spec §7.2, §10).

    It does not decide the incident's status. What it reports -
    `nothing_worth_trying`, the candidate list, the index of the one to try - is
    what the status is derived from, one place further out.

    `record_hypothesis` defaults to the real recorder, and
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
    # The flag provider's account of what changed, read here rather than in
    # the node that proposes an action. What memory compares is not a candidate
    # but the action that answers it, and that question cannot be asked before
    # the history is in hand - so it is read at the top of the round, once, and
    # carried to everything in the round that needs it.
    flag_changes = _what_the_provider_recorded(state, fetch_flag_changes, publisher)
    # What memory makes of this round's candidates, before anything is chosen
    # from them. Read once here rather than per candidate: one search, a
    # deterministic order, and one line accounting for it.
    #
    # The description is built from this round's best answer, because that is
    # what this incident looks like as far as anyone knows yet - the alert's own
    # words plus what the investigation just concluded.
    reordered = demoting_what_was_refuted(
        what_each_would_do(findings.candidates, flag_changes, state.alert.service),
        recall_similar(
            what_it_looked_like(state.alert, findings.candidates[0]),
            state.alert.service
        )
    )
    candidates = [entry.candidate for entry in reordered.candidates]

    if reordered.moved is not None and reordered.on_the_strength_of is not None:
        publish(
            CandidatesReordered(
                incident_id=state.incident_id,
                action_type=reordered.moved.action_type,
                subject=reordered.moved.subject,
                on_the_strength_of=reordered.on_the_strength_of
            ),
            publisher
        )

    # Routing reads the best answer, as it always has. The rest are what the
    # walk moves on to when this one is refuted.
    # The best answer this round has that the walk has not already disproved.
    # On a first round that is simply the best answer; on a later one it matters,
    # because a re-investigation is free to reach the same conclusion as the one
    # that was just refuted, and acting on it again would take the same action
    # over and over until the round budget ran out - a flag moved back and
    # forth, or a service restarted once per round, which is the same loop
    # wearing a different word.
    next_up = the_next_worth_trying(reordered.candidates, state.attempts, start=0)
    hypothesis = next_up[1] if next_up is not None else candidates[0]
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
    for candidate in candidates:
        record_hypothesis(candidate)

    return StateDelta(
        hypothesis=hypothesis,
        candidates=candidates,
        candidate_index=next_up[0] if next_up is not None else 0,
        # Carried on, including where it is `None`: the nodes after this one
        # act on the same history this round was reasoned from, and a provider
        # that could not be read has to reach them as that rather than as a
        # history that happens to be empty.
        flag_changes=flag_changes,
        # Everything read across this incident, not only this round's, so a
        # third round is told about the first as well as the second.
        already_read=[*state.already_read, *findings.already_read],
        rounds=state.rounds + 1,
        confidence=hypothesis.confidence,
        nothing_worth_trying=nothing_worth_trying,
        narration=Narration(action=_what_the_investigation_did(hypothesis)),
    )


def _what_the_provider_recorded(state: IncidentState,
                                fetch_flag_changes: FetchFlagChanges,
                                publisher: Publisher) -> list[FlagChange] | None:
    """What the flag provider says changed, or `None` where it would not say.

    A provider that cannot be read answers nothing rather than raising. "I
    could not find out what changed" and "nothing changed" lead to the same
    place - no action, and a human - and neither is a reason to fail the
    graph. They are not the same fact, though, which is why the failure is
    `None` and not an empty list: everything downstream that reasons about a
    flag reasons differently about the two.

    Published from here, because this is where it is read. The account carries
    the whole basis of every action this round might propose - which flag
    moved, which way, and when - and by the time an action exists that history
    has already been reduced to one decision about one flag. The failure is
    deliberately unpublished: an empty history on the page would state that
    nothing had changed, and the two look identical there while meaning
    opposite things.
    """
    try:
        flag_changes = fetch_flag_changes()
    except Exception:
        return None

    publish(
        FlagChangesRetrieved(incident_id=state.incident_id, changes=flag_changes),
        publisher
    )

    return flag_changes


def _what_the_investigation_did(hypothesis: Hypothesis) -> str:
    """What the timeline records the Investigator as having done (spec §11.2).

    Two escalations reach this line for different reasons, and the timeline is
    where a human finds out which. A named cause below the threshold means a
    hypothesis was formed and is on file to be doubted; no cause at all means
    the loop read everything it was allowed to and still had nothing - the
    next step there is more evidence, not a second opinion on the first.
    """
    return "hypothesis formed" if hypothesis.failure_mode is not None else "insufficient evidence"


def route_after_investigation(state: IncidentState) -> str:
    return MITIGATING_ROUTE if state.status == IncidentStatus.MITIGATING else ESCALATED_ROUTE
