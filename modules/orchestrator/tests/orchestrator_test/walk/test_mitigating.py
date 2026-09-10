from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import take_action
from argus_core.events import ActionTaken, IncidentEvent, Publisher, VerdictReached, nobody
from argus_core.models.action import Action, Outcome, Verdict
from argus_core.models.alert import Alert
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.undo_descriptor import UndoDescriptor
from argus_incidents.withdrawal import IsStillWanted
from argus_testkit import Assertion, Scenario, all_of, calling
from orchestrator.walk import ports
from orchestrator.walk.mitigating import mitigation_node, route_after_mitigation
from orchestrator.walk.routes import ESCALATED_ROUTE, NEXT_CANDIDATE_ROUTE, RESOLVED_ROUTE

from ..framework.builders import a_determined_hypothesis, a_random_id, an_incident_state

"""Performing the action the gate admitted, and recording what came of it.

The node reports the verdict it measured and never a status: where the incident
stands as a result is a conclusion drawn from it one place further out, and
drawing it here is how the same verdict came to mean two different statuses in
two places.

The other half is what a resumed walk does. The claim on an action is written
before the action and outlives the worker that wrote it, so a walk refused the
claim is a walk that has been resumed inside this node - and what it does next
depends on what the earlier attempt left behind: a recorded outcome, a change
that reached the provider with nothing measured after it, or nothing at all.
"""

type NodeResult = dict[str, Any]

DONT_CARE_FLAG = "dont-care-flag"
SOME_FLAG_THE_CANDIDATE_BLAMES = "monthly-spend-feature"
SOME_MOMENT_THE_CLAIM_WAS_WRITTEN = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)


@pytest.fixture
def record_action() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.RecordAction, instance=True))


@pytest.fixture
def complete_action() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.CompleteAction, instance=True))


@pytest.fixture
def take() -> MagicMock:
    return cast(MagicMock, create_autospec(take_action))


@pytest.fixture
def already_taken() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.ActionAlreadyTaken, instance=True))


@pytest.fixture
def claimed_at() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.ActionClaimedAt, instance=True))


@pytest.fixture
def still_wanted() -> MagicMock:
    wanted = cast(MagicMock, create_autospec(IsStillWanted, instance=True))
    wanted.return_value = True

    return wanted


@pytest.fixture
def change_landed() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.ChangeLanded, instance=True))


@pytest.fixture
def record_outcome() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.RecordOutcome, instance=True))


