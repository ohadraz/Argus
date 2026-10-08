"""One round of investigation: what it found, and its account of finding it.

The round also reads the flag provider, which the node that proposes an action
used to do. It has to: what memory demotes, and what the walk skips, is the
action a candidate would be answered with - and that question cannot be asked
before the history is in hand. Read once here and carried, so that the round
that chose a candidate and the node that acts on it reason about one account of
the provider rather than two.
"""

from __future__ import annotations

import logging
from datetime import datetime

from argus_core.events import (
    AgentInvoked,
    AlarmDisproven,
    CandidatesReordered,
    FlagChangesRetrieved,
    Publisher,
    RetrievalUnanswered,
    SimilarIncidentsRecalled,
    nobody,
    publish,
)
from argus_core.models import (
    Actor,
    ChangeEvent,
    Disproof,
    FlagChange,
    Hypothesis,
    IncidentStatus,
    ServiceDependency,
)

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both.
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing
from incident_memory.describing import what_it_looked_like
from incident_memory.ordering import demoting_what_was_refuted

from orchestrator.walk.candidates import (
    the_circumstances,
    the_next_worth_trying,
    what_each_would_do,
)
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import (
    FetchDependencies,
    FetchDeployments,
    FetchFlagChanges,
    Investigate,
    RecallSimilar,
    RecordHypothesis,
)
from orchestrator.walk.routes import ESCALATED_ROUTE, MITIGATING_ROUTE
from orchestrator.walk.state import IncidentState

_logger = logging.getLogger(__name__)


