"""Turning four tables back into one incident.

The agent holds no connection and reads no rows: what it is handed is this,
assembled from the incident's own row, the account it published, the
candidates it ranked and the actions it took. Gathering is the Orchestrator's
work because the tables are, and because an agent that queried for its own
evidence could ask a different question than the page beside it.

Nothing here is derived or judged. Every value comes from something that was
recorded while it was happening - which is the point: what happened was
decided then, and a postmortem re-deciding it from conclusions would be
writing a different incident.

The last case covers the other half of this module - writing the document
rather than gathering what goes in it - and exists to hold a claim that would
otherwise be only an assertion in a commit message: that this path can be
driven with no payment provider, no on-call system, no HR source, no read tier
and no model. Every one of those is a plain function here. Before the sources
and the client factory arrived as arguments, this call could not be made at all
without all five installed and reachable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from agent_postmortem import CandidateRecord, DeploymentChangesRecord, IncidentEvidence, Sources
from argus_core import connect_from_env, new_id, parse_iso, utc_now
from argus_core.anomaly import AnomalyThresholds
from argus_core.events import (
    ActionRecommended,
    ActionRefused,
    ActionTaken,
    AlertAcknowledged,
    ChangesRetrieved,
    DeploymentChangesRead,
    FixAttempted,
    FlagChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    IncidentRemembered,
    LeadWeighed,
    LogsRetrieved,
    MessageUnderstood,
    OnsetDetected,
    PersonWrote,
    QuestionAnswered,
    RecoveryChecked,
    RememberingFailed,
    ResolutionOffered,
    RetrievalRequested,
    RetrievalUnanswered,
    StatusChanged,
)
from argus_core.llm import ClientFor, LLMClient
from argus_core.models import (
    CHAT_THREAD,
    DISCARD_CACHE_ENTRIES,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    ActionProgress,
    ActionType,
    Alert,
    ChangeEvent,
    ChangeKind,
    ChannelReading,
    CodeUse,
    DeploymentComparison,
    DeploymentRollbackUndo,
    FailureMode,
    FileAsItRan,
    FirstTold,
    FixOutcome,
    FlagChange,
    FlagUndo,
    ForCandidate,
    Hypothesis,
    IncidentStatus,
    Meaning,
    ModelPolicy,
    OpenedPullRequest,
    PostmortemDocument,
    Reference,
    Refusal,
    Report,
    ReportChannel,
    RetrievalChannel,
    Standing,
    ThreadMessage,
    ToolCall,
    ToolDefinition,
    Transcript,
    Turn,
    UndoDescriptor,
    Undone,
    Verdict,
    Weighing,
    a_chat_message,
    a_chat_thread,
    as_a_change,
)
from argus_core.replay import CallType, Replay
from argus_incidents import calls_into
from argus_incidents.repository import (
    conversation,
    events,
    hypotheses,
    incidents,
    references,
    replay,
    taken_actions,
)
from argus_narration import what_to_do
from argus_testkit import Assertion, Scenario, all_of, calling, the_answer_was
from argus_testkit.assertions import an_error_was_raised
from argus_testkit.scenario import attempting
from orchestrator.gathering import gather_evidence, write_postmortem_for
from orchestrator.walk.investigating import ASKING_THE_FLAG_PROVIDER

# How many hours a year the bands are divided by. Any number does: nothing here
# publishes a cost, and the arithmetic that would use it is the agent's own
# suite's business.
DONT_CARE_WORKING_YEAR = 1800.0

# Where the detector draws its lines. Unread by these cases - the metrics
# source answers with nothing - but `Sources` has no default for them, and
# deliberately: thresholds a caller left unwired would be a recovery measured
# against numbers no deployment configured.
DONT_CARE_THRESHOLDS = AnomalyThresholds(
    deviations_from_baseline=3.0,
    persistence_minutes=2,
    recovery_fraction_of_the_rise=0.8
)

# How late the metrics source reports a minute. Unread here for the reason the
# thresholds are, and without a default for the same one.
DONT_CARE_REPORTING_LAG_MINUTES = 0

# When an action a case never asks the moment of was taken.
DONT_CARE_TAKEN_AT = parse_iso("2026-09-02T11:52:00Z")

# A message a person wrote in the incident's thread. Any reference does.
SOME_MESSAGE = Reference(source="some-chat", kind="some-kind", value="some-message")

# The flag the actions here act on. Any name does.
SOME_FLAG = "monthly-spend-feature"
SOME_OTHER_FLAG = "legacy-checkout-fallback"


@pytest.mark.component
def test_the_evidence_spans_the_incident_from_its_start_to_its_end(a_clean_database: None) -> None:
    # The window every figure in the document is measured over. Taken from the
    # incident's own row rather than from the last thing logged, so it does not
    # move when something is written late.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _spans_the_incident(conn, incident_id)
            )


@pytest.mark.component
def test_the_evidence_is_alerted_when_the_alert_says_it_fired(a_clean_database: None) -> None:
    # Its sender's own date, which delivery comes after: a sender groups and
    # waits before it sends.
    some_firing = parse_iso("2026-10-11T14:03:00Z")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn, started_at=some_firing)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id).alerted_at
            ) \
            .then(
                the_answer_was(some_firing)
            )


@pytest.mark.component
def test_an_alert_that_dates_nothing_is_alerted_when_the_incident_opened(
    a_clean_database: None
) -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn, started_at=None),
                the_incident := incidents.get(conn, incident_id)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id).alerted_at
            ) \
            .then(
                the_answer_was(the_incident.created_at if the_incident is not None else None)
            )


@pytest.mark.component
def test_the_evidence_carries_the_candidates_the_investigation_ranked(
    a_clean_database: None
) -> None:
    # Including the ones never tried. An investigation that was confident and
    # right and one that ran out of options look identical from their outcome,
    # and the difference is most of what the walk has to say.
    some_cause = "the checkout fallback flag was switched off"
    some_failure_mode = FailureMode.FEATURE_FLAG_TOGGLE
    dont_care_confidence = 0.8

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: hypotheses.record(conn, Hypothesis(
                    incident_id=incident_id,
                    summary=some_cause,
                    failure_mode=some_failure_mode,
                    confidence=dont_care_confidence,
                    supporting_evidence=[]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(
                    lambda evidence: [candidate.summary for candidate in evidence.candidates],
                    some_cause
                )
            )


@pytest.mark.component
def test_a_candidate_carries_what_it_blamed_and_what_became_of_it(
    a_clean_database: None
) -> None:
    # The trigger is the change the confirmed candidate blamed, so the
    # candidate has to arrive as the values it was recorded with - its subject,
    # the two ends of the change, and the verdict - rather than as a sentence
    # the document would have to take apart again.
    some_confidence = 0.8

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        a_candidate = Hypothesis(incident_id=incident_id,
                                 summary="a flag change on account pages",
                                 failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                                 confidence=some_confidence,
                                 supporting_evidence=[],
                                 subject=SOME_FLAG,
                                 from_state="off",
                                 to_state="on")
        hypotheses.record(conn, a_candidate)

        Scenario() \
            .given(
                calling(lambda: hypotheses.record_outcome(
                    conn, a_candidate.id, tested=True, result=Verdict.CONFIRMED))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_candidates([CandidateRecord(
                    summary="a flag change on account pages",
                    failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                    confidence=some_confidence,
                    subject=SOME_FLAG,
                    from_state="off",
                    to_state="on",
                    tested=True,
                    result=Verdict.CONFIRMED
                )])
            )


@pytest.mark.component
def test_a_line_that_formed_candidates_names_them_among_the_evidence_s_own(
    a_clean_database: None
) -> None:
    # So the write-up can point at a candidate under its own label rather than
    # say it twice. By the hypothesis each line formed, not by counting: the
    # candidates are listed across every round, and a line forms only its own
    # round's - here the second round's, which a count from the line's own
    # first would number from one.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _a_candidate_formed(conn, incident_id, rank=1, number=1)),
                calling(lambda: _a_candidate_formed(conn, incident_id, rank=2, number=2)),
                calling(lambda: events.record(conn, StatusChanged(
                    incident_id=incident_id, to_status=IncidentStatus.INVESTIGATING))),
                calling(lambda: _a_candidate_formed(conn, incident_id, rank=1, number=3))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _the_lines_name_the_candidates([[0, 1], [2]])
            )


@pytest.mark.component
def test_a_line_acting_for_a_candidate_says_where_it_sits_and_how_the_line_names_it(
    a_clean_database: None
) -> None:
    # So the write-up can name it by its label rather than by the narration's
    # words for it. By the hypothesis the line acted for, as a line forming
    # candidates is found - here the second, which the line names #2.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        _a_candidate_formed(conn, incident_id, rank=1, number=1)
        the_second = _a_candidate_formed(conn, incident_id, rank=2, number=2)

        Scenario() \
            .given(
                calling(lambda: events.record(conn, ActionRefused(
                    incident_id=incident_id, hypothesis_id=the_second, candidate_number=2,
                    refusal=Refusal.NOTHING_COULD_CONFIRM_IT)))
            ) \
            .when(
                lambda: [entry.for_candidate for entry in
                         gather_evidence(conn, incident_id).timeline
                         if entry.for_candidate is not None]
            ) \
            .then(
                the_answer_was([ForCandidate(place=1, said_as="candidate cause #2")])
            )


@pytest.mark.component
def test_the_evidence_carries_the_log_lines_the_incident_read(a_clean_database: None) -> None:
    # From the published account rather than from the log store, which has
    # moved on. What the model explains has to be what Argus actually saw.
    some_window_start = "2026-09-02T11:30:00Z"
    some_window_end = "2026-09-02T12:30:00Z"
    some_log_line = "12:04 ERROR checkout: fallback unavailable"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, LogsRetrieved(
                    incident_id=incident_id,
                    window_start=some_window_start,
                    window_end=some_window_end,
                    lines=[some_log_line]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(lambda evidence: evidence.log_lines, some_log_line)
            )


@pytest.mark.component
def test_a_line_read_again_by_a_wider_read_is_read_once(a_clean_database: None) -> None:
    # An investigation that widens its window reads the minutes it has already
    # read, and a line counted once per read is a failure counted twice. Each
    # line is kept as often as one read returned it - so a re-read adds nothing
    # and two replicas logging in one minute still count as two.
    a_failure = "2026-09-02T12:04:00Z ERROR checkout: fallback unavailable"
    another = "2026-09-02T12:05:00Z WARN checkout: error rate at 30.00%"
    a_later_one = "2026-09-02T12:06:00Z ERROR checkout: fallback unavailable"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, LogsRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T12:00:00Z",
                    window_end="2026-09-02T12:05:30Z",
                    lines=[a_failure, a_failure, another]
                ))),
                calling(lambda: events.record(conn, LogsRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T11:30:00Z",
                    window_end="2026-09-02T12:30:00Z",
                    lines=[a_failure, another, a_later_one]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_log_lines([a_failure, a_failure, another, a_later_one])
            )


@pytest.mark.component
def test_the_evidence_carries_where_the_furthest_read_of_the_logs_ended(
        a_clean_database: None) -> None:
    # Where the lines stop is as often where the reading stopped as where the
    # service did, and nothing in a line says which. The furthest end of any
    # read, since nothing after it was read - whatever order the reads came in.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, LogsRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T11:30:00Z",
                    window_end="2026-09-02T12:30:00Z",
                    lines=[]
                ))),
                calling(lambda: events.record(conn, LogsRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T12:00:00Z",
                    window_end="2026-09-02T12:05:30Z",
                    lines=[]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _the_logs_were_read_until(parse_iso("2026-09-02T12:30:00Z"))
            )


@pytest.mark.component
def test_an_incident_that_read_no_logs_says_no_reading_of_them_ended(
        a_clean_database: None) -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _the_logs_were_read_until(None)
            )


@pytest.mark.component
def test_the_evidence_carries_the_changes_the_investigation_read(a_clean_database: None) -> None:
    # What dates the trigger: the change the confirmed candidate blamed is one
    # of these, and the moment it was made is the one the record holds - not a
    # moment the document estimates.
    some_change = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                              occurred_at="2026-09-02T11:49:52Z",
                              reference=SOME_FLAG,
                              summary="enabled at 40%")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, ChangesRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T10:00:00Z",
                    window_end="2026-09-02T12:30:00Z",
                    changes=[some_change]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_changes([some_change])
            )


@pytest.mark.component
def test_a_change_two_reads_both_held_is_carried_once_where_it_was_first_read(
        a_clean_database: None) -> None:
    # One change is one change. A later round re-reads a window overlapping the
    # first, and a change carried once per read gets a label per read - so the
    # numbering would depend on whether the first read happened to reach it.
    the_flip = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                           occurred_at="2026-09-02T11:49:52Z",
                           reference=SOME_FLAG,
                           summary="switched on")
    the_revert = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                             occurred_at="2026-09-02T11:51:10Z",
                             reference=SOME_FLAG,
                             summary="switched off")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, ChangesRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T10:00:00Z",
                    window_end="2026-09-02T11:50:00Z",
                    changes=[the_flip]
                ))),
                calling(lambda: events.record(conn, ChangesRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T11:30:00Z",
                    window_end="2026-09-02T12:30:00Z",
                    changes=[the_flip, the_revert]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_changes([the_flip, the_revert])
            )


@pytest.mark.component
def test_a_flag_change_only_the_walk_read_is_carried_once_in_its_place_in_time(
        a_clean_database: None) -> None:
    # The walk acts on the flag history it reads over a window of its own, and a
    # write-up has to be able to cite the change Argus acted on - so a flag
    # switched outside the investigation's window is carried too, where it falls
    # in time among the rest; and a change both of them read is still one change.
    the_flip = FlagChange(flag=SOME_FLAG, enabled=True, occurred_at="2026-09-02T11:49:52Z")
    the_flip_only_the_walk_read = FlagChange(flag=SOME_OTHER_FLAG,
                                             enabled=True,
                                             occurred_at="2026-09-02T11:20:00Z")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, ChangesRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T11:30:00Z",
                    window_end="2026-09-02T12:30:00Z",
                    changes=[as_a_change(the_flip)]
                ))),
                calling(lambda: events.record(conn, FlagChangesRetrieved(
                    incident_id=incident_id,
                    changes=[the_flip_only_the_walk_read, the_flip]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_changes([as_a_change(the_flip_only_the_walk_read),
                                      as_a_change(the_flip)])
            )


@pytest.mark.component
def test_changes_a_later_read_reached_further_back_for_are_carried_in_time_order(
        a_clean_database: None) -> None:
    # A change is labelled by its place among the changes, and a later round
    # re-reads a window reaching further back than the first one did. Carried in
    # the order they were read, the change the first read found would keep its
    # place only until something earlier turned up - and a write-up citing it by
    # its label would then be naming another.
    the_flip = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                           occurred_at="2026-09-02T11:49:52Z",
                           reference=SOME_FLAG,
                           summary="switched on")
    an_earlier_flip = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                  occurred_at="2026-09-02T10:20:00Z",
                                  reference=SOME_OTHER_FLAG,
                                  summary="switched on")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, ChangesRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T11:30:00Z",
                    window_end="2026-09-02T12:30:00Z",
                    changes=[the_flip]
                ))),
                calling(lambda: events.record(conn, ChangesRetrieved(
                    incident_id=incident_id,
                    window_start="2026-09-02T10:00:00Z",
                    window_end="2026-09-02T12:30:00Z",
                    changes=[an_earlier_flip, the_flip]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_changes([an_earlier_flip, the_flip])
            )


@pytest.mark.component
def test_a_flag_change_from_once_the_walk_had_acted_is_not_carried(
        a_clean_database: None) -> None:
    # A later round reads the flag history again with its far end open, and from
    # the first action on what it finds is the walk's own doing - told already
    # as an action, and no cause of the incident it was acting on.
    the_flip = FlagChange(flag=SOME_FLAG, enabled=True, occurred_at="2026-09-02T11:49:52Z")
    first_acted_at = parse_iso("2026-09-02T11:52:00Z")
    the_walks_own_revert = FlagChange(flag=SOME_FLAG,
                                      enabled=False,
                                      occurred_at="2026-09-02T11:52:00Z")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: _an_action_claimed_then_taken(conn, incident_id, first_acted_at)),
                calling(lambda: events.record(conn, FlagChangesRetrieved(
                    incident_id=incident_id,
                    changes=[the_flip, the_walks_own_revert]
                )))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_changes([as_a_change(the_flip)])
            )


@pytest.mark.component
@pytest.mark.parametrize(("channel", "reading_of"), [
    (RetrievalChannel.CHANGES, "deploys_reading"),
    (RetrievalChannel.LOGS, "logs_reading")
], ids=["deploys", "logs"])
@pytest.mark.parametrize(("asked", "answered", "asked_of_the_other", "reading"), [
    (0, 0, 0, ChannelReading.NOT_ASKED),
    (0, 0, 1, ChannelReading.NOT_ASKED),
    (1, 0, 0, ChannelReading.UNANSWERED),
    (1, 1, 0, ChannelReading.READ),
    (2, 1, 0, ChannelReading.READ)
], ids=["never-asked", "only-the-other-asked", "asked-and-nothing-back", "answered-empty",
        "answered-once-of-twice"])
def test_what_came_of_a_read_the_investigation_makes_is_what_was_asked_and_answered(
        a_clean_database: None, channel: RetrievalChannel, reading_of: str, asked: int,
        answered: int, asked_of_the_other: int, reading: ChannelReading) -> None:
    # An empty list is three things - read and found nothing, never asked, and
    # asked with nothing back - and the account tells them apart: a request is
    # published before each read, and a reading once it is answered. A request
    # with no reading is a source that failed or a walk stopped mid-read, and
    # either way nothing came back. One answer is a read, however often it was
    # asked.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: _recorded_in_order(conn, _the_reads_of(
                    channel, incident_id, asked=asked, answered=answered,
                    asked_of_the_other=asked_of_the_other)))
            ) \
            .when(
                lambda: getattr(gather_evidence(conn, incident_id), reading_of)
            ) \
            .then(
                the_answer_was(reading)
            )


@pytest.mark.component
@pytest.mark.parametrize(("toggled_at", "reading"), [
    ([], ChannelReading.READ),
    (["2026-09-02T11:52:00Z"], ChannelReading.ONLY_SINCE_ARGUS_ACTED),
    (["2026-09-02T11:49:52Z", "2026-09-02T11:52:00Z"], ChannelReading.READ)
], ids=["nothing-came-back", "only-the-walks-own-came-back", "a-change-before-it-acted-came-back"])
def test_a_flag_history_read_says_whether_anything_but_the_walks_own_came_back(
        a_clean_database: None, toggled_at: list[str], reading: ChannelReading) -> None:
    # A later round reads the history again with its far end open and finds
    # the toggle the walk made itself, which is not carried - so the read shows
    # no rows though something came back, and is not a read that found nothing.
    first_acted_at = parse_iso("2026-09-02T11:52:00Z")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: _an_action_claimed_then_taken(conn, incident_id, first_acted_at)),
                calling(lambda: events.record(conn, FlagChangesRetrieved(
                    incident_id=incident_id,
                    changes=[FlagChange(flag=SOME_FLAG, enabled=True, occurred_at=at)
                             for at in toggled_at])))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id).flags_reading
            ) \
            .then(
                the_answer_was(reading)
            )


@pytest.mark.component
@pytest.mark.parametrize(("unanswered", "reading"), [
    ([], ChannelReading.NOT_ASKED),
    ([ASKING_THE_FLAG_PROVIDER], ChannelReading.UNANSWERED),
    (["what the platform recorded deploying"], ChannelReading.NOT_ASKED)
], ids=["never-asked", "asked-and-nothing-back", "something-else-unanswered"])
def test_a_flag_history_never_read_says_whether_it_was_asked_for(
        a_clean_database: None, unanswered: list[str], reading: ChannelReading) -> None:
    # The walk publishes no request before it reads the flags, only what came
    # back or that nothing did - and another history unanswered says nothing
    # of this one.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: _recorded_in_order(conn, [
                    RetrievalUnanswered(incident_id=incident_id, what_was_asked=asked,
                                        because="dont care")
                    for asked in unanswered]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id).flags_reading
            ) \
            .then(
                the_answer_was(reading)
            )


@pytest.mark.component
def test_the_evidence_carries_what_each_deployment_read_changed(a_clean_database: None) -> None:
    # What tells a configuration change from a code change, and what names the
    # deploy that carried one: every line, under the revision it was read for,
    # and whether the lines list every file it changed. Read twice, one
    # deployment is one row - a row per read would number the deployments by
    # how often the model happened to ask.
    the_diff = ["Deployment of revision 7c3ca00 to io-shop, compared against 1a2b3c4 - "
                "the revision deployed before it.",
                "modified deploy/values-production.yaml",
                "  -  model: v1",
                "  +  model: v2"]
    another_diff = ["Deployment of revision 1a2b3c4 to io-shop, compared against 9f8e7d6 - "
                    "the revision deployed before it.",
                    "modified src/target_app/app.py"]

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, DeploymentChangesRead(
                    incident_id=incident_id, revision="7c3ca00", said=the_diff,
                    lists_every_file=True))),
                calling(lambda: events.record(conn, DeploymentChangesRead(
                    incident_id=incident_id, revision="1a2b3c4", said=another_diff,
                    lists_every_file=False))),
                calling(lambda: events.record(conn, DeploymentChangesRead(
                    incident_id=incident_id, revision="7c3ca00", said=the_diff,
                    lists_every_file=True)))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_deployment_changes([
                    DeploymentChangesRecord(revision="7c3ca00", said=the_diff,
                                            lists_every_file=True),
                    DeploymentChangesRecord(revision="1a2b3c4", said=another_diff,
                                            lists_every_file=False)
                ])
            )


@pytest.mark.component
def test_the_evidence_carries_whether_each_deployment_read_was_compared(
        a_clean_database: None) -> None:
    # Only a comparison is a diff. A deployment with nothing before it, or a
    # revision no deployment has, is said in the write-up's own words, of the
    # service whose history was read.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, DeploymentChangesRead(
                    incident_id=incident_id, revision="7c3ca00", said=["dont care"],
                    comparison=DeploymentComparison.NOTHING_BEFORE_IT, service="io-shop"))),
                calling(lambda: events.record(conn, DeploymentChangesRead(
                    incident_id=incident_id, revision="1a2b3c4", said=["dont care"])))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_each_deployment_read_as([
                    ("7c3ca00", DeploymentComparison.NOTHING_BEFORE_IT, "io-shop"),
                    ("1a2b3c4", DeploymentComparison.COMPARED, None)
                ])
            )


@pytest.mark.component
def test_the_evidence_carries_the_timeline_in_the_order_it_happened(a_clean_database: None) -> None:
    # The narration the document is written from - the same lines, from the same
    # renderer, as the page shows. Out of order it is a different incident: a
    # mitigation before the investigation that proposed it explains nothing.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(all_of(
                _timeline_begins_with("Received HighErrorRate"),
                _timeline_ends_with(str(IncidentStatus.RESOLVED).upper())
            ))


@pytest.mark.component
def test_a_line_written_outside_the_walk_is_carried_as_such(a_clean_database: None) -> None:
    # The document numbers the walk's lines apart from these: where a person's
    # report lands among the walk's is timing, and counted with them it
    # renumbers every line of the walk after it.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                somebody_reporting := StatusChanged(
                    incident_id=incident_id,
                    to_status=IncidentStatus.RESOLVED,
                    reported=Report(by="some person", channel=ReportChannel.ARGUS_UI))
            ) \
            .when(
                lambda: _the_evidence_after_publishing(conn, incident_id, somebody_reporting)
            ) \
            .then(
                _only_the_lines_dated_are_outside_the_walk([somebody_reporting.at])
            )


@pytest.mark.component
def test_a_resolution_written_in_the_thread_is_said_as_the_report_it_was(
        a_clean_database: None) -> None:
    # Said as no more than something written, a report reads as one Argus was
    # free to pass over - and every write-up told so said Argus pressed on
    # regardless of it. By the name it was offered back under.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        the_message = SOME_MESSAGE

        Scenario() \
            .given(
                calling(lambda: _recorded_in_order(conn, [
                    PersonWrote(incident_id=incident_id, message=the_message,
                                person_id="U-some-person", text="rolled it back, all fine"),
                    MessageUnderstood(incident_id=incident_id, message=the_message,
                                      meaning=Meaning.RESOLVE),
                    ResolutionOffered(incident_id=incident_id, message=the_message,
                                      person_id="U-some-person", person_name="Some Person",
                                      said="rolled it back, all fine")]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _the_timeline_holds("Some Person",
                                    "Reported the incident resolved in the thread: "
                                    "rolled it back, all fine")
            )


@pytest.mark.component
def test_the_offer_back_to_the_person_is_not_on_the_timeline(a_clean_database: None) -> None:
    # The offer is how a report is confirmed: it says nothing the report and the
    # move it made do not.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        the_message = SOME_MESSAGE

        Scenario() \
            .given(
                calling(lambda: _recorded_in_order(conn, [
                    PersonWrote(incident_id=incident_id, message=the_message,
                                person_id="U-some-person", text="dont care"),
                    MessageUnderstood(incident_id=incident_id, message=the_message,
                                      meaning=Meaning.RESOLVE),
                    ResolutionOffered(incident_id=incident_id, message=the_message,
                                      person_id="U-some-person", person_name="Some Person",
                                      said="dont care")]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _no_line_of_the_timeline_says("to confirm")
            )


@pytest.mark.component
@pytest.mark.parametrize("meaning", [Meaning.QUESTION, Meaning.INFORMATION, Meaning.OTHER])
def test_a_message_that_bore_on_nothing_is_not_on_the_timeline(meaning: Meaning,
                                                                 a_clean_database: None) -> None:
    # A question, a thank-you, or something never weighed as a lead: neither
    # what the person wrote nor what was made of it says anything of the
    # incident.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        the_message = SOME_MESSAGE

        Scenario() \
            .given(
                calling(lambda: _recorded_in_order(conn, [
                    PersonWrote(incident_id=incident_id, message=the_message,
                                person_id="U-some-person", text="some words"),
                    MessageUnderstood(incident_id=incident_id, message=the_message,
                                      meaning=meaning),
                    QuestionAnswered(incident_id=incident_id, message=the_message,
                                     answer="some answer")]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(all_of(
                _no_line_of_the_timeline_says("some words"),
                _no_line_of_the_timeline_says("Classified the message"),
                _no_line_of_the_timeline_says("some answer"),
                _says_people_wrote(False)
            ))


@pytest.mark.component
@pytest.mark.parametrize("standing", [Standing.REFUTED, Standing.SUPPORTED])
def test_a_lead_the_investigation_weighed_is_on_the_timeline(standing: Standing,
                                                             a_clean_database: None) -> None:
    # Ruled out or taken up, a lead is part of the story: one ruled out is what
    # the investigation did not follow, and why.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        the_message = SOME_MESSAGE

        Scenario() \
            .given(
                calling(lambda: _recorded_in_order(conn, [
                    PersonWrote(incident_id=incident_id, message=the_message,
                                person_id="U-some-person", text="the cache was flushed"),
                    MessageUnderstood(incident_id=incident_id, message=the_message,
                                      meaning=Meaning.INFORMATION),
                    LeadWeighed(incident_id=incident_id, message=the_message,
                                standing=standing, reason="dont care")]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(all_of(
                _the_timeline_holds("A person",
                                    "Wrote in the incident's thread: the cache was flushed"),
                _says_people_wrote(True)
            ))


@pytest.mark.component
def test_the_evidence_says_when_argus_first_posted_where_people_could_read_it(
        a_clean_database: None) -> None:
    # Told only that nobody was paged, a write-up said nobody was told at all,
    # of an incident Argus had announced in its thread. The thread is written
    # down once the chat platform accepted the line that opened it, and is the
    # only record a line was said.
    some_thread = a_chat_thread(ReportChannel.SLACK, "C-some-channel", "1.000100")

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: references.add(conn, incident_id, [some_thread]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id).first_told
            ) \
            .then(
                _told_in_its_thread(conn, incident_id, ReportChannel.SLACK)
            )


@pytest.mark.component
def test_a_candidate_says_how_far_the_action_testing_it_got(a_clean_database: None) -> None:
    # A person's ending can stop the test before anything is measured, which
    # leaves the candidate's row untested - and without the action, a write-up
    # reads it as never tried. Only an action performed tried it: a row is also
    # written for an attempt that changed nothing, a platform that never
    # answered among them, and for one a dead worker left with the change made
    # and no verdict, or with nobody able to say whether it was made at all.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(conn, incident_id, REVERT_FEATURE_FLAG,
                                                 Verdict.STOPPED,
                                                 FlagUndo(flag=SOME_FLAG, was_enabled=True))),
                calling(lambda: _an_action_taken(conn, incident_id, ROLL_BACK_DEPLOYMENT,
                                                 Verdict.PLATFORM_UNREACHABLE, None,
                                                 summary="a rollback that never ran",
                                                 performed=False)),
                calling(lambda: _an_action_left_at(conn, incident_id, ActionProgress.PERFORMED,
                                                   summary="a change a dead worker made")),
                calling(lambda: _an_action_left_at(conn, incident_id, ActionProgress.UNKNOWN,
                                                   summary="a change nobody can account for")),
                calling(lambda: _an_action_left_at(conn, incident_id, ActionProgress.CLAIMED,
                                                   summary="a claim never answered")),
                calling(lambda: hypotheses.record(conn, Hypothesis(
                    incident_id=incident_id, summary="an untried cause",
                    failure_mode=FailureMode.FEATURE_FLAG_TOGGLE, confidence=0.1,
                    supporting_evidence=[])))
            ) \
            .when(
                lambda: {candidate.summary: (candidate.progress, candidate.verdict_recorded)
                         for candidate in gather_evidence(conn, incident_id).candidates}
            ) \
            .then(
                the_answer_was({
                    "dont care": (ActionProgress.PERFORMED, True),
                    "a rollback that never ran": (ActionProgress.NOT_PERFORMED, True),
                    "a change a dead worker made": (ActionProgress.PERFORMED, False),
                    "a change nobody can account for": (ActionProgress.UNKNOWN, False),
                    "a claim never answered": (ActionProgress.CLAIMED, False),
                    "an untried cause": (None, False)
                })
            )


@pytest.mark.component
def test_an_incident_argus_never_posted_about_was_told_nowhere(a_clean_database: None) -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id).first_told
            ) \
            .then(
                the_answer_was(None)
            )


@pytest.mark.component
def test_a_move_to_act_that_no_act_followed_is_not_on_the_timeline(
        a_clean_database: None) -> None:
    # A person ended the incident first, and the walk held off from the moment
    # the move was written. On the timeline after their report, the move reads
    # as Argus pressing on regardless of it.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_a_person_ended(conn,
                                                           after=[IncidentStatus.MITIGATING])
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _no_line_of_the_timeline_says("MITIGATING")
            )


@pytest.mark.component
def test_a_move_to_act_the_walk_went_on_from_is_on_the_timeline(
        a_clean_database: None) -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_a_person_ended(
                    conn, after=[IncidentStatus.MITIGATING, IncidentStatus.ESCALATED])
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(lambda evidence: [entry.text for entry in evidence.timeline],
                                "MITIGATING")
            )


@pytest.mark.component
@pytest.mark.parametrize("filing", [
    pytest.param(lambda incident_id: IncidentRemembered(incident_id=incident_id, tried=[]),
                 id="filed"),
    pytest.param(lambda incident_id: RememberingFailed(incident_id=incident_id,
                                                       refusal="some-refusal"),
                 id="not-filed")
])
def test_filing_the_incident_for_the_next_one_is_not_carried(
    filing: Callable[[str], IncidentEvent],
    a_clean_database: None
) -> None:
    # Argus keeping its own books for an incident that has not happened yet:
    # the page shows it, and a document about this incident has nothing to say
    # about it.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                some_filing := filing(incident_id)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(conn, incident_id, some_filing)
            ) \
            .then(
                _timeline_ends_with(str(IncidentStatus.RESOLVED).upper())
            )


@pytest.mark.component
def test_a_read_of_what_a_deployment_changed_is_a_line_of_the_timeline(
        a_clean_database: None) -> None:
    # The document gives what was read a row of its own, and the line says when
    # it was read - which the row does not. Left out, the timeline skipped the
    # step the investigation turned on.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                some_read := DeploymentChangesRead(incident_id=incident_id,
                                                   revision="some-revision",
                                                   said=["some line of the diff"])
            ) \
            .when(
                lambda: _the_evidence_after_publishing(conn, incident_id, some_read)
            ) \
            .then(
                _timeline_ends_with("Read what the deployment of some-revision changed")
            )


@pytest.mark.component
def test_a_wait_is_carried_once_by_the_look_that_settled_it(a_clean_database: None) -> None:
    # Told look by look, the walk's lines number by how many looks a wait took
    # and where a person's message fell among them - which is timing, not the
    # incident. The last look is what the wait came to.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        the_looks = [
            RecoveryChecked(incident_id=incident_id, at=parse_iso("2026-09-02T12:06:10Z"),
                            minute="2026-09-02T12:06:00Z", recovered=False),
            RecoveryChecked(incident_id=incident_id, at=parse_iso("2026-09-02T12:06:20Z"),
                            minute="2026-09-02T12:06:00Z", recovered=False),
            RecoveryChecked(incident_id=incident_id, at=parse_iso("2026-09-02T12:07:10Z"),
                            minute="2026-09-02T12:07:00Z", recovered=True,
                            recovered_minute="2026-09-02T12:06:00Z")
        ]
        somebody_writing = PersonWrote(
            incident_id=incident_id,
            at=parse_iso("2026-09-02T12:06:15Z"),
            message=Reference(source="some-chat", kind="some-kind", value="some-message"),
            person_id="some-person-id",
            text="looks fine to me")

        Scenario() \
            .given(
                calling(lambda: _recorded_in_order(
                    conn, [the_looks[0], somebody_writing, the_looks[1], the_looks[2]]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _the_looks_carried_are(the_looks, [the_looks[-1]])
            )


@pytest.mark.component
def test_an_incident_that_has_not_ended_cannot_be_summarised(a_clean_database: None) -> None:
    # A postmortem is written once, when the incident is over. Asked for one
    # earlier, this refuses rather than inventing an end - a duration measured
    # to "now" would be a different number every time it was asked for.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := incidents.create(
                    conn, Alert(service="io-shop", alert_name="HighErrorRate"),
                    at=utc_now())
            ) \
            .when(
                attempting(lambda: gather_evidence(conn, incident_id))
            ) \
            .then(
                an_error_was_raised(ValueError)
            )


@pytest.mark.component
def test_an_incident_that_does_not_exist_cannot_be_summarised(a_clean_database: None) -> None:
    # Distinct from an incident still running: there is nothing to summarise
    # rather than nothing yet. Both refuse, and neither invents a document.
    with connect_from_env() as conn:
        Scenario() \
            .when(
                attempting(lambda: gather_evidence(conn, new_id()))
            ) \
            .then(
                an_error_was_raised(ValueError)
            )


@pytest.mark.component
def test_the_evidence_carries_the_onset_the_investigation_measured(a_clean_database: None) -> None:
    # The instant the service actually began to fail, which is not the instant
    # Argus was told: an alert fires on a rule that needs some minutes of bad
    # traffic to trip. The loss is measured from the onset, so those minutes
    # are the difference between a baseline of calm trade and one that already
    # contains the damage.
    #
    # Read from what the Investigator published rather than measured again
    # here. A postmortem that re-derived it from a wider window would date the
    # same incident differently from the page that showed it.
    some_onset = "2026-09-02T11:50"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(
                    conn, incident_id, OnsetDetected(incident_id=incident_id,
                                                     onset=some_onset))
            ) \
            .then(
                _carries_the_onset(parse_iso(some_onset))
            )


@pytest.mark.component
def test_an_incident_whose_onset_was_never_found_carries_none(a_clean_database: None) -> None:
    # A window in which no minute departed from the baseline has no onset to
    # anchor on (spec §9), so the investigation exits without publishing one.
    # The gathering must report that rather than substituting the alert's own
    # time, because the document refuses to cost an incident it cannot date.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_no_onset()
            )


@pytest.mark.component
def test_the_evidence_carries_the_minute_the_recovery_was_recorded_at(
        a_clean_database: None) -> None:
    # The onset's counterpart, read off the account for the same reason. The
    # minute was measured on the window the verification wait was polling, where
    # the document reads a window bounded by the incident's close - so deriving
    # it again there is the same rule over different minutes, and one incident
    # ends up with two recovery times and nothing to say which Argus acted on.
    #
    # The two minutes the look carries are deliberately different. 12:09 is
    # where the verdict was read from, which is a fact about Argus; 12:06 is
    # when the shop came back, which is a fact about the shop. A fixture where
    # they matched would pass whichever one the gathering picked up.
    the_minute_the_verdict_was_read_from = "2026-09-02T12:09:00Z"
    the_minute_it_came_back = "2026-09-02T12:06:00Z"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(
                    conn, incident_id, RecoveryChecked(
                        incident_id=incident_id,
                        minute=the_minute_the_verdict_was_read_from,
                        recovered=True,
                        recovered_minute=the_minute_it_came_back))
            ) \
            .then(
                _carries_the_recovery(parse_iso(the_minute_it_came_back))
            )


@pytest.mark.component
def test_the_evidence_carries_when_a_person_reported_the_incident_resolved(
        a_clean_database: None) -> None:
    # A person saying the incident is over is the fact (spec §16). Carried apart
    # from a recovery Argus recorded, because the document searches the series
    # from a recorded minute for where the service was back to normal - and
    # searching it from a report would be Argus looking for a level falling to
    # corroborate a report it does not test.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                the_report := StatusChanged(
                    incident_id=incident_id,
                    to_status=IncidentStatus.RESOLVED,
                    reported=Report(by="some person", channel=ReportChannel.ARGUS_UI)
                )
            ) \
            .when(
                lambda: _the_evidence_after_publishing(conn, incident_id, the_report)
            ) \
            .then(all_of(
                _carries_the_report(the_report.at, "some person"),
                _carries_no_recovery()
            ))


@pytest.mark.component
def test_a_recovery_argus_confirmed_and_a_later_resolution_are_both_carried(
        a_clean_database: None) -> None:
    # Which of the two ends the incident is the document's to say, and it says
    # the earlier measurement: not a contradiction of the report, but a better
    # answer to when the service came back.
    the_minute_it_came_back = "2026-09-02T12:06:00Z"

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        events.record(conn, RecoveryChecked(incident_id=incident_id,
                                            minute="2026-09-02T12:09:00Z",
                                            recovered=True,
                                            recovered_minute=the_minute_it_came_back))

        Scenario() \
            .given(
                the_report := StatusChanged(
                    incident_id=incident_id,
                    to_status=IncidentStatus.RESOLVED,
                    reported=Report(by="some person", channel=ReportChannel.ARGUS_UI)
                )
            ) \
            .when(
                lambda: _the_evidence_after_publishing(conn, incident_id, the_report)
            ) \
            .then(all_of(
                _carries_the_recovery(parse_iso(the_minute_it_came_back)),
                _carries_the_report(the_report.at, "some person")
            ))


@pytest.mark.component
def test_an_ending_argus_reached_itself_dates_no_recovery(a_clean_database: None) -> None:
    # Only a person's report stands in for a measurement. Argus's own move to an
    # ending is not a claim that the service came back, and the document
    # measures its own answer from the series there.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(all_of(
                _carries_no_recovery(),
                _carries_no_report()
            ))


@pytest.mark.component
def test_an_incident_watched_and_never_seen_to_recover_says_so(a_clean_database: None) -> None:
    # Not recovering while watched is an answer, not an absence of one. The
    # document must not ask it again of its own window: on a service that flaps,
    # that window shows a lull in one run and not in the next.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        events.record(conn, RecoveryChecked(incident_id=incident_id,
                                            minute="2026-09-02T12:06:00Z",
                                            recovered=False,
                                            recovered_minute=None))

        Scenario() \
            .given(
                a_later_look := RecoveryChecked(incident_id=incident_id,
                                                minute="2026-09-02T12:09:00Z",
                                                recovered=False,
                                                recovered_minute=None)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(conn, incident_id, a_later_look)
            ) \
            .then(all_of(
                _carries_no_recovery(),
                _was_watched_and_never_recovered(True)
            ))


@pytest.mark.component
def test_a_recovery_confirmed_without_a_minute_is_not_said_never_to_have_come(
        a_clean_database: None) -> None:
    # Confirmed on a window with nothing in it to date: the service came back,
    # and the document dates it from the series.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(
                    conn, incident_id, RecoveryChecked(incident_id=incident_id,
                                                       minute="2026-09-02T12:09:00Z",
                                                       recovered=True,
                                                       recovered_minute=None))
            ) \
            .then(
                _was_watched_and_never_recovered(False)
            )


@pytest.mark.component
def test_an_incident_nobody_watched_is_not_said_never_to_have_recovered(
        a_clean_database: None) -> None:
    # Escalated before any action, or never mitigated: nobody looked, so the
    # document measures its own answer from the series.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _was_watched_and_never_recovered(False)
            )


@pytest.mark.component
def test_an_incident_argus_escalated_is_said_to_have_been_handed_to_a_person(
        a_clean_database: None) -> None:
    # Argus running out of moves and handing over is how the incident ended,
    # and a summary saying only what Argus did reads as an incident it closed.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                the_escalation := StatusChanged(incident_id=incident_id,
                                                to_status=IncidentStatus.ESCALATED)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(conn, incident_id, the_escalation)
            ) \
            .then(
                _was_escalated(True)
            )


@pytest.mark.component
def test_an_incident_argus_never_escalated_is_not_said_to_have_been_handed_over(
        a_clean_database: None) -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _was_escalated(False)
            )


@pytest.mark.component
def test_an_action_left_for_a_person_is_said_as_an_instruction(a_clean_database: None) -> None:
    # It becomes an action item, in a list that says everything else as
    # something to do, and is said there in the narration's own words.
    some_service = "io-shop"

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                the_recommendation := ActionRecommended(incident_id=incident_id,
                                                        hypothesis_id=None,
                                                        action_type=ROLL_BACK_DEPLOYMENT,
                                                        subject=some_service)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(conn, incident_id, the_recommendation)
            ) \
            .then(
                _recommends(what_to_do(ROLL_BACK_DEPLOYMENT, some_service))
            )


@pytest.mark.component
def test_an_action_nothing_put_back_is_said_to_be_still_in_place(a_clean_database: None) -> None:
    # After a resolution nothing is unwound, so a flag Argus turned off is off
    # when the document is written - and a responder reading it needs to know
    # there is a change of Argus's still standing in production.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, REVERT_FEATURE_FLAG, Verdict.CONFIRMED,
                    FlagUndo(flag=SOME_FLAG, was_enabled=True)))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(
                    lambda evidence: [action.standing for action in evidence.actions],
                    "still in place"
                )
            )


@pytest.mark.component
def test_an_action_that_did_not_help_is_said_to_be_put_back(a_clean_database: None) -> None:
    # Mitigation puts a refuted change back itself, before the walk moves on.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, REVERT_FEATURE_FLAG, Verdict.REFUTED,
                    FlagUndo(flag=SOME_FLAG, was_enabled=True)))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(
                    lambda evidence: [action.standing for action in evidence.actions],
                    "put back"
                )
            )


@pytest.mark.component
def test_an_action_that_did_not_help_and_was_changed_since_is_said_to_be_left_as_found(
        a_clean_database: None) -> None:
    # Refuted too, and not put back: somebody changed the flag after Argus set
    # it, so it was left as they set it. Said as put back, a reader would take
    # the flag for Argus's again.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, REVERT_FEATURE_FLAG, Verdict.REFUTED,
                    FlagUndo(flag=SOME_FLAG, was_enabled=True),
                    undone=Undone.LEFT_AS_FOUND))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(all_of(
                _mentions_among(
                    lambda evidence: [action.standing for action in evidence.actions],
                    "left as found"
                ),
                _mentions_none_among(
                    lambda evidence: [action.standing for action in evidence.actions],
                    "put back"
                )
            ))


@pytest.mark.component
@pytest.mark.parametrize(("progress", "standing"), [
    pytest.param(ActionProgress.PERFORMED, "may still be in place", id="made-and-never-judged"),
    pytest.param(ActionProgress.UNKNOWN, "not known whether it was made", id="unaccounted-for"),
    pytest.param(ActionProgress.CLAIMED, "not known whether it was made", id="never-answered")
])
def test_an_action_with_no_verdict_on_file_is_not_said_to_be_still_in_place(
        progress: ActionProgress, standing: str, a_clean_database: None) -> None:
    # A refuted change is put back before its verdict is written, so a worker
    # that died in between left it put back with nothing on file - and a claim
    # that never said more may never have been made. "Still in place" would
    # send a responder to undo what may not be there.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_left_at(conn, incident_id, progress))
            ) \
            .when(
                lambda: [action.standing
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([standing])
            )


@pytest.mark.component
def test_an_action_never_performed_is_said_as_not_done_and_as_changing_nothing(
        a_clean_database: None) -> None:
    # A platform that never answered: nothing was rolled back and nothing is in
    # place, and the write-up said both the other way round.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(conn, incident_id, ROLL_BACK_DEPLOYMENT,
                                                 Verdict.PLATFORM_UNREACHABLE, None,
                                                 performed=False))
            ) \
            .when(
                lambda: [(action.action, action.standing, action.progress,
                          action.has_a_way_back, action.left_behind_known)
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                # Nothing to put back either: a rollback's kind leaves a way
                # back, and one never made left nothing.
                the_answer_was([(f"Did not roll back the deployment of {SOME_FLAG}",
                                 "nothing was changed", ActionProgress.NOT_PERFORMED, False,
                                 True)])
            )


@pytest.mark.component
def test_an_action_a_tier_refused_unaccountably_is_not_said_to_have_changed_nothing(
        a_clean_database: None) -> None:
    # A refusal nobody can account for - a change request whose answer was
    # lost, a tool that raised for a reason nobody foresaw - and nobody can say
    # what production holds. Nor that there is nothing to put back.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(conn, incident_id, ROLL_BACK_DEPLOYMENT,
                                                 Verdict.ESCALATED, None, performed=False,
                                                 left_behind_known=False))
            ) \
            .when(
                lambda: [(action.standing, action.has_a_way_back, action.left_behind_known)
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([("not known whether anything was changed", False, False)])
            )


@pytest.mark.component
def test_an_action_a_tier_refused_before_asking_for_any_change_is_said_to_have_changed_nothing(
        a_clean_database: None) -> None:
    # A tier that refused before asking for any change - "could not read
    # [io-shop]" - said so, and the row kept it: the write-up says nothing was
    # changed rather than that nobody knows.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(conn, incident_id, ROLL_BACK_DEPLOYMENT,
                                                 Verdict.ESCALATED, None, performed=False,
                                                 left_behind_known=True))
            ) \
            .when(
                lambda: [(action.standing, action.has_a_way_back, action.left_behind_known)
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([("nothing was changed", False, True)])
            )


@pytest.mark.component
def test_an_action_whose_answer_was_lost_after_a_suspension_says_both(
        a_clean_database: None) -> None:
    # The suspension is in place either way, and whether the rollback itself
    # landed is what nobody can say.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, ROLL_BACK_DEPLOYMENT, Verdict.ESCALATED,
                    DeploymentRollbackUndo(application=SOME_FLAG, was_on_history_id=41,
                                           was_on_revision="0f1e2d3",
                                           was_syncing_itself=True),
                    performed=False, left_behind_known=False))
            ) \
            .when(
                lambda: [(action.standing, action.has_a_way_back)
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([("not known whether it was made; what it changed on the way "
                                 "is still in place", True)])
            )


@pytest.mark.component
def test_a_flag_set_at_the_provider_and_never_seen_in_effect_is_said_as_made(
        a_clean_database: None) -> None:
    # "Not made" would be false: the provider took the write. What nobody saw
    # is the flag evaluating as set, and what is left is the flag itself.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, REVERT_FEATURE_FLAG, Verdict.ESCALATED,
                    FlagUndo(flag=SOME_FLAG, was_enabled=True),
                    performed=False, left_behind_known=True))
            ) \
            .when(
                lambda: [(action.standing, action.has_a_way_back)
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([("made at the provider but never seen in effect; still in "
                                 "place", True)])
            )


@pytest.mark.component
@pytest.mark.parametrize("progress", [ActionProgress.CLAIMED, ActionProgress.UNKNOWN],
                         ids=["claimed", "unknown"])
def test_an_action_nobody_can_account_for_is_named_in_no_tense(
        progress: ActionProgress, a_clean_database: None) -> None:
    # Nothing announced it and nothing says it ran, so "Reverted the feature
    # flag" would claim it was done and "Did not" that it was not. How far it
    # got travels with it, so the brief lists it under neither heading.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_left_at(conn, incident_id, progress))
            ) \
            .when(
                lambda: [(action.action, action.progress)
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([(f"Reverting {SOME_FLAG}", progress)])
            )


@pytest.mark.component
def test_an_action_never_performed_that_left_something_on_the_way_says_it_is_in_place(
        a_clean_database: None) -> None:
    # The platform went after the sync was suspended: the rollback was not
    # made, and the suspension it left is still there for somebody to undo.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, ROLL_BACK_DEPLOYMENT, Verdict.PLATFORM_UNREACHABLE,
                    DeploymentRollbackUndo(application=SOME_FLAG, was_on_history_id=41,
                                           was_on_revision="0f1e2d3",
                                           was_syncing_itself=True),
                    performed=False))
            ) \
            .when(
                lambda: [(action.standing, action.has_a_way_back)
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([("not made; what it changed on the way is still in place",
                                 True)])
            )


@pytest.mark.component
def test_an_action_with_no_way_back_is_said_to_leave_nothing_to_put_back(
        a_clean_database: None) -> None:
    # A discard of stale cached figures changed something real and owes nothing
    # back. "Still in place" would send somebody looking for a change to undo.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, DISCARD_CACHE_ENTRIES, Verdict.CONFIRMED, None))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(
                    lambda evidence: [action.standing for action in evidence.actions],
                    "nothing to put back"
                )
            )


@pytest.mark.component
@pytest.mark.parametrize(("outcome", "was_syncing_itself", "paused"), [
    pytest.param(Verdict.CONFIRMED, True, "io-shop", id="standing-with-sync-stopped"),
    pytest.param(Verdict.REFUTED, True, None, id="put-back"),
    pytest.param(Verdict.CONFIRMED, False, None, id="sync-found-stopped")
])
def test_an_action_standing_with_automatic_sync_stopped_says_whose(
    outcome: Verdict,
    was_syncing_itself: bool,
    paused: str | None,
    a_clean_database: None
) -> None:
    # A rollback stops the platform syncing the application from its
    # repository, and leaves it stopped while the rollback stands. Put back,
    # sync is put back with it; found stopped, Argus stopped nothing.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, ROLL_BACK_DEPLOYMENT, outcome,
                    DeploymentRollbackUndo(
                        application="io-shop",
                        was_on_history_id=2,
                        was_on_revision="7c3ca00c7528df68d533f6e87acd4f23a55ab342",
                        was_syncing_itself=was_syncing_itself)))
            ) \
            .when(
                lambda: [action.paused_sync_of
                         for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([paused])
            )


@pytest.mark.component
def test_an_action_is_said_in_words(a_clean_database: None) -> None:
    # The document's resolution, action items and timeline all read this, and
    # a reader is not owed the action's tag.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, REVERT_FEATURE_FLAG, Verdict.CONFIRMED,
                    FlagUndo(flag=SOME_FLAG, was_enabled=True)))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _mentions_among(
                    lambda evidence: [action.action for action in evidence.actions],
                    f"Reverted the feature flag {SOME_FLAG}"
                )
            )


@pytest.mark.component
def test_an_action_carries_the_candidate_it_was_for(a_clean_database: None) -> None:
    # By that candidate's place among the candidates, which is what its label
    # counts. Nothing else says which an action was for: the move to
    # mitigating names none, and a write-up left to guess credited the action
    # to the leading candidate and called the one it was for never acted on.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: hypotheses.record(conn, Hypothesis(
                    incident_id=incident_id, summary="the leading cause",
                    failure_mode=FailureMode.FEATURE_FLAG_TOGGLE, confidence=0.9,
                    supporting_evidence=[], number=1))),
                calling(lambda: _an_action_taken(
                    conn, incident_id, ROLL_BACK_DEPLOYMENT, Verdict.ESCALATED, None,
                    performed=False, number=2))
            ) \
            .when(
                lambda: [action.candidate for action in gather_evidence(conn, incident_id).actions]
            ) \
            .then(
                the_answer_was([2])
            )


@pytest.mark.component
def test_an_action_carries_the_verdict_it_reached(a_clean_database: None) -> None:
    # The document numbers an action that brought recovery as an action item
    # already done, so whether it did has to arrive as the verdict, not as a
    # word somewhere in a sentence about it.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_taken(
                    conn, incident_id, REVERT_FEATURE_FLAG, Verdict.CONFIRMED,
                    FlagUndo(flag=SOME_FLAG, was_enabled=True)))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_one_action_whose_verdict_was(Verdict.CONFIRMED)
            )


@pytest.mark.component
def test_an_action_is_dated_by_when_it_was_taken_not_by_when_it_was_claimed(
        a_clean_database: None) -> None:
    # The row is a claim written before anything happens, so that a walk
    # resumed inside the step is refused by the database. Dated by the claim,
    # the action comes before the agent was even called in to take it.
    some_taken_at = parse_iso("2026-10-11T23:44:44Z")

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _an_action_claimed_then_taken(conn, incident_id, some_taken_at))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _dates_its_one_action_at(some_taken_at)
            )


@pytest.mark.component
def test_each_action_points_at_its_own_line_once_each_wait_is_told_once(
        a_clean_database: None) -> None:
    # The document marks the line that took the action credited with the
    # recovery, by its place in the timeline. The timeline tells a wait by its
    # last look alone, so a place counted before the looks were dropped puts an
    # action that followed a wait on a line further on.
    some_other_flag = "some-other-flag"

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        the_first = _a_candidate_acted_on(conn, incident_id, SOME_FLAG, Verdict.REFUTED,
                                          "2026-09-02T12:05:00Z")
        the_second = _a_candidate_acted_on(conn, incident_id, some_other_flag, Verdict.CONFIRMED,
                                           "2026-09-02T12:08:00Z")

        Scenario() \
            .given(
                calling(lambda: _recorded_in_order(conn, [
                    _announced(incident_id, the_first, SOME_FLAG, "2026-09-02T12:05:00Z"),
                    RecoveryChecked(incident_id=incident_id, at=parse_iso("2026-09-02T12:06:10Z"),
                                    minute="2026-09-02T12:06:00Z", recovered=False),
                    RecoveryChecked(incident_id=incident_id, at=parse_iso("2026-09-02T12:06:20Z"),
                                    minute="2026-09-02T12:06:00Z", recovered=False),
                    RecoveryChecked(incident_id=incident_id, at=parse_iso("2026-09-02T12:07:10Z"),
                                    minute="2026-09-02T12:07:00Z", recovered=False),
                    _announced(incident_id, the_second, some_other_flag, "2026-09-02T12:08:00Z")]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _each_action_is_said_by_the_line_it_points_at()
            )


@pytest.mark.component
def test_an_action_announced_twice_points_at_the_announcement_it_was_taken_by(
        a_clean_database: None) -> None:
    # A walk that stopped after announcing an action and before taking it
    # announces it again when it resumes, on the same candidate. The second
    # line is the one the action is dated and said by, so it is the line the
    # document marks.
    the_resumed_announcement = "2026-09-02T12:09:00Z"

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        the_candidate = _a_candidate_acted_on(conn, incident_id, SOME_FLAG, Verdict.CONFIRMED,
                                              "2026-09-02T12:05:00Z")

        Scenario() \
            .given(
                calling(lambda: _recorded_in_order(conn, [
                    _announced(incident_id, the_candidate, SOME_FLAG, "2026-09-02T12:05:00Z"),
                    _announced(incident_id, the_candidate, SOME_FLAG, the_resumed_announcement)]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(all_of(
                _dates_its_one_action_at(parse_iso(the_resumed_announcement)),
                _each_action_is_said_by_the_line_it_points_at()))


@pytest.mark.component
def test_the_evidence_points_at_each_line_saying_the_gate_refused_to_act(
        a_clean_database: None) -> None:
    # A refusal is a decision about how the incident ended, which the document
    # lists beside the actions taken - by its line in the timeline, so it is
    # dated and said as the timeline says it.
    the_refusal = "2026-09-02T12:05:00Z"

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

        Scenario() \
            .given(
                calling(lambda: _recorded_in_order(conn, [
                    ActionRefused(incident_id=incident_id, hypothesis_id=None,
                                  refusal=Refusal.WOULD_UNDO_A_MEANT_CHANGE,
                                  at=parse_iso(the_refusal))]))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _points_at_refusals_dated([(parse_iso(the_refusal),
                                            Refusal.WOULD_UNDO_A_MEANT_CHANGE)])
            )


@pytest.mark.component
def test_the_evidence_carries_the_fix_that_was_proposed(a_clean_database: None) -> None:
    # Read off the event rather than left in the timeline for the model to
    # notice. The walk opened the pull request and recorded where; a document
    # that depended on the summary mentioning it loses the address on every run
    # whose prose reads perfectly well without one.
    where_it_can_be_read = "https://github.invalid/ohadraz/io-shop/pull/7"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(
                    conn,
                    incident_id,
                    FixAttempted(
                        incident_id=incident_id,
                        outcome=FixOutcome.PROPOSED,
                        pull_request=OpenedPullRequest(
                            number=7,
                            url=where_it_can_be_read,
                            branch="argus/fix-abc"
                        ),
                        detail="dont care what the node said"
                    )
                )
            ) \
            .then(
                _carries_the_proposal_at(where_it_can_be_read)
            )


@pytest.mark.component
def test_an_incident_that_read_the_code_and_changed_nothing_carries_no_fix(
    a_clean_database: None
) -> None:
    # The ordinary ending, and a real one: the flag went back and there was
    # nothing in the code to change. The step still published its event, so an
    # evidence bundle reading "there was a fix" off the event's presence rather
    # than off its pull request would invent a proposal.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: _the_evidence_after_publishing(
                    conn,
                    incident_id,
                    FixAttempted(
                        incident_id=incident_id,
                        outcome=FixOutcome.NOT_WARRANTED,
                        pull_request=None,
                        detail="dont care what the node said"
                    )
                )
            ) \
            .then(
                _carries_no_proposal()
            )


@pytest.mark.component
def test_the_evidence_carries_what_code_fix_last_said_of_the_code(a_clean_database: None) -> None:
    # The last attempt's, for the reason the proposal is the last one: a walk
    # that went back to investigate can reach the code twice, and what stands
    # is what was said of it last.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, FixAttempted(
                    incident_id=incident_id, outcome=FixOutcome.NOT_WARRANTED,
                    detail="dont care", explanation="an earlier reading"))),
                calling(lambda: events.record(conn, FixAttempted(
                    incident_id=incident_id, outcome=FixOutcome.NOT_WARRANTED,
                    detail="dont care", explanation="the reading that stands")))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_what_code_fix_said("the reading that stands")
            )


@pytest.mark.component
def test_the_evidence_carries_which_branch_code_fix_read_off_the_reading_that_stands(
    a_clean_database: None
) -> None:
    # Off the same attempt as what it said: the branch and whether it held what
    # ran are facts about that reading, and an earlier attempt's would describe
    # a reading the document no longer shows.
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, FixAttempted(
                    incident_id=incident_id, outcome=FixOutcome.NOT_WARRANTED,
                    detail="dont care", explanation="an earlier reading",
                    branch_read="release", holds_what_ran=True))),
                calling(lambda: events.record(conn, FixAttempted(
                    incident_id=incident_id, outcome=FixOutcome.NOT_WARRANTED,
                    detail="dont care", explanation="the reading that stands",
                    branch_read="main", holds_what_ran=False)))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_what_code_fix_read("main", False)
            )


@pytest.mark.component
def test_the_evidence_carries_the_files_as_they_ran_off_the_reading_that_stands(
    a_clean_database: None
) -> None:
    # The files the standing reading names, as they ran: an earlier attempt's
    # would settle a reading the document no longer shows.
    the_file = FileAsItRan(path="deploy/scrape.yaml", revision="53f02e9", as_read=False,
                           content="selector:\n  port: metrics\n")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, FixAttempted(
                    incident_id=incident_id, outcome=FixOutcome.NOT_WARRANTED,
                    detail="dont care", explanation="an earlier reading",
                    as_it_ran=[the_file.model_copy(update={"path": "deploy/other.yaml"})]))),
                calling(lambda: events.record(conn, FixAttempted(
                    incident_id=incident_id, outcome=FixOutcome.NOT_WARRANTED,
                    detail="dont care", explanation="the reading that stands",
                    as_it_ran=[the_file])))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_as_they_ran([the_file])
            )


@pytest.mark.component
def test_the_evidence_carries_the_uses_outside_the_patch_off_the_reading_that_stands(
    a_clean_database: None
) -> None:
    # The uses that stand beside the reading the document shows: an earlier
    # attempt's patch changed something else.
    the_use = CodeUse(name="total_this_month_cents", path="src/io_shop/spend_reconciliation.py",
                      line=109, function="reconcile_monthly_totals",
                      does="compares it with _bought_this_month(account)")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn),
                calling(lambda: events.record(conn, FixAttempted(
                    incident_id=incident_id, outcome=FixOutcome.NOT_WARRANTED,
                    detail="dont care", explanation="an earlier reading",
                    uses_outside=[the_use.model_copy(update={"line": 115})]))),
                calling(lambda: events.record(conn, FixAttempted(
                    incident_id=incident_id, outcome=FixOutcome.NOT_WARRANTED,
                    detail="dont care", explanation="the reading that stands",
                    uses_outside=[the_use])))
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_uses_outside([the_use])
            )


@pytest.mark.component
def test_the_evidence_carries_what_people_told_the_incident_as_it_was_weighed(
    a_clean_database: None
) -> None:
    # Off the record rather than off the timeline: the timeline says a lead was
    # weighed, and the record is where its words and its standing are kept
    # together. A message that was not information - a question, a request to
    # end it - was never a lead, and the document has nothing to say of it.
    some_weighing = Weighing(standing=Standing.SUPPORTED, reason="the flag history agrees")

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        a_lead = _a_message_understood_as(conn, incident_id, Meaning.INFORMATION,
                                          "the kuki flag was flipped at noon",
                                          ts="1760000100.000200")
        _a_message_understood_as(conn, incident_id, Meaning.QUESTION,
                                 "is anyone looking at this",
                                 ts="1760000200.000300")
        conversation.weighed(conn, a_lead.message, some_weighing)

        Scenario() \
            .given(
                incident_id
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_leads([a_lead.model_copy(update={"weighing": some_weighing})])
            )


@pytest.mark.component
def test_the_evidence_carries_the_rule_that_paged(a_clean_database: None) -> None:
    # The postmortem reads the incident's metrics again, over the whole of it,
    # and has to read them for the rule the walk read them for - or the series
    # that paged is missing from the one window the document is measured from.
    some_rule = "kuki-rule"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn, rule=some_rule)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_rule(some_rule)
            )


@pytest.mark.component
def test_the_evidence_carries_what_the_alert_said_it_found(a_clean_database: None) -> None:
    # A check that reconciles stored figures says what it found - how many, by
    # how much, since when. Without it the postmortem credits those figures to
    # the investigation, or to nobody.
    some_finding = "240 of 240 shopper totals do not reconcile"

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn, summary=some_finding)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_alert_finding(some_finding)
            )


@pytest.mark.component
def test_an_alert_that_said_nothing_carries_no_finding(a_clean_database: None) -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_alert_finding(None)
            )


@pytest.mark.component
def test_the_evidence_carries_when_the_alert_said_the_incident_began(
        a_clean_database: None) -> None:
    # A check that reconciles stored figures dates the fault itself, by the
    # oldest record it found wrong, and finds it on its own schedule - so the
    # time from that onset to the alert is the schedule, not detection.
    some_onset = parse_iso("2026-10-15T19:56:00Z")

    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn, stated_onset=some_onset)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_stated_onset(some_onset)
            )


@pytest.mark.component
def test_an_alert_that_dated_nothing_carries_no_stated_onset(a_clean_database: None) -> None:
    with connect_from_env() as conn:
        Scenario() \
            .given(
                incident_id := _an_incident_that_ended(conn)
            ) \
            .when(
                lambda: gather_evidence(conn, incident_id)
            ) \
            .then(
                _carries_the_stated_onset(None)
            )


@pytest.mark.component
def test_a_postmortem_is_written_from_the_sources_it_was_handed(
    a_clean_database: None
) -> None:
    # The seam M4 bought, exercised. Every provider is a function written here
    # and the model is a stand-in that submits one answer - so this runs with
    # no vendor SDK, no credential and no network, which is the whole claim.
    #
    # Asserted three ways, because there are three things that could be wired
    # wrongly and still return a document: the answer has to reach the page,
    # the sources handed in have to be the ones measured against, and the
    # client has to be asked for per incident rather than shared.
    some_root_cause = "the checkout fallback flag was switched off"
    windows_asked_about: list[tuple[datetime, datetime]] = []
    clients_asked_for: list[Replay] = []

    # Seeded on its own connection and committed by leaving the block: the call
    # under test opens its own, and would not otherwise see any of this.
    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)
        incident = incidents.get(conn, incident_id)
        assert incident is not None and incident.ended_at is not None
        the_incidents_own_window = (incident.created_at, incident.ended_at)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: write_postmortem_for(
                incident_id,
                connections=connect_from_env,
                sources=_sources_recording_into(windows_asked_about),
                client_for=_a_model_submitting(some_root_cause, clients_asked_for)
            )
        ) \
        .then(all_of(
            _it_reports_the_root_cause(some_root_cause),
            _the_revenue_source_was_asked_about(the_incidents_own_window,
                                                windows_asked_about),
            _one_client_was_asked_for(clients_asked_for)
        ))


@pytest.mark.component
def test_a_postmortem_counts_the_tokens_its_own_writing_spent(
    a_clean_database: None
) -> None:
    # What the incident cost Argus includes the write-up. The replay log is the
    # one count of every call, and a total read from it before the writer ran
    # left the writer's own calls out of a figure that claims to be all of them.
    some_tokens_a_call = 9_148

    with connect_from_env() as conn:
        incident_id = _an_incident_that_ended(conn)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: write_postmortem_for(
                incident_id,
                connections=connect_from_env,
                sources=_sources_recording_into([]),
                client_for=_a_model_spending(some_tokens_a_call),
                recorder=calls_into(connect_from_env)
            )
        ) \
        .then(
            _it_reports_every_token_the_replay_log_holds(incident_id)
        )


def _sources_recording_into(
    windows_asked_about: list[tuple[datetime, datetime]]
) -> Sources:
    """Every port the document reads, answered without reaching anything.

    All five say they could not answer, which is a real state and the one that
    needs no arithmetic to be right: what is under test here is that the record
    reaches the measurement at all, not what the figures come to. The revenue
    port notes the window it was asked about on the way past, because that is
    the evidence that it was this incident being measured.
    """
    def revenue(started_at: datetime,
                ended_at: datetime) -> Mapping[str, Decimal] | None:
        windows_asked_about.append((started_at, ended_at))

        return None

    return Sources(
        revenue=revenue,
        rates=lambda: None,
        engagement=lambda dont_care_incident_id: None,
        bands=lambda: None,
        metrics=lambda dont_care_start, dont_care_end, dont_care_rule: [],
        thresholds=DONT_CARE_THRESHOLDS,
        working_hours_a_year=DONT_CARE_WORKING_YEAR,
        reporting_currency="USD",
        metrics_reporting_lag_minutes=DONT_CARE_REPORTING_LAG_MINUTES,
        alert_rule=lambda dont_care_rule: None
    )


class _AModelSubmitting:
    """A stand-in that answers with one submitted postmortem, first time.

    The parameter names are the `LLMClient` protocol's own rather than this
    file's `dont_care_` convention: a stand-in whose parameters are named
    differently does not satisfy the protocol, and satisfying it is the point.

    It names no tool of its own. Which tool to call comes from the list it is
    offered, so this knows nothing about what the agent asks for - only that
    whatever was offered is what an answer goes back as.
    """

    def __init__(self, answering: Mapping[str, str]) -> None:
        self._answering = answering

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        return Turn(
            text="",
            tool_calls=[ToolCall(id=new_id(),
                                 name=tools[0].name,
                                 arguments=dict(self._answering))],
            input_tokens=0,
            output_tokens=0
        )


def _a_model_submitting(root_cause: str,
                        clients_asked_for: list[Replay]) -> ClientFor:
    """The factory the document asks for a client, noting each time it does.

    A factory rather than a client because the receipt belongs to an incident,
    and this is where that is checked: one document, one client asked for.

    The summary carries no figure. A summary stating an amount is checked
    against the one Argus computed, and with every source answering `None`
    there is no computed figure for it to agree with - so a number here would
    be sent back as invented and this stand-in would answer the same thing
    twice.
    """
    def client_for(replay: Replay, policy: ModelPolicy | None = None) -> LLMClient:
        clients_asked_for.append(replay)

        return _AModelSubmitting({
            "root_cause": root_cause,
            "executive_summary": "The fallback was off and checkout failed."
        })

    return client_for


def _it_reports_the_root_cause(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.root_cause != expected:
            raise AssertionError(
                f"Expected the document to report [{expected}], got "
                f"[{document.root_cause}].")

        return True

    return assertion


def _the_revenue_source_was_asked_about(
    expected: tuple[datetime, datetime],
    windows_asked_about: list[tuple[datetime, datetime]]
) -> Assertion[PostmortemDocument]:
    """The incident's own span, among the windows the source was asked about.

    Among rather than alone: the document compares what the service took while
    it was failing against a calm window before it, so the source is asked
    twice and how the baseline is chosen is the agent's business. What this
    holds is narrower and is the part that would be wrong silently - that the
    incident measured was this one, and not some other window that would come
    back looking exactly like it.
    """
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        if expected not in windows_asked_about:
            raise AssertionError(
                f"Expected the revenue source to be asked about {expected}, "
                f"it was asked about {windows_asked_about}.")

        return True

    return assertion


def _one_client_was_asked_for(
    clients_asked_for: list[Replay]
) -> Assertion[PostmortemDocument]:
    """One document, one client.

    A client is asked for per incident because the receipt it keeps is filed
    under one - so a path that asked for none took a shared one from somewhere,
    and one that asked twice would file one document's calls under two.
    """
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        if len(clients_asked_for) != 1:
            raise AssertionError(
                f"Expected exactly one client to be asked for, "
                f"{len(clients_asked_for)} were.")

        return True

    return assertion


class _AModelSpending:
    """The submitting stand-in, filing each call it answers the way the real
    client does - through the receipt it was handed - with what it spent.

    The parameter names are the `LLMClient` protocol's own, for the reason
    `_AModelSubmitting` gives.
    """

    def __init__(self, replay: Replay, answering: Mapping[str, str], spends: int) -> None:
        self._replay = replay
        self._answering = _AModelSubmitting(answering)
        self._spends = spends

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        self._replay.record(call_type=CallType.LLM,
                            target="dont care",
                            request={},
                            response={"input_tokens": self._spends, "output_tokens": 0})

        return self._answering.converse(transcript, tools, max_tokens)


def _a_model_spending(tokens: int) -> ClientFor:
    """The factory the document asks for a client, handing back one that files
    each call it makes under the incident, `tokens` at a time. The summary
    carries no figure, for the reason `_a_model_submitting` gives."""
    def client_for(replay: Replay, policy: ModelPolicy | None = None) -> LLMClient:
        return _AModelSpending(replay,
                               {"root_cause": "dont care",
                                "executive_summary": "The fallback was off and checkout failed."},
                               spends=tokens)

    return client_for


def _it_reports_every_token_the_replay_log_holds(
    incident_id: str
) -> Assertion[PostmortemDocument]:
    """The document's figure against the log's own total, read once the writing
    is over - and a total of more than nothing, since a log holding none of the
    writer's calls would agree with a figure that left them out."""
    def assertion(document: PostmortemDocument) -> bool:
        with connect_from_env() as conn:
            held = replay.get_tokens_spent(conn, incident_id)

        if held == 0 or document.tokens_spent != held:
            raise AssertionError(
                f"Expected the document to report the [{held}] tokens the replay log "
                f"holds, its own writing included, got [{document.tokens_spent}].")

        return True

    return assertion