@pytest.mark.unit
def test_a_confirmed_action_reports_the_verdict_it_measured(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(_the_verdict_reported_is(str(Verdict.CONFIRMED)))


@pytest.mark.unit
def test_a_refuted_action_reports_the_verdict_it_measured(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(_the_verdict_reported_is(str(Verdict.REFUTED)))


@pytest.mark.unit
def test_an_escalated_outcome_is_reported_as_the_verdict_it_is(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.ESCALATED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(_the_verdict_reported_is(str(Verdict.ESCALATED)))


@pytest.mark.unit
def test_the_node_that_takes_the_action_decides_no_status(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The verdict is what this node measured; where the incident stands as a
    # result is a conclusion drawn from it elsewhere. Drawing it here is how the
    # same verdict came to mean two different statuses in two places.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(_no_status_was_decided())


@pytest.mark.unit
def test_the_action_row_records_the_undo_descriptor_the_write_returned(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The descriptor the write tier returned, not the one proposed: it is the
    # record of what actually changed, and it is what a human reading the
    # incident afterwards would have to act on.
    some_undo_descriptor = UndoDescriptor(flag=SOME_FLAG_THE_CANDIDATE_BLAMES,
                                          was_enabled=False,
                                          environment="production")

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take,
                                                  Verdict.CONFIRMED,
                                                  some_undo_descriptor)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(_the_action_row_records_the_way_back(some_undo_descriptor,
                                                   complete_action))


@pytest.mark.unit
def test_a_candidate_abandoned_mid_verification_is_not_recorded_as_tested(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # Withdrawn is not a verdict about the hypothesis. The action was taken and
    # then abandoned, so nothing was measured - and marking the candidate tested
    # would leave the incident claiming an explanation was ruled out by an
    # experiment that never finished.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.WITHDRAWN)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_determined_hypothesis(a_random_id())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(_the_candidate_learned_nothing(record_outcome))


@pytest.mark.unit
def test_an_abandoned_action_still_records_what_would_put_it_back(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The candidate learns nothing, but the action row must: the flag is still
    # changed, and the undo descriptor is the only record of what would restore
    # it. Without it the withdrawal has nothing to unwind.
    some_undo_descriptor = UndoDescriptor(flag=DONT_CARE_FLAG, was_enabled=True)

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take,
                                                  Verdict.WITHDRAWN,
                                                  some_undo_descriptor)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_determined_hypothesis(a_random_id())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_row_records_the_outcome((str(Verdict.WITHDRAWN)), complete_action),
                     _the_action_row_records_the_way_back(some_undo_descriptor,
                                                          complete_action)))


@pytest.mark.unit
def test_the_candidate_that_was_acted_on_records_what_the_attempt_settled(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # An action was taken and the service was measured afterwards, so this
    # candidate was genuinely tested - and the verdict is the answer it was
    # tested for. Without it the incident records a list of explanations and no
    # sign of which one the walk was on.
    some_candidate = a_determined_hypothesis(a_random_id())

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(), about=some_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(_the_candidate_was_tested_and_settled(some_candidate,
                                                    str(Verdict.REFUTED),
                                                    record_outcome))


@pytest.mark.unit
def test_a_walk_resumed_after_the_action_was_taken_does_not_take_it_again(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    record_outcome: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # A worker died inside this node and another took the run up. The claim is
    # already in the database, so this walk is refused it - and refusing it is
    # the whole guard: acting again would set a flag that is already set and,
    # worse, write a second attempt into an incident that made one.
    the_outcome_the_first_attempt_recorded = str(Verdict.CONFIRMED)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, the_outcome_the_first_attempt_recorded)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      record_outcome=record_outcome,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_not_taken(take),
                     _nothing_was_completed(complete_action),
                     _the_verdict_reported_is(the_outcome_the_first_attempt_recorded)))


@pytest.mark.unit
def test_a_walk_that_claimed_the_action_takes_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    record_outcome: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The other half, so the guard cannot pass by never acting at all: a walk
    # that got the claim is the one attempt, and it does the work.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      record_outcome=record_outcome,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_taken(take),
                     _no_earlier_outcome_was_looked_up(already_taken)))


@pytest.mark.unit
def test_a_claim_with_no_outcome_whose_change_landed_escalates(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    change_landed: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The worst state to find: the flag was changed and nobody measured what
    # happened next. Argus cannot invent that measurement, and acting again
    # would not produce it either - so it says so and stops.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None)),
            calling(lambda: _the_claim_was_written_at(
                claimed_at, SOME_MOMENT_THE_CLAIM_WAS_WRITTEN)),
            calling(lambda: _the_change_reached_the_provider(change_landed)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=_a_candidate_blaming(SOME_FLAG_THE_CANDIDATE_BLAMES)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      change_landed=change_landed,
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_not_taken(take),
                     _the_incident_was_escalated()))


@pytest.mark.unit
def test_a_claim_whose_change_never_landed_is_acted_on(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    change_landed: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The claim was written and the worker died before it reached the provider.
    # Nothing happened, so there is nothing to be careful about: this walk takes
    # the action the claim was for.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None)),
            calling(lambda: _the_claim_was_written_at(
                claimed_at, SOME_MOMENT_THE_CLAIM_WAS_WRITTEN)),
            calling(lambda: _the_change_never_reached_the_provider(change_landed)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=_a_candidate_blaming(SOME_FLAG_THE_CANDIDATE_BLAMES)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      change_landed=change_landed,
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_taken(take),
                     _the_verdict_reported_is(str(Verdict.CONFIRMED))))