def investigator_node(
    state: IncidentState,
    record_hypothesis: RecordHypothesis,
    investigate: Investigate,
    recall_similar: RecallSimilar,
    fetch_flag_changes: FetchFlagChanges,
    fetch_dependencies: FetchDependencies,
    fetch_deployments: FetchDeployments | None = None,
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
    model calls.

    `fetch_deployments` is the one collaborator that may be absent, and absent
    means the history was never read rather than that nothing was deployed: it
    is carried as `None`, which is what an unreadable history is carried as. One
    mode reads it, so a walk without it loses that mode's rollback and nothing
    else."""
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
    if findings.disproof is not None:
        # The window contradicted what the alarm claimed, so there is no incident
        # for the rest of this round to be about. Returned here rather than
        # carried through it: every read below asks what changed around a fault
        # that did not happen, and memory would be searched for incidents
        # resembling a service that was well.
        return _the_alarm_was_disproven(state, findings.disproof, publisher)

    # The flag provider's account of what changed, read here rather than in
    # the node that proposes an action. What memory compares is not a candidate
    # but the action that answers it, and that question cannot be asked before
    # the history is in hand - so it is read at the top of the round, once, and
    # carried to everything in the round that needs it.
    flag_changes = _what_the_provider_recorded(
        state, findings.readings_cover_the_incident, fetch_flag_changes, publisher
    )
    # And the platform's account of what was deployed, over the same window: a
    # mode that names the damage rather than the change is answered by undoing
    # whichever of the two sits at the onset, so the two are read as one.
    deployments = _what_the_platform_recorded(
        state, findings.readings_cover_the_incident, fetch_deployments, publisher
    )
    # The estate this incident is allowed to reach into, read in the same
    # breath. Nothing in this round uses it: it is read here because it is
    # read *once*, and the node that needs it is a gate two steps away that
    # must not have its answer depend on a document store being up at the
    # instant it asks.
    dependencies = _what_the_register_lists(state, fetch_dependencies)
    # What earlier incidents on this service looked like this one. Searched once
    # per round rather than once per candidate: one search, and a deterministic
    # order for everything below to reason from.
    #
    # The description is built from this round's best answer, because that is
    # what this incident looks like as far as anyone knows yet - the alert's own
    # words plus what the investigation just concluded.
    #
    # Held in a local rather than read inside the demotion, because two readers
    # want it: what memory demotes, and the account of the search itself.
    recalled = recall_similar(
        what_it_looked_like(state.alert, findings.candidates[0]),
        state.alert.service
    )

    # Said before anything is done with it, and said whether or not anything is.
    # A reordering needs a candidate to move something behind, and how many
    # candidates a round offers is the model's to decide - so a timeline carrying
    # only the reordering is silent about memory on the walks where memory was
    # read and did find something.
    if recalled:
        publish(
            SimilarIncidentsRecalled(
                incident_id=state.incident_id,
                incident_ids=[remembered.incident_id for remembered in recalled]
            ),
            publisher
        )

    # What memory makes of this round's candidates, before anything is chosen from
    # them. The action that answers a candidate is what is matched, not the
    # candidate's own prose - which is why the flag history had to be in hand
    # before this point, and why the alert's keys go with it: the action for a
    # divergence is addressed to entries only the evidence ever named, so a
    # candidate asked without them is a candidate memory has nothing to
    # recognise.
    reordered = demoting_what_was_refuted(
        what_each_would_do(
            findings.candidates,
            # The placement this round's investigation recorded, not the state's:
            # the state still holds the last round's until this node returns.
            the_circumstances(
                state.alert, flag_changes, deployments, findings.placement
            )
        ),
        recalled
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
        deployments=deployments,
        # This round's placement, `None` included: every round re-reads, and a
        # placement this round could not read must clear the last one rather
        # than leave pods recorded against an earlier onset standing.
        placement=findings.placement,
        # Carried on for the gate, which is where it is finally asked a
        # question. Empty where the register would not answer, deliberately
        # indistinguishable from a register that listed nothing: both leave
        # every mitigation addressed to the alerting service available and
        # refuse everything aimed elsewhere.
        dependencies=dependencies,
        # Everything read across this incident, not only this round's, so a
        # third round is told about the first as well as the second.
        already_read=[*state.already_read, *findings.already_read],
        # This round's reading of the window, not the incident's accumulated one:
        # every round re-reads, and what the gate needs to know is whether the
        # evidence in front of the walk now says anything about the incident's own
        # minutes.
        readings_cover_the_incident=findings.readings_cover_the_incident,
        rounds=state.rounds + 1,
        confidence=hypothesis.confidence,
        nothing_worth_trying=nothing_worth_trying,
        narration=Narration(action=_what_the_investigation_did(hypothesis)),
    )


def _what_the_provider_recorded(state: IncidentState,
                                readings_cover_the_incident: bool,
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
    has already been reduced to one decision about one flag.

    The failure is published as the thing it is, and never as an empty history:
    an empty history on the page would state that nothing had changed, and the
    two look identical there while meaning opposite things. Saying nothing at all
    was the other way of getting it wrong - a channel that was asked and refused
    then reads exactly like one nobody thought to try, which is the distinction
    `ChannelsUnread` exists to draw and cannot draw on its own.
    """
    try:
        flag_changes = fetch_flag_changes(
            onset=_where_the_change_window_ends(state, readings_cover_the_incident)
        )
    except Exception as unanswered:
        # No minute, because there is none to name: this is the window the round
        # asked about rather than a minute being judged, and a field filled in to
        # look complete would put a moment on the page that nothing measured.
        publish(
            RetrievalUnanswered(
                incident_id=state.incident_id,
                what_was_asked="what the flag provider recorded changing",
                because=str(unanswered)
            ),
            publisher
        )

        return None

    publish(
        FlagChangesRetrieved(incident_id=state.incident_id, changes=flag_changes),
        publisher
    )

    return flag_changes


def _what_the_platform_recorded(state: IncidentState,
                                readings_cover_the_incident: bool,
                                fetch_deployments: FetchDeployments | None,
                                publisher: Publisher) -> list[ChangeEvent] | None:
    """What the platform says was deployed to the alerting service, or `None`
    where it would not say or nobody wired it.

    The flag history's twin, over the same window and failing the same way: an
    unreadable history is `None` and is said to have gone unanswered, never an
    empty list, which would state that nothing was deployed.

    Not published when it answers. The Investigator reads the same channel
    itself and its reading is already in the account; this is a second read,
    over the flag history's window rather than the Investigator's, held for the
    one mode whose action it decides.
    """
    if fetch_deployments is None:
        return None

    try:
        return fetch_deployments(
            service=state.alert.service,
            onset=_where_the_change_window_ends(state, readings_cover_the_incident)
        )
    except Exception as unanswered:
        publish(
            RetrievalUnanswered(
                incident_id=state.incident_id,
                what_was_asked="what the platform recorded deploying",
                because=str(unanswered)
            ),
            publisher
        )

        return None


def _where_the_change_window_ends(state: IncidentState,
                                  readings_cover_the_incident: bool
                                  ) -> datetime | None:
    """The onset a change history's window ends at, or `None` for the present.

    The onset the alert stated, or nothing - which is what every alert that
    measured its own says, and what leaves the window ending where it always
    ended.

    Nothing, too, where no reading covers the incident's own minutes. A stated
    onset is ordinarily the minute the incident began; where the readings stop at
    it, it is the last one there was, and what ended them is the change - so the
    change lies at or after that minute and a window ending there holds none of
    it. Asking for the present is then the right question for the reason it is
    the wrong one for a weekly check: this incident is happening now, and the
    change is still in force.
    """
    return state.alert.stated_onset if readings_cover_the_incident else None


def _what_the_register_lists(state: IncidentState,
                             fetch_dependencies: FetchDependencies
                             ) -> list[ServiceDependency]:
    """What the register says the alerting service calls, or nothing at all.

    Asked about the service that was paged, because that is the service whose
    dependencies bound where a mitigation for this incident may be aimed.

    A register that cannot be read answers nothing rather than raising, as the
    flag provider does - but unlike the flag provider it answers with an empty
    list rather than with a third value, and the difference is what the two
    absences mean. "Nobody could say what changed" is a fact the walk reasons
    about differently from "nothing changed"; "nobody could say what this
    service calls" is not a fact the walk reasons about at all. It is simply an
    estate Argus cannot vouch for, and an estate it cannot vouch for is one it
    does not touch - which is exactly what an empty list already means here.

    Unpublished for the same reason. What a service calls is a fact about how it
    is built rather than about this incident, and a line on the timeline saying
    the register was read would be a line every walk carries and nobody reads.
    What a reader needs to know is the one thing the register decided, and the
    gate says that where it happens: an action refused for being addressed
    outside what Argus may touch.
    """
    try:
        return fetch_dependencies(state.alert.service)
    except Exception:
        _logger.warning(
            "the service register could not be read; nothing but %s is within reach",
            state.alert.service,
            exc_info=True
        )

        return []


def _the_alarm_was_disproven(state: IncidentState,
                             disproof: Disproof,
                             publisher: Publisher) -> StateDelta:
    """The round that established there was nothing to investigate.

    Nothing is recorded as a hypothesis and no candidate is carried on. A
    candidate is an explanation of a fault, and what this round found is that
    there was no fault - so a row offering an explanation would be the record
    naming something for a reader to doubt instead of something to act on.

    The round is still counted. It happened, it read the metrics, and a count
    that skipped it would make the one thing this walk did invisible to anything
    totalling what Argus spent.
    """
    publish(
        AlarmDisproven(
            incident_id=state.incident_id,
            # The alert's own words for what it reported, rather than Argus's
            # summary of them. The claim that was ruled out has to be the claim
            # as the rule made it, or a reader cannot match the two.
            condition=state.alert.summary or state.alert.alert_name,
            signals_judged=disproof.signals_judged,
            earliest_minute=disproof.earliest_minute,
            latest_minute=disproof.latest_minute,
            minutes_judged=disproof.minutes_judged
        ),
        publisher
    )

    return StateDelta(
        disproof=disproof,
        rounds=state.rounds + 1,
        narration=Narration(
            # Read in two places and written for the harder one. The
            # timeline shows it beside the disproof event, which carries the
            # grounds; the channel announcement shows it as the whole reason
            # the incident ended, with nothing else beside it. So it says what
            # was found rather than naming the finding.
            action="the alarm's own claim was not in the window"
        )
    )


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
