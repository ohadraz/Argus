from __future__ import annotations

from collections.abc import Iterator

import httpx
import psycopg
import pytest
from agent_investigator import investigate
from anthropic_double import recordings
from anthropic_double.server import DEFAULT_BASE_URL
from argus_core.models.alert import Alert
from argus_core.models.change_event import ChangeEvent
from argus_core.models.metrics import MetricBucket
from argus_core.replay import CallType, ReplayEntry
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.publishing import record_call
from orchestrator.repository import incidents, replay

from tests.framework.recordings import RECORDED_TOOL_USE_TURN

"""That an investigation's calls - to the model and to the read tier - actually
reach the replay log.

The unit tests either side of this one hold the halves: `argus_core` proves an
entry is built and written, `agent_investigator` proves a conversation is bound
to the right incident and recorder. Neither can prove they were joined - the
seam between them is a default argument, and a default nobody passes is exactly
the kind of wiring that is written once, never exercised, and discovered empty
on the day somebody wants to re-score a benchmark run.

So this drives a real investigation: the real adapter, the real recorder, a
real database. Only two things are stood in for, and neither is on the path
under test - the model answers from a committed recording, and retrieval
answers from memory, because what is being checked is that a call was written
down rather than what the model made of it.
"""

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

SOME_ONSET = "2026-08-29T22:15:00Z"


@pytest.fixture
def double() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=DEFAULT_BASE_URL, timeout=30.0) as control:
        control.post("/double-control/reset").raise_for_status()
        control.post(
            "/double-control/seed",
            json={"recording": RECORDED_TOOL_USE_TURN, "repeat": None},
        ).raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.mark.integration
def test_an_investigations_calls_reach_the_replay_log(
    double: httpx.Client,
) -> None:
    # One row at least, for this incident, naming a model call - and carrying
    # both payloads, because an entry that reached the table with an empty
    # request is a row that satisfies a count and replays nothing.
    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, _an_alert())
        the_replay_log_holds = _the_replay_log_holds

        Scenario() \
            .given(
                lambda: _the_double_is_answering(double)
            ) \
            .when(
                lambda: investigate(
                    alert=_an_alert(),
                    incident_id=incident_id,
                    fetch_metrics=_metrics_that_show_an_onset,
                    fetch_logs=_logs_that_say_little,
                    fetch_change_events=_no_changes,
                    recorder=record_call,
                )
            ) \
            .then(
                all_of(
                    the_replay_log_holds(conn, incident_id, at_least=1),
                    _the_log_holds_both_kinds_of_call(conn, incident_id),
                    _every_entry_carries_both_payloads(conn, incident_id),
                )
            )


@pytest.mark.integration
def test_an_investigation_that_records_nowhere_still_investigates(
    double: httpx.Client,
) -> None:
    # The default, and the promise that goes with it: recording is not part of
    # the work. An investigation asked to record nowhere must reach the same
    # conclusion, and must not leave rows behind under some other incident.
    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, _an_alert())

        Scenario() \
            .given(
                lambda: _the_double_is_answering(double)
            ) \
            .when(
                lambda: investigate(
                    alert=_an_alert(),
                    incident_id=incident_id,
                    fetch_metrics=_metrics_that_show_an_onset,
                    fetch_logs=_logs_that_say_little,
                    fetch_change_events=_no_changes,
                )
            ) \
            .then(
                all_of(
                    _findings_were_reached(),
                    _the_replay_log_holds(conn, incident_id, at_least=0, exactly=True),
                )
            )


def _an_alert() -> Alert:
    return Alert(service="io-shop", alert_name="HighErrorRate")


def _the_double_is_answering(double: httpx.Client) -> bool:
    """That the recording this test rests on is actually in the store.

    Checked rather than assumed: a missing recording makes the double answer
    with an error, the investigation escalate, and this test fail for a reason
    that has nothing to do with the replay log.
    """
    if RECORDED_TOOL_USE_TURN not in recordings.available():
        raise AssertionError(f"no recording named {RECORDED_TOOL_USE_TURN!r} to answer from")

    return True


def _metrics_that_show_an_onset(dont_care_window_start: str | None) -> list[MetricBucket]:
    """Enough of a departure that the investigation does not stop at retrieval.

    An incident with no metrics escalates before a model is ever called, which
    would make this test pass an empty replay log for the wrong reason.
    """
    return [
        MetricBucket(
            bucket_id="2026-08-29T22:10:00Z",
            error_rate=0.01,
            p50_ms=40,
            p95_ms=120,
            request_volume=200,
        ),
        MetricBucket(
            bucket_id=SOME_ONSET,
            error_rate=0.31,
            p50_ms=60,
            p95_ms=900,
            request_volume=200,
        ),
    ]


def _logs_that_say_little(dont_care_start: str, dont_care_end: str) -> list[str]:
    return ["2026-08-29T22:15:00Z ERROR io-shop: request failed"]


def _no_changes(dont_care_service: str,
                dont_care_start: str,
                dont_care_end: str) -> list[ChangeEvent]:
    return []


def _recorded_calls(conn: psycopg.Connection, incident_id: str) -> list[ReplayEntry]:
    return replay.get_by_incident(conn, incident_id)


def _the_replay_log_holds(conn: psycopg.Connection,
                          incident_id: str,
                          at_least: int,
                          exactly: bool = False) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        held = len(_recorded_calls(conn, incident_id))

        if exactly and held != at_least:
            raise AssertionError(f"Expected exactly [{at_least}] calls recorded, got [{held}].")

        if not exactly and held < at_least:
            raise AssertionError(
                f"Expected at least [{at_least}] calls recorded, got [{held}]."
            )

        return True

    return assertion


def _the_log_holds_both_kinds_of_call(conn: psycopg.Connection,
                                      incident_id: str) -> Assertion[object]:
    """Both, because either alone leaves a run unreplayable.

    The model calls without the retrievals say what was asked and not what the
    answers were about; the retrievals without the model calls say what was
    read and not what was made of it. Asserted as presence rather than as a
    count: how many turns a model takes is its own business, and pinning it
    here would make this test fail the day a recording is re-taken.
    """
    def assertion(_result: object) -> bool:
        kinds = {entry.call_type for entry in _recorded_calls(conn, incident_id)}
        missing = {CallType.LLM, CallType.MCP} - kinds

        if missing:
            raise AssertionError(f"Expected both kinds of call recorded, {missing} was not.")

        return True

    return assertion


def _every_entry_carries_both_payloads(conn: psycopg.Connection,
                                       incident_id: str) -> Assertion[object]:
    """That what was written down could stand in for the call.

    An entry with an empty request or response satisfies a row count and
    replays nothing, which is the failure this whole table exists to prevent.
    """
    def assertion(_result: object) -> bool:
        empty = [
            entry.id
            for entry in _recorded_calls(conn, incident_id)
            if not entry.request or not entry.response
        ]

        if empty:
            raise AssertionError(f"Expected every entry to carry both payloads, {empty} did not.")

        return True

    return assertion


def _findings_were_reached() -> Assertion[object]:
    def assertion(findings: object) -> bool:
        if findings is None:
            raise AssertionError("Expected the investigation to have reached findings.")

        return True

    return assertion