@pytest.mark.unit
def test_a_claim_the_provider_cannot_answer_for_escalates(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    change_landed: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # Unreachable, or a deployment where Argus and its operators share a
    # credential. Either way nobody can say whether the change was made, and
    # acting on a guess is the one thing that is worse than stopping.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None)),
            calling(lambda: _the_claim_was_written_at(
                claimed_at, SOME_MOMENT_THE_CLAIM_WAS_WRITTEN)),
            calling(lambda: _the_provider_cannot_say(change_landed)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=_a_candidate_blaming(SOME_FLAG_THE_CANDIDATE_BLAMES)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      change_landed=change_landed,
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_not_taken(take),
                     _the_incident_was_escalated()))


@pytest.mark.unit
def test_an_action_that_settled_the_incident_is_routed_to_the_postmortem() -> None:
    Scenario() \
        .given(a_resolved_incident := _an_incident_in(IncidentStatus.RESOLVED)) \
        .when(lambda: route_after_mitigation(a_resolved_incident)) \
        .then(_the_route_is(RESOLVED_ROUTE))


@pytest.mark.unit
def test_a_refuted_action_is_handed_to_the_walk() -> None:
    # A refuted action stays in `mitigating` - the same phase of the same
    # incident, with another explanation about to be tried. It asks the walk
    # whether there is one, and Code-Fix is what happens when there is not.
    Scenario() \
        .given(a_mitigating_incident := _an_incident_in(IncidentStatus.MITIGATING)) \
        .when(lambda: route_after_mitigation(a_mitigating_incident)) \
        .then(_the_route_is(NEXT_CANDIDATE_ROUTE))


@pytest.mark.unit
def test_an_action_that_could_not_be_answered_for_reaches_a_human() -> None:
    Scenario() \
        .given(an_escalated_incident := _an_incident_in(IncidentStatus.ESCALATED)) \
        .when(lambda: route_after_mitigation(an_escalated_incident)) \
        .then(_the_route_is(ESCALATED_ROUTE))


@pytest.mark.unit
def test_the_graph_says_what_action_it_took_and_for_which_candidate(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The one moment production state changes. An account that omitted it
    # would describe an investigation rather than an intervention.
    published: list[IncidentEvent] = []
    some_candidate = a_determined_hypothesis(a_random_id())
    the_action = _an_action_with_an_undo_descriptor()

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=the_action, about=some_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_exactly_one_action_was_announced(some_candidate, the_action, published))


@pytest.mark.unit
def test_the_graph_says_which_way_it_moved_the_flag(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # "A flag was changed" is the half of the sentence nobody can act on.
    # Whether the service is now running with the feature on or off is the
    # whole point of the change.
    published: list[IncidentEvent] = []
    the_action = _an_action_with_an_undo_descriptor()

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(proposing=the_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_announced_action_moved_the_flag(the_action.enabled, published))


@pytest.mark.unit
def test_the_graph_says_what_verdict_came_back(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The verdict is what the action was for, and it arrives after it - two
    # lines in the narration, because they are two moments. It travels with the
    # verdict's own write rather than separately, so the two cannot disagree.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      claimed_at=claimed_at,
                                      still_wanted=still_wanted)) \
        .then(_the_verdict_was_narrated(str(Verdict.REFUTED), complete_action))


@pytest.mark.unit
def test_a_node_nobody_is_listening_to_does_the_same_thing(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    claimed_at: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The account is never part of the work, at this level as at every other.
    def run(publisher: Publisher) -> NodeResult:
        return mitigation_node(
            _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor()),
            take=take,
            record_action=record_action,
            complete_action=complete_action,
            record_outcome=record_outcome,
            already_taken=already_taken,
            claimed_at=claimed_at,
            still_wanted=still_wanted,
            publisher=publisher
        )

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
        ) \
        .when(
            lambda: (
                run(_a_listener()), 
                run(nobody)
            )
        ) \
        .then(_both_runs_did_the_same_work())


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    return an_incident_state(some_alert, status)


def _a_mitigating_incident(proposing: Action | None = None,
                           about: Hypothesis | None = None) -> IncidentState:
    state = _an_incident_in(IncidentStatus.MITIGATING)

    return state.model_copy(
        update={
            "hypothesis": about or a_determined_hypothesis(state.incident_id),
            "proposed_action": proposing
        }
    )


