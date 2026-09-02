from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

import psycopg
import pytest
from argus_core.models.alert import Alert
from argus_core.replay import CallType, ReplayEntry
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.repository import incidents, replay

"""Where a call Argus made out of its own process is written down (spec §11.1).

The subscriber's counterpart for the replay log: `argus_core.replay` says what
an entry is and how it is handed over, and this is the only thing that knows
it ends up in Postgres.

It writes here and touches nothing else, which is what leaves spec §7.1's
single-writer rule intact as this table arrives - the four domain tables keep
the one writer they had, the account has its own, and this has a third.

What is under test is the round trip and the order. Both matter more here than
in most tables: an entry exists to stand in for a call that will not be made
again, so a payload that came back reshaped is a call that cannot be replayed,
and two calls read back in the wrong order are a conversation that no longer
makes sense.
"""

DATABASE_URL = "postgresql://argus:argus@localhost:5432/argus"

SOME_MODEL = "claude-opus-5"


@pytest.mark.integration
def test_a_recorded_call_comes_back_with_both_payloads_whole() -> None:
    # The whole point of the table. Both sides cross the boundary as JSON, so
    # both are what can come back a string that merely looks like a mapping -
    # and an entry that lost either is an entry that replays nothing.
    some_request = {
        "transcript": [{"text": "what caused the error rate to climb at 22:15?"}],
        "tools": [{"name": "get_logs"}]
    }
    some_response = {
        "text": "checking what changed before it",
        "tool_calls": [{"id": "toolu_01ABC", "name": "get_logs", "arguments": {}}],
        "input_tokens": 22,
        "output_tokens": 308,
        "cache_read_tokens": 9479,
        "cache_write_tokens": 0
    }

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = _an_incident_created_for(conn, _an_alert())
        an_entry = _an_entry_for(incident_id, request=some_request, response=some_response)
        the_recorded_calls_are = partial(_the_recorded_calls_are, conn, incident_id)

        Scenario() \
            .when(
                lambda: replay.record(conn, an_entry)
            ) \
            .then(
                the_recorded_calls_are([an_entry])
            )


@pytest.mark.integration
def test_the_calls_of_an_incident_come_back_in_the_order_they_were_made() -> None:
    # By `seq` rather than by `at`, and the two are not interchangeable: a loop
    # takes several turns inside one second, and a conversation read back in
    # whichever order two identical timestamps happened to sort is not a
    # conversation.
    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = _an_incident_created_for(conn, _an_alert())
        the_first_call = _an_entry_for(incident_id, request={"turn": 1})
        the_second_call = _an_entry_for(incident_id, request={"turn": 2})
        a_call_was_recorded = partial(_a_call_was_recorded, conn)
        the_recorded_calls_are = partial(_the_recorded_calls_are, conn, incident_id)

        Scenario() \
            .given(
                a_call_was_recorded(the_first_call)
            ) \
            .when(
                lambda: replay.record(conn, the_second_call)
            ) \
            .then(
                the_recorded_calls_are([the_first_call, the_second_call])
            )


@pytest.mark.integration
def test_calls_made_for_another_incident_are_not_this_incidents() -> None:
    # A benchmark run drives many incidents through one database, and a metric
    # computed over a run that mixed two of them is wrong in a way no assertion
    # downstream would catch.
    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = _an_incident_created_for(conn, _an_alert())
        another_incident_id = _an_incident_created_for(conn, _an_alert())
        this_incidents_call = _an_entry_for(incident_id)
        a_call_was_recorded = partial(_a_call_was_recorded, conn)
        the_recorded_calls_are = partial(_the_recorded_calls_are, conn, incident_id)

        Scenario() \
            .given(
                a_call_was_recorded(_an_entry_for(another_incident_id))
            ) \
            .when(
                lambda: replay.record(conn, this_incidents_call)
            ) \
            .then(
                all_of(
                    the_recorded_calls_are([this_incidents_call])
                )
            )


@pytest.mark.integration
def test_an_incident_that_made_no_calls_reads_as_empty_rather_than_missing() -> None:
    # An incident escalated on retrieval alone never reaches a model, and that
    # is a real path. Nothing recorded is a fact about the run, not a lookup
    # that failed.
    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = _an_incident_created_for(conn, _an_alert())

        assert replay.get_by_incident(conn, incident_id) == []


