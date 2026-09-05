from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock, create_autospec

import agent_investigator
import pytest
from agent_mitigation import take_action
from agent_mitigation.tools import fetch_recent_flag_changes
from argus_core.models.action import Action, Outcome, Verdict
from argus_core.models.alert import Alert
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Scenario, all_of
from orchestrator import graph
from orchestrator.graph import (
    Narration,
    investigator_node,
    mitigation_node,
    mitigation_proposal_node,
    tier_gate_node,
)

from ..framework.assertions import assert_that
from ..framework.builders import (
    a_determined_hypothesis,
    a_random_id,
    an_incident_state,
    an_undetermined_hypothesis,
)

"""What each node does, which is its work and its account of it - never a status.

Where the incident stands is derived from these returns one place further out,
by `status_after`, and tested there. A node asserting a status here would be
asserting a decision it no longer makes.
"""

DONT_CARE_FLAG = "dont-care-flag"
DONT_CARE_MOMENT = "2026-08-20T11:05:00Z"


@pytest.fixture
def investigate() -> MagicMock:
    return cast(MagicMock, create_autospec(agent_investigator.investigate))


@pytest.fixture
def record_hypothesis() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.RecordHypothesis, instance=True))


@pytest.fixture
def record_outcome() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.RecordOutcome, instance=True))


@pytest.fixture
def record_action() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.RecordAction, instance=True))


@pytest.fixture
def complete_action() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.CompleteAction, instance=True))


@pytest.fixture
def fetch_flag_changes() -> MagicMock:
    return cast(MagicMock, create_autospec(fetch_recent_flag_changes))


@pytest.fixture
def take() -> MagicMock:
    return cast(MagicMock, create_autospec(take_action))


@pytest.fixture
def already_taken() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.ActionAlreadyTaken, instance=True))


@pytest.fixture
def claimed_at() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.ActionClaimedAt, instance=True))


@pytest.fixture
def change_landed() -> MagicMock:
    return cast(MagicMock, create_autospec(graph.ChangeLanded, instance=True))


@pytest.mark.unit
def test_investigator_node_offers_the_cause_it_named_as_the_one_to_try(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    an_investigating_incident_state = _an_investigating_incident()
    some_incident_id = an_investigating_incident_state.incident_id
    some_hypothesis = a_determined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            lambda: _investigation_returned(investigate, some_hypothesis)
        ) \
        .when(
            result := investigator_node(an_investigating_incident_state,
                                        investigate=investigate,
                                        record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            assert_that(result).is_equal_to(
                {
                    "hypothesis": some_hypothesis,
                    "candidates": [some_hypothesis],
                    "candidate_index": 0,
                    "already_read": [],
                    "rounds": 1,
                    "confidence": some_hypothesis.confidence,
                    "nothing_worth_trying": False,
                    "narration": Narration(
                        action="hypothesis formed",
                        result=some_hypothesis.summary,
                        confidence=some_hypothesis.confidence,
                    ),
                }
            ),
            assert_that(record_hypothesis).was_called_with(some_hypothesis),
        ))


@pytest.mark.unit
def test_a_doubtful_cause_is_still_offered_as_the_one_to_try(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # A cause was named, and that is the whole admission test for a reversible
    # mitigation. Confidence used to gate this, and it was the wrong question:
    # the action is taken alone, confirmed against the service and put back
    # when it does not help, so an unsure answer is a reason to try it and see -
    # not a reason to stop and fetch a human. The ambiguous incident, where the
    # model splits its confidence across two explanations, is exactly the one
    # this used to abandon and the walk exists to work through.
    an_investigating_incident_state = _an_investigating_incident()
    some_incident_id = an_investigating_incident_state.incident_id
    some_doubtful_confidence = 0.4
    a_doubtful_hypothesis = a_determined_hypothesis(
        some_incident_id, some_doubtful_confidence
    )

    Scenario() \
        .given(
            lambda: _investigation_returned(investigate, a_doubtful_hypothesis)
        ) \
        .when(
            result := investigator_node(an_investigating_incident_state,
                                        investigate=investigate,
                                        record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            assert_that(result["hypothesis"]).is_equal_to(a_doubtful_hypothesis),
            assert_that(result["nothing_worth_trying"]).is_equal_to(False),
        ))


@pytest.mark.unit
def test_investigator_node_reports_a_round_that_named_no_cause_at_all(
    investigate: MagicMock, record_hypothesis: MagicMock
) -> None:
    # The loop reached the end of what it could read and named nothing. The
    # timeline has to say *that*, not "hypothesis formed" - a human picking
    # the incident up needs to know whether to look for more evidence or to
    # doubt the one on file.
    #
    # `nothing_worth_trying` is the fact that carries it: it is what tells this
    # round apart from a walk that has worked through everything it was offered,
    # since the two leave the same candidate list behind.
    an_investigating_incident_state = _an_investigating_incident()
    some_incident_id = an_investigating_incident_state.incident_id
    a_hypothesis_with_no_cause = an_undetermined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            lambda: _investigation_returned(investigate, a_hypothesis_with_no_cause)
        ) \
        .when(
            result := investigator_node(an_investigating_incident_state,
                                        investigate=investigate,
                                        record_hypothesis=record_hypothesis)
        ) \
        .then(all_of(
            assert_that(result).is_equal_to(
                {
                    "hypothesis": a_hypothesis_with_no_cause,
                    "candidates": [a_hypothesis_with_no_cause],
                    "candidate_index": 0,
                    "already_read": [],
                    "rounds": 1,
                    "confidence": None,
                    "nothing_worth_trying": True,
                    "narration": Narration(
                        action="insufficient evidence",
                        result=a_hypothesis_with_no_cause.summary,
                        confidence=None,
                    ),
                }
            ),
            assert_that(record_hypothesis).was_called_with(a_hypothesis_with_no_cause),
        ))


