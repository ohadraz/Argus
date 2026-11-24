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

from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from core import RunLost, get_settings
from core.autonomy import Admitted, admit
from core.budget import StillWanted, wanted_throughout
from core.events import IncidentEvent, Publisher, StepRunAgain, nobody
from core.models import (
    ActionProgress,
    Alert,
    AlreadyClaimed,
    Attempt,
    ChangeFound,
    Claimed,
    ClaimedFix,
    ClaimFix,
    EstablishedOnset,
    Evidence,
    ExecutiveSynopsisDocument,
    FailureMode,
    FixClaimed,
    FlagChange,
    FlagHistory,
    FlagUndo,
    Hypothesis,
    IncidentStatus,
    Leads,
    NotMade,
    PostmortemDocument,
    ProposedFix,
    Reading,
    RevertFeatureFlag,
    RollBackDeployment,
    Standing,
    ThreadMessage,
    UndoDescriptor,
    Weighing,
    WhatArgusDid,
    claimed_as_asked,
    no_leads,
    nothing_claimed,
)
from core.replay import Recorder
from core.replay import nobody as records_nothing
from incident_record import EndedByAPerson, WaitForPeople, the_current_step
from investigation_agent import Findings
from langgraph.checkpoint.memory import MemorySaver
from mitigation import Action, ChangeMade, Outcome, PutBackOwed, Verdict
from orchestrator.walk import ports
from orchestrator.walk.collaborators import Collaborators
from orchestrator.walk.graph import (
    CODEFIX_NODE,
    INVESTIGATOR_NODE,
    MITIGATION_NODE,
    MITIGATION_PROPOSAL_NODE,
    NEXT_CANDIDATE_NODE,
    POSTMORTEM_NODE,
    REMEMBERING_NODE,
    SYNOPSIS_NODE,
    TIER_GATE_NODE,
    build_graph,
    recursion_limit,
)
from orchestrator.walk.state import IncidentState, Recommended, WhatWasLearnt

from orchestrator_test.framework.builders import (
    a_corruption_blamed_on,
    a_deployment,
    a_lead,
    a_person_ended_the_incident,
    an_incident_state,
    an_undetermined_hypothesis,
    nobody_ended_the_incident,
    reverting,
)

type Walked = tuple[IncidentState, list[str]]

SOME_FLAG = "monthly-spend-feature"
SOME_OTHER_FLAG = "legacy-checkout-fallback"
DONT_CARE_ALERT = Alert(service="kuki-service", alert_name="HighErrorRate")
DONT_CARE_INCIDENT_ID = "dont-care"
DONT_CARE_ACTION_ID = "6f1c1d2e-0000-4000-8000-0000000000a0"
DONT_CARE_WORDS = "the kuki flag was flipped at noon"

EVERY_ROUND = get_settings().investigation_max_rounds
# More candidates than any case here offers in a round, so no walk is cut short.
SOME_CANDIDATE_BUDGET = 4
A_GENEROUS_BUDGET = recursion_limit(max_rounds=EVERY_ROUND, max_candidates=SOME_CANDIDATE_BUDGET)
SOME_ROUND_BUDGET = 3
# The cap is not what any case here turns on, and a walk that reaches it would
# stop for a reason the test never asked about.
EVERY_ATTEMPT_A_WALK_MAKES = 99

# What a walk is noted doing, by the doubles that note it: waiting for people,
# and writing the postmortem.
WAITED = "waited"
WRITTEN = "written"


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
        admit=admit,
        attempts_per_subject=EVERY_ATTEMPT_A_WALK_MAKES,
        take=_an_action_that(Verdict.CONFIRMED),
        plan_action=lambda dont_care_action, /: None,
        record_action=lambda *dont_care_args, **dont_care_keywords: Claimed(
            action_id=DONT_CARE_ACTION_ID
        ),
        complete_action=lambda *dont_care_args, **dont_care_keywords: None,
        already_taken=lambda incident_id, hypothesis_id: None,
        acting_for=lambda dont_care_action_id: nullcontext(),
        advance_action=lambda *dont_care_args, **dont_care_keywords: None,
        owe_a_put_back=lambda *dont_care_args, **dont_care_keywords: None,
        resuming=_a_resumption_nothing_reaches(),
        propose_fix=lambda dont_care_hypothesis, dont_care_incident_id, **dont_care_keywords: (
            ProposedFix(pull_request=None, explanation=None)),
        actions_taken=lambda dont_care_incident: [],
        recall_similar=lambda dont_care_description, dont_care_service: [],
        remember_incident=lambda dont_care_record: None,
        write_postmortem=lambda dont_care_incident: _a_document(),
        record_postmortem=lambda dont_care_incident, dont_care_document: None,
        write_synopsis=lambda dont_care_incident: _a_synopsis(),
        record_synopsis=lambda dont_care_incident, dont_care_synopsis: None,
        transition_incident=transition_incident,
        discard_the_interrupted_attempt=(
            lambda dont_care_incident_id, dont_care_step, dont_care_saying, /: False),
        publisher=nobody,
        recorder=records_nothing,
        ended_by_a_person=nobody_ended_the_incident(),
        still_held=lambda: True,
        wait_for_people=lambda dont_care_incident_id, /: False,
        leads_of=lambda dont_care_incident_id, /: [],
        what_argus_did=lambda dont_care_incident_id, /: [],
        claimed_fix=lambda dont_care_incident_id, /: None,
        claim_fix=lambda dont_care_incident_id, fix, /, **dont_care_keywords: fix,
        record_weighing=lambda dont_care_lead, /: None
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
        .given(a_walk_where_everything_works := collaborators) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_where_everything_works)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
            _the_incident_ended(IncidentStatus.MITIGATED)))


