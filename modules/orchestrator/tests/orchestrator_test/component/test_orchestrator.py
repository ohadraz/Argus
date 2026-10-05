"""The whole walk, through the graph the Orchestrator actually assembles.

Every node is the real one, so what is under test is the module: that a node's
work implies a status, that the status is derived and written once, that the
router reading it reaches a node that exists, and that an incident arrives at
an ending §10 has a name for. Only what lies outside the Orchestrator is
doubled - the agents it delegates to and the repositories it writes through,
both of which it already names as ports.

That leaves no database, no model and no flag provider, so this says the same
thing about the same graph that `e2e` does and says it in a second. What it
cannot say is whether the agents behind those ports are any good; that is
theirs to answer, one module down.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from agent_investigator import Findings
from agent_mitigation import Action, Outcome, Verdict
from argus_core import get_settings
from argus_core.events import Publisher, nobody
from argus_core.models import (
    Alert,
    Attempt,
    Evidence,
    FailureMode,
    FlagChange,
    Hypothesis,
    IncidentStatus,
    PostmortemDocument,
    Reading,
    RevertFeatureFlag,
    RollBackDeployment,
)
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing
from argus_testkit import Assertion, Scenario, all_of
from langgraph.checkpoint.memory import MemorySaver
from orchestrator.walk import ports
from orchestrator.walk.assembling import Collaborators
from orchestrator.walk.graph import (
    CODEFIX_NODE,
    INVESTIGATOR_NODE,
    MITIGATION_NODE,
    MITIGATION_PROPOSAL_NODE,
    NEXT_CANDIDATE_NODE,
    POSTMORTEM_NODE,
    REMEMBERING_NODE,
    TIER_GATE_NODE,
    build_graph,
    recursion_limit,
)
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.builders import (
    a_corruption_blamed_on,
    a_deployment,
    a_random_id,
    the_incident_is_still_wanted,
    the_incident_was_withdrawn,
)

type Walked = tuple[IncidentState, list[str]]

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"
DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")

EVERY_ROUND = get_settings().investigation_max_rounds
A_GENEROUS_BUDGET = recursion_limit(max_rounds=EVERY_ROUND, max_candidates=4)
SOME_ROUND_BUDGET = 3
# The cap is not what any case here turns on, and a walk that reaches it would
# stop for a reason the test never asked about.
EVERY_ATTEMPT_A_WALK_MAKES = 99


@pytest.fixture
def collaborators(transition_incident: MagicMock) -> Collaborators:
    """Every port answered by the least eventful thing that can answer it.

    A test then names only the ports its own case turns on, and what it does
    not name cannot be what made it pass.
    """
    return Collaborators(
        investigate=_an_investigation_offering(a_candidate_blaming(SOME_FLAG)),
        max_rounds=SOME_ROUND_BUDGET,
        record_hypothesis=lambda dont_care_hypothesis: None,
        fetch_flag_changes=_a_provider_reporting(_an_enabling_of(SOME_FLAG)),
        fetch_deployments=lambda **dont_care_question: [],
        fetch_dependencies=lambda dont_care_service: [],
        record_outcome=lambda *dont_care_args, **dont_care_keywords: None,
        admitted=lambda dont_care_action: True,
        attempts_per_subject=EVERY_ATTEMPT_A_WALK_MAKES,
        take=_an_action_that(Verdict.CONFIRMED),
        record_action=lambda *dont_care_args, **dont_care_keywords: True,
        complete_action=lambda *dont_care_args, **dont_care_keywords: None,
        already_taken=lambda incident_id, hypothesis_id: None,
        change_landed=_a_change_that_never_landed(),
        propose_fix=lambda dont_care_hypothesis, dont_care_incident_id: None,
        actions_taken=lambda dont_care_incident: [],
        recall_similar=lambda dont_care_description, dont_care_service: [],
        remember_incident=lambda dont_care_record: None,
        write_postmortem=lambda dont_care_incident: _a_document(),
        record_postmortem=lambda dont_care_incident, dont_care_document: None,
        transition_incident=transition_incident,
        publisher=nobody,
        recorder=records_nothing,
        still_wanted=the_incident_is_still_wanted()
    )


@pytest.mark.component
def test_an_action_that_helps_ends_the_incident_in_a_postmortem(
    collaborators: Collaborators
) -> None:
    # The happy path, whole: one investigation, one candidate, one action, and
    # the service recovers - and then Code-Fix, because a mitigation that
    # worked leaves a fault in the code with a flag holding it off. Every node
    # between the alert and the document is reached exactly once.
    Scenario() \
        .given(everything_works := collaborators) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), everything_works)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.MITIGATED)))


@pytest.mark.component
def test_an_investigation_that_names_no_cause_reaches_a_human(
    collaborators: Collaborators
) -> None:
    # Nothing to try is not a reason to act. The walk is over before it starts,
    # and it still ends in a postmortem: an incident nobody could explain is
    # one somebody has to read about.
    Scenario() \
        .given(
            an_investigation_finding_nothing := replace(
                collaborators,
                investigate=_an_investigation_offering(_a_candidate_naming_no_cause())
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   an_investigation_finding_nothing)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE, REMEMBERING_NODE, POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.ESCALATED)))


@pytest.mark.component
def test_a_refuted_action_is_followed_by_the_next_explanation(
    collaborators: Collaborators
) -> None:
    # The loop, and the reason the walk exists. Being wrong about a correlated
    # change is the ordinary case in an incident, so a refuted action sends the
    # incident back for the next candidate rather than to a human - and the
    # second attempt is a whole attempt, gate included.
    Scenario() \
        .given(
            a_first_answer_that_does_not_hold := replace(
                collaborators,
                investigate=_an_investigation_offering(
                    a_candidate_blaming(SOME_FLAG), a_candidate_blaming(ANOTHER_FLAG)
                ),
                fetch_flag_changes=_a_provider_reporting(_an_enabling_of(SOME_FLAG),
                                                         _an_enabling_of(ANOTHER_FLAG)),
                take=_actions_that(Verdict.REFUTED, Verdict.CONFIRMED)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   a_first_answer_that_does_not_hold)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           NEXT_CANDIDATE_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.MITIGATED)))


@pytest.mark.component
def test_a_walk_with_no_action_left_to_try_ends_at_code_fix_and_a_human(
    collaborators: Collaborators
) -> None:
    # The provider reports nothing that matches the explanation, so no action
    # is proposed and the gate refuses what it was not given. With the last
    # round spent, what remains is a permanent fix - and when Code-Fix has none
    # either, a person.
    Scenario() \
        .given(
            a_provider_reporting_nothing_relevant := replace(
                collaborators, fetch_flag_changes=_a_provider_reporting()
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_on_its_last_round(),
                                   a_provider_reporting_nothing_relevant)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           NEXT_CANDIDATE_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.ESCALATED)))


@pytest.mark.component
def test_an_incident_nobody_wants_any_more_leaves_the_graph_at_once(
    collaborators: Collaborators,
    transition_incident: MagicMock
) -> None:
    # Asked before the node rather than after: a node that has already toggled
    # a flag cannot be stopped by anything done with its return value. Nothing
    # runs, nothing is written, and the walk leaves the graph from where it
    # stood - the row already says withdrawn, and whoever withdrew it recorded
    # that.
    Scenario() \
        .given(
            an_incident_withdrawn := replace(
                collaborators, still_wanted=the_incident_was_withdrawn()
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), an_incident_withdrawn)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE),
                     _the_incident_ended(IncidentStatus.WITHDRAWN),
                     _nothing_was_written(transition_incident)))


@pytest.mark.component
def test_an_action_nothing_could_confirm_is_recommended_rather_than_taken(
    collaborators: Collaborators
) -> None:
    # The gate's one refusal that is not a judgement on the action. The alert
    # dated this incident because no series could, so nothing would say
    # afterwards whether the revert worked - and an action taken, reported and
    # never judged leaves an incident that looks handled. The walk still reaches
    # Code-Fix, for the reason a mitigation that worked does: nobody is putting
    # the flag back, so the fault behind it is the only thing anybody gets.
    Scenario() \
        .given(
            a_cause_only_next_week_could_confirm := replace(
                collaborators,
                investigate=_an_investigation_offering(
                    a_candidate_blaming(
                        SOME_FLAG,
                        failure_mode=FailureMode.SILENT_DATA_CORRUPTION)
                )
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_dated_by_its_alert(),
                                   a_cause_only_next_week_could_confirm)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.RECOMMENDED),
            _the_action_recommended_was(SOME_FLAG)))


@pytest.mark.component
def test_a_corruption_a_deployment_left_behind_is_recommended_a_rollback(
    collaborators: Collaborators
) -> None:
    # The same damage as the flag case above, left by the other kind of change.
    # The flag history is quiet and the platform recorded a deployment, so the
    # change to undo is the deployment - and it is recommended rather than
    # taken for the same reason: the readings already cover the incident, and a
    # rollback reports nothing of its own that would say whether it worked.
    Scenario() \
        .given(
            a_deployment_behind_the_damage := replace(
                collaborators,
                investigate=_an_investigation_offering(
                    a_corruption_blamed_on("dont-care", "some prose")
                ),
                fetch_flag_changes=_a_provider_reporting(),
                fetch_deployments=lambda **dont_care_question: [a_deployment()]
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_dated_by_its_alert(),
                                   a_deployment_behind_the_damage)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.RECOMMENDED),
            _a_rollback_of_the_alerting_service_was_recommended()))


@pytest.mark.component
def test_a_mode_nothing_answers_goes_to_code_fix_past_a_rollback_it_could_have_taken(
    collaborators: Collaborators
) -> None:
    # The leading explanation is a deliberate change the monitoring did not
    # follow, and nothing answers it. The second is a bad deployment, which a
    # rollback answers, and a deployment is recorded for it to roll back - so
    # the walk has a move it could make and must not. It goes straight to
    # Code-Fix: no second candidate, no second round, and nothing taken.
    Scenario() \
        .given(
            a_rollback_within_reach := replace(
                collaborators,
                investigate=_an_investigation_offering(
                    a_candidate_blaming(
                        "dont-care",
                        failure_mode=FailureMode.MONITORING_CONFIGURATION_DRIFT
                    ),
                    a_candidate_blaming(
                        "dont-care", failure_mode=FailureMode.BAD_DEPLOYMENT
                    )
                ),
                fetch_flag_changes=_a_provider_reporting(),
                fetch_deployments=lambda **dont_care_question: [a_deployment()]
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   a_rollback_within_reach)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE),
            _the_incident_ended(IncidentStatus.ESCALATED)))


def _the_walk_of(incident: IncidentState, collaborators: Collaborators) -> Walked:
    """One incident through the compiled graph, and the nodes it passed.

    The nodes are recorded by wrapping the graph's own stream rather than the
    nodes themselves, so what is asserted is the path LangGraph actually took.
    """
    graph = build_graph(MemorySaver(), collaborators)
    config: Any = {"configurable": {"thread_id": incident.incident_id},
                   "recursion_limit": A_GENEROUS_BUDGET}
    visited: list[str] = []
    final = incident

    for step in graph.stream(incident, config=config, stream_mode="updates"):
        for name, updates in step.items():
            visited.append(name)
            final = final.model_copy(update=updates)

    return final, visited


def _an_incident_just_alerted() -> IncidentState:
    return IncidentState(incident_id=a_random_id(),
                         alert=DONT_CARE_ALERT,
                         status=IncidentStatus.INVESTIGATING)


def _an_incident_on_its_last_round() -> IncidentState:
    """One round short of the budget, so the investigation about to run is the
    last one this incident gets."""
    return _an_incident_just_alerted().model_copy(update={"rounds": EVERY_ROUND - 1})


def _an_incident_dated_by_its_alert() -> IncidentState:
    """An incident whose onset only the alert could state.

    One inference rather than a flag: an alert dating the incident means the
    series measured no departure, which means nothing would mark a recovery
    either. A week back, because that is the distance at which a weekly
    integrity check finds a fault nothing else noticed.
    """
    a_week_before_anybody_noticed = datetime(2026, 8, 13, 11, 0, tzinfo=UTC)

    return IncidentState(
        incident_id=a_random_id(),
        alert=DONT_CARE_ALERT.model_copy(
            update={"stated_onset": a_week_before_anybody_noticed}),
        status=IncidentStatus.INVESTIGATING
    )


def a_candidate_blaming(
    flag: str,
    failure_mode: FailureMode = FailureMode.FEATURE_FLAG_TOGGLE
) -> Hypothesis:
    """A candidate naming one flag as the cause.

    The mode is a parameter because two of these walks differ in nothing else:
    a toggle and a silent corruption are both answered by putting the flag
    back, and what separates them is whether anything could confirm it.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id="dont-care",
                      summary=f"the {flag} flag was switched on",
                      failure_mode=failure_mode,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=flag)


