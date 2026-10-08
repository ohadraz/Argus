"""Walking the candidates an investigation offered, one at a time.

Being wrong about a correlated change is the ordinary case in an incident, not
the exceptional one, so a refuted mitigation is not the end of what Argus can
do - it is the end of what Argus can do *about that candidate*. These cover the
decision made after each attempt: try the next explanation, buy a wider look,
or admit there are no moves left.

One node owns that decision. Both ways an attempt can fail to settle anything -
the gate refusing it, and the service refusing to recover - arrive at the same
place, because "what now" has one answer and splitting it across two nodes
would be two chances to get it wrong.

The node reports what it found and never a status. Where that leaves the
incident is derived from the state it produced, which is what `_the_walk_goes_to`
does here and what the graph does in production.

Nothing here tells anybody. A longer walk is a longer silence before a human
hears anything, and what closes that gap is the relay in `agent_communicator`,
which follows the events these decisions are published as - so the node
decides, publishes, and knows nothing about who is listening.
"""

from __future__ import annotations

import pytest
from argus_core.events import CandidateSelected, IncidentEvent
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    Alert,
    DiscardCacheEntries,
    Evidence,
    FailureMode,
    FlagChange,
    FlagUndo,
    Hypothesis,
    IncidentStatus,
    PinToAccelerator,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    the_actions_through,
)
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.choosing import next_candidate_node, route_after_next_candidate
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.routes import (
    ESCALATED_ROUTE,
    FIXING_ROUTE,
    INVESTIGATING_ROUTE,
    MITIGATING_ROUTE,
)
from orchestrator.walk.state import IncidentState, status_after

from orchestrator_test.framework.assertions import the_updates_carry
from orchestrator_test.framework.builders import (
    a_candidate_blaming,
    a_corruption_blamed_on,
    a_deployment,
    a_determined_hypothesis,
    a_divergence_blamed_on,
    a_placement,
    a_random_id,
    an_accelerator_blamed_on,
    an_undetermined_hypothesis,
)

# How many times one incident may be investigated. Stated rather than read:
# the node is told its budget now, and a test taking the number from the
# same configuration would agree with itself whatever either said.
SOME_ROUND_BUDGET = 3

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"
DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
DONT_CARE_MOMENT = "2026-08-20T11:05:00Z"


@pytest.mark.unit
def test_a_refuted_candidate_hands_over_to_the_next_one() -> None:
    incident_id = a_random_id()
    the_next_candidate = a_determined_hypothesis(incident_id)

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id), the_next_candidate],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            the_updates_carry("candidate_index", 1),
            the_updates_carry("hypothesis", the_next_candidate),
            _the_walk_goes_to(MITIGATING_ROUTE, a_walk)))


@pytest.mark.unit
def test_moving_to_the_next_candidate_is_published_rather_than_narrated() -> None:
    # This node's own comment says it: narration, and no transition behind it.
    # Moving to the next candidate is progress through a phase rather than out
    # of one, so the only account of it has to be an event - and which
    # explanation is now under test is the thing the lines after this are about.
    incident_id = a_random_id()
    the_next_candidate = a_determined_hypothesis(incident_id)
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id), the_next_candidate],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET,
                                          publisher=published.append)) \
        .then(all_of(
            _the_candidate_selected_was(the_next_candidate, published),
            _nothing_was_narrated()))


@pytest.mark.unit
def test_what_was_tried_is_remembered_for_the_round_after() -> None:
    # A later investigation is only worth running because it can be told this.
    # Recorded here rather than in the investigator node, so the fact stays
    # attached to the attempt that produced it.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(incident_id,
                                 [a_determined_hypothesis(incident_id)],
                                 index=0,
                                 acted_on=SOME_FLAG)
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_attempts_recorded_are([SOME_FLAG]))


@pytest.mark.unit
def test_a_walk_with_a_candidate_left_carries_on() -> None:
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id),
                 a_determined_hypothesis(incident_id)],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_walk_goes_to(MITIGATING_ROUTE, a_walk))


