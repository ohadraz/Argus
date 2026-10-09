"""What one round of investigation leaves behind, which is its work and its
account of it - never a status.

Where the incident stands is derived from these returns one place further out,
by `status_after`, and tested there. A node asserting a status here would be
asserting a decision it no longer makes.

A cause was named is the whole admission test. Confidence used to gate it, and
that was the wrong question: the action is taken alone, confirmed against the
service and put back when it does not help, so an unsure answer is a reason to
try it and see.

The round also reads the flag provider, which the proposal node used to do. It
has to: what memory compares, and what the walk skips, is the action a
candidate would be answered with - and that question cannot be asked before the
history is in hand. So the cases about reading it are here, beside the ones
about what is done with what it said.

It reads the service register in the same breath and for a related reason: what
the gate has to decide about an action addressed somewhere other than the
alerting service is whether that somewhere is the organisation's own, and a gate
that asked a document store for itself would be one whose answer depended on the
store being reachable at the instant it asked.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock, create_autospec

import agent_investigator
import pytest
from argus_core.events import (
    AgentInvoked,
    AlarmDisproven,
    CandidatesReordered,
    FlagChangesRetrieved,
    IncidentEvent,
    RetrievalUnanswered,
    SimilarIncidentsRecalled,
)
from argus_core.models import (
    ActionIdentity,
    Actor,
    Alert,
    Attempt,
    Disproof,
    FlagChange,
    Hypothesis,
    IncidentStatus,
    Ownership,
    Reading,
    RecordedPlacement,
    RetrievalChannel,
    ServiceDependency,
    Verdict,
)
from argus_incidents import IsStillWanted
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    calling,
    one_record_was_logged,
)
from incident_memory.records import RememberedIncident, WhatWasTried
from orchestrator.walk import ports
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.investigating import investigator_node, route_after_investigation
from orchestrator.walk.routes import ESCALATED_ROUTE, MITIGATING_ROUTE
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.assertions import (
    assert_that,
    the_result_at,
    the_result_is,
    the_route_is,
)
from orchestrator_test.framework.builders import (
    a_candidate_blaming,
    a_corruption_blamed_on,
    a_deployment,
    a_determined_hypothesis,
    a_divergence_blamed_on,
    a_leak_blamed_on,
    a_placement,
    an_accelerator_blamed_on,
    an_identity,
    an_incident_state,
    an_undetermined_hypothesis,
    discarding,
    holding_to_a_card,
    putting_back,
    restarting,
    rolling_back,
)

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"
SOME_SERVICE = "kuki-service"
DONT_CARE_MOMENT = "2026-08-20T11:05:00Z"

# Every flag these cases name, recorded as having moved. Fixed rather than
# varied per case: a candidate blaming a flag the provider never recorded is
# answered by no action at all, and a case about the order of two candidates
# would quietly become a case about neither of them being answerable.
WHAT_THE_PROVIDER_RECORDED = [
    FlagChange(flag=SOME_FLAG, enabled=True, occurred_at=DONT_CARE_MOMENT),
    FlagChange(flag=ANOTHER_FLAG, enabled=True, occurred_at=DONT_CARE_MOMENT)
]

# What the register says the alerting service calls. Non-empty for the reason
# the flag history above is: an empty register is what an unreadable one looks
# like, so a fixture answering nothing would make every case here indexes
# indistinguishable from the one case about the register failing.
WHAT_THE_REGISTER_LISTS = [
    ServiceDependency(
        name="kuki-pricing",
        purpose="quotes the price shown on the account page",
        host="pricing.io-internal.svc",
        owner="platform",
        ownership=Ownership.INTERNAL
    )
]

A_DISPROOF = Disproof(
    signals_judged=("error_rate", "p95_ms"),
    earliest_minute="2026-10-03T09:00Z",
    latest_minute="2026-10-03T09:29Z",
    minutes_judged=30
)

# What the platform's history holds around the onset. Non-empty for the reason
# the two above are: an empty history is what an unreadable one would look like
# carried forward, and a case about carrying it could not tell the two apart.
WHAT_THE_PLATFORM_RECORDED = [a_deployment()]

# What a source fails with when it cannot be reached. Named because the error is
# carried onto the page, and it is how a case tells which source a line about an
# unanswered retrieval is about.
FLAG_PROVIDER_UNREACHABLE = "The Feature Flag provider could not be reached."
PLATFORM_UNREACHABLE = "The deployment platform could not be reached."


@pytest.fixture
def investigate() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.Investigate, instance=True))


@pytest.fixture
def record_hypothesis() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.RecordHypothesis, instance=True))


@pytest.fixture
def fetch_flag_changes() -> MagicMock:
    fetch = cast(MagicMock, create_autospec(ports.FetchFlagChanges, instance=True))
    fetch.return_value = list(WHAT_THE_PROVIDER_RECORDED)

    return fetch


@pytest.fixture
def fetch_dependencies() -> MagicMock:
    fetch = cast(MagicMock, create_autospec(ports.FetchDependencies, instance=True))
    fetch.return_value = list(WHAT_THE_REGISTER_LISTS)

    return fetch


@pytest.fixture
def fetch_deployments() -> MagicMock:
    fetch = cast(MagicMock, create_autospec(ports.FetchDeployments, instance=True))
    fetch.return_value = list(WHAT_THE_PLATFORM_RECORDED)

    return fetch


@pytest.mark.unit
def test_investigator_node_offers_the_cause_it_named_as_the_one_to_try(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    an_investigating_incident = _an_investigating_incident()
    some_hypothesis = a_determined_hypothesis(an_investigating_incident.incident_id)

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate, some_hypothesis))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(all_of(
            the_result_is(
                StateDelta(
                    hypothesis=some_hypothesis,
                    candidates=[some_hypothesis],
                    candidate_index=0,
                    flag_changes=WHAT_THE_PROVIDER_RECORDED,
                    dependencies=WHAT_THE_REGISTER_LISTS,
                    already_read=[],
                    readings_cover_the_incident=True,
                    rounds=1,
                    confidence=some_hypothesis.confidence,
                    nothing_worth_trying=False,
                    narration=Narration(action="hypothesis formed")
                )
            ),
            assert_that(record_hypothesis).was_called_with(some_hypothesis)
        ))


@pytest.mark.unit
def test_whether_the_incident_was_read_at_all_is_carried_to_the_gate(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The gate decides whether an action on this incident could ever be confirmed,
    # and it holds the onset and never the window - so a fact measured where both
    # are has to travel. Carried like the flag history and the register beside it:
    # read once, in the round that read the evidence, and handed to the node that
    # acts on it.
    an_investigating_incident = _an_investigating_incident()
    some_hypothesis = a_determined_hypothesis(an_investigating_incident.incident_id)

    Scenario() \
        .given(
            calling(lambda: _the_investigation_found_the_incident_unread(
                investigate, some_hypothesis
            ))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(
            the_result_is(
                StateDelta(
                    hypothesis=some_hypothesis,
                    candidates=[some_hypothesis],
                    candidate_index=0,
                    flag_changes=WHAT_THE_PROVIDER_RECORDED,
                    dependencies=WHAT_THE_REGISTER_LISTS,
                    already_read=[],
                    readings_cover_the_incident=False,
                    rounds=1,
                    confidence=some_hypothesis.confidence,
                    nothing_worth_trying=False,
                    narration=Narration(action="hypothesis formed")
                )
            )
        )


@pytest.mark.unit
def test_the_flag_history_is_asked_at_an_onset_the_alert_stated(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The history the gate's action is chosen from, asked about the minute the
    # incident began rather than about the present. For an alert raised by a
    # check that runs weekly those are a week apart, and a window ending now
    # reaches no flag at all - so Mitigation would name no action, and an
    # incident whose whole point is an action nobody may take would escalate
    # with nothing to recommend.
    a_stated_onset = datetime(2026, 9, 22, 14, 10, tzinfo=UTC)
    an_incident_found_by_a_check = an_incident_state(
        Alert(
            service=SOME_SERVICE,
            alert_name="SpendTotalsDoNotReconcile",
            stated_onset=a_stated_onset
        ),
        IncidentStatus.INVESTIGATING
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(
                    an_incident_found_by_a_check.incident_id
                )
            ))
        ) \
        .when(
            lambda: investigator_node(an_incident_found_by_a_check,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(
            assert_that(fetch_flag_changes).was_called_with(onset=a_stated_onset)
        )


@pytest.mark.unit
def test_an_alert_that_states_no_onset_asks_the_flag_history_for_the_present(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The branch every existing incident takes. An alert that measured its own
    # onset says nothing here, and the history is asked the question it has
    # always been asked - what somebody just changed.
    an_ordinary_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(an_ordinary_incident.incident_id)
            ))
        ) \
        .when(
            lambda: investigator_node(an_ordinary_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(
            assert_that(fetch_flag_changes).was_called_with(onset=None)
        )


@pytest.mark.unit
def test_an_incident_whose_minutes_nothing_read_asks_the_flag_history_for_the_present(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # A stated onset is ordinarily the minute the incident began, and the history
    # is asked about it. Where no reading covers the incident's own minutes it is
    # instead the last reading there was - and what ended the readings is the
    # change, so the change lies at or after that minute and a window ending
    # there holds none of it. Mitigation is then handed an empty history and
    # proposes nothing, on the one incident whose only mitigation is putting back
    # the flag that blinded it.
    a_stated_onset = datetime(2026, 9, 22, 14, 10, tzinfo=UTC)
    an_incident_nothing_saw = an_incident_state(
        Alert(
            service=SOME_SERVICE,
            alert_name="NoMetricsReceived",
            stated_onset=a_stated_onset
        ),
        IncidentStatus.INVESTIGATING
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_found_the_incident_unread(
                investigate, a_determined_hypothesis(
                    an_incident_nothing_saw.incident_id
                )
            ))
        ) \
        .when(
            lambda: investigator_node(an_incident_nothing_saw,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(
            assert_that(fetch_flag_changes).was_called_with(onset=None)
        )


@pytest.mark.unit
def test_a_doubtful_cause_is_still_offered_as_the_one_to_try(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # A cause was named, and that is the whole admission test for a reversible
    # mitigation. The ambiguous incident, where the model splits its confidence
    # across two explanations, is exactly the one this used to abandon and the
    # walk exists to work through.
    an_investigating_incident = _an_investigating_incident()
    some_doubtful_confidence = 0.4
    a_doubtful_hypothesis = a_determined_hypothesis(
        an_investigating_incident.incident_id, some_doubtful_confidence
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        a_doubtful_hypothesis))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(all_of(
            the_result_at("hypothesis", a_doubtful_hypothesis),
            the_result_at("nothing_worth_trying", False)
        ))


@pytest.mark.unit
def test_investigator_node_reports_a_round_that_named_no_cause_at_all(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The loop reached the end of what it could read and named nothing. The
    # timeline has to say *that*, not "hypothesis formed" - a human picking
    # the incident up needs to know whether to look for more evidence or to
    # doubt the one on file.
    #
    # `nothing_worth_trying` is the fact that carries it: it is what tells this
    # round apart from a walk that has worked through everything it was offered,
    # since the two leave the same candidate list behind.
    an_investigating_incident = _an_investigating_incident()
    a_hypothesis_with_no_cause = an_undetermined_hypothesis(
        an_investigating_incident.incident_id
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        a_hypothesis_with_no_cause))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(all_of(
            the_result_is(
                StateDelta(
                    hypothesis=a_hypothesis_with_no_cause,
                    candidates=[a_hypothesis_with_no_cause],
                    candidate_index=0,
                    flag_changes=WHAT_THE_PROVIDER_RECORDED,
                    dependencies=WHAT_THE_REGISTER_LISTS,
                    already_read=[],
                    readings_cover_the_incident=True,
                    rounds=1,
                    confidence=None,
                    nothing_worth_trying=True,
                    narration=Narration(action="insufficient evidence")
                )
            ),
            assert_that(record_hypothesis).was_called_with(a_hypothesis_with_no_cause)
        ))


@pytest.mark.unit
def test_a_round_that_disproved_the_alarm_carries_the_window_that_did_it(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The round that found there was nothing to investigate, and the one thing
    # it leaves behind. The disproof travels with its own evidence because
    # nothing later in the walk or after it can check the claim - no recovery
    # confirms it and no next poll contradicts it.
    #
    # No hypothesis and no candidate, though the findings carried one. A
    # candidate is an explanation of a fault, and what this round established is
    # that there was no fault - so a row offering one would be the record
    # naming something to doubt where there is nothing to act on.
    #
    # The round is still counted. It happened and it read the metrics, and a
    # count that skipped it would make the only thing this walk did invisible to
    # anything totalling what Argus spent.
    an_investigating_incident = _an_investigating_incident()
    a_hypothesis_nobody_will_use = an_undetermined_hypothesis(
        an_investigating_incident.incident_id
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_disproved_the_alarm(
                investigate, a_hypothesis_nobody_will_use
            ))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(all_of(
            the_result_is(
                StateDelta(
                    disproof=A_DISPROOF,
                    rounds=1,
                    narration=Narration(
                        action="the alarm's own claim was not in the window"
                    )
                )
            ),
            _nothing_was_recorded(record_hypothesis)
        ))


@pytest.mark.unit
def test_a_disproved_alarm_reads_no_channel_and_searches_no_memory(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # What the short-circuit is for. Every read this round would otherwise make
    # asks what changed around a fault that did not happen, and memory would be
    # searched for earlier incidents resembling a service that was well - so the
    # round that establishes there is nothing to investigate must not go on
    # investigating.
    #
    # Asserted as the collaborators not having been reached rather than as the
    # delta being small, because a delta can be small for the wrong reason: a
    # node that read all three and then discarded the answers would satisfy the
    # case above and none of this one.
    an_investigating_incident = _an_investigating_incident()
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_disproved_the_alarm(
                investigate,
                an_undetermined_hypothesis(an_investigating_incident.incident_id)
            ))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      publisher=published.take)
        ) \
        .then(all_of(
            _no_channel_was_read(fetch_flag_changes, fetch_dependencies),
            _the_disproof_published_names(A_DISPROOF, published)
        ))


@pytest.mark.unit
def test_a_stopped_investigation_records_nothing_and_reads_nothing(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Stopped because the incident is no longer wanted. Every read and every
    # record below would be work on an incident nobody wants, so the node hands
    # back nothing at all and the walk's own check routes it out.
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_was_stopped(
                investigate,
                an_undetermined_hypothesis(an_investigating_incident.incident_id)
            ))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(all_of(
            the_result_is(StateDelta()),
            _nothing_was_reached_after_the_stop(
                record_hypothesis, fetch_flag_changes, fetch_dependencies
            )
        ))


@pytest.mark.unit
def test_the_investigation_asks_whether_this_incident_is_still_wanted(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The agent asks without knowing which incident it is working on, so the
    # node binds it: a question handed down about any other incident would
    # stop the wrong walk, or none.
    an_investigating_incident = _an_investigating_incident()
    asked: list[str] = []

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)
            ))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      still_wanted=_a_question_recording_who_it_asks_about(asked))
        ) \
        .then(
            _the_question_handed_down_asks_about(
                investigate, asked, an_investigating_incident.incident_id
            )
        )


@pytest.mark.unit
def test_a_disproved_alarm_leaves_the_walk_without_trying_a_mitigation() -> None:
    # The ending it reaches, and the one it must not: an incident with nothing
    # wrong with it has nothing to mitigate, so the route out of this node is the
    # one that leads to the write-up rather than to the proposal.
    Scenario() \
        .given(a_disproven_incident := _an_incident_in(IncidentStatus.DISPROVEN)) \
        .when(lambda: route_after_investigation(a_disproven_incident)) \
        .then(the_route_is(ESCALATED_ROUTE))


@pytest.mark.unit
def test_an_investigation_that_named_a_cause_is_routed_to_the_proposal() -> None:
    Scenario() \
        .given(a_mitigating_incident := _an_incident_in(IncidentStatus.MITIGATING)) \
        .when(lambda: route_after_investigation(a_mitigating_incident)) \
        .then(the_route_is(MITIGATING_ROUTE))


@pytest.mark.unit
def test_every_candidate_the_investigation_offered_is_recorded(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The incident's record should say what was considered, not only what was
    # acted on. A runner-up that never reached the table is a finding a human
    # picking the incident up cannot see Argus ever having had.
    an_investigating_incident = _an_investigating_incident()
    incident_id = an_investigating_incident.incident_id
    some_doubtful_confidence = 0.4
    the_best_answer = a_determined_hypothesis(incident_id)
    a_runner_up = a_determined_hypothesis(incident_id, some_doubtful_confidence)

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        the_best_answer,
                                                        a_runner_up))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(all_of(
            _every_candidate_was_recorded([the_best_answer, a_runner_up],
                                          record_hypothesis),
            the_result_at("candidates", [the_best_answer, a_runner_up]),
            the_result_at("candidate_index", 0),
            the_result_at("hypothesis", the_best_answer)))


@pytest.mark.unit
def test_a_resumed_investigation_is_told_what_was_read_and_what_failed(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Both halves of what makes a second round worth paying for. Without what
    # was already read it cannot tell a fresh window from one it has seen;
    # without the attempts it re-answers the question that has already been
    # answered.
    a_window_already_read = Reading(channel=RetrievalChannel.LOGS,
                                    window_start="2026-08-20T10:30:00Z",
                                    window_end="2026-08-20T11:08:00Z")
    a_refuted_attempt = _an_attempt_to(putting_back(SOME_FLAG))
    a_second_round = _an_investigating_incident().model_copy(
        update={"already_read": [a_window_already_read],
                "attempts": [a_refuted_attempt]}
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(a_second_round.incident_id)))
        ) \
        .when(
            lambda: investigator_node(a_second_round,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(all_of(
            _the_investigation_was_told("already_read", [a_window_already_read],
                                        investigate),
            _the_investigation_was_told("already_refuted", [a_refuted_attempt],
                                        investigate)))


@pytest.mark.unit
def test_a_later_round_does_not_act_on_an_explanation_already_refuted(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # A second investigation is told what was tried, and is free to conclude the
    # same thing anyway - being told does not oblige it to change its mind. What
    # it must not do is send the walk back to change the same flag a second
    # time, which would spend the round budget flipping one flag back and forth.
    #
    # The round reports that it found nothing worth trying, which is what ends
    # the incident. It is a fact about the investigation, not a status: the walk
    # leaves an identical candidate list behind when it runs out, and those two
    # do not end the same way.
    a_round_after_that_flag_was_tried = _an_investigating_incident().model_copy(
        update={"attempts": [_an_attempt_to(putting_back(SOME_FLAG))]}
    )
    the_same_explanation_again = a_candidate_blaming(
        a_round_after_that_flag_was_tried.incident_id, SOME_FLAG
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        the_same_explanation_again))
        ) \
        .when(
            lambda: investigator_node(a_round_after_that_flag_was_tried,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(the_result_at("nothing_worth_trying", True))


@pytest.mark.unit
def test_a_later_round_does_not_restart_a_service_it_already_restarted(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The same guard, for the kind of action it never used to cover. A leak is
    # described in fresh prose every round, so comparing the candidates found
    # nothing alike and the walk would restart one service once per candidate -
    # with the gate's cap as the only thing stopping it.
    a_round_after_the_restart = _an_investigating_incident().model_copy(
        update={"attempts": [_an_attempt_to(restarting(SOME_SERVICE))]}
    )
    the_same_leak_in_other_words = a_leak_blamed_on(
        a_round_after_the_restart.incident_id, "unbounded cache growth"
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(investigate,
                                                        the_same_leak_in_other_words))
        ) \
        .when(
            lambda: investigator_node(a_round_after_the_restart,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(the_result_at("nothing_worth_trying", True))


@pytest.mark.unit
def test_an_investigation_that_named_none_reaches_a_human() -> None:
    Scenario() \
        .given(an_escalated_incident := _an_incident_in(IncidentStatus.ESCALATED)) \
        .when(lambda: route_after_investigation(an_escalated_incident)) \
        .then(the_route_is(ESCALATED_ROUTE))


@pytest.mark.unit
def test_an_action_an_earlier_incident_refuted_is_tried_last(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The one thing memory is allowed to do to a walk. The model believed the
    # first candidate more, and an earlier incident says taking that action did
    # not help - which is evidence the model had no way to weigh, because it is
    # not about this incident at all.
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_candidate_blaming(an_investigating_incident.incident_id, SOME_FLAG),
                a_candidate_blaming(an_investigating_incident.incident_id,
                                     ANOTHER_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    putting_back(SOME_FLAG)
                ),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                fetch_dependencies=fetch_dependencies)
        ) \
        .then(_the_candidates_are_about([ANOTHER_FLAG, SOME_FLAG]))


@pytest.mark.unit
def test_a_restart_an_earlier_incident_refuted_demotes_a_leak_worded_otherwise(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # What the identity bought across incidents. Two incidents describe one
    # leak in two sets of words, and a restart addressed to the alert's service
    # is the same experiment in both - which the record could not say while it
    # kept the model's prose as the thing it was found by.
    an_investigating_incident = _an_investigating_incident()
    the_leak_nobody_worded_the_same_way = "kuki-service resident set climbing"

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_leak_blamed_on(an_investigating_incident.incident_id,
                                  the_leak_nobody_worded_the_same_way),
                a_candidate_blaming(an_investigating_incident.incident_id,
                                     ANOTHER_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    restarting(SOME_SERVICE)
                ),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                fetch_dependencies=fetch_dependencies)
        ) \
        .then(_the_candidates_are_about([ANOTHER_FLAG,
                                         the_leak_nobody_worded_the_same_way]))


@pytest.mark.unit
def test_a_discard_an_earlier_incident_refuted_demotes_a_divergence_worded_otherwise(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The same thing the restart case says, for the cause whose action this
    # round has to supply the address of. Two incidents describe one stale
    # cache in two sets of words, and discarding the entries the alert named is
    # the same experiment in both - which this round can only say while it is
    # still handing those keys down. Stop handing them down and the candidate
    # is answered by nothing, memory recognises nothing, and the walk starts on
    # an experiment an earlier incident already ran and refuted.
    a_diverging_incident = _a_diverging_incident()
    the_divergence_nobody_worded_the_same_way = "monthly spend totals read low"

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_divergence_blamed_on(a_diverging_incident.incident_id,
                                        the_divergence_nobody_worded_the_same_way),
                a_candidate_blaming(a_diverging_incident.incident_id, ANOTHER_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                a_diverging_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    discarding(SOME_SERVICE)
                ),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                fetch_dependencies=fetch_dependencies)
        ) \
        .then(_the_candidates_are_about(
            [ANOTHER_FLAG, the_divergence_nobody_worded_the_same_way]))


@pytest.mark.unit
def test_an_order_memory_changed_is_said_on_the_timeline(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # A walk that tried its second-best candidate first, with nothing saying
    # why, is a walk a human reading the incident back cannot account for. What
    # is said is the action, because "moved kuki-service down the list" is true
    # of a service restarted and of a flag put back.
    an_investigating_incident = _an_investigating_incident()
    the_incident_that_moved_it = "3f2b1a09-0000-4000-8000-00000000000a"
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_candidate_blaming(an_investigating_incident.incident_id, SOME_FLAG),
                a_candidate_blaming(an_investigating_incident.incident_id,
                                     ANOTHER_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_an_earlier_incident_that_refuted(
                    putting_back(SOME_FLAG), incident_id=the_incident_that_moved_it
                ),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                fetch_dependencies=fetch_dependencies,
                publisher=published.take)
        ) \
        .then(_it_was_said_that(published,
                                putting_back(SOME_FLAG),
                                the_incident_that_moved_it))


@pytest.mark.unit
def test_an_order_memory_left_alone_is_not_said(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The ordinary incident, and the one that has to stay silent. A line on
    # every walk saying the order did not change is a timeline nobody reads.
    an_investigating_incident = _an_investigating_incident()
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_candidate_blaming(an_investigating_incident.incident_id, SOME_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_nothing_like_it_has_happened(),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                fetch_dependencies=fetch_dependencies,
                publisher=published.take)
        ) \
        .then(_no_reordering_was_said(published))


@pytest.mark.unit
def test_what_memory_recalled_is_said_on_the_timeline(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Said whether or not anything moved, which is the whole reason it is a line
    # of its own. A reordering is visible only where a round offered something to
    # move a candidate behind, and how many candidates a round offers is the
    # model's to decide - so a timeline carrying only `CandidatesReordered` is
    # silent about memory on every walk where memory was read and did find
    # something. One candidate here, so nothing can move and the recall is the
    # only thing there is to say.
    an_investigating_incident = _an_investigating_incident()
    the_nearest = "3f2b1a09-0000-4000-8000-00000000000a"
    the_one_behind_it = "3f2b1a09-0000-4000-8000-00000000000b"
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_candidate_blaming(an_investigating_incident.incident_id, SOME_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_earlier_incidents_nearest_first(
                    the_nearest, the_one_behind_it
                ),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                fetch_dependencies=fetch_dependencies,
                publisher=published.take)
        ) \
        .then(_the_recall_said(published, [the_nearest, the_one_behind_it]))


@pytest.mark.unit
def test_a_recall_that_found_nothing_is_not_said(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Silent on an empty search, for the reason a reordering that moved nothing is
    # silent: a line on every walk saying memory held nothing is a timeline nobody
    # reads.
    an_investigating_incident = _an_investigating_incident()
    published: Kept[IncidentEvent] = Kept()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_candidate_blaming(an_investigating_incident.incident_id, SOME_FLAG)
            ))
        ) \
        .when(
            lambda: investigator_node(
                an_investigating_incident,
                investigate=investigate,
                recall_similar=_nothing_like_it_has_happened(),
                record_hypothesis=record_hypothesis,
                fetch_flag_changes=fetch_flag_changes,
                fetch_dependencies=fetch_dependencies,
                publisher=published.take)
        ) \
        .then(_no_recall_was_said(published))


@pytest.mark.unit
def test_the_round_says_what_flag_history_it_reasoned_from(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Every action this round might propose rests on this and nothing else:
    # which flag moved, which way, and when. Published from the node that reads
    # it, because by the time an action exists the history has already been
    # reduced to one decision about one flag.
    published: Kept[IncidentEvent] = Kept()
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      publisher=published.take)
        ) \
        .then(_the_history_published_is(WHAT_THE_PROVIDER_RECORDED, published))


@pytest.mark.unit
def test_a_flag_history_that_could_not_be_read_is_not_published_as_an_empty_one(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # "Nothing changed" and "the provider did not answer" lead to the same
    # place - no action - and are not the same fact. A page showing an empty
    # history for the second would be stating that nothing had changed, and a
    # round carrying one forward would let the proposal node act on it.
    published: Kept[IncidentEvent] = Kept()
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_provider_cannot_be_reached(fetch_flag_changes)),
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      publisher=published.take)
        ) \
        .then(all_of(
            _no_history_was_published(published),
            the_result_at("flag_changes", None)))


@pytest.mark.unit
def test_a_flag_history_that_could_not_be_read_is_said_to_have_gone_unanswered(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The other half of the test above it. That one refuses the wrong line - an
    # empty history, which would state that nothing changed - and refusing it
    # left the round with no line at all, which is its own misstatement: an
    # unread channel and a channel that was asked and refused look identical in
    # an account that says nothing about either.
    #
    # It is the provider's own failure and not the round's, so the round carries
    # on: `flag_changes` is still `None`, the investigation still runs, and what
    # this adds is only that a person reading the incident can see which of the
    # two silences they are looking at.
    published: Kept[IncidentEvent] = Kept()
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_provider_cannot_be_reached(fetch_flag_changes)),
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      publisher=published.take)
        ) \
        .then(all_of(
            _the_retrieval_was_said_to_have_not_answered(published, FLAG_PROVIDER_UNREACHABLE),
            _no_history_was_published(published),
            the_result_at("flag_changes", None)))


@pytest.mark.unit
def test_the_deploy_history_is_asked_at_an_onset_the_alert_stated(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock,
    fetch_deployments: MagicMock
) -> None:
    # The flag history's question, asked of the other change a service has. A
    # mode that names the damage rather than the change is answered by undoing
    # whichever of the two sits at the onset, so both are read there - and read
    # about the service that was paged, since a deployment belongs to one.
    a_stated_onset = datetime(2026, 9, 22, 14, 10, tzinfo=UTC)
    an_incident_found_by_a_check = an_incident_state(
        Alert(
            service=SOME_SERVICE,
            alert_name="SpendTotalsDoNotReconcile",
            stated_onset=a_stated_onset
        ),
        IncidentStatus.INVESTIGATING
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(
                    an_incident_found_by_a_check.incident_id
                )
            ))
        ) \
        .when(
            lambda: investigator_node(an_incident_found_by_a_check,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      fetch_deployments=fetch_deployments)
        ) \
        .then(
            assert_that(fetch_deployments).was_called_with(
                service=SOME_SERVICE, onset=a_stated_onset
            )
        )


@pytest.mark.unit
def test_the_round_carries_the_deploy_history_it_read(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock,
    fetch_deployments: MagicMock
) -> None:
    # Carried for the reason the flag history is: the candidate the round chose
    # and the action proposed for it later must be reasoned from one account of
    # what changed, not from two reads that could disagree.
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      fetch_deployments=fetch_deployments)
        ) \
        .then(
            the_result_at("deployments", WHAT_THE_PLATFORM_RECORDED)
        )


@pytest.mark.unit
def test_the_round_carries_the_placement_the_investigation_recorded(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Carried rather than read again where it is used. A pin to a card is
    # decided from it, and a placement read when acting is read after whatever
    # the walk did first has moved the pods - which is reading the remedy as the
    # cause.
    an_investigating_incident = _an_investigating_incident()
    the_placement_recorded = a_placement()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_recorded_the_placement(
                investigate,
                the_placement_recorded,
                a_determined_hypothesis(an_investigating_incident.incident_id)
            ))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(
            the_result_at("placement", the_placement_recorded)
        )


@pytest.mark.unit
def test_a_round_that_could_not_read_the_placement_does_not_keep_the_last_one(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Every round re-reads, as the flag history is re-read, and what a round
    # could not read reaches the state as unread. An earlier round's placement
    # left standing would be pods recorded against an onset and a fleet this
    # round no longer has - and a pin decided from it is decided from the past.
    an_incident_an_earlier_round_placed = _an_investigating_incident().model_copy(
        update={"placement": a_placement()}
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_incident_an_earlier_round_placed.incident_id)
            ))
        ) \
        .when(
            lambda: investigator_node(an_incident_an_earlier_round_placed,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(
            _the_placement_is_sent_on_as_unread()
        )


@pytest.mark.unit
def test_a_deploy_history_that_could_not_be_read_is_carried_as_unread(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock,
    fetch_deployments: MagicMock
) -> None:
    # `None` rather than an empty history, as the flag history's failure is: an
    # empty one says nothing was deployed, and a corruption whose cause was a
    # deployment would then be answered by nothing for a reason that is false.
    published: Kept[IncidentEvent] = Kept()
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_platform_cannot_be_reached(fetch_deployments)),
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      fetch_deployments=fetch_deployments,
                                      publisher=published.take)
        ) \
        .then(all_of(
            _the_retrieval_was_said_to_have_not_answered(published, PLATFORM_UNREACHABLE),
            the_result_at("deployments", None)))


@pytest.mark.unit
def test_a_later_round_does_not_roll_back_a_deployment_it_already_rolled_back(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock,
    fetch_deployments: MagicMock
) -> None:
    # The guard once more, for the candidate whose answer is read off the deploy
    # history. The round asks each candidate which action would answer it, and
    # has to ask with the history it just read: asked without it, a corruption
    # no flag caused reads as answered by nothing, which matches nothing already
    # tried - so the walk would roll the same deployment back once per wording.
    a_round_after_the_rollback = _an_investigating_incident().model_copy(
        update={"attempts": [_an_attempt_to(rolling_back(SOME_SERVICE))]}
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_corruption_blamed_on(a_round_after_the_rollback.incident_id,
                                       "monthly totals fall behind the purchases")))
        ) \
        .when(
            lambda: investigator_node(a_round_after_the_rollback,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      fetch_deployments=fetch_deployments)
        ) \
        .then(the_result_at("nothing_worth_trying", True))


@pytest.mark.unit
def test_a_later_round_does_not_hold_the_fleet_to_a_card_it_already_held_it_to(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The guard once more, for the candidate whose answer is read off the
    # placement. The round asks each candidate which action would answer it, and
    # has to ask with the placement its investigation just recorded: asked
    # without it, a moved replica reads as answered by nothing, which matches
    # nothing already tried - so the walk would pin the same fleet once per
    # wording.
    a_round_after_the_pin = _an_investigating_incident().model_copy(
        update={"attempts": [_an_attempt_to(holding_to_a_card(SOME_SERVICE))]}
    )

    Scenario() \
        .given(
            calling(lambda: _the_investigation_recorded_the_placement(
                investigate,
                a_placement(),
                an_accelerator_blamed_on(a_round_after_the_pin.incident_id,
                                         "one replica holds far more for review")))
        ) \
        .when(
            lambda: investigator_node(a_round_after_the_pin,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(the_result_at("nothing_worth_trying", True))


@pytest.mark.unit
def test_the_round_carries_what_the_register_says_this_service_calls(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Read at the top of the round, beside the flag history, and asked about
    # the service that was paged - which is the service whose dependencies
    # bound what the gate will let an action be addressed to. A gate that
    # fetched this for itself would be one whose answer depended on a document
    # store being reachable at the instant it asked.
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(all_of(
            the_result_at("dependencies", WHAT_THE_REGISTER_LISTS),
            _the_register_was_asked_about(SOME_SERVICE, fetch_dependencies)))


@pytest.mark.unit
def test_a_register_that_could_not_be_read_leaves_nothing_else_within_reach(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # Unlike the flag history, an unreadable register is not carried as its own
    # fact. Every mitigation addressed to the alerting service stays available -
    # that one is within reach whatever the register says - and everything aimed
    # elsewhere is refused, which is the restrictive direction and the right one:
    # an estate is not a thing to guess at. An incident does not stall because a
    # document store was down.
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_register_cannot_be_reached(fetch_dependencies)),
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(the_result_at("dependencies", []))


@pytest.mark.unit
def test_a_flag_history_that_could_not_be_read_is_logged_as_a_warning(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock,
    caplog: pytest.LogCaptureFixture
) -> None:
    # Degraded rather than lost: the round carries on without it, and no flag
    # this round blames can be acted on - which is worth a line of its own
    # before anybody wonders why no flag was reverted.
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_provider_cannot_be_reached(fetch_flag_changes)),
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.investigating", logging.WARNING,
                                  "flag history could not be read", failure=RuntimeError)
        )


@pytest.mark.unit
def test_a_deploy_history_that_could_not_be_read_is_logged_as_a_warning(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock,
    fetch_deployments: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_platform_cannot_be_reached(fetch_deployments)),
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      fetch_deployments=fetch_deployments)
        ) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.investigating", logging.WARNING,
                                  "deployment history could not be read",
                                  failure=RuntimeError)
        )


@pytest.mark.unit
def test_a_register_that_could_not_be_read_is_logged_as_a_warning(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock,
    caplog: pytest.LogCaptureFixture
) -> None:
    # Nothing but the alerting service is within reach for the rest of the
    # round, which is the line saying why a dependency was never restarted.
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_register_cannot_be_reached(fetch_dependencies)),
            calling(lambda: _the_investigation_returned(
                investigate,
                a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies)
        ) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.investigating", logging.WARNING,
                                  "service register could not be read",
                                  values={"service": an_investigating_incident.alert.service},
                                  failure=RuntimeError)
        )


@pytest.mark.unit
def test_the_graph_says_when_it_invokes_the_investigator(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # A narration that begins at the first retrieval starts mid-sentence: the
    # Orchestrator handing the incident over is the thing that caused it.
    published: list[IncidentEvent] = []
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      publisher=published.append)
        ) \
        .then(_the_agents_invoked_were([Actor.INVESTIGATOR], published))


@pytest.mark.unit
def test_the_investigation_publishes_to_the_same_place_the_graph_does(
    investigate: MagicMock, record_hypothesis: MagicMock,
    fetch_flag_changes: MagicMock, fetch_dependencies: MagicMock
) -> None:
    # The Investigator's own account and the graph's are one narration, and
    # they are only one if the node hands its publisher down rather than
    # letting the agent publish somewhere of its own.
    published: list[IncidentEvent] = []
    an_investigating_incident = _an_investigating_incident()

    Scenario() \
        .given(
            calling(lambda: _the_investigation_returned(
                investigate, a_determined_hypothesis(an_investigating_incident.incident_id)))
        ) \
        .when(
            lambda: investigator_node(an_investigating_incident,
                                      investigate=investigate,
                                      recall_similar=_nothing_like_it_has_happened(),
                                      record_hypothesis=record_hypothesis,
                                      fetch_flag_changes=fetch_flag_changes,
                                      fetch_dependencies=fetch_dependencies,
                                      publisher=published.append)
        ) \
        .then(_the_investigation_was_told("publisher", published.append, investigate))


def _the_provider_cannot_be_reached(fetch_flag_changes: MagicMock) -> None:
    fetch_flag_changes.side_effect = RuntimeError(FLAG_PROVIDER_UNREACHABLE)


def _the_register_cannot_be_reached(fetch_dependencies: MagicMock) -> None:
    fetch_dependencies.side_effect = RuntimeError(
        "The service register could not be reached."
    )


def _the_platform_cannot_be_reached(fetch_deployments: MagicMock) -> None:
    fetch_deployments.side_effect = RuntimeError(PLATFORM_UNREACHABLE)


def _an_earlier_incident_that_refuted(
    identity: ActionIdentity,
    incident_id: str = "3f2b1a09-0000-4000-8000-00000000000a"
) -> ports.RecallSimilar:
    """Memory holding one incident that took this action and did not recover.

    Everything a search would have needed to find it is arbitrary: the search
    already happened by the time a walk reads one, and what it reads is the
    list of what was tried.
    """
    def recall(dont_care_description: str,
               dont_care_service: str) -> list[RememberedIncident]:
        return [
            RememberedIncident(
                incident_id=incident_id,
                described_as="an incident that looked like this one",
                service=SOME_SERVICE,
                alert_name="HighErrorRate",
                tried=[WhatWasTried(identity=identity, verdict=Verdict.REFUTED)]
            )
        ]

    return recall


def _earlier_incidents_nearest_first(*incident_ids: str) -> ports.RecallSimilar:
    """Memory holding several incidents, in the order a search returned them.

    What each of them tried was refuted, and refuted on a subject no candidate
    here blames - so nothing memory holds can move anything, which is the
    arrangement these two cases need. What is under test is that the search is
    accounted for at all, and a stub that also demoted a candidate would let a
    reordering's own line satisfy the assertion.
    """
    def recall(dont_care_description: str,
               dont_care_service: str) -> list[RememberedIncident]:
        return [
            RememberedIncident(
                incident_id=incident_id,
                described_as="an incident that looked like this one",
                service=SOME_SERVICE,
                alert_name="HighErrorRate",
                tried=[
                    WhatWasTried(
                        identity=putting_back(ANOTHER_FLAG), verdict=Verdict.REFUTED
                    )
                ]
            )
            for incident_id in incident_ids
        ]

    return recall


def _the_candidates_are_about(expected: list[str]) -> Assertion[StateDelta]:
    def assertion(delta: StateDelta) -> bool:
        if delta.candidates is None:
            raise AssertionError(
                f"Expected {expected}, the delta carried no candidates."
            )

        subjects = [candidate.subject for candidate in delta.candidates]

        if subjects != expected:
            raise AssertionError(f"Expected {expected}, got {subjects}")

        return True

    return assertion


def _the_register_was_asked_about(service: str,
                                  fetch_dependencies: MagicMock) -> Assertion[object]:
    """That the register was asked about the service the alert named, once.

    Once, because the answer is carried rather than re-read: a round that asked
    twice would be a round able to reason about two registers, which is the
    thing carrying it in the state exists to prevent.
    """
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args[0] for call in fetch_dependencies.call_args_list]

        if asked != [service]:
            raise AssertionError(
                f"Expected the register to be asked about [{service}] once, "
                f"it was asked about {asked}."
            )

        return True

    return assertion


def _it_was_said_that(published: Kept[IncidentEvent],
                      moved: ActionIdentity,
                      on_the_strength_of: str) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [
            event for event in published.taken
            if isinstance(event, CandidatesReordered)
        ]

        if not said:
            raise AssertionError(
                f"Expected a reordering to be said, got "
                f"{[event.kind for event in published.taken]}"
            )

        what_it_said = an_identity(said[0].action_type, said[0].subject)

        if what_it_said != moved:
            raise AssertionError(
                f"Expected [{moved}] to have moved, got [{what_it_said}]."
            )

        if said[0].on_the_strength_of != on_the_strength_of:
            raise AssertionError(
                f"Expected it said on [{on_the_strength_of}], "
                f"got [{said[0].on_the_strength_of}]."
            )

        return True

    return assertion


def _no_reordering_was_said(published: Kept[IncidentEvent]) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [
            event for event in published.taken
            if isinstance(event, CandidatesReordered)
        ]

        if said:
            raise AssertionError(f"Expected no reordering to be said, got {said}")

        return True

    return assertion


def _the_recall_said(published: Kept[IncidentEvent],
                     expected: list[str]) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [
            event for event in published.taken
            if isinstance(event, SimilarIncidentsRecalled)
        ]

        if len(said) != 1:
            raise AssertionError(
                f"Expected one recall to be said, got "
                f"{[event.kind for event in published.taken]}."
            )

        if said[0].incident_ids != expected:
            raise AssertionError(
                f"Expected the recall to name {expected} nearest first, got "
                f"{said[0].incident_ids}."
            )

        return True

    return assertion


def _no_recall_was_said(published: Kept[IncidentEvent]) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [
            event for event in published.taken
            if isinstance(event, SimilarIncidentsRecalled)
        ]

        if said:
            raise AssertionError(f"Expected no recall to be said, got {said}.")

        return True

    return assertion


def _the_history_published_is(expected: list[FlagChange],
                              published: Kept[IncidentEvent]
                              ) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        read = [event for event in published.taken
                if isinstance(event, FlagChangesRetrieved)]

        if len(read) != 1:
            raise AssertionError(f"Expected one FlagChangesRetrieved, got {len(read)}")

        if read[0].changes != expected:
            raise AssertionError(
                f"Expected the history {expected} to be published, got "
                f"{read[0].changes}"
            )

        return True

    return assertion


def _no_history_was_published(published: Kept[IncidentEvent]
                              ) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        read = [event for event in published.taken
                if isinstance(event, FlagChangesRetrieved)]

        if read:
            raise AssertionError(
                f"Expected an unreadable provider to publish no history, it "
                f"published {read}"
            )

        return True

    return assertion


def _the_retrieval_was_said_to_have_not_answered(
    published: Kept[IncidentEvent],
    because: str
) -> Assertion[StateDelta]:
    """One line saying a retrieval would not answer, carrying the error it
    failed with and no minute.

    The error is how a reader tells which retrieval it was. Each source here
    fails with one of its own, so a line carrying the flag provider's error in
    a case about the platform is a line about the wrong source.

    The companion to `_no_history_was_published` above, and the two are the
    whole claim between them: not an empty history, which would state that
    nothing changed, *and* not silence either, which states nothing at all and
    reads on the page as a channel nobody thought to try.

    No minute, because there is none. A history is not about a minute the way
    a verification's failed read is - it is the window the round asked about -
    and a field filled in to look complete would put a moment on the page that
    nothing here measured.
    """
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [event for event in published.taken
                if isinstance(event, RetrievalUnanswered)]

        if len(said) != 1:
            raise AssertionError(
                f"Expected one line saying a retrieval would not answer, and "
                f"{len(said)} were published - so a reader cannot tell a "
                f"source that was asked and refused from one nobody asked."
            )

        if said[0].because != because:
            raise AssertionError(
                f"Expected the line to carry [{because}], the error the source "
                f"under test failed with, and it carries [{said[0].because}] - "
                f"so it is about some other retrieval."
            )

        if said[0].minute is not None:
            raise AssertionError(
                f"Expected no minute on a history that could not be read, and "
                f"it names [{said[0].minute}] - which puts a moment on the "
                f"page that nothing here measured."
            )

        return True

    return assertion


def _an_investigating_incident() -> IncidentState:
    return _an_incident_in(IncidentStatus.INVESTIGATING)


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    some_alert = Alert(service=SOME_SERVICE, alert_name="HighErrorRate")

    return an_incident_state(some_alert, status)


def _a_diverging_incident() -> IncidentState:
    """An incident whose alert named the cache entries that disagree.

    The only incident in this file whose alert carries more than a service.
    What memory is allowed to demote is matched on the action a candidate would
    be answered with, and the action for this cause is addressed to keys - so a
    round that stopped carrying them would leave this candidate answered by
    nothing and memory with nothing to recognise it by.
    """
    the_entries_the_check_found = ("io-shop:summary:2026-09:shopper-4",
                                   "io-shop:summary:2026-09:shopper-9")
    the_alert_that_found_them = Alert(
        service=SOME_SERVICE,
        alert_name="CachedSpendTotalsAreStale",
        stale_entry_keys=the_entries_the_check_found,
        stale_entries_found=len(the_entries_the_check_found)
    )

    return an_incident_state(the_alert_that_found_them,
                             IncidentStatus.INVESTIGATING)


def _no_channel_was_read(*channels: MagicMock) -> Assertion[StateDelta]:
    """That none of the named collaborators was reached at all.

    The whole set rather than the first, because the failure this guards against
    is a short-circuit that was never taken - in which case every one of them was
    reached, and a message naming one would understate it.
    """
    def assertion(dont_care_delta: StateDelta) -> bool:
        read = [channel for channel in channels if channel.called]

        if read:
            raise AssertionError(
                f"Expected no channel to be read, and {len(read)} of "
                f"{len(channels)} were - so the round went on investigating a "
                f"service it had already established was well."
            )

        return True

    return assertion


def _nothing_was_recorded(record_hypothesis: MagicMock) -> Assertion[StateDelta]:
    """That no candidate reached the incident's record.

    A candidate is an explanation of a fault. A row offering one here would be
    the record naming something for a reader to doubt where there was nothing to
    act on.
    """
    def assertion(dont_care_delta: StateDelta) -> bool:
        if record_hypothesis.called:
            raise AssertionError(
                f"Expected no candidate to be recorded, and "
                f"{record_hypothesis.call_count} were."
            )

        return True

    return assertion


def _the_disproof_published_names(expected: Disproof,
                                  published: Kept[IncidentEvent]
                                  ) -> Assertion[StateDelta]:
    """That the timeline carries the disproof, with the grounds it was made on.

    The grounds are the assertion. A disproof is the one claim in a walk that
    nothing later can check, so an event announcing one without saying what was
    judged and over how long would leave the record with a verdict and no case.
    """
    def assertion(dont_care_delta: StateDelta) -> bool:
        said = [
            event for event in published.taken if isinstance(event, AlarmDisproven)
        ]

        if len(said) != 1:
            raise AssertionError(
                f"Expected exactly one disproof to be published, got {said}."
            )

        grounds = (
            said[0].signals_judged, said[0].earliest_minute,
            said[0].latest_minute, said[0].minutes_judged
        )
        wanted = (
            expected.signals_judged, expected.earliest_minute,
            expected.latest_minute, expected.minutes_judged
        )

        if grounds != wanted:
            raise AssertionError(
                f"Expected the disproof to have been published on the grounds "
                f"{wanted}, and it was published on {grounds}."
            )

        return True

    return assertion


def _the_investigation_was_stopped(investigate: MagicMock,
                                   *candidates: Hypothesis) -> None:
    """An investigation that ended because its incident is no longer wanted.

    The candidates are still handed back, because findings always carry at
    least one - the point of the cases below is that this node does nothing
    with them.
    """
    investigate.return_value = agent_investigator.Findings(
        candidates=list(candidates), already_read=[], stopped=True
    )


def _a_question_recording_who_it_asks_about(asked: list[str]) -> IsStillWanted:
    def still_wanted(incident_id: str, /) -> bool:
        asked.append(incident_id)
        return True

    return still_wanted


def _nothing_was_reached_after_the_stop(*collaborators: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        reached = [collaborator for collaborator in collaborators if collaborator.called]

        if reached:
            raise AssertionError(
                f"Expected nothing to be read or recorded once the investigation "
                f"stopped, and {len(reached)} of {len(collaborators)} were reached."
            )

        return True

    return assertion


def _the_question_handed_down_asks_about(investigate: MagicMock,
                                         asked: list[str],
                                         incident_id: str) -> Assertion[StateDelta]:
    def assertion(dont_care_delta: StateDelta) -> bool:
        handed_down = investigate.call_args.kwargs.get("still_wanted")

        if handed_down is None:
            raise AssertionError(
                "Expected the investigation to be handed a way to ask whether it "
                "is still wanted, and it was handed none."
            )

        handed_down()

        if asked != [incident_id]:
            raise AssertionError(
                f"Expected the question handed down to ask about incident "
                f"[{incident_id}], and it asked about {asked}."
            )

        return True

    return assertion


def _the_investigation_disproved_the_alarm(investigate: MagicMock,
                                           *candidates: Hypothesis) -> None:
    """An investigation whose window held none of what the alarm claimed.

    The candidates are still handed back, because findings always carry at
    least one - the point of the cases below is that this node does nothing
    with them.
    """
    investigate.return_value = agent_investigator.Findings(
        candidates=list(candidates), already_read=[], disproof=A_DISPROOF
    )


def _the_investigation_returned(investigate: MagicMock,
                                *candidates: Hypothesis) -> None:
    investigate.return_value = agent_investigator.Findings(
        candidates=list(candidates), already_read=[]
    )


def _the_investigation_recorded_the_placement(investigate: MagicMock,
                                              placement: RecordedPlacement,
                                              *candidates: Hypothesis) -> None:
    investigate.return_value = agent_investigator.Findings(
        candidates=list(candidates), already_read=[], placement=placement
    )


def _the_placement_is_sent_on_as_unread() -> Assertion[StateDelta]:
    """Sent on as `None`, rather than left out of the update.

    Left out, the state would keep whatever an earlier round put there - which
    is the failure this asks about, and which `None` read off the delta itself
    could not tell from a node that never mentioned the field.
    """
    def assertion(delta: StateDelta) -> bool:
        updates = delta.as_updates()

        if "placement" not in updates or updates["placement"] is not None:
            raise AssertionError(
                f"Expected the placement to be sent on as unread, and the round "
                f"sent {updates.get('placement', 'nothing about it')!r}."
            )

        return True

    return assertion


def _the_investigation_found_the_incident_unread(investigate: MagicMock,
                                                *candidates: Hypothesis) -> None:
    """An investigation whose window said nothing about the incident's minutes.

    The shape a monitoring blind spot produces: readings up to the minute before
    the onset and none at or after it - the onset being the first minute nothing
    reported. What matters to this node is only that the findings say so and that
    the saying reaches the gate, which is where the fact is finally asked a
    question.
    """
    investigate.return_value = agent_investigator.Findings(
        candidates=list(candidates),
        already_read=[],
        readings_cover_the_incident=False
    )


def _an_attempt_to(identity: ActionIdentity) -> Attempt:
    return Attempt(identity=identity, enabled=False, occurred_at="2026-08-29T16:00:00Z")


def _every_candidate_was_recorded(expected: list[Hypothesis],
                                  record_hypothesis: MagicMock) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        recorded = [call.args[0] for call in record_hypothesis.call_args_list]
        if recorded != expected:
            raise AssertionError(
                f"Expected {len(expected)} candidate(s) recorded, got {len(recorded)}"
            )

        return True

    return assertion


def _the_investigation_was_told(field: str,
                                expected: object,
                                investigate: MagicMock) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        told = investigate.call_args.kwargs[field]
        if told != expected:
            raise AssertionError(
                f"Expected the investigation to be told [{field}] = {expected}, "
                f"it was told {told}"
            )

        return True

    return assertion


def _the_agents_invoked_were(expected: list[Actor],
                             published: list[IncidentEvent]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        invoked = [event.agent for event in published
                   if isinstance(event, AgentInvoked)]
        if invoked != expected:
            raise AssertionError(
                f"Expected {expected} to have been announced, got {invoked}"
            )

        return True

    return assertion


def _nothing_like_it_has_happened() -> ports.RecallSimilar:
    """Memory with nothing in it, which is what most cases here assume.

    These are cases about what an investigation found and what the walk does
    with it. What an earlier incident was done about is a different subject with
    a file of its own, and a recall answering here would put a second reason
    behind every order these cases assert.
    """
    def recall(dont_care_description: str,
               dont_care_service: str) -> list[RememberedIncident]:
        return []

    return recall
