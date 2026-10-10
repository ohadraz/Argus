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
from argus_core.budget import StillWanted, wanted_throughout
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
from argus_incidents import EndedByAPerson, WaitForPeople
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
    a_person_ended_the_incident,
    a_random_id,
    nobody_ended_the_incident,
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
        propose_fix=lambda dont_care_hypothesis, dont_care_incident_id, **dont_care_keywords: None,
        actions_taken=lambda dont_care_incident: [],
        recall_similar=lambda dont_care_description, dont_care_service: [],
        remember_incident=lambda dont_care_record: None,
        write_postmortem=lambda dont_care_incident: _a_document(),
        record_postmortem=lambda dont_care_incident, dont_care_document: None,
        transition_incident=transition_incident,
        publisher=nobody,
        recorder=records_nothing,
        ended_by_a_person=nobody_ended_the_incident(),
        wait_for_people=lambda dont_care_incident_id, /: False
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
                collaborators,
                ended_by_a_person=a_person_ended_the_incident(IncidentStatus.WITHDRAWN)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), an_incident_withdrawn)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE),
                     _the_incident_ended(IncidentStatus.WITHDRAWN),
                     _nothing_was_written(transition_incident)))


@pytest.mark.component
def test_the_investigation_is_handed_the_walks_own_question(
    collaborators: Collaborators
) -> None:
    # The investigator stops between turns only if the question it holds is the
    # walk's. Any other - the default nobody can answer "no" to - would leave it
    # reading for minutes after a person said stop.
    asked: list[str] = []
    reached: list[bool] = []

    Scenario() \
        .given(
            a_traced_walk := replace(
                collaborators,
                investigate=_an_investigation_whose_question_is_traced(asked, reached),
                ended_by_a_person=_a_question_counting_its_asks(asked)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_traced_walk)) \
        .then(_the_question_reached_the_walk(reached))


@pytest.mark.component
def test_code_fix_is_handed_the_walks_own_question(
    collaborators: Collaborators
) -> None:
    # The same wiring at the other loop that reads for minutes, and the one that
    # ends in a write: a branch and a pull request nobody wants any more.
    asked: list[str] = []
    reached: list[bool] = []

    Scenario() \
        .given(
            a_traced_walk := replace(
                collaborators,
                propose_fix=_a_fix_channel_whose_question_is_traced(asked, reached),
                ended_by_a_person=_a_question_counting_its_asks(asked)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_traced_walk)) \
        .then(_the_question_reached_the_walk(reached))


@pytest.mark.component
def test_an_incident_resolved_before_its_walk_is_written_up_and_nothing_else(
    collaborators: Collaborators,
    transition_incident: MagicMock
) -> None:
    # Resolved while the run was still queued. Nothing is investigated or
    # tried, and nothing is written over the person's status - but the
    # incident is remembered and written up, which is what they are owed.
    recorded: list[str] = []

    Scenario() \
        .given(
            an_incident_resolved := replace(
                collaborators,
                ended_by_a_person=a_person_ended_the_incident(IncidentStatus.RESOLVED),
                record_postmortem=lambda incident_id, dont_care_document: recorded.append(
                    incident_id)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), an_incident_resolved)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE, REMEMBERING_NODE, POSTMORTEM_NODE),
                     _the_incident_ended(IncidentStatus.RESOLVED),
                     _a_postmortem_was_recorded(recorded),
                     _nothing_was_written(transition_incident)))


@pytest.mark.component
def test_an_incident_resolved_after_an_action_skips_code_fix_and_is_written_up(
    collaborators: Collaborators
) -> None:
    # The person reported it over while Argus's change was being verified. The
    # walk goes no further with it - no Code-Fix, whatever the action came to -
    # and on to remembering and the write-up.
    acted: list[bool] = []
    recorded: list[str] = []

    Scenario() \
        .given(
            resolved_once_it_acted := replace(
                collaborators,
                take=_an_action_noting_it_landed(acted, Verdict.CONFIRMED),
                ended_by_a_person=_resolved_once_it_acted(acted),
                record_postmortem=lambda incident_id, dont_care_document: recorded.append(
                    incident_id)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), resolved_once_it_acted)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE,
                                    MITIGATION_PROPOSAL_NODE,
                                    TIER_GATE_NODE,
                                    MITIGATION_NODE,
                                    REMEMBERING_NODE,
                                    POSTMORTEM_NODE),
                     _the_incident_ended(IncidentStatus.RESOLVED),
                     _a_postmortem_was_recorded(recorded)))


@pytest.mark.component
def test_a_person_answering_while_the_walk_waits_ends_it_before_code_fix(
    collaborators: Collaborators
) -> None:
    # A person said it was over, and the walk waited for their answer once its
    # change was verified. Their press lands during the wait, so Code-Fix is
    # never entered - however long the press took.
    acted: list[bool] = []
    answered: list[bool] = []

    Scenario() \
        .given(
            answered_while_waiting := replace(
                collaborators,
                take=_an_action_noting_it_landed(acted, Verdict.CONFIRMED),
                wait_for_people=_a_person_answering_once_it_acted(acted, answered),
                ended_by_a_person=_resolved_once_it_acted(answered)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), answered_while_waiting)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE,
                                    MITIGATION_PROPOSAL_NODE,
                                    TIER_GATE_NODE,
                                    MITIGATION_NODE,
                                    REMEMBERING_NODE,
                                    POSTMORTEM_NODE),
                     _the_incident_ended(IncidentStatus.RESOLVED)))