def _an_action_taken(conn: psycopg.Connection,
                     incident_id: str,
                     action_type: ActionType,
                     outcome: Verdict,
                     undo_descriptor: UndoDescriptor | None,
                     summary: str = "dont care",
                     performed: bool = True,
                     left_behind_known: bool = True,
                     number: int = 1,
                     undone: Undone | None = None) -> None:
    """One finished action, on a candidate of its own - performed, unless a
    case says the attempt ended before its write, and known to have left what
    its descriptor says, unless a case says nobody can tell."""
    candidate = Hypothesis(incident_id=incident_id,
                           summary=summary,
                           failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                           confidence=0.8,
                           supporting_evidence=[],
                           number=number)
    hypotheses.record(conn, candidate)
    taken_actions.record(conn, incident_id,
                         hypothesis_id=candidate.id,
                         action_type=action_type,
                         subject=SOME_FLAG,
                         outcome=outcome,
                         undo_descriptor=undo_descriptor,
                         at=DONT_CARE_TAKEN_AT,
                         performed=performed,
                         left_behind_known=left_behind_known,
                         undone=undone)


def _an_action_left_at(conn: psycopg.Connection,
                       incident_id: str,
                       progress: ActionProgress,
                       summary: str = "dont care") -> None:
    """One flag revert whose row got as far as `progress` and recorded no
    verdict - what a worker that died mid-attempt leaves, on a candidate of its
    own."""
    candidate = Hypothesis(incident_id=incident_id,
                           summary=summary,
                           failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                           confidence=0.8,
                           supporting_evidence=[])
    hypotheses.record(conn, candidate)
    taken_actions.claim(conn, incident_id,
                        hypothesis_id=candidate.id,
                        action_type=REVERT_FEATURE_FLAG,
                        subject=SOME_FLAG,
                        at=DONT_CARE_TAKEN_AT)

    if progress is not ActionProgress.CLAIMED:
        taken_actions.advance(conn, incident_id,
                              hypothesis_id=candidate.id,
                              to=progress,
                              undo_descriptor=None)