@pytest.mark.component
def test_the_change_the_agent_tells_of_is_put_on_the_claim_the_walk_holds(
    collaborators: Collaborators
) -> None:
    # The wiring, whole: the graph hands its mitigation node the collaborator
    # the deployment supplied, so the change reaches the row before the wait
    # rather than a stand-in nobody reads.
    advanced: list[tuple[ActionProgress, UndoDescriptor | None]] = []

    def advance_action(incident_id: str, hypothesis_id: str, to: ActionProgress,
                       undo_descriptor: UndoDescriptor | None,
                       performed_at: datetime | None = None) -> None:
        advanced.append((to, undo_descriptor))

    Scenario() \
        .given(
            a_walk_recording_its_claims := replace(collaborators,
                                                   advance_action=advance_action)
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_recording_its_claims)) \
        .then(
            _one_claim_was_moved_on_to_performed_carrying_a_way_back_for(advanced, SOME_FLAG)
        )


@pytest.mark.component
def test_the_action_is_taken_acting_for_the_row_its_claim_wrote(
    collaborators: Collaborators
) -> None:
    # The wiring, whole: the graph hands its mitigation node the deployment's
    # way of acting for an action, and the claim's row is what it acts for - so
    # what the write tier marks is the row a reader of the incident finds.
    some_action_id = "6f1c1d2e-0000-4000-8000-0000000000a1"
    acted_for: list[str] = []

    @contextmanager
    def acting_for(action_id: str) -> Generator[None]:
        acted_for.append(action_id)
        yield

    Scenario() \
        .given(
            a_walk_acting_for_its_claims := replace(
                collaborators,
                record_action=lambda *dont_care_args, **dont_care_keywords: Claimed(
                    action_id=some_action_id
                ),
                acting_for=acting_for
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_acting_for_its_claims)) \
        .then(
            _it_acted_for(acted_for, [some_action_id])
        )


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
                investigate=_an_investigation_offering(
                    an_undetermined_hypothesis(DONT_CARE_INCIDENT_ID)
                )
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   an_investigation_finding_nothing)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE, REMEMBERING_NODE, POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
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
                    a_candidate_blaming(SOME_FLAG), a_candidate_blaming(SOME_OTHER_FLAG)
                ),
                fetch_flag_changes=_a_provider_reporting(_an_enabling_of(SOME_FLAG),
                                                         _an_enabling_of(SOME_OTHER_FLAG)),
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
                           POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
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
                           POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
            _the_incident_ended(IncidentStatus.ESCALATED)))


@pytest.mark.component
def test_a_round_naming_only_what_was_refuted_ends_at_code_fix_and_a_human(
    collaborators: Collaborators
) -> None:
    # The second round is told the flag was reverted and did not help, and names
    # it again anyway. Changing it again would run an experiment already run, so
    # the walk passes over it - and a round with nothing new on it has spent the
    # list rather than found nothing. What remains is a permanent fix, as for any
    # spent list, and when Code-Fix has none either, a person.
    Scenario() \
        .given(
            a_walk_given_the_same_answer_twice := replace(
                collaborators, take=_an_action_that(Verdict.REFUTED)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   a_walk_given_the_same_answer_twice)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           NEXT_CANDIDATE_NODE,
                           INVESTIGATOR_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
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
def test_an_investigation_whose_run_was_taken_back_stops_at_its_next_turn(
    collaborators: Collaborators
) -> None:
    # Between two turns of a model, a walk paused past its lease wakes and asks
    # whether to go on. The answer is not the incident's: the run is another
    # claim's now, and the walk is stopped there rather than after every turn
    # left in its budget has been paid for.
    Scenario() \
        .given(
            a_walk_whose_run_was_taken_back := replace(
                collaborators,
                investigate=_an_investigation_asking_between_its_turns(),
                still_held=lambda: False
            )
        ) \
        .when(attempting(
            lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_whose_run_was_taken_back)
        )) \
        .then(
            an_error_was_raised(RunLost)
        )


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
def test_the_investigation_is_handed_what_people_told_the_incident(
    collaborators: Collaborators
) -> None:
    # The thread is read through the walk, so a lead reaches the investigation
    # only if the graph hands the node the walk's own reader. Any other - the
    # default that says nobody wrote - would leave the model never told.
    some_leads = [a_lead(DONT_CARE_WORDS)]
    told: list[list[ThreadMessage]] = []

    Scenario() \
        .given(
            a_walk_with_a_thread := replace(
                collaborators,
                investigate=_an_investigation_noting_what_it_was_told(told),
                leads_of=lambda dont_care_incident_id, /: some_leads
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_with_a_thread)) \
        .then(_the_investigation_was_told(told, some_leads))


@pytest.mark.component
def test_code_fix_is_handed_what_people_told_the_incident(
    collaborators: Collaborators
) -> None:
    # The same wiring at the other agent a lead reaches, and the one a lead
    # written after the investigation answered reaches first.
    some_leads = [a_lead(DONT_CARE_WORDS)]
    told: list[list[ThreadMessage]] = []

    Scenario() \
        .given(
            a_walk_with_a_thread := replace(
                collaborators,
                propose_fix=_a_fix_channel_noting_what_it_was_told(told),
                leads_of=lambda dont_care_incident_id, /: some_leads
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_with_a_thread)) \
        .then(_the_fix_was_told(told, some_leads))


@pytest.mark.component
def test_code_fix_is_handed_what_argus_did(
    collaborators: Collaborators
) -> None:
    # The same wiring for what was done about the incident. The node's own
    # default reads nothing, so a graph that never handed the record down would
    # leave Code-Fix told what the leads were weighed as and nothing of what
    # the actions then showed.
    dont_care_standing = "still in place"
    some_done = [WhatArgusDid(identity=reverting(SOME_FLAG),
                              verdict=Verdict.CONFIRMED,
                              standing=dont_care_standing)]
    handed: list[list[WhatArgusDid]] = []

    Scenario() \
        .given(
            a_walk_with_a_record := replace(
                collaborators,
                propose_fix=_a_fix_channel_noting_what_argus_did(handed),
                what_argus_did=lambda dont_care_incident_id, /: some_done
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_with_a_record)) \
        .then(_the_fix_was_handed(handed, some_done))