def _a_candidate_blaming(flag: str) -> Hypothesis:
    """The subject matters in the resumed cases: it is the flag the provider's
    log is asked about, so a candidate blaming nothing in particular would make
    the question unanswerable for a reason the test never meant to introduce."""
    return a_determined_hypothesis(a_random_id()).model_copy(update={"subject": flag})


def _an_action_with_an_undo_descriptor() -> Action:
    return Action(action_type="revert-feature-flag",
                  flag=DONT_CARE_FLAG,
                  enabled=False,
                  undo_descriptor=UndoDescriptor(flag=DONT_CARE_FLAG, was_enabled=True))


def _the_action_came_back(take: MagicMock,
                          verdict: Verdict,
                          undo_descriptor: UndoDescriptor | None = None) -> None:
    take.return_value = Outcome(verdict=verdict,
                                detail="dont care",
                                undo_descriptor=undo_descriptor)


def _this_walk_holds_the_claim(record_action: MagicMock) -> None:
    record_action.return_value = True


def _an_earlier_attempt_holds_the_claim(record_action: MagicMock,
                                        already_taken: MagicMock,
                                        nothing_recorded: str | None) -> None:
    """The claim was written by a worker that is gone. `nothing_recorded` is
    what it left against it - an outcome, or `None` where it stopped between
    taking the action and saying what happened."""
    record_action.return_value = False
    already_taken.return_value = nothing_recorded


def _the_claim_was_written_at(claimed_at: MagicMock, moment: datetime) -> None:
    claimed_at.return_value = moment


def _the_change_reached_the_provider(change_landed: MagicMock) -> None:
    change_landed.return_value = True


def _the_change_never_reached_the_provider(change_landed: MagicMock) -> None:
    change_landed.return_value = False


def _the_provider_cannot_say(change_landed: MagicMock) -> None:
    change_landed.return_value = None


def _the_verdict_reported_is(expected: str) -> Assertion[NodeResult]:
    def assertion(updates: NodeResult) -> bool:
        reported = updates.get("action_outcome")
        if reported != expected:
            raise AssertionError(
                f"expected the verdict [{expected}], the node reported [{reported}]"
            )

        return True

    return assertion


def _no_status_was_decided() -> Assertion[NodeResult]:
    def assertion(updates: NodeResult) -> bool:
        if "status" in updates:
            raise AssertionError(
                f"expected the node to decide no status, it decided "
                f"[{updates['status']}]"
            )

        return True

    return assertion


def _the_incident_was_escalated() -> Assertion[NodeResult]:
    """The one case where this node does name a status: nothing was measured
    and nothing can be, so there is no verdict for anything downstream to draw
    a conclusion from."""
    def assertion(updates: NodeResult) -> bool:
        if updates.get("status") != IncidentStatus.ESCALATED:
            raise AssertionError(
                f"expected the incident to be escalated, the node returned "
                f"[{updates.get('status')}]"
            )

        return True

    return assertion


def _the_action_row_records_the_way_back(expected: UndoDescriptor,
                                         complete_action: MagicMock
                                         ) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        recorded = complete_action.call_args.kwargs["undo_descriptor"]
        if recorded != expected:
            raise AssertionError(
                f"expected the action row to record {expected}, it recorded "
                f"{recorded}"
            )

        return True

    return assertion


def _the_action_row_records_the_outcome(expected: str,
                                        complete_action: MagicMock
                                        ) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        recorded = complete_action.call_args.kwargs["outcome"]
        if recorded != expected:
            raise AssertionError(
                f"expected the action row to record [{expected}], it recorded "
                f"[{recorded}]"
            )

        return True

    return assertion