def _a_candidate_naming_no_cause() -> Hypothesis:
    return Hypothesis(incident_id="dont-care",
                      summary="no cause determined from the evidence retrieved",
                      failure_mode=None,
                      confidence=None,
                      supporting_evidence=[Evidence(claim="some log line", at=None)])


def _an_enabling_of(flag: str) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at="2026-08-20T11:05:00Z")


def _an_investigation_offering(*candidates: Hypothesis) -> ports.Investigate:
    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    already_read: Sequence[Reading] | None = None,
                    already_refuted: Sequence[Attempt] | None = None,
                    publisher: Publisher = nobody,
                    recorder: Recorder = records_nothing) -> Findings:
        return Findings(
            candidates=[candidate.model_copy(update={"incident_id": incident_id})
                        for candidate in candidates],
            already_read=[]
        )

    return investigate


def _a_provider_reporting(*changes: FlagChange) -> ports.FetchFlagChanges:
    """Whatever the provider recorded, whichever window it is asked about.

    The onset is taken and ignored: which window these changes would fall in is
    settled where the window is built, and a double that filtered on it would be
    a second implementation of that rule agreeing with itself. Named rather than
    starred, so that a caller passing it positionally stops here instead of
    landing on a parameter this does not have.
    """
    def fetch_flag_changes(*, onset: datetime | None) -> list[FlagChange]:
        return list(changes)

    return fetch_flag_changes