@pytest.mark.unit
def test_a_spent_list_buys_another_investigation() -> None:
    # Every explanation this round offered has been tried and failed, which is
    # the moment another round is worth paying for - and what pays for it is the
    # refutation rather than a wider window. Argus changed production and the
    # service did not answer; no amount of re-reading produces that fact, and
    # the model has never seen it. One round is already spent here, which is the
    # ordinary shape of a hard incident by the time its first answer comes back
    # refuted.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(incident_id,
                                 [a_determined_hypothesis(incident_id)],
                                 index=0,
                                 rounds=1)
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_walk_goes_to(INVESTIGATING_ROUTE, a_walk))


@pytest.mark.unit
def test_a_walk_that_has_used_every_round_ends() -> None:
    # The bound is a count of rounds rather than the walk's own judgement: each
    # round is a model call and another set of real changes to production, and
    # "keep going until something works" is not a stopping condition.
    #
    # It ends in `fixing`, not `escalated`: nothing reversible is left and what
    # remains is a permanent fix, which is what Code-Fix is for. `escalated`
    # comes later, once Code-Fix has nothing either.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(incident_id,
                                 [a_determined_hypothesis(incident_id)],
                                 index=0,
                                 rounds=_every_round())
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_walk_goes_to(FIXING_ROUTE, a_walk))


@pytest.mark.unit
def test_a_walk_with_nothing_left_on_a_reachable_platform_escalates() -> None:
    # Not another investigation and not a permanent fix, which are the two
    # endings this node had. A further round would re-read the same evidence and
    # arrive at candidates on the same dead platform, and a permanent fix is not
    # what an incident needs when what failed is how Argus acts at all.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_whose_platform_went(
                incident_id, [a_determined_hypothesis(incident_id)]
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_the_walk_goes_to(ESCALATED_ROUTE, a_walk))


@pytest.mark.unit
def test_an_escalation_over_a_platform_names_it_and_what_it_took_away() -> None:
    # What a person is handed. The difference between "the rollback failed" and
    # "the deployment platform is not answering, so the restart, the rollback,
    # the scale-out and the pin are all unavailable" is the difference between
    # looking at one action and looking at the platform - and only the second
    # sends them to the right place.
    #
    # The actions are named rather than left to be looked up: a reader told only
    # a platform's name has to go and work out which of Argus's five went with
    # it, which is the thing saying anything at all exists to prevent.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_whose_platform_went(
                incident_id, [a_determined_hypothesis(incident_id)]
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            _what_it_said_names(DEPLOYMENT_PLATFORM),
            _what_it_said_names(*the_actions_through(DEPLOYMENT_PLATFORM))
        ))


@pytest.mark.unit
def test_an_escalation_over_a_platform_does_not_claim_the_evidence_ran_out() -> None:
    # The sentence this node would otherwise reach for, and it is false here.
    # "No explanation left to try" and "the evidence offers nothing further" say
    # the investigation is exhausted, where in fact the evidence is fine and
    # untried explanations are still on the list - what is gone is the means of
    # acting on them. A postmortem built on that would describe the wrong
    # incident.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_whose_platform_went(
                incident_id, [a_determined_hypothesis(incident_id)]
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(_what_it_said_does_not_name("the evidence offers nothing further"))


@pytest.mark.unit
def test_a_doubtful_candidate_is_tried_like_any_other() -> None:
    # Confidence orders the list; it does not decide who gets on it. By the time
    # the walk reaches a doubtful candidate, every explanation the model
    # believed more has been tried and refuted - so the ranking that made this
    # one doubtful has already been proved wrong about the ones above it, and
    # the cost of finding out is one reversible change and two minutes.
    some_doubtful_confidence = 0.4
    incident_id = a_random_id()
    a_doubtful_candidate = a_determined_hypothesis(incident_id, some_doubtful_confidence)

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id), a_doubtful_candidate],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(_the_walk_goes_to(MITIGATING_ROUTE, a_walk),
                     the_updates_carry("hypothesis", a_doubtful_candidate)))