@pytest.mark.component
def test_every_step_takes_back_its_interrupted_attempt_before_it_runs(
    collaborators: Collaborators
) -> None:
    # The map of which steps discard, read off a whole walk: the graph hands
    # every node its own discard, under its own name. Code-Fix's too - its
    # branch and pull request are a change in the world, but the fix it claimed
    # before writing either is no line of its step, and a step run again writes
    # that claim again and says so in a line of its own.
    discarded: list[str] = []

    Scenario() \
        .given(
            a_walk_noting_its_discards := replace(
                collaborators,
                discard_the_interrupted_attempt=_a_discard_noting(discarded)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_noting_its_discards)) \
        .then(all_of(
            _the_walk_went(INVESTIGATOR_NODE,
                           MITIGATION_PROPOSAL_NODE,
                           TIER_GATE_NODE,
                           MITIGATION_NODE,
                           CODEFIX_NODE,
                           REMEMBERING_NODE,
                           POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
            _the_steps_that_discarded_were(discarded, [INVESTIGATOR_NODE,
                                                       MITIGATION_PROPOSAL_NODE,
                                                       TIER_GATE_NODE,
                                                       MITIGATION_NODE,
                                                       CODEFIX_NODE,
                                                       REMEMBERING_NODE,
                                                       POSTMORTEM_NODE,
                                                       SYNOPSIS_NODE])
        ))


@pytest.mark.component
def test_a_step_run_again_from_its_checkpoint_takes_back_the_step_its_interruption_wrote(
    collaborators: Collaborators
) -> None:
    # The key, across a real resume: a step that raised left the checkpoint
    # from before it, so the walk resumed on its thread runs it again reading
    # the step number its interrupted attempt read - which is what finds that
    # attempt's rows - and the step after it reads the next one.
    asked_at: list[tuple[str, int]] = []
    written: list[bool] = []

    Scenario() \
        .given(
            a_walk_whose_write_up_fails_once := replace(
                collaborators,
                write_postmortem=_a_postmortem_failing_once(written),
                discard_the_interrupted_attempt=_a_discard_noting_the_step(asked_at)
            )
        ) \
        .when(lambda: _the_walk_resumed_after_it_stopped(_an_incident_just_alerted(),
                                                         a_walk_whose_write_up_fails_once)) \
        .then(_the_step_was_asked_again_at_its_own_number(asked_at, POSTMORTEM_NODE,
                                                          followed_by=SYNOPSIS_NODE))


@pytest.mark.component
def test_a_code_fix_step_run_again_is_handed_the_fix_its_interrupted_attempt_claimed(
    collaborators: Collaborators
) -> None:
    # The worker stopped inside Code-Fix once the fix was claimed - after its
    # branch was written, as like as not. The step's discard takes back its
    # lines and leaves the claim, so the step run again is handed the fix the
    # first attempt claimed, which it writes rather than asking for another.
    claims: dict[str, ClaimedFix] = {}
    handed: list[ClaimedFix | None] = []

    Scenario() \
        .given(
            a_walk_whose_code_fix_stops_once_it_has_claimed := replace(
                collaborators,
                propose_fix=_code_fix_stopping_once_it_has_claimed(handed),
                claimed_fix=lambda incident_id, /: claims.get(incident_id),
                claim_fix=lambda incident_id, fix, /, **dont_care_keywords: (
                    claims.setdefault(incident_id, fix))
            )
        ) \
        .when(lambda: _the_walk_resumed_after_it_stopped(
            _an_incident_just_alerted(), a_walk_whose_code_fix_stops_once_it_has_claimed,
            stopped_by=RunLost)) \
        .then(_code_fix_was_handed(handed, [None, SOME_CLAIMED_FIX]))


@pytest.mark.component
def test_every_candidate_and_every_line_a_walk_writes_belongs_to_a_step(
    collaborators: Collaborators
) -> None:
    # What a step run again finds its interrupted attempt's rows by. A row
    # written with no step bound is one no step ever takes back, and the
    # account would then tell that step twice.
    formed_in: list[int | None] = []
    said_in: list[int | None] = []

    Scenario() \
        .given(
            a_walk_noting_its_steps := replace(
                collaborators,
                record_hypothesis=lambda dont_care_hypothesis, /: formed_in.append(
                    the_current_step()),
                publisher=lambda dont_care_event, /: said_in.append(the_current_step())
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_noting_its_steps)) \
        .then(all_of(
            _each_was_written_inside_a_step(formed_in, "candidate"),
            _each_was_written_inside_a_step(said_in, "line")
        ))


@pytest.mark.component
def test_every_lead_the_investigation_weighed_is_kept(
    collaborators: Collaborators
) -> None:
    # The same wiring on the way back: a standing the graph does not hand to
    # the record is one the next round, Code-Fix and the person who wrote the
    # lead never hear.
    dont_care_reason = "the flag history agrees"
    some_weighed = [a_lead(DONT_CARE_WORDS,
                           Weighing(standing=Standing.SUPPORTED, reason=dont_care_reason))]
    kept: list[ThreadMessage] = []

    Scenario() \
        .given(
            a_walk_that_weighs := replace(
                collaborators,
                investigate=_an_investigation_weighing(some_weighed),
                record_weighing=lambda lead, /: kept.append(lead)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_that_weighs)) \
        .then(_the_weighings_kept_were(kept, some_weighed))


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
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE, REMEMBERING_NODE, POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
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
            a_walk_resolved_once_it_acted := replace(
                collaborators,
                take=_an_action_noting_it_landed(acted, Verdict.CONFIRMED),
                ended_by_a_person=_resolved_once_it_acted(acted),
                record_postmortem=lambda incident_id, dont_care_document: recorded.append(
                    incident_id)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   a_walk_resolved_once_it_acted)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE,
                                    MITIGATION_PROPOSAL_NODE,
                                    TIER_GATE_NODE,
                                    MITIGATION_NODE,
                                    REMEMBERING_NODE,
                                    POSTMORTEM_NODE,
                                    SYNOPSIS_NODE),
                     _the_incident_ended(IncidentStatus.RESOLVED),
                     _a_postmortem_was_recorded(recorded)))