@pytest.mark.integration
def test_what_an_incident_spent_is_every_count_its_model_calls_reported() -> None:
    # All four counts, not `input_tokens` and `output_tokens`. With caching on,
    # most of a prompt arrives as a cache read, and a total that ignored those
    # would report an investigation as a fraction of what it cost - and the
    # cheaper it was cached, the more wrong the figure.
    some_input_tokens = 22
    some_output_tokens = 308
    some_cache_read_tokens = 9_479
    some_cache_write_tokens = 1_204

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, Alert(service="io-shop", alert_name="HighErrorRate"))
        replay.record(conn, _a_model_call(incident_id,
                                          input_tokens=some_input_tokens,
                                          output_tokens=some_output_tokens,
                                          cache_read_tokens=some_cache_read_tokens,
                                          cache_write_tokens=some_cache_write_tokens))

        spent = replay.get_tokens_spent(conn, incident_id)

    assert spent == (some_input_tokens + some_output_tokens
                     + some_cache_read_tokens + some_cache_write_tokens)


@pytest.mark.integration
def test_what_an_incident_spent_counts_nothing_for_the_tools_it_called() -> None:
    # A retrieval is a call out of the process and costs no tokens. Counted
    # here it would inflate every incident by however many windows it read,
    # and most by more than the model.
    dont_care_tool = "get_log_lines"
    dont_care_request: dict[str, object] = {}
    dont_care_response: dict[str, object] = {"lines": []}
    dont_care_latency_ms = 12

    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, Alert(service="io-shop", alert_name="HighErrorRate"))
        replay.record(conn, ReplayEntry(
            incident_id=incident_id,
            call_type=CallType.MCP,
            target=dont_care_tool,
            request=dont_care_request,
            response=dont_care_response,
            latency_ms=dont_care_latency_ms,
        ))

        assert replay.get_tokens_spent(conn, incident_id) == 0


@pytest.mark.integration
def test_an_incident_that_called_no_model_spent_nothing_rather_than_nothing_known() -> None:
    # A real path: escalating on retrieval alone never reaches a model. Zero
    # is the measurement, and the postmortem is entitled to print it.
    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, Alert(service="io-shop", alert_name="HighErrorRate"))

        assert replay.get_tokens_spent(conn, incident_id) == 0


def _an_alert() -> Alert:
    return Alert(service="io-shop", alert_name="HighErrorRate")


def _an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    return incidents.create(conn, alert)


def _an_entry_for(incident_id: str,
                  request: dict[str, Any] | None = None,
                  response: dict[str, Any] | None = None) -> ReplayEntry:
    dont_care_latency_ms = 4820

    return ReplayEntry(
        incident_id=incident_id,
        call_type=CallType.LLM,
        target=SOME_MODEL,
        request=request if request is not None else {"dont": "care"},
        response=response if response is not None else {"dont": "care"},
        latency_ms=dont_care_latency_ms
    )


def _a_call_was_recorded(
    conn: psycopg.Connection, entry: ReplayEntry
) -> Callable[[], None]:
    def step() -> None:
        replay.record(conn, entry)

    return step


def _the_recorded_calls_are(conn: psycopg.Connection,
                            incident_id: str,
                            expected: list[ReplayEntry]) -> Assertion[Any]:
    """Every call recorded for this incident, in the order it was made.

    Compared as whole entries rather than field by field: what the table has to
    give back is the entry that went in, and an assertion that checked three
    fields would pass on a row that lost the other four.
    """
    def assertion(_result: Any) -> bool:
        stored = replay.get_by_incident(conn, incident_id)

        if stored != expected:
            raise AssertionError(f"Expected {expected!r}, got {stored!r}.")

        return True

    return assertion


def _a_model_call(incident_id: str,
                  input_tokens: int,
                  output_tokens: int,
                  cache_read_tokens: int,
                  cache_write_tokens: int) -> ReplayEntry:
    """One recorded model call, whose response is a turn as one is stored."""
    dont_care_request: dict[str, object] = {"transcript": []}
    dont_care_text = "kukibuki"
    dont_care_tool_calls: list[dict[str, Any]] = []
    dont_care_latency_ms = 980

    return ReplayEntry(
        incident_id=incident_id,
        call_type=CallType.LLM,
        target=SOME_MODEL,
        request=dont_care_request,
        response={
            "text": dont_care_text,
            "tool_calls": dont_care_tool_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_write_tokens
        },
        latency_ms=dont_care_latency_ms,
    )