@pytest.mark.unit
def test_a_candidate_blaming_a_flag_already_tried_is_skipped() -> None:
    # The same subject, twice on one list. Changing it again would be running
    # the experiment that has already been run and undone, against a world that
    # answered once - so the walk passes over it and reaches the first
    # explanation that is actually new.
    incident_id = a_random_id()
    a_candidate_blaming_something_else = a_candidate_blaming(incident_id, ANOTHER_FLAG)

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_candidate_blaming(incident_id, SOME_FLAG),
                 a_candidate_blaming(incident_id, SOME_FLAG),
                 a_candidate_blaming_something_else],
                index=0,
                acted_on=SOME_FLAG
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            the_updates_carry("hypothesis", a_candidate_blaming_something_else),
            the_updates_carry("candidate_index", 2)))


@pytest.mark.unit
def test_a_candidate_naming_no_cause_is_never_tried() -> None:
    # The one thing on the list that is not an experiment. "I found no cause"
    # names nothing to change, which is a different answer from "I am unsure
    # which of these it is" - and acting on it would mean changing production
    # with no hypothesis behind the change at all.
    incident_id = a_random_id()

    Scenario() \
        .given(
            a_walk := _a_walk_at(
                incident_id,
                [a_determined_hypothesis(incident_id),
                 an_undetermined_hypothesis(incident_id)],
                index=0,
                rounds=_every_round()
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(_the_walk_goes_to(FIXING_ROUTE, a_walk),
                     _no_candidate_was_taken_up()))


@pytest.mark.unit
def test_a_candidate_answered_by_a_restart_already_taken_is_skipped() -> None:
    # The same guard, for the kind of action a candidate cannot name. A leak
    # is worded freshly by every round, so two candidates that read nothing
    # alike are one experiment - and the walk knows that only because it asks
    # what each would be answered with.
    #
    # It is also the one case that pins where a restart is addressed. The
    # service comes from the alert, not from the candidate: hand this node any
    # other service and the identities stop matching, the second leak is taken
    # up, and one service is restarted twice on one incident.
    incident_id = a_random_id()
    a_candidate_blaming_a_flag = a_candidate_blaming(incident_id, ANOTHER_FLAG)

    Scenario() \
        .given(
            a_walk := _a_walk_that_restarted_the_service(
                incident_id,
                [_a_leak_worded_as(incident_id, "resident set climbing"),
                 _a_leak_worded_as(incident_id, "unbounded cache growth"),
                 a_candidate_blaming_a_flag],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            the_updates_carry("hypothesis", a_candidate_blaming_a_flag),
            the_updates_carry("candidate_index", 2)))


@pytest.mark.unit
def test_a_candidate_answered_by_a_discard_already_taken_is_skipped() -> None:
    # The same guard once more, for the one action addressed by neither the
    # candidate nor the history. Two rounds word one stale cache two ways and
    # both are answered by discarding the entries the alert named - which this
    # node knows only while it is still passing those keys down. Stop passing
    # them and the second wording is taken up as though it were a new
    # experiment, on an incident where nothing has changed since the first.
    incident_id = a_random_id()
    a_candidate_blaming_a_flag = a_candidate_blaming(incident_id, ANOTHER_FLAG)

    Scenario() \
        .given(
            a_walk := _a_walk_that_discarded_entries(
                incident_id,
                [a_divergence_blamed_on(incident_id, "monthly totals look wrong"),
                 a_divergence_blamed_on(incident_id, "the cache fell behind"),
                 a_candidate_blaming_a_flag],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            the_updates_carry("hypothesis", a_candidate_blaming_a_flag),
            the_updates_carry("candidate_index", 2)))


@pytest.mark.unit
def test_a_corruption_answered_by_a_rollback_already_taken_is_skipped() -> None:
    # The guard once more, for the candidate whose answer is read off the deploy
    # history. Two rounds word one corruption two ways, and both are answered
    # by returning the deployment the platform recorded - which this node knows
    # only while it is still passing that history down. Stop passing it and the
    # second wording reads as answered by nothing, which the guard cannot match
    # against the rollback already taken.
    incident_id = a_random_id()
    a_candidate_blaming_a_flag = a_candidate_blaming(incident_id, ANOTHER_FLAG)

    Scenario() \
        .given(
            a_walk := _a_walk_that_rolled_back(
                incident_id,
                [a_corruption_blamed_on(incident_id, "monthly totals look wrong"),
                 a_corruption_blamed_on(incident_id, "the totals fell behind"),
                 a_candidate_blaming_a_flag],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            the_updates_carry("hypothesis", a_candidate_blaming_a_flag),
            the_updates_carry("candidate_index", 2)))


@pytest.mark.unit
def test_a_moved_replica_answered_by_a_pin_already_taken_is_skipped() -> None:
    # The guard once more, for the candidate whose answer is read off the
    # placement. Two wordings of one moved replica are both answered by holding
    # the fleet to its card - which this node knows only while it still hands the
    # placement down. Stop handing it and the second wording reads as answered by
    # nothing, which the guard cannot match against the pin already taken.
    incident_id = a_random_id()
    a_candidate_blaming_a_flag = a_candidate_blaming(incident_id, ANOTHER_FLAG)

    Scenario() \
        .given(
            a_walk := _a_walk_that_held_the_fleet_to_its_card(
                incident_id,
                [an_accelerator_blamed_on(incident_id, "one replica holds more"),
                 an_accelerator_blamed_on(incident_id, "the A100 replica differs"),
                 a_candidate_blaming_a_flag],
                index=0
            )
        ) \
        .when(lambda: next_candidate_node(a_walk, SOME_ROUND_BUDGET)) \
        .then(all_of(
            the_updates_carry("hypothesis", a_candidate_blaming_a_flag),
            the_updates_carry("candidate_index", 2)))


def _every_round() -> int:
    return SOME_ROUND_BUDGET


def _a_walk_at(incident_id: str,
               candidates: list[Hypothesis],
               index: int,
               acted_on: str = SOME_FLAG,
               rounds: int = 1) -> IncidentState:
    """An incident mid-walk: a candidate has just been tried and did not settle
    anything, and the state carries what it takes to decide what happens next.

    Nothing is carried in `already_read` throughout this file. The walk is
    bounded by how many times the incident may be investigated, not by how much
    of the window is left unread - a hard incident has usually read everything
    it can reach by the time the answer it found gets refuted, and that is
    exactly when another round is worth buying.
    """
    return IncidentState(
        incident_id=incident_id,
        alert=DONT_CARE_ALERT,
        status=IncidentStatus.MITIGATING,
        candidates=candidates,
        candidate_index=index,
        hypothesis=candidates[index],
        rounds=rounds,
        # The history the round read, holding every flag these candidates
        # blame. A candidate blaming a flag the provider never recorded is
        # answered by no action at all, and a case about which candidate comes
        # next would quietly become a case about none of them being answerable.
        flag_changes=[
            FlagChange(flag=flag, enabled=True, occurred_at=DONT_CARE_MOMENT)
            for flag in dict.fromkeys(
                candidate.subject
                for candidate in candidates if candidate.subject is not None
            )
        ],
        proposed_action=RevertFeatureFlag(
            flag=acted_on,
            enabled=False,
            undo_descriptor=FlagUndo(flag=acted_on, was_enabled=True)
        )
    )


def _a_walk_that_restarted_the_service(incident_id: str,
                                       candidates: list[Hypothesis],
                                       index: int) -> IncidentState:
    """The same walk, after the action that puts nothing back.

    A restart is addressed to the service the alert names, so that is what the
    attempt this node is about to remember is addressed to - and it is the
    only place these cases read the alert for anything.
    """
    return _a_walk_at(incident_id, candidates, index).model_copy(
        update={"proposed_action": RestartService(service=DONT_CARE_ALERT.service)}
    )


def _a_walk_that_discarded_entries(incident_id: str,
                                   candidates: list[Hypothesis],
                                   index: int) -> IncidentState:
    """The same walk, after the action whose address the alert had to supply.

    A discard is addressed to keys, and keys are the one thing neither the
    candidate nor the flag history carries - so what this node asks of a
    candidate can only be answered while it is still handing the alert's keys
    down. The alert is replaced rather than the action alone because an action
    naming entries the alert never found would be this file inventing the
    evidence the rule depends on.
    """
    the_entries_the_check_found = ("io-shop:summary:2026-09:shopper-4",
                                   "io-shop:summary:2026-09:shopper-9")
    the_alert_that_found_them = Alert(
        service=DONT_CARE_ALERT.service,
        alert_name="CachedSpendTotalsAreStale",
        stale_entry_keys=the_entries_the_check_found,
        stale_entries_found=len(the_entries_the_check_found)
    )

    return _a_walk_at(incident_id, candidates, index).model_copy(
        update={
            "alert": the_alert_that_found_them,
            "proposed_action": DiscardCacheEntries(
                service=the_alert_that_found_them.service,
                keys=the_entries_the_check_found
            )
        }
    )


def _a_walk_that_rolled_back(incident_id: str,
                             candidates: list[Hypothesis],
                             index: int) -> IncidentState:
    """The same walk, after returning the deployment the platform recorded.

    The deploy history is carried with it, because a corruption is answered by
    a rollback only where the platform recorded a deployment - so whether a
    second wording of one is the same experiment can only be known while this
    node is still handing that history down.

    The flag history holds the flag candidates' flags alone. `_a_walk_at`
    records every subject as a flag that moved, and a corruption's subject is
    prose - left in, it would be answered by a flag revert, and the case would
    be about the flag history instead of the deploy history.
    """
    return _a_walk_at(incident_id, candidates, index).model_copy(
        update={
            "flag_changes": [
                FlagChange(flag=candidate.subject, enabled=True,
                           occurred_at=DONT_CARE_MOMENT)
                for candidate in candidates
                if candidate.failure_mode is FailureMode.FEATURE_FLAG_TOGGLE
                and candidate.subject is not None
            ],
            "deployments": [a_deployment()],
            "proposed_action": RollBackDeployment(application=DONT_CARE_ALERT.service)
        }
    )


def _a_walk_that_held_the_fleet_to_its_card(incident_id: str,
                                            candidates: list[Hypothesis],
                                            index: int) -> IncidentState:
    """The same walk, after holding the fleet to the card it ran on.

    The placement is carried with it, because a moved replica is answered by a
    pin only where the round recorded one - so whether a second wording of it is
    the same experiment can only be known while this node is still handing that
    placement down. The flag history holds the flag candidates' flags alone, for
    `_a_walk_that_rolled_back`'s reason.
    """
    return _a_walk_at(incident_id, candidates, index).model_copy(
        update={
            "flag_changes": [
                FlagChange(flag=candidate.subject, enabled=True,
                           occurred_at=DONT_CARE_MOMENT)
                for candidate in candidates
                if candidate.failure_mode is FailureMode.FEATURE_FLAG_TOGGLE
                and candidate.subject is not None
            ],
            "placement": a_placement(),
            "proposed_action": PinToAccelerator(
                application=DONT_CARE_ALERT.service,
                accelerator="Tesla-V100-SXM2-16GB"
            )
        }
    )


def _a_leak_worded_as(incident_id: str, prose: str) -> Hypothesis:
    """A leak, named the way a model actually names one.

    Different prose at every call, which is the point: the subject is a
    description of the symptom, and two rounds describing one leak agree about
    nothing a comparison over candidates could use.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="something is accumulating and never released",
                      failure_mode=FailureMode.RESOURCE_LEAK,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=prose)


def _the_walk_goes_to(expected: str, state: IncidentState) -> Assertion[StateDelta]:
    """Where the graph takes the state this node produced.

    The status is derived rather than read off the updates, because the node no
    longer supplies one - so this asserts where the node's work actually leaves
    the incident, by exactly the path the graph takes. `narration` is dropped on
    the way, as the graph drops it: it is what the node said, not part of the
    state.
    """
    def assertion(updates: StateDelta) -> bool:
        work = updates.as_updates()
        after = state.model_copy(update=work)
        routed = route_after_next_candidate(
            after.model_copy(update={"status": status_after(after, _every_round())})
        )

        if routed != expected:
            raise AssertionError(
                f"Expected the walk to go to [{expected}], it went to [{routed}]."
            )

        return True

    return assertion


def _no_candidate_was_taken_up() -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if "hypothesis" in updates.model_fields_set:
            raise AssertionError(
                f"Expected no candidate to be taken up, the node took up "
                f"[{updates.hypothesis}]."
            )

        return True

    return assertion


def _the_attempts_recorded_are(expected: list[str]) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        recorded = [attempt.identity.subject for attempt in updates.attempts or []]
        if recorded != expected:
            raise AssertionError(
                f"Expected the attempts to record {expected}, they record {recorded}."
            )

        return True

    return assertion


def _the_candidate_selected_was(expected: Hypothesis,
                                published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """The explanation the next few lines are about, said out loud.

    Published rather than left to be inferred from the ranked list: the walk
    skips any candidate it cannot act on, so a reader given only the ranking
    cannot tell which one an attempt belongs to.
    """
    def assertion(dont_care_updates: StateDelta) -> bool:
        selected = [event for event in published if isinstance(event, CandidateSelected)]

        if not selected:
            raise AssertionError(
                f"Expected the candidate now under test to be published, got "
                f"{[event.kind for event in published]}."
            )

        if selected[0].hypothesis_id != expected.id:
            raise AssertionError(
                f"Expected [{expected.id}] published, got "
                f"[{selected[0].hypothesis_id}]."
            )

        return True

    return assertion


def _nothing_was_narrated() -> Assertion[StateDelta]:
    """Moving on to the next candidate moves the incident nowhere.

    It was mitigating before and is mitigating after, so there is no transition
    for a narration to account for - and a sentence returned anyway is what
    routed this into a second account of an event already published.
    """
    def assertion(updates: StateDelta) -> bool:
        if updates.narration is not None:
            raise AssertionError(
                f"Expected no narration where the incident moved nowhere, it "
                f"said [{updates.narration.action}]."
            )

        return True

    return assertion


def _a_walk_whose_platform_went(incident_id: str,
                                candidates: list[Hypothesis]) -> IncidentState:
    """A walk past its last candidate, with the deployment platform down.

    Past the last one on purpose. This node is reached with a platform down long
    before the list is spent - the rollback fails, the flag revert is still ahead
    - and that case is about which candidate comes next. This one is about the
    other ending: the platform took away everything that was left.
    """
    return _a_walk_at(incident_id, candidates, index=len(candidates) - 1) \
        .model_copy(update={"unreachable_platforms": [DEPLOYMENT_PLATFORM]})


def _what_it_said_names(*wanted: str) -> Assertion[StateDelta]:
    """The narration mentions each of these, wherever it puts them.

    Matched on substrings rather than on a whole sentence, because what is being
    held is which facts a person is given and not the prose around them. A test
    pinning the wording would fail on every rewording and pass a sentence that
    dropped a fact while keeping the shape.
    """
    def assertion(updates: StateDelta) -> bool:
        said = "" if updates.narration is None else (
            f"{updates.narration.action} {updates.narration.detail}"
        )
        missing = [one for one in wanted if one not in said]

        if missing:
            raise AssertionError(
                f"Expected what the walk said to name {missing}, and it said "
                f"[{said}]."
            )

        return True

    return assertion


def _what_it_said_does_not_name(*unwanted: str) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        said = "" if updates.narration is None else (
            f"{updates.narration.action} {updates.narration.detail}"
        )
        present = [one for one in unwanted if one in said]

        if present:
            raise AssertionError(
                f"Expected what the walk said not to name {present}, and it said "
                f"[{said}]."
            )

        return True

    return assertion