@pytest.mark.component
def test_an_incident_resolved_mid_investigation_is_investigated_to_its_answer(
    collaborators: Collaborators
) -> None:
    # The person reported it over between two of the investigation's turns.
    # They are owed the write-up, and the cause it names is what the
    # investigation finds - so the investigation goes on to its answer, and the
    # answer is recorded. Nothing is tried: the resolution still stops every
    # step that changes the world.
    pressed: list[bool] = []
    went_on: list[bool] = []
    recorded: list[Hypothesis] = []

    Scenario() \
        .given(
            a_walk_resolved_mid_investigation := replace(
                collaborators,
                investigate=_an_investigation_resolved_between_its_turns(pressed, went_on),
                ended_by_a_person=_resolved_once_pressed(pressed),
                record_hypothesis=recorded.append
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   a_walk_resolved_mid_investigation)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE,
                                    REMEMBERING_NODE,
                                    POSTMORTEM_NODE,
                                    SYNOPSIS_NODE),
                     _the_incident_ended(IncidentStatus.RESOLVED),
                     _the_investigation_went_on(went_on),
                     _one_hypothesis_was_recorded_blaming(recorded, SOME_FLAG)))


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
            a_walk_answered_while_waiting := replace(
                collaborators,
                take=_an_action_noting_it_landed(acted, Verdict.CONFIRMED),
                wait_for_people=_a_person_answering_once_it_acted(acted, answered),
                ended_by_a_person=_resolved_once_it_acted(answered)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   a_walk_answered_while_waiting)) \
        .then(all_of(_the_walk_went(INVESTIGATOR_NODE,
                                    MITIGATION_PROPOSAL_NODE,
                                    TIER_GATE_NODE,
                                    MITIGATION_NODE,
                                    REMEMBERING_NODE,
                                    POSTMORTEM_NODE,
                                    SYNOPSIS_NODE),
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
            a_walk_noting_what_happened := replace(
                collaborators,
                wait_for_people=_a_wait_noting(happened),
                write_postmortem=_a_postmortem_noting(happened)
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(), a_walk_noting_what_happened)) \
        .then(_the_last_thing_that_happened_was(happened, WRITTEN))


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
                           POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
            _the_incident_ended(IncidentStatus.RECOMMENDED),
            _the_action_recommended_was(SOME_FLAG)))