def _an_action_claimed_then_taken(conn: psycopg.Connection,
                                  incident_id: str,
                                  taken_at: datetime) -> None:
    """One action whose row was claimed before the account says its change was
    made at `taken_at` - the two moments a walk writes for every action."""
    candidate = Hypothesis(incident_id=incident_id,
                           summary="dont care",
                           failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                           confidence=0.8,
                           supporting_evidence=[])
    hypotheses.record(conn, candidate)
    taken_actions.record(conn, incident_id,
                         hypothesis_id=candidate.id,
                         action_type=REVERT_FEATURE_FLAG,
                         subject=SOME_FLAG,
                         outcome=Verdict.CONFIRMED,
                         undo_descriptor=FlagUndo(flag=SOME_FLAG, was_enabled=True),
                         at=taken_at - timedelta(minutes=4),
                         left_behind_known=True)
    events.record(conn, ActionTaken(incident_id=incident_id,
                                    hypothesis_id=candidate.id,
                                    action_type=REVERT_FEATURE_FLAG,
                                    subject=SOME_FLAG,
                                    at=taken_at))


def _a_candidate_acted_on(conn: psycopg.Connection,
                          incident_id: str,
                          subject: str,
                          outcome: Verdict,
                          taken_at: str) -> str:
    """A candidate and its action's row, the account's lines about it left to
    the case - a walk can announce one action more than once."""
    candidate = Hypothesis(incident_id=incident_id,
                           summary="dont care",
                           failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                           confidence=0.8,
                           supporting_evidence=[])
    hypotheses.record(conn, candidate)
    taken_actions.record(conn, incident_id,
                         hypothesis_id=candidate.id,
                         action_type=REVERT_FEATURE_FLAG,
                         subject=subject,
                         outcome=outcome,
                         undo_descriptor=FlagUndo(flag=subject, was_enabled=True),
                         at=parse_iso(taken_at),
                         left_behind_known=True)

    return candidate.id