@pytest.mark.unit
def test_the_proposal_node_proposes_an_action_for_the_flag_that_changed(
    fetch_flag_changes: MagicMock
) -> None:
    # The node reads the provider and hands the choice to the agent; nothing
    # mutating happens here, which is what leaves room for the gate between
    # this node and the one that acts.
    some_flag = "monthly-spend-feature"
    a_mitigating_incident = _a_mitigating_incident()
    fetch_flag_changes.return_value = [_an_enabling_of(some_flag)]

    result = mitigation_proposal_node(
        a_mitigating_incident, fetch_flag_changes=fetch_flag_changes
    )

    proposed = result["proposed_action"]
    assert proposed is not None
    assert proposed.flag == some_flag
    assert proposed.enabled is False


@pytest.mark.unit
def test_the_proposal_node_proposes_nothing_when_the_provider_cannot_be_read(
    fetch_flag_changes: MagicMock
) -> None:
    # "Nothing changed" and "I could not find out" both mean there is no action
    # to take, and neither is a reason to crash the graph - the incident goes
    # to a human, which is what an unreachable provider warrants.
    a_mitigating_incident = _a_mitigating_incident()
    fetch_flag_changes.side_effect = RuntimeError("the provider could not be reached")

    result = mitigation_proposal_node(
        a_mitigating_incident, fetch_flag_changes=fetch_flag_changes
    )

    assert result["proposed_action"] is None


@pytest.mark.unit
def test_the_gate_lets_an_action_carrying_an_undo_descriptor_through(
    record_outcome: MagicMock
) -> None:
    a_gated_incident = _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor())

    result = tier_gate_node(a_gated_incident, record_outcome=record_outcome)

    assert result == {}
    # The candidate is about to be put to the question, so nothing is known
    # about it yet - a row marked with an outcome here would be marked before
    # the experiment that produces one.
    assert record_outcome.call_count == 0


@pytest.mark.unit
def test_the_gate_rejects_an_action_whose_undo_descriptor_is_empty(
    record_outcome: MagicMock
) -> None:
    # The guarantee cannot rest on the agent that performs the write also
    # policing itself: a reversible action is only reversible if something
    # recorded how to reverse it, and this is the last point at which that can
    # still be checked for free.
    a_gated_incident = _a_mitigating_incident(proposing=_an_action_with_no_undo_descriptor())

    result = tier_gate_node(a_gated_incident, record_outcome=record_outcome)

    # The action is cleared rather than the incident ended: the gate is judging
    # this action, and whether anything follows it is the walk's call. It moves
    # the incident nowhere, so there is narration and no status.
    assert result["proposed_action"] is None
    assert "status" not in result
    assert result["narration"].action == "action rejected at the tier gate"
    assert "not reversible" in result["narration"].result


@pytest.mark.unit
def test_the_gate_rejects_an_incident_with_no_proposed_action(
    record_outcome: MagicMock
) -> None:
    a_gated_incident = _a_mitigating_incident()

    result = tier_gate_node(a_gated_incident, record_outcome=record_outcome)

    assert result["proposed_action"] is None
    assert "status" not in result
    assert result["narration"].result == "no reversible action was proposed for this cause"


@pytest.mark.unit
def test_a_candidate_the_gate_refused_is_recorded_as_never_having_been_tried(
    record_outcome: MagicMock
) -> None:
    # A refused action is not the candidate being wrong - it is the candidate
    # never having been put to the question, and its row has to say so. The
    # reason is written down here because this is the only place that knows it:
    # the rejection clears the action on the way out.
    some_candidate = a_determined_hypothesis(a_random_id())
    a_gated_incident = _a_mitigating_incident(
        proposing=_an_action_with_no_undo_descriptor(), about=some_candidate
    )

    tier_gate_node(a_gated_incident, record_outcome=record_outcome)

    assert record_outcome.call_args.args[0] == some_candidate.id
    assert record_outcome.call_args.kwargs["tested"] is False
    assert "not reversible" in record_outcome.call_args.kwargs["result"]