@pytest.mark.component
def test_a_corruption_a_deployment_left_behind_is_recommended_a_rollback(
    collaborators: Collaborators
) -> None:
    # The same damage as the flag case above, left by the other kind of change.
    # The candidate blames a revision the platform recorded deploying, so the
    # change to undo is that deployment - and it is recommended rather than
    # taken for the same reason: the readings already cover the incident, and a
    # rollback reports nothing of its own that would say whether it worked.
    a_recorded_deployment = a_deployment()

    Scenario() \
        .given(
            a_deployment_behind_the_damage := replace(
                collaborators,
                investigate=_an_investigation_offering(
                    a_corruption_blamed_on(DONT_CARE_INCIDENT_ID,
                                           a_recorded_deployment.reference)
                ),
                fetch_flag_changes=_a_provider_reporting(),
                fetch_deployments=lambda **dont_care_question: [a_recorded_deployment]
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
                           POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
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
    dont_care_flag = "dont-care"

    Scenario() \
        .given(
            a_rollback_within_reach := replace(
                collaborators,
                investigate=_an_investigation_offering(
                    a_candidate_blaming(
                        dont_care_flag,
                        failure_mode=FailureMode.MONITORING_CONFIGURATION_DRIFT
                    ),
                    a_candidate_blaming(
                        dont_care_flag, failure_mode=FailureMode.BAD_DEPLOYMENT
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
                           POSTMORTEM_NODE,
                           SYNOPSIS_NODE),
            _the_incident_ended(IncidentStatus.ESCALATED)))


@pytest.mark.component
def test_a_resumed_mitigation_nobody_can_account_for_leaves_the_incident_escalated_saying_why(
    collaborators: Collaborators,
    transition_incident: MagicMock
) -> None:
    # The claim an earlier worker wrote is found, and nothing can say whether its
    # action was carried out. The node reports the verdict and says why; the
    # status is derived from that like every other, and the row is moved to
    # escalated with the sentence a person reads.
    Scenario() \
        .given(
            a_walk_resuming_a_claim_nobody_can_account_for := replace(
                collaborators,
                record_action=lambda *dont_care_args, **dont_care_keywords: AlreadyClaimed(),
                already_taken=lambda incident_id, hypothesis_id: ports.ClaimedAction(
                    action_id=DONT_CARE_ACTION_ID, outcome=None,
                    claimed_at=SOME_MOMENT_AN_EARLIER_WORKER_CLAIMED_IT,
                    progress=ActionProgress.UNKNOWN
                )
            )
        ) \
        .when(lambda: _the_walk_of(_an_incident_just_alerted(),
                                   a_walk_resuming_a_claim_nobody_can_account_for)) \
        .then(all_of(
            _the_incident_ended(IncidentStatus.ESCALATED),
            _the_row_was_moved_to(transition_incident, IncidentStatus.ESCALATED,
                                  saying=A_CHANGE_NOBODY_CAN_ACCOUNT_FOR)
        ))


# When the worker that is gone wrote its claim, which nothing here reads.
SOME_MOMENT_AN_EARLIER_WORKER_CLAIMED_IT = datetime(2026, 8, 20, 11, 10, tzinfo=UTC)
# How a resumed walk hands over a claim nobody can account for, in the words a
# person reads.
A_CHANGE_NOBODY_CAN_ACCOUNT_FOR = ("an earlier attempt claimed this action and nothing can "
                                   "say whether it was carried out")


def _the_row_was_moved_to(transition_incident: MagicMock,
                          status: IncidentStatus,
                          saying: str) -> Assertion[Walked]:
    """The row was moved to `status` once, with the line saying `saying`."""
    def assertion(dont_care_walked: Walked) -> bool:
        moves = [(call.args[1], call.kwargs["narrating"].detail)
                 for call in transition_incident.call_args_list
                 if call.args[1] == status]

        if moves != [(status, saying)]:
            raise AssertionError(
                f"Expected the row moved to [{status}] once saying [{saying}], got "
                f"{[(call.args, call.kwargs) for call in transition_incident.call_args_list]}."
            )

        return True

    return assertion


def _a_discard_noting(discarded: list[str]) -> ports.DiscardTheInterruptedAttempt:
    """A discard that notes which step asked, by the name its line carries,
    and found nothing to take back."""
    def discard(dont_care_incident_id: str, dont_care_step: int, saying: IncidentEvent,
                /) -> bool:
        if isinstance(saying, StepRunAgain):
            discarded.append(saying.step)

        return False

    return discard


def _a_discard_noting_the_step(asked_at: list[tuple[str, int]]
                               ) -> ports.DiscardTheInterruptedAttempt:
    """A discard that notes which step asked, and at which number."""
    def discard(dont_care_incident_id: str, step: int, saying: IncidentEvent, /) -> bool:
        if isinstance(saying, StepRunAgain):
            asked_at.append((saying.step, step))

        return False

    return discard


# The fix Code-Fix's interrupted attempt claimed, told apart from any other by
# being this one.
SOME_CLAIMED_FIX = ClaimedFix(files={"src/io_shop/spend_summary.py": "def spend(): ...\n"},
                              base_branch="main",
                              base_commit="8c1d4b07a2e95f3360d1c4e8b7a9f20e51d6c3a4",
                              title="guard the monthly divisor",
                              body="dont-care-body",
                              brings_a_test=False,
                              reading=ProposedFix(pull_request=None, explanation=None))


def _code_fix_stopping_once_it_has_claimed(handed: list[ClaimedFix | None]
                                           ) -> ports.ProposeFix:
    """Code-Fix noting the claim it is handed each time it is asked, whose
    first attempt claims `SOME_CLAIMED_FIX` and stops there - as a worker
    stopping mid-step stops it."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                done: Sequence[WhatArgusDid] = (),
                deployed: str | None = None,
                claimed: FixClaimed = nothing_claimed,
                claim: ClaimFix = claimed_as_asked) -> ProposedFix:
        handed.append(claimed())

        if len(handed) == 1:
            claim(SOME_CLAIMED_FIX)
            raise RunLost("the worker stopped once the fix was claimed")

        return ProposedFix(pull_request=None, explanation=None)

    return propose


def _code_fix_was_handed(handed: list[ClaimedFix | None],
                         expected: list[ClaimedFix | None]) -> Assertion[list[str]]:
    def assertion(dont_care_resumed: list[str]) -> bool:
        if handed != expected:
            raise AssertionError(
                f"Expected Code-Fix handed {expected!r}, one claim per attempt, and it "
                f"was handed {handed!r}."
            )

        return True

    return assertion


def _a_postmortem_failing_once(written: list[bool]) -> ports.WritePostmortem:
    """A write-up whose first attempt is interrupted, as a worker stopping
    mid-step interrupts it."""
    def write(dont_care_incident: str) -> PostmortemDocument:
        if not written:
            written.append(False)
            raise RuntimeError("the worker stopped mid-write-up")

        written.append(True)

        return _a_document()

    return write


def _the_walk_resumed_after_it_stopped(incident: IncidentState,
                                       collaborators: Collaborators,
                                       stopped_by: type[Exception] = RuntimeError
                                       ) -> list[str]:
    """One incident through the compiled graph until a step raises
    `stopped_by`, then walked again on its own thread from the checkpoint it
    left - as the worker resumes it - and the steps the resumed walk took.

    `stopped_by` is what the step raised: Code-Fix answers every failure but a
    lost run as a fix it could not propose, so a lost run is what stops it."""
    graph = build_graph(MemorySaver(), collaborators)
    config: Any = {"configurable": {"thread_id": incident.incident_id},
                   "recursion_limit": A_GENEROUS_BUDGET}

    with suppress(stopped_by):
        graph.invoke(incident, config=config)

    return [name
            for step in graph.stream(None, config=config, stream_mode="updates")
            for name in step]


def _the_step_was_asked_again_at_its_own_number(asked_at: list[tuple[str, int]],
                                                step: str,
                                                followed_by: str) -> Assertion[list[str]]:
    def assertion(dont_care_resumed: list[str]) -> bool:
        numbers = [number for name, number in asked_at if name == step]
        after = [number for name, number in asked_at if name == followed_by]

        if len(numbers) != 2 or numbers[0] != numbers[1]:
            raise AssertionError(
                f"Expected the [{step}] step to be asked twice at one number - once "
                f"interrupted, once run again - and it was asked at {numbers} "
                f"(every step asked: {asked_at})."
            )

        if after != [numbers[0] + 1]:
            raise AssertionError(
                f"Expected [{followed_by}] asked once, at the number after [{step}]'s "
                f"[{numbers[0]}], and it was asked at {after}."
            )

        return True

    return assertion


def _the_steps_that_discarded_were(discarded: list[str],
                                   expected: list[str]) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if discarded != expected:
            raise AssertionError(
                f"Expected the steps {expected} to take back their interrupted attempts, "
                f"in that order, and {discarded} did."
            )

        return True

    return assertion


def _each_was_written_inside_a_step(written_in: list[int | None],
                                    what: str) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if not written_in:
            raise AssertionError(
                f"Expected the walk to write at least one {what}, and it wrote none - "
                f"so nothing was asserted."
            )

        if None in written_in:
            raise AssertionError(
                f"Expected every {what} the walk wrote to belong to a step, and the steps "
                f"they were written in were {written_in}."
            )

        return True

    return assertion


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
    return an_incident_state(DONT_CARE_ALERT, IncidentStatus.INVESTIGATING)


def _an_incident_on_its_last_round() -> IncidentState:
    """One round short of the budget, so the investigation about to run is the
    last one this incident gets."""
    return _an_incident_just_alerted().model_copy(
        update={"history": WhatWasLearnt(rounds=EVERY_ROUND - 1)}
    )


def _an_incident_dated_by_its_alert() -> IncidentState:
    """An incident whose onset only the alert could state.

    One inference rather than a flag: an alert dating the incident means the
    series measured no departure, which means nothing would mark a recovery
    either. A week back, because that is the distance at which a weekly
    integrity check finds a fault nothing else noticed.
    """
    when_it_was_noticed = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
    a_week_before_anybody_noticed = when_it_was_noticed - timedelta(weeks=1)

    return an_incident_state(
        DONT_CARE_ALERT.model_copy(update={"stated_onset": a_week_before_anybody_noticed}),
        IncidentStatus.INVESTIGATING
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
    dont_care_claim = "some log line"

    return Hypothesis(incident_id=DONT_CARE_INCIDENT_ID,
                      summary=f"the {flag} flag was switched on",
                      failure_mode=failure_mode,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim=dont_care_claim, at=None)],
                      subject=flag)


# When the provider double says a flag was enabled.
SOME_ENABLING_AT = "2026-08-20T11:05:00Z"


def _an_enabling_of(flag: str) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at=SOME_ENABLING_AT)


def _an_investigation_asking_between_its_turns() -> ports.Investigate:
    """An investigation that asks the walk's question before its first turn,
    as the real one does, and finds nothing if it is let go on."""
    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    already_read: Sequence[Reading] | None = None,
                    already_refuted: Sequence[Attempt] | None = None,
                    publisher: Publisher = nobody,
                    recorder: Recorder = records_nothing,
                    still_wanted: StillWanted = wanted_throughout,
                    leads: Leads = no_leads,
                    established_onset: EstablishedOnset | None = None,
                    earlier_candidates: int = 0) -> Findings:
        still_wanted()

        return Findings(candidates=[], already_read=[])

    return investigate


def _an_investigation_offering(*candidates: Hypothesis) -> ports.Investigate:
    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    already_read: Sequence[Reading] | None = None,
                    already_refuted: Sequence[Attempt] | None = None,
                    publisher: Publisher = nobody,
                    recorder: Recorder = records_nothing,
                    still_wanted: StillWanted = wanted_throughout,
                    leads: Leads = no_leads,
                    established_onset: EstablishedOnset | None = None,
                    earlier_candidates: int = 0) -> Findings:
        return Findings(
            candidates=[candidate.model_copy(update={"incident_id": incident_id})
                        for candidate in candidates],
            already_read=[]
        )

    return investigate


# The window a provider double says it was read over, which no case here reads.
DONT_CARE_HISTORY_START = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
DONT_CARE_HISTORY_END = DONT_CARE_HISTORY_START + timedelta(minutes=30)


def _a_provider_reporting(*changes: FlagChange) -> ports.FetchFlagChanges:
    """Whatever the provider recorded, whichever window it is asked about.

    The onset is taken and ignored: which window these changes would fall in is
    settled where the window is built, and a double that filtered on it would be
    a second implementation of that rule agreeing with itself. Named rather than
    starred, so that a caller passing it positionally stops here instead of
    landing on a parameter this does not have.
    """
    def fetch_flag_changes(*, onset: datetime | None) -> FlagHistory:
        return FlagHistory(changes=list(changes), since=DONT_CARE_HISTORY_START,
                           until=DONT_CARE_HISTORY_END)

    return fetch_flag_changes


def _an_action_that(verdict: Verdict) -> ports.TakeAction:
    return _actions_that(verdict)


def _actions_that(*verdicts: Verdict) -> ports.TakeAction:
    """One verdict per attempt, in the order the walk makes them - which is how
    a walk whose first answer is refuted and whose second holds is stated."""
    answers = iter(verdicts)
    last = verdicts[-1]
    dont_care_detail = "dont care"

    def take(admitted: Admitted[Action],
             /,
             *,
             plan: Any = None,
             acted_from: datetime | None = None,
             still_wanted: Any = None,
             incident_id: str | None = None,
             publisher: Publisher = nobody,
             onset: datetime | None = None,
             incident_began: str | None = None,
             rule: str | None = None,
             change_made: ChangeMade = lambda dont_care_undo_descriptor: None,
             put_back_owed: PutBackOwed = lambda dont_care_because: None) -> Outcome:
        # Only one kind of action leaves anything behind, and the stand-in
        # hands back exactly what the real one would - and tells of it as the
        # change is made, as the real one does.
        the_way_back = (
            admitted.action.undo_descriptor if isinstance(admitted.action, RevertFeatureFlag)
            else None
        )
        change_made(the_way_back)

        return Outcome(verdict=next(answers, last),
                       detail=dont_care_detail,
                       undo_descriptor=the_way_back,
                       left_behind_known=True)

    return take


def _it_acted_for(acted_for: list[str], expected: list[str]) -> Assertion[Walked]:
    def assertion(_walked: Walked) -> bool:
        if acted_for != expected:
            raise AssertionError(
                f"Expected the walk to act for the actions {expected}, it acted for "
                f"{acted_for}."
            )

        return True

    return assertion


def _one_claim_was_moved_on_to_performed_carrying_a_way_back_for(
        advanced: list[tuple[ActionProgress, UndoDescriptor | None]],
        flag: str) -> Assertion[Walked]:
    def assertion(_walked: Walked) -> bool:
        found = [(to, undo.flag if isinstance(undo, FlagUndo) else undo)
                 for to, undo in advanced]
        if found != [(ActionProgress.PERFORMED, flag)]:
            raise AssertionError(f"Expected one claim moved on to [performed], carrying "
                                 f"the way back for [{flag}], got {advanced}.")

        return True

    return assertion


def _a_resumption_nothing_reaches() -> ports.Resuming:
    """What a resumed walk reads and carries on with, for walks no case here
    resumes: every claim is won, so none of it is asked - and were it asked,
    nothing of a claim landed, a change told as made is still Argus's, and
    nothing is on file."""
    return ports.Resuming(
        whether_it_was_made=lambda dont_care_action, dont_care_plan, /, **dont_care: NotMade(
            left_behind=None),
        still_argus_s=lambda dont_care_plan, dont_care_descriptor, /: ChangeFound(
            still_argus_s=True),
        watch=_a_watch_that(Verdict.CONFIRMED),
        settle=_a_watch_that(Verdict.REFUTED),
        announced=lambda dont_care_incident_id, dont_care_hypothesis_id: False,
        plan_the_claim=lambda dont_care_incident_id, dont_care_hypothesis_id, dont_care_plan: None,
        metrics_window=timedelta(minutes=get_settings().metrics_window_minutes)
    )


def _a_watch_that(verdict: Verdict) -> Callable[..., Outcome]:
    """A watch, or a put-back, that answers `verdict` whatever it is handed."""
    def watching(*dont_care_args: object, **dont_care_keywords: object) -> Outcome:
        return Outcome(verdict=verdict, detail="dont care", left_behind_known=True)

    return watching


def _a_document() -> PostmortemDocument:
    return PostmortemDocument(root_cause=None,
                              executive_summary=None,
                              customer_loss_estimate=None,
                              estimate_currency=None,
                              engineer_minutes=None,
                              responders=None,
                              tokens_spent=None,
                              assumptions=[])


def _a_synopsis() -> ExecutiveSynopsisDocument:
    dont_care_reason = "dont care"

    return ExecutiveSynopsisDocument(overview=None, withheld_because=dont_care_reason)


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
        recommended = final.ending.action if isinstance(final.ending, Recommended) else None

        if not isinstance(recommended, RollBackDeployment):
            raise AssertionError(
                f"Expected the incident to recommend rolling a deployment back, "
                f"it recommends [{recommended!r}]."
            )

        if recommended.application != final.alert.service:
            raise AssertionError(
                f"Expected the rollback to be addressed to the alerting service "
                f"[{final.alert.service}], it is addressed to "
                f"[{recommended.application}]."
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
        recommended = final.ending.action if isinstance(final.ending, Recommended) else None

        if not isinstance(recommended, RevertFeatureFlag):
            raise AssertionError(
                f"Expected the incident to recommend reverting a flag, it "
                f"recommends [{recommended!r}]."
            )

        if recommended.flag != flag:
            raise AssertionError(
                f"Expected the recommendation to name [{flag}], it names "
                f"[{recommended.flag}]."
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


def _resolved_once_pressed(pressed: list[bool]) -> EndedByAPerson:
    """Nobody's ending until the person presses, and a resolution after."""
    def ended_by_a_person(dont_care_incident_id: str, /) -> IncidentStatus | None:
        return IncidentStatus.RESOLVED if pressed else None

    return ended_by_a_person


def _an_investigation_resolved_between_its_turns(pressed: list[bool],
                                                 went_on: list[bool]) -> ports.Investigate:
    """An investigation during whose first turn the person presses. It asks
    the walk's question before its second turn, as the real one does, notes
    the answer, and offers a candidate only if it was let go on."""
    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    already_read: Sequence[Reading] | None = None,
                    already_refuted: Sequence[Attempt] | None = None,
                    publisher: Publisher = nobody,
                    recorder: Recorder = records_nothing,
                    still_wanted: StillWanted = wanted_throughout,
                    leads: Leads = no_leads,
                    established_onset: EstablishedOnset | None = None,
                    earlier_candidates: int = 0) -> Findings:
        pressed.append(True)
        went_on.append(still_wanted())

        if not went_on[-1]:
            return Findings(candidates=[], already_read=[], stopped=True)

        return Findings(
            candidates=[a_candidate_blaming(SOME_FLAG).model_copy(
                update={"incident_id": incident_id}
            )],
            already_read=[]
        )

    return investigate


def _the_investigation_went_on(went_on: list[bool]) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if went_on != [True]:
            raise AssertionError(
                f"Expected the investigation to be let go on to its answer after "
                f"the press, once, and the walk's question answered {went_on}."
            )

        return True

    return assertion


def _one_hypothesis_was_recorded_blaming(recorded: list[Hypothesis],
                                         flag: str) -> Assertion[Walked]:
    """The cause the write-up names is the hypothesis on record, so a resolved
    incident with none recorded is written up without one."""
    def assertion(dont_care_walked: Walked) -> bool:
        blamed = [hypothesis.subject for hypothesis in recorded]

        if blamed != [flag]:
            raise AssertionError(
                f"Expected one hypothesis recorded, blaming [{flag}], got {blamed}."
            )

        return True

    return assertion


def _a_wait_noting(happened: list[str]) -> WaitForPeople:
    def wait(dont_care_incident_id: str, /) -> bool:
        happened.append(WAITED)

        return False

    return wait


def _a_postmortem_noting(happened: list[str]) -> ports.WritePostmortem:
    def write(dont_care_incident_id: str) -> PostmortemDocument:
        happened.append(WRITTEN)

        return _a_document()

    return write


def _an_action_noting_it_landed(acted: list[bool], verdict: Verdict) -> ports.TakeAction:
    """`verdict`, and a note that the action was taken."""
    take = _an_action_that(verdict)

    def taken(admitted: Admitted[Action], /, **keywords: Any) -> Outcome:
        acted.append(True)
        return take(admitted, **keywords)

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
                    still_wanted: StillWanted = wanted_throughout,
                    leads: Leads = no_leads,
                    established_onset: EstablishedOnset | None = None,
                    earlier_candidates: int = 0) -> Findings:
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


def _an_investigation_noting_what_it_was_told(told: list[list[ThreadMessage]]
                                              ) -> ports.Investigate:
    """An investigation that asks what people told the incident, and notes
    the answer."""
    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    already_read: Sequence[Reading] | None = None,
                    already_refuted: Sequence[Attempt] | None = None,
                    publisher: Publisher = nobody,
                    recorder: Recorder = records_nothing,
                    still_wanted: StillWanted = wanted_throughout,
                    leads: Leads = no_leads,
                    established_onset: EstablishedOnset | None = None,
                    earlier_candidates: int = 0) -> Findings:
        told.append(leads())

        return Findings(
            candidates=[a_candidate_blaming(SOME_FLAG).model_copy(
                update={"incident_id": incident_id}
            )],
            already_read=[]
        )

    return investigate