def _an_action_that(verdict: Verdict) -> ports.TakeAction:
    return _actions_that(verdict)


def _actions_that(*verdicts: Verdict) -> ports.TakeAction:
    """One verdict per attempt, in the order the walk makes them - which is how
    a walk whose first answer is refuted and whose second holds is stated."""
    answers = iter(verdicts)
    last = verdicts[-1]

    def take(action: Action,
             /,
             *,
             still_wanted: Any = None,
             incident_id: str | None = None,
             publisher: Publisher = nobody,
             onset: datetime | None = None) -> Outcome:
        # Only one kind of action leaves anything behind, and the stand-in
        # hands back exactly what the real one would.
        the_way_back = (
            action.undo_descriptor if isinstance(action, RevertFeatureFlag) else None
        )

        return Outcome(verdict=next(answers, last),
                       detail="dont care",
                       undo_descriptor=the_way_back)

    return take


def _a_change_that_never_landed() -> ports.ChangeLanded:
    def change_landed(flag: str, since: datetime) -> bool | None:
        return False

    return change_landed


def _a_document() -> PostmortemDocument:
    return PostmortemDocument(root_cause=None,
                              executive_summary=None,
                              customer_loss_estimate=None,
                              estimate_currency=None,
                              engineer_minutes=None,
                              responders=None,
                              tokens_spent=None,
                              assumptions=[],
                              checklist_complete=False)