@pytest.mark.unit
def test_a_confirmed_action_reports_the_verdict_it_measured(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    record_outcome: MagicMock
) -> None:
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.CONFIRMED)

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             complete_action=complete_action,
                             record_outcome=record_outcome)

    assert result["action_outcome"] == "confirmed"


@pytest.mark.unit
def test_a_refuted_action_reports_the_verdict_it_measured(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    record_outcome: MagicMock
) -> None:
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.REFUTED)

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             complete_action=complete_action,
                             record_outcome=record_outcome)

    assert result["action_outcome"] == "refuted"


@pytest.mark.unit
def test_the_node_that_takes_the_action_decides_no_status(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    record_outcome: MagicMock
) -> None:
    # The verdict is what this node measured; where the incident stands as a
    # result is a conclusion drawn from it elsewhere. Drawing it here is how the
    # same verdict came to mean two different statuses in two places.
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.REFUTED)

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             complete_action=complete_action,
                             record_outcome=record_outcome)

    assert "status" not in result


@pytest.mark.unit
def test_an_escalated_outcome_is_reported_as_the_verdict_it_is(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    record_outcome: MagicMock
) -> None:
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.ESCALATED)

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             complete_action=complete_action,
                             record_outcome=record_outcome)

    assert result["action_outcome"] == "escalated"


@pytest.mark.unit
def test_the_action_row_records_the_undo_descriptor_the_write_returned(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    record_outcome: MagicMock
) -> None:
    # The descriptor the write tier returned, not the one proposed: it is the
    # record of what actually changed, and it is what a human reading the
    # incident afterwards would have to act on.
    some_undo_descriptor = {
        "tool": "set_feature_flag",
        "flag": "monthly-spend-feature",
        "environment": "production",
        "was_enabled": False,
    }
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    take.return_value = _an_outcome(Verdict.CONFIRMED, undo_descriptor=some_undo_descriptor)

    mitigation_node(an_action_taking_incident,
                    take=take,
                    complete_action=complete_action,
                    record_action=record_action,
                    record_outcome=record_outcome)

    assert complete_action.call_args.kwargs["undo_descriptor"] == some_undo_descriptor


@pytest.mark.unit
def test_the_candidate_that_was_acted_on_records_what_the_attempt_settled(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    record_outcome: MagicMock
) -> None:
    # An action was taken and the service was measured afterwards, so this
    # candidate was genuinely tested - and the verdict is the answer it was
    # tested for. Without it the incident records a list of explanations and no
    # sign of which one the walk was on.
    some_candidate = a_determined_hypothesis(a_random_id())
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor(), about=some_candidate
    )
    take.return_value = _an_outcome(Verdict.REFUTED)

    mitigation_node(an_action_taking_incident,
                    take=take,
                    complete_action=complete_action,
                    record_action=record_action,
                    record_outcome=record_outcome)

    assert record_outcome.call_args.args[0] == some_candidate.id
    assert record_outcome.call_args.kwargs["tested"] is True
    assert record_outcome.call_args.kwargs["result"] == "refuted"


@pytest.mark.unit
def test_a_walk_resumed_after_the_action_was_taken_does_not_take_it_again(
    take: MagicMock, record_action: MagicMock, complete_action: MagicMock,
    already_taken: MagicMock, record_outcome: MagicMock
) -> None:
    # A worker died inside this node and another took the run up. The claim is
    # already in the database, so this walk is refused it - and refusing it is
    # the whole guard: acting again would set a flag that is already set and,
    # worse, write a second attempt into an incident that made one.
    the_outcome_the_first_attempt_recorded = "confirmed"
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    record_action.return_value = False
    already_taken.return_value = the_outcome_the_first_attempt_recorded

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             complete_action=complete_action,
                             already_taken=already_taken,
                             record_outcome=record_outcome)

    assert take.called is False
    assert complete_action.called is False
    assert result["action_outcome"] == the_outcome_the_first_attempt_recorded


@pytest.mark.unit
def test_a_walk_that_claimed_the_action_takes_it(
    take: MagicMock, record_action: MagicMock, complete_action: MagicMock,
    already_taken: MagicMock, record_outcome: MagicMock
) -> None:
    # The other half, so the guard cannot pass by never acting at all: a walk
    # that got the claim is the one attempt, and it does the work.
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor()
    )
    record_action.return_value = True
    take.return_value = _an_outcome(Verdict.CONFIRMED)

    mitigation_node(an_action_taking_incident,
                    take=take,
                    record_action=record_action,
                    complete_action=complete_action,
                    already_taken=already_taken,
                    record_outcome=record_outcome)

    assert take.called is True
    assert already_taken.called is False