def _an_investigation_weighing(weighed: list[ThreadMessage]) -> ports.Investigate:
    """An investigation that returns these weighings beside its answer."""
    def investigate(alert: Alert,
                    incident_id: str,
                    *,
                    already_read: Sequence[Reading] | None = None,
                    already_refuted: Sequence[Attempt] | None = None,
                    publisher: Publisher = nobody,
                    recorder: Recorder = records_nothing,
                    still_wanted: StillWanted = wanted_throughout,
                    leads: Leads = no_leads,
                    established_onset: EstablishedOnset | None = None,
                    earlier_candidates: int = 0) -> Findings:
        return Findings(
            candidates=[a_candidate_blaming(SOME_FLAG).model_copy(
                update={"incident_id": incident_id}
            )],
            already_read=[],
            leads_weighed=weighed
        )

    return investigate


def _the_investigation_was_told(told: list[list[ThreadMessage]],
                                expected: list[ThreadMessage]) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if told != [expected]:
            raise AssertionError(
                f"Expected the investigation to be told the {len(expected)} "
                f"lead(s) the thread holds, once, and it was told {told}."
            )

        return True

    return assertion


def _the_fix_was_told(told: list[list[ThreadMessage]],
                      expected: list[ThreadMessage]) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if told != [expected]:
            raise AssertionError(
                f"Expected Code-Fix to be told the {len(expected)} lead(s) the "
                f"thread holds, once, and it was told {told}."
            )

        return True

    return assertion