def _announced(incident_id: str, hypothesis_id: str, subject: str, at: str) -> ActionTaken:
    return ActionTaken(incident_id=incident_id,
                       hypothesis_id=hypothesis_id,
                       action_type=REVERT_FEATURE_FLAG,
                       subject=subject,
                       at=parse_iso(at))


def _each_action_is_said_by_the_line_it_points_at() -> Assertion[IncidentEvidence]:
    """The line at each action's place in the timeline is the one its moment
    and its words were read from."""
    def assertion(evidence: IncidentEvidence) -> bool:
        expected = [(action.taken_at, action.action) for action in evidence.actions]
        pointed_at = [(evidence.timeline[action.line].at, evidence.timeline[action.line].text)
                      if action.line is not None and 0 <= action.line < len(evidence.timeline)
                      else None
                      for action in evidence.actions]

        if not expected or any(line is None or line[0] != at or not line[1].startswith(words)
                               for (at, words), line in zip(expected, pointed_at, strict=True)):
            raise AssertionError(
                f"Expected each action to point at its own line, said as {expected}, "
                f"and they point at {pointed_at}.")

        return True

    return assertion


def _points_at_refusals_dated(
        expected: list[tuple[datetime, Refusal]]) -> Assertion[IncidentEvidence]:
    """The lines the evidence points at as refusals are dated as `expected`,
    each carrying the refusal it says."""
    def assertion(evidence: IncidentEvidence) -> bool:
        pointed_at = [(evidence.timeline[refused.line].at, refused.refusal)
                      if 0 <= refused.line < len(evidence.timeline) else None
                      for refused in evidence.refusals]

        if pointed_at != expected:
            raise AssertionError(
                f"Expected the refusals to point at lines dated {expected}, "
                f"and they point at {pointed_at}.")

        return True

    return assertion