def _the_walk_went(*expected: str) -> Assertion[Walked]:
    def assertion(walked: Walked) -> bool:
        dont_care_final, visited = walked
        if visited != list(expected):
            raise AssertionError(
                f"Expected the walk to go {list(expected)}, it went {visited}"
            )

        return True

    return assertion


def _the_incident_ended(expected: IncidentStatus) -> Assertion[Walked]:
    def assertion(walked: Walked) -> bool:
        final, dont_care_visited = walked
        if final.status != expected:
            raise AssertionError(
                f"Expected the incident to end [{expected}], it ended [{final.status}]."
            )

        return True

    return assertion


def _nothing_was_written(transition_incident: MagicMock) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if transition_incident.called:
            raise AssertionError(
                f"Expected nothing to be written, got "
                f"{transition_incident.call_args_list}"
            )

        return True

    return assertion


def _a_rollback_of_the_alerting_service_was_recommended() -> Assertion[Walked]:
    """The rollback the incident is left recommending, and what it is addressed to.

    Addressed by relation rather than by name: a rollback answers the service
    that alerted, so a recommendation naming any other application is one
    somebody would carry out against the wrong deployment.
    """
    def assertion(walked: Walked) -> bool:
        final, dont_care_visited = walked

        if not isinstance(final.recommended_action, RollBackDeployment):
            raise AssertionError(
                f"Expected the incident to recommend rolling a deployment back, "
                f"it recommends [{final.recommended_action!r}]."
            )

        if final.recommended_action.application != final.alert.service:
            raise AssertionError(
                f"Expected the rollback to be addressed to the alerting service "
                f"[{final.alert.service}], it is addressed to "
                f"[{final.recommended_action.application}]."
            )

        return True

    return assertion


def _the_action_recommended_was(flag: str) -> Assertion[Walked]:
    """What the incident is left recommending, and what it is addressed to.

    The status alone would pass on a walk that recommended nothing and derived
    `RECOMMENDED` from something else. The whole of this ending is that
    somebody is handed an action, so the action is what is asserted.
    """
    def assertion(walked: Walked) -> bool:
        final, dont_care_visited = walked

        if not isinstance(final.recommended_action, RevertFeatureFlag):
            raise AssertionError(
                f"Expected the incident to recommend putting a flag back, it "
                f"recommends [{final.recommended_action!r}]."
            )

        if final.recommended_action.flag != flag:
            raise AssertionError(
                f"Expected the recommendation to name [{flag}], it names "
                f"[{final.recommended_action.flag}]."
            )

        return True

    return assertion