def _the_fix_was_handed(handed: list[list[WhatArgusDid]],
                        expected: list[WhatArgusDid]) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if handed != [expected]:
            raise AssertionError(
                f"Expected Code-Fix to be handed the {len(expected)} action(s) the "
                f"record holds, once, and it was handed {handed}."
            )

        return True

    return assertion


def _the_weighings_kept_were(kept: list[ThreadMessage],
                             expected: list[ThreadMessage]) -> Assertion[Walked]:
    def assertion(dont_care_walked: Walked) -> bool:
        if kept != expected:
            raise AssertionError(
                f"Expected the {len(expected)} weighing(s) the investigation "
                f"returned to be kept, and what was kept was {kept}."
            )

        return True

    return assertion


def _a_fix_channel_whose_question_is_traced(asked: list[str],
                                            reached: list[bool]) -> ports.ProposeFix:
    """Code-Fix that asks the question it was handed, and notes whether asking
    it reached the walk's own."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                done: Sequence[WhatArgusDid] = (),
                deployed: str | None = None,
                claimed: FixClaimed = nothing_claimed,
                claim: ClaimFix = claimed_as_asked) -> ProposedFix:
        before = len(asked)
        still_wanted()
        reached.append(len(asked) > before)

        return ProposedFix(pull_request=None, explanation=None)

    return propose


def _a_fix_channel_noting_what_it_was_told(told: list[list[ThreadMessage]]
                                           ) -> ports.ProposeFix:
    """Code-Fix that asks what people told the incident, and notes the
    answer."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                done: Sequence[WhatArgusDid] = (),
                deployed: str | None = None,
                claimed: FixClaimed = nothing_claimed,
                claim: ClaimFix = claimed_as_asked) -> ProposedFix:
        told.append(leads())

        return ProposedFix(pull_request=None, explanation=None)

    return propose


def _a_fix_channel_noting_what_argus_did(handed: list[list[WhatArgusDid]]
                                         ) -> ports.ProposeFix:
    """Code-Fix that notes what it was told Argus did."""
    def propose(dont_care_hypothesis: Hypothesis | None,
                dont_care_incident_id: str,
                *,
                still_wanted: StillWanted = wanted_throughout,
                leads: Leads = no_leads,
                done: Sequence[WhatArgusDid] = (),
                deployed: str | None = None,
                claimed: FixClaimed = nothing_claimed,
                claim: ClaimFix = claimed_as_asked) -> ProposedFix:
        handed.append(list(done))

        return ProposedFix(pull_request=None, explanation=None)

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