def _dates_its_one_action_at(expected: datetime) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        dated = [action.taken_at for action in evidence.actions]

        if dated != [expected]:
            raise AssertionError(
                f"Expected one action dated [{expected}], got {dated}.")

        return True

    return assertion


def _carries_no_recovery() -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.recorded_recovery_at is not None:
            raise AssertionError(
                f"Expected no recovery recorded, got [{evidence.recorded_recovery_at}].")

        return True

    return assertion


def _the_evidence_after_publishing(conn: psycopg.Connection,
                                   incident_id: str,
                                   event: IncidentEvent) -> IncidentEvidence:
    events.record(conn, event)

    return gather_evidence(conn, incident_id)


def _carries_the_recovery(expected: datetime) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.recorded_recovery_at != expected:
            raise AssertionError(
                f"Expected the recovery recorded at [{expected}], got "
                f"[{evidence.recorded_recovery_at}].")

        return True

    return assertion


def _carries_the_report(at: datetime, by: str) -> Assertion[IncidentEvidence]:
    """The resolution reported at `at` by `by`, pointing at the timeline's line
    of that report."""
    def assertion(evidence: IncidentEvidence) -> bool:
        resolution = evidence.resolution
        if resolution is None or (resolution.at, resolution.by) != (at, by):
            raise AssertionError(
                f"Expected the resolution reported at [{at}] by [{by}], got [{resolution}].")

        line = evidence.timeline[resolution.line] if resolution.line is not None else None
        if line is None or line.at != at or not line.outside_the_walk:
            raise AssertionError(
                f"Expected the resolution to point at its report's line, dated [{at}], "
                f"got [{line}].")

        return True

    return assertion