def _the_candidate_learned_nothing(record_outcome: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if record_outcome.call_count != 0:
            raise AssertionError(
                f"expected the candidate to be left untouched, it was recorded "
                f"as {record_outcome.call_args_list}"
            )

        return True

    return assertion


def _the_candidate_was_tested_and_settled(candidate: Hypothesis,
                                          verdict: str,
                                          record_outcome: MagicMock
                                          ) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        recorded_about = record_outcome.call_args.args[0]
        if recorded_about != candidate.id:
            raise AssertionError(
                f"expected the outcome to be about [{candidate.id}], it was "
                f"about [{recorded_about}]"
            )

        recorded = record_outcome.call_args.kwargs
        if recorded["tested"] is not True:
            raise AssertionError(
                "expected the candidate to be recorded as having been tested"
            )

        if recorded["result"] != verdict:
            raise AssertionError(
                f"expected the candidate to record [{verdict}], it recorded "
                f"[{recorded['result']}]"
            )

        return True

    return assertion


def _the_action_was_taken(take: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if not take.called:
            raise AssertionError("expected the action to be taken, it was not")

        return True

    return assertion


def _the_action_was_not_taken(take: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if take.called:
            raise AssertionError(
                f"expected the action not to be taken, it was taken with "
                f"{take.call_args}"
            )

        return True

    return assertion


def _nothing_was_completed(complete_action: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        if complete_action.called:
            raise AssertionError(
                f"expected no action row to be completed, one was completed with "
                f"{complete_action.call_args}"
            )

        return True

    return assertion


def _no_earlier_outcome_was_looked_up(already_taken: MagicMock
                                      ) -> Assertion[NodeResult]:
    """A walk holding the claim has no earlier attempt to ask about, and asking
    anyway would mean the guard was reading state it had already ruled out."""
    def assertion(dont_care_result: NodeResult) -> bool:
        if already_taken.called:
            raise AssertionError(
                "expected no earlier outcome to be looked up, one was"
            )

        return True

    return assertion


def _the_route_is(expected: str) -> Assertion[str]:
    def assertion(route: str) -> bool:
        if route != expected:
            raise AssertionError(f"expected the route [{expected}], got [{route}]")

        return True

    return assertion


def _a_listener() -> Publisher:
    """A subscriber that does nothing with what it hears. What matters is that
    somebody is listening, not what they make of it."""
    published: list[IncidentEvent] = []

    return published.append


def _exactly_one_action_was_announced(candidate: Hypothesis,
                                      action: Action,
                                      published: list[IncidentEvent]
                                      ) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        taken = [event for event in published if isinstance(event, ActionTaken)]
        if len(taken) != 1:
            raise AssertionError(f"expected one action announced, got {len(taken)}")

        announced = taken[0]
        if (announced.hypothesis_id, announced.action_type) != (candidate.id,
                                                                action.action_type):
            raise AssertionError(
                f"expected [{action.action_type}] for candidate [{candidate.id}], "
                f"got [{announced.action_type}] for [{announced.hypothesis_id}]"
            )

        return True

    return assertion


def _the_announced_action_moved_the_flag(expected: bool,
                                         published: list[IncidentEvent]
                                         ) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        moved_to = [event.enabled for event in published
                    if isinstance(event, ActionTaken)]
        if moved_to != [expected]:
            raise AssertionError(
                f"expected the flag to be announced as [{expected}], got {moved_to}"
            )

        return True

    return assertion


def _the_verdict_was_narrated(expected: str,
                              complete_action: MagicMock) -> Assertion[NodeResult]:
    def assertion(dont_care_result: NodeResult) -> bool:
        narrating = complete_action.call_args.kwargs["narrating"]
        if not isinstance(narrating, VerdictReached):
            raise AssertionError(
                f"expected the verdict to be narrated as one, it was narrated as "
                f"[{type(narrating).__name__}]"
            )

        if narrating.outcome != expected:
            raise AssertionError(
                f"expected the narration to report [{expected}], it reported "
                f"[{narrating.outcome}]"
            )

        return True

    return assertion


def _both_runs_did_the_same_work() -> Assertion[tuple[NodeResult, NodeResult]]:
    def assertion(runs: tuple[NodeResult, NodeResult]) -> bool:
        listened_to, unheard = runs
        if listened_to != unheard:
            raise AssertionError(
                f"expected the same work with nobody listening, got {unheard} "
                f"instead of {listened_to}"
            )

        return True

    return assertion