@pytest.mark.component
def test_nothing_is_waited_for_once_the_postmortem_is_written(
    collaborators: Collaborators
) -> None:
    # The last step has no next one to hold off. A walk that waited after it
    # would leave the incident open for five minutes over nothing.
    happened: list[str] = []

    Scenario() \
        .given(
            noting_what_happened := replace(
                collaborators,
                wait_for_people=_a_wait_noting(happened),
                write_postmortem=_a_postmortem_noting(happened)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), noting_what_happened)) \
        .then(_the_last_thing_that_happened_was(happened, "written"))


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
                    recorder: Recorder = records_nothing,
                    still_wanted: StillWanted = wanted_throughout) -> Findings:
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
             onset: datetime | None = None,
             rule: str | None = None) -> Outcome:
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


def _a_question_counting_its_asks(asked: list[str]) -> EndedByAPerson:
    """The walk's own question, answered "nobody", keeping who it was asked about."""
    def ended_by_a_person(incident_id: str, /) -> IncidentStatus | None:
        asked.append(incident_id)
        return None

    return ended_by_a_person


def _resolved_once_it_acted(acted: list[bool]) -> EndedByAPerson:
    """Nobody's ending until the action lands, and a resolution after - the
    person who reported it over pressing the button while Argus's change was
    being verified."""
    def ended_by_a_person(dont_care_incident_id: str, /) -> IncidentStatus | None:
        return IncidentStatus.RESOLVED if acted else None

    return ended_by_a_person


def _a_person_answering_once_it_acted(acted: list[bool], answered: list[bool]) -> WaitForPeople:
    """A wait that ends with the person's press - once there is something to
    have waited for, which is after the action."""
    def wait(dont_care_incident_id: str, /) -> bool:
        if acted:
            answered.append(True)

        return bool(acted)

    return wait


def _a_wait_noting(happened: list[str]) -> WaitForPeople:
    def wait(dont_care_incident_id: str, /) -> bool:
        happened.append("waited")

        return False

    return wait


def _a_postmortem_noting(happened: list[str]) -> ports.WritePostmortem:
    def write(dont_care_incident_id: str) -> PostmortemDocument:
        happened.append("written")

        return _a_document()

    return write


def _an_action_noting_it_landed(acted: list[bool], verdict: Verdict) -> ports.TakeAction:
    """`verdict`, and a note that the action was taken."""
    take = _an_action_that(verdict)

    def taken(action: Action, /, **keywords: Any) -> Outcome:
        acted.append(True)
        return take(action, **keywords)

    return taken


def _a_postmortem_was_recorded(recorded: list[str]) -> Assertion[Walked]:
    """That the write-up was stored, not merely that its node was passed - a
    node a person's ending stopped is still a step the graph streams."""
    def assertion(dont_care_walked: Walked) -> bool:
        if len(recorded) != 1:
            raise AssertionError(
                f"Expected one postmortem recorded, got {len(recorded)}."
            )

        return True

    return assertion


def _an_investigation_whose_question_is_traced(asked: list[str],
                                               reached: list[bool]) -> ports.Investigate:
    """An investigation that asks the question it was handed, and notes whether
    asking it reached the walk's own."""
    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    already_read: Sequence[Reading] | None = None,
                    already_refuted: Sequence[Attempt] | None = None,
                    publisher: Publisher = nobody,
                    recorder: Recorder = records_nothing,
                    still_wanted: StillWanted = wanted_throughout) -> Findings:
        before = len(asked)
        still_wanted()
        reached.append(len(asked) > before)

        return Findings(
            candidates=[a_candidate_blaming(SOME_FLAG).model_copy(
                update={"incident_id": incident_id}
            )],
            already_read=[]
        )

    return investigate


def _a_fix_channel_whose_question_is_traced(asked: list[str],
                                            reached: list[bool]) -> ports.ProposeFix:
    """Code-Fix that asks the question it was handed, and notes whether asking
    it reached the walk's own."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout) -> None:
        before = len(asked)
        still_wanted()
        reached.append(len(asked) > before)

        return None

    return propose


def _the_question_reached_the_walk(reached: list[bool]) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if reached != [True]:
            raise AssertionError(
                f"Expected the agent's question to be the walk's own, asked once, "
                f"and what it reached was {reached} - so a person saying stop "
                f"would not be heard until the step ended."
            )

        return True

    return assertion


def _the_last_thing_that_happened_was(happened: list[str], expected: str) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if not happened or happened[-1] != expected:
            raise AssertionError(f"Expected [{expected}] to happen last, got {happened}.")

        return True

    return assertion