@pytest.mark.unit
def test_a_claim_with_no_outcome_whose_change_landed_escalates(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    already_taken: MagicMock, 
    claimed_at: MagicMock, 
    change_landed: MagicMock,
    record_outcome: MagicMock
) -> None:
    # The worst state to find: the flag was changed and nobody measured what
    # happened next. Argus cannot invent that measurement, and acting again
    # would not produce it either - so it says so and stops.
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor(),
        about=a_determined_hypothesis(a_random_id()).model_copy(
            update={"subject": "monthly-spend-feature"}
        ),
    )
    record_action.return_value = False
    already_taken.return_value = None
    claimed_at.return_value = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
    change_landed.return_value = True

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             complete_action=complete_action,
                             already_taken=already_taken,
                             claimed_at=claimed_at,
                             change_landed=change_landed,
                             record_outcome=record_outcome)

    assert take.called is False
    assert result["status"] == IncidentStatus.ESCALATED


@pytest.mark.unit
def test_a_claim_whose_change_never_landed_is_acted_on(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    already_taken: MagicMock, 
    claimed_at: MagicMock, 
    change_landed: MagicMock,
    record_outcome: MagicMock
) -> None:
    # The claim was written and the worker died before it reached the provider.
    # Nothing happened, so there is nothing to be careful about: this walk takes
    # the action the claim was for.
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor(),
        about=a_determined_hypothesis(a_random_id()).model_copy(
            update={"subject": "monthly-spend-feature"}
        ),
    )
    record_action.return_value = False
    already_taken.return_value = None
    claimed_at.return_value = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
    change_landed.return_value = False
    take.return_value = _an_outcome(Verdict.CONFIRMED)

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             complete_action=complete_action,
                             already_taken=already_taken,
                             claimed_at=claimed_at,
                             change_landed=change_landed,
                             record_outcome=record_outcome)

    assert take.called is True
    assert result["action_outcome"] == "confirmed"


@pytest.mark.unit
def test_a_claim_the_provider_cannot_answer_for_escalates(
    take: MagicMock, 
    record_action: MagicMock, 
    complete_action: MagicMock,
    already_taken: MagicMock, 
    claimed_at: MagicMock, 
    change_landed: MagicMock,
    record_outcome: MagicMock
) -> None:
    # Unreachable, or a deployment where Argus and its operators share a
    # credential. Either way nobody can say whether the change was made, and
    # acting on a guess is the one thing that is worse than stopping.
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor(),
        about=a_determined_hypothesis(a_random_id()).model_copy(
            update={"subject": "monthly-spend-feature"}
        ),
    )
    record_action.return_value = False
    already_taken.return_value = None
    claimed_at.return_value = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
    change_landed.return_value = None

    result = mitigation_node(an_action_taking_incident,
                             take=take,
                             record_action=record_action,
                             complete_action=complete_action,
                             already_taken=already_taken,
                             claimed_at=claimed_at,
                             change_landed=change_landed,
                             record_outcome=record_outcome)

    assert take.called is False
    assert result["status"] == IncidentStatus.ESCALATED


def _an_investigating_incident() -> IncidentState:
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    return an_incident_state(some_alert, IncidentStatus.INVESTIGATING)


def _a_mitigating_incident(
    proposing: Action | None = None, about: Hypothesis | None = None
) -> IncidentState:
    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    return state.model_copy(
        update={
            "hypothesis": about or a_determined_hypothesis(state.incident_id),
            "proposed_action": proposing,
        }
    )


def _an_enabling_of(flag: str) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at=DONT_CARE_MOMENT)


def _an_action_with_an_undo_descriptor() -> Action:
    return Action(
        action_type="revert-feature-flag",
        flag=DONT_CARE_FLAG,
        enabled=False,
        undo_descriptor={"tool": "set_feature_flag", "flag": DONT_CARE_FLAG,
                         "was_enabled": True},
    )


def _an_action_with_no_undo_descriptor() -> Action:
    return Action(
        action_type="revert-feature-flag",
        flag=DONT_CARE_FLAG,
        enabled=False,
        undo_descriptor={},
    )


def _an_outcome(verdict: Verdict,
                undo_descriptor: dict[str, object] | None = None) -> Outcome:
    return Outcome(
        verdict=verdict,
        detail="dont care",
        undo_descriptor=undo_descriptor or {},
    )


def _investigation_returned(investigate: MagicMock, hypothesis: Hypothesis) -> None:
    investigate.return_value = agent_investigator.Findings(
        candidates=[hypothesis], already_read=[]
    )