def _carries_no_report() -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.resolution is not None:
            raise AssertionError(
                f"Expected no resolution reported, got [{evidence.resolution}].")

        return True

    return assertion


def _was_escalated(expected: bool) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.escalated != expected:
            raise AssertionError(
                f"Expected the evidence to say Argus {'' if expected else 'never '}handed the "
                f"incident to a person, and it says it "
                f"{'did' if evidence.escalated else 'did not'}.")

        return True

    return assertion


def _recommends(expected: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.recommended_action != expected:
            raise AssertionError(
                f"Expected the evidence to recommend [{expected}], got "
                f"[{evidence.recommended_action}].")

        return True

    return assertion


def _was_watched_and_never_recovered(expected: bool) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.watched_and_never_recovered != expected:
            raise AssertionError(
                f"Expected the evidence to say the incident was "
                f"{'' if expected else 'not '}watched and never seen to recover, and "
                f"it says it was{'' if evidence.watched_and_never_recovered else ' not'}.")

        return True

    return assertion


def _carries_the_rule(expected: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.rule != expected:
            raise AssertionError(
                f"Expected the rule that paged, [{expected}], got [{evidence.rule}].")

        return True

    return assertion


def _carries_the_alert_finding(expected: str | None) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.alert_finding != expected:
            raise AssertionError(
                f"Expected the alert's finding [{expected}], got [{evidence.alert_finding}].")

        return True

    return assertion


def _carries_the_stated_onset(expected: datetime | None) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.onset_stated_by_the_alert != expected:
            raise AssertionError(
                f"Expected the onset the alert stated, [{expected}], got "
                f"[{evidence.onset_stated_by_the_alert}].")

        return True

    return assertion


def _carries_the_onset(expected: datetime) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.onset_at != expected:
            raise AssertionError(
                f"Expected the onset [{expected}], got [{evidence.onset_at}].")

        return True

    return assertion


def _carries_no_onset() -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.onset_at is not None:
            raise AssertionError(
                f"Expected no onset where none was published, got "
                f"[{evidence.onset_at}] - the alert's own time would date the "
                f"loss from after the damage began.")

        return True

    return assertion


def _carries_the_proposal_at(expected: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        proposed = evidence.pull_request.url if evidence.pull_request else None

        if proposed != expected:
            raise AssertionError(
                f"Expected the fix proposed at [{expected}], got [{proposed}].")

        return True

    return assertion


def _carries_no_proposal() -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.pull_request is not None:
            raise AssertionError(
                f"Expected no fix proposed, got [{evidence.pull_request}].")

        return True

    return assertion


def _carries_what_code_fix_said(expected: str | None) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.fix_explanation != expected:
            raise AssertionError(
                f"Expected what Code-Fix said of the code to be [{expected}], got "
                f"[{evidence.fix_explanation}].")

        return True

    return assertion


def _carries_as_they_ran(expected: list[FileAsItRan]) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.files_as_they_ran != expected:
            raise AssertionError(
                f"Expected the files Code-Fix's reading names, as they ran, to be "
                f"{expected}, got {evidence.files_as_they_ran}.")

        return True

    return assertion


def _carries_the_uses_outside(expected: list[CodeUse]) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.uses_outside != expected:
            raise AssertionError(
                f"Expected how the code outside Code-Fix's patch uses what it changes "
                f"to be {expected}, got {evidence.uses_outside}.")

        return True

    return assertion


def _carries_what_code_fix_read(branch: str | None,
                                holds_what_ran: bool | None) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        read = (evidence.fix_branch_read, evidence.fix_holds_what_ran)

        if read != (branch, holds_what_ran):
            raise AssertionError(
                f"Expected Code-Fix to have read [{branch}], holding what ran "
                f"[{holds_what_ran}], got {read}.")

        return True

    return assertion



def _carries_the_leads(expected: list[ThreadMessage]) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.leads != expected:
            raise AssertionError(
                f"Expected the evidence to carry the leads "
                f"{[(lead.text, lead.weighing) for lead in expected]}, and it carried "
                f"{[(lead.text, lead.weighing) for lead in evidence.leads]}."
            )

        return True

    return assertion


def _a_candidate_formed(conn: psycopg.Connection,
                        incident_id: str,
                        rank: int,
                        number: int) -> str:
    """One candidate as the walk leaves it: the row, and the line saying it was
    formed - one hypothesis, seen twice."""
    a_candidate = Hypothesis(incident_id=incident_id,
                             summary="dont care",
                             failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                             confidence=0.5,
                             supporting_evidence=[],
                             rank=rank,
                             number=number)
    hypotheses.record(conn, a_candidate)
    events.record(conn, HypothesisFormed(incident_id=incident_id,
                                         hypothesis_id=a_candidate.id,
                                         summary=a_candidate.summary,
                                         failure_mode=a_candidate.failure_mode,
                                         confidence=a_candidate.confidence,
                                         subject=None,
                                         rank=rank,
                                         number=number))

    return a_candidate.id


def _the_lines_name_the_candidates(expected: list[list[int]]) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        named = [entry.candidates for entry in evidence.timeline if entry.candidates]

        if named != expected:
            raise AssertionError(
                f"Expected the lines to name the candidates at {expected}, got {named}.")

        return True

    return assertion


def _carries_the_candidates(expected: list[CandidateRecord]) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.candidates != expected:
            raise AssertionError(
                f"Expected the evidence to carry the candidates {expected}, and it "
                f"carried {evidence.candidates}."
            )

        return True

    return assertion


def _carries_the_log_lines(expected: list[str]) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.log_lines != expected:
            raise AssertionError(
                f"Expected the log lines {expected}, got {evidence.log_lines}.")

        return True

    return assertion


def _the_logs_were_read_until(expected: datetime | None) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.logs_read_until != expected:
            raise AssertionError(
                f"Expected the logs to have been read until {expected}, and the evidence "
                f"says {evidence.logs_read_until}.")

        return True

    return assertion


def _carries_the_changes(expected: list[ChangeEvent]) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.changes != expected:
            raise AssertionError(
                f"Expected the evidence to carry the changes {expected}, and it "
                f"carried {evidence.changes}."
            )

        return True

    return assertion


def _carries_the_deployment_changes(
        expected: list[DeploymentChangesRecord]) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.deployment_changes != expected:
            raise AssertionError(
                f"Expected the evidence to carry what each deployment read changed, "
                f"{expected}, and it carried {evidence.deployment_changes}."
            )

        return True

    return assertion


def _carries_each_deployment_read_as(
        expected: list[tuple[str, DeploymentComparison, str | None]]
        ) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        carried = [(record.revision, record.comparison, record.service)
                   for record in evidence.deployment_changes]

        if carried != expected:
            raise AssertionError(
                f"Expected the evidence to carry each deployment read as {expected} - "
                f"whether it was compared, and of which service - and it carried {carried}."
            )

        return True

    return assertion


def _carries_one_action_whose_verdict_was(expected: Verdict) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        verdicts = [action.verdict for action in evidence.actions]

        if verdicts != [expected]:
            raise AssertionError(
                f"Expected one action, whose verdict was [{expected}], got {verdicts}.")

        return True

    return assertion


def _a_message_understood_as(conn: psycopg.Connection,
                             incident_id: str,
                             meaning: Meaning,
                             words: str,
                             ts: str) -> ThreadMessage:
    """Something a person wrote in the incident's thread, on the record and
    understood as `meaning` - the message named by `ts`."""
    written = ThreadMessage(incident_id=incident_id,
                            message=a_chat_message(ReportChannel.SLACK, "C-some-channel", ts),
                            person_id="U-some-person",
                            text=words,
                            written_at=parse_iso("2026-08-20T11:05:00Z"))
    conversation.write(conn, written)
    conversation.understood(conn, written.message, meaning)

    return written.model_copy(update={"meaning": meaning})


def _an_incident_that_ended(conn: psycopg.Connection,
                            rule: str | None = None,
                            summary: str | None = None,
                            started_at: datetime | None = None,
                            stated_onset: datetime | None = None) -> str:
    """An incident with both a row and an account of itself.

    The events as well as the rows, because the document is written from the
    account now rather than from the status column: an incident whose rows
    moved and whose story says nothing is one the postmortem has nothing to
    read.
    """
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate", rule=rule, summary=summary,
                       started_at=started_at, stated_onset=stated_onset)
    incident_id = incidents.create(conn, some_alert, at=utc_now())
    events.record(conn, AlertAcknowledged(incident_id=incident_id, alert=some_alert))
    incidents.transition(
        conn,
        incident_id,
        IncidentStatus.RESOLVED,
        at=utc_now(),
    )
    events.record(
        conn,
        StatusChanged(incident_id=incident_id, to_status=IncidentStatus.RESOLVED)
    )

    return incident_id


def _an_incident_a_person_ended(conn: psycopg.Connection,
                                after: list[IncidentStatus]) -> str:
    """An incident the walk moved through `after`, in order, and a person then
    reported resolved - with no move of the walk's own after their report."""
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")
    incident_id = incidents.create(conn, some_alert, at=utc_now())
    events.record(conn, AlertAcknowledged(incident_id=incident_id, alert=some_alert))
    for status in after:
        events.record(conn, StatusChanged(incident_id=incident_id, to_status=status))
    incidents.transition(conn, incident_id, IncidentStatus.RESOLVED, at=utc_now())
    events.record(conn, StatusChanged(
        incident_id=incident_id,
        to_status=IncidentStatus.RESOLVED,
        reported=Report(by="some person", channel=ReportChannel.SLACK)))

    return incident_id


def _the_timeline_holds(who: str, text: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        said = [(entry.who, entry.text) for entry in evidence.timeline]

        if (who, text) not in said:
            raise AssertionError(f"Expected [{who}] saying [{text}] on the timeline, got {said}.")

        return True

    return assertion


def _no_line_of_the_timeline_says(words: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        saying = [entry.text for entry in evidence.timeline if words in entry.text]

        if saying:
            raise AssertionError(f"Expected no line of the timeline saying [{words}], "
                                 f"got {saying}.")

        return True

    return assertion


def _told_in_its_thread(conn: psycopg.Connection,
                        incident_id: str,
                        channel: ReportChannel) -> Assertion[FirstTold | None]:
    """Told on that platform, at the moment the thread's own row says it was
    written down."""
    def assertion(told: FirstTold | None) -> bool:
        row = conn.execute(
            "SELECT recorded_at FROM incident_reference WHERE incident_id = %s AND kind = %s",
            (incident_id, CHAT_THREAD)
        ).fetchone()
        expected = FirstTold(channel=channel, at=row[0]) if row else None

        if told != expected:
            raise AssertionError(f"Expected the incident first told as {expected}, got {told}.")

        return True

    return assertion


def _says_people_wrote(expected: bool) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.people_wrote != expected:
            raise AssertionError(
                f"Expected people_wrote to be [{expected}], got [{evidence.people_wrote}].")

        return True

    return assertion


def _spans_the_incident(conn: psycopg.Connection,
                        incident_id: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        incident = incidents.get(conn, incident_id)
        assert incident is not None and incident.ended_at is not None

        return all_of(
            _starts_at(incident.created_at),
            _ends_at(incident.ended_at)
        )(evidence)

    return assertion


def _starts_at(expected: object) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.started_at != expected:
            raise AssertionError(
                f"Expected the evidence to start at [{expected}], got [{evidence.started_at}].")

        return True

    return assertion


def _ends_at(expected: object) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        if evidence.ended_at != expected:
            raise AssertionError(
                f"Expected the evidence to end at [{expected}], got [{evidence.ended_at}].")

        return True

    return assertion


def _mentions_among(reading: Callable[[IncidentEvidence], list[str]],
                    expected: str) -> Assertion[IncidentEvidence]:
    """One value of the bundle, whichever list it belongs in.

    The lists differ in what they hold and not in how they are checked, so the
    test names what to read and the text and nothing else.
    """
    def assertion(evidence: IncidentEvidence) -> bool:
        lines = reading(evidence)

        if not any(expected in line for line in lines):
            raise AssertionError(f"Expected [{expected}] among {lines}.")

        return True

    return assertion


def _mentions_none_among(reading: Callable[[IncidentEvidence], list[str]],
                         unwanted: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        lines = reading(evidence)

        if any(unwanted in line for line in lines):
            raise AssertionError(f"Expected [{unwanted}] in none of {lines}.")

        return True

    return assertion


def _only_the_lines_dated_are_outside_the_walk(expected: list[datetime]
                                               ) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        outside = [entry.at for entry in evidence.timeline if entry.outside_the_walk]

        if outside != expected:
            raise AssertionError(
                f"Expected only the lines dated {expected} carried as outside the walk, "
                f"got {outside}.")

        return True

    return assertion


def _the_looks_carried_are(looked: list[RecoveryChecked],
                           expected: list[RecoveryChecked]) -> Assertion[IncidentEvidence]:
    """Which of the looks the timeline tells, found by when each was taken."""
    def assertion(evidence: IncidentEvidence) -> bool:
        taken_at = {look.at for look in looked}
        carried = [entry.at for entry in evidence.timeline if entry.at in taken_at]

        if carried != [look.at for look in expected]:
            raise AssertionError(
                f"Expected the looks taken at {[look.at for look in expected]} carried, "
                f"got {carried}.")

        return True

    return assertion


def _recorded_in_order(conn: psycopg.Connection, account: list[IncidentEvent]) -> None:
    for event in account:
        events.record(conn, event)


def _the_reads_of(channel: RetrievalChannel, incident_id: str, *, asked: int, answered: int,
                  asked_of_the_other: int) -> list[IncidentEvent]:
    """An investigation's reads of `channel` as the account records them: the
    request it publishes before each, and the reading it publishes once one is
    answered - each answer bringing nothing back, so only the reading says one
    came. Then the requests it made of the other channel it reads."""
    other = (RetrievalChannel.LOGS if channel is RetrievalChannel.CHANGES
             else RetrievalChannel.CHANGES)
    start, end = "2026-09-02T11:30:00Z", "2026-09-02T12:30:00Z"
    answer: IncidentEvent = (
        ChangesRetrieved(incident_id=incident_id, window_start=start, window_end=end, changes=[])
        if channel is RetrievalChannel.CHANGES
        else LogsRetrieved(incident_id=incident_id, window_start=start, window_end=end, lines=[]))

    return [*(RetrievalRequested(incident_id=incident_id, channel=channel,
                                 window_start=start, window_end=end) for _ in range(asked)),
            *(answer for _ in range(answered)),
            *(RetrievalRequested(incident_id=incident_id, channel=other,
                                 window_start=start, window_end=end)
              for _ in range(asked_of_the_other))]


def _timeline_begins_with(expected: str) -> Assertion[IncidentEvidence]:
    def assertion(evidence: IncidentEvidence) -> bool:
        said = [entry.text for entry in evidence.timeline]

        if not said or expected not in said[0]:
            raise AssertionError(
                f"Expected the timeline to open on [{expected}], got {said}.")

        return True

    return assertion


def _timeline_ends_with(expected: str) -> Assertion[IncidentEvidence]:
    """Where the incident finished, in the account's own words.

    Both ends rather than one: a timeline holding only its first line is in
    order trivially, and the order is the whole claim.
    """
    def assertion(evidence: IncidentEvidence) -> bool:
        said = [entry.text for entry in evidence.timeline]

        if not said or expected not in said[-1]:
            raise AssertionError(
                f"Expected the timeline to close on [{expected}], got {said}.")

        return True

    return assertion
