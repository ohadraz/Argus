from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_investigator.retrieval import fetch_logs
from agent_investigator.tools import LOGS_TOOL, Dispatcher
from argus_core.models.transcript import ToolResult
from argus_core.replay import CallType, Replay, ReplayEntry
from argus_testkit import Assertion, Kept, Scenario, all_of

from ..framework.builders.dispatcher import A_SERVICE, AN_ALERT_TIME, AN_ONSET, a_call_to

"""How an investigation's retrievals come to be written down.

The other half of the replay log. `test_recorded_reasoning.py` holds the model
calls; these are the calls to the read tier, and a log holding only the first
kind says what the model was asked and not what it was answering about - which
is most of why a run cannot be re-read without paying for it again.

Recorded here rather than in each channel, because the dispatcher is the one
place every call passes through: three channels each keeping their own receipt
would be three chances to forget, and a fourth channel added later would arrive
silent.

Only a call that was actually served is written down. A tool name that is not a
channel, a window that ends before it starts, a window already read - none of
those reached a server, so a row for them would be a receipt for a call nobody
made, and an eval counting retrievals would count Argus talking to itself.
"""

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"


@pytest.mark.unit
def test_a_retrieval_that_was_served_is_written_down() -> None:
    # Everything needed to stand in for the call: which channel answered, the
    # window it was asked about, and what came back. An entry missing the last
    # of those satisfies a count and replays nothing.
    some_line = "2026-08-29T22:15:00Z ERROR checkout: request failed"
    some_window_start = "2026-08-29T21:50:00Z"
    some_window_end = "2026-08-29T22:05:00Z"

    Scenario() \
        .given(
            recorded := _a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _a_dispatcher_recording_to(
                recorded, reads_logs=create_autospec(fetch_logs, return_value=[some_line])
            ).dispatch(
                a_call_to(LOGS_TOOL,
                          window_start=some_window_start,
                          window_end=some_window_end)
            )
        ) \
        .then(
            all_of(
                _the_entry_was_recorded_for(recorded, SOME_INCIDENT_ID),
                _the_entry_was_a_call_to(recorded, LOGS_TOOL),
                _the_entry_asked_about(recorded, some_window_start, some_window_end),
                _the_entry_carries(recorded, some_line)
            )
        )


@pytest.mark.unit
def test_a_call_nothing_could_serve_is_not_written_down() -> None:
    # Nothing left the process, so there is nothing to keep a receipt for. A row
    # here would make a model's typo look like a retrieval that happened, and
    # the count of what an investigation read is exactly what an eval reads this
    # table for.
    a_tool_that_is_not_offered = "delete_everything"

    Scenario() \
        .given(
            recorded := _a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _a_dispatcher_recording_to(recorded).dispatch(
                a_call_to(a_tool_that_is_not_offered)
            )
        ) \
        .then(
            _nothing_was_recorded(recorded)
        )


@pytest.mark.unit
def test_a_window_asked_for_twice_is_written_down_once() -> None:
    # The refusal is not a retrieval. The second call is answered from what the
    # dispatcher already knows, without reaching the read tier at all, and a
    # second row would report a read that never happened - against precisely the
    # model behaviour this refusal exists to stop.
    dont_care_window_start = "2026-08-29T21:50:00Z"
    dont_care_window_end = "2026-08-29T22:05:00Z"
    some_dispatcher = _a_dispatcher_recording_to(
        recorded := _a_recorder_that_keeps_what_it_is_given()
    )

    def the_same_window_again() -> ToolResult:
        return some_dispatcher.dispatch(
            a_call_to(LOGS_TOOL,
                      window_start=dont_care_window_start,
                      window_end=dont_care_window_end)
        )

    Scenario() \
        .given(
            the_same_window_again
        ) \
        .when(
            the_same_window_again
        ) \
        .then(
            _exactly_one_entry_was_recorded(recorded)
        )


def _a_recorder_that_keeps_what_it_is_given() -> Kept[ReplayEntry]:
    """A recorder that collects entries instead of storing them.

    Handed over as `recorded.take` rather than as the object itself: a
    `Scenario` calls anything callable it is given, and a recorder that ran
    while the test was being arranged would record nothing and report it
    faithfully.
    """
    return Kept()


def _a_dispatcher_recording_to(recorded: Kept[ReplayEntry],
                               reads_logs: Any = None) -> Dispatcher:
    """A dispatcher whose retrievals reach this test's recorder.

    Built here rather than through the shared builder because the recorder is
    what these tests are about; every other channel answers with nothing, so a
    test that meant to read logs cannot pass on somebody else's evidence.
    """
    return Dispatcher(
        service=A_SERVICE,
        onset=AN_ONSET,
        alert_time=AN_ALERT_TIME,
        replay=Replay(SOME_INCIDENT_ID, recorded.take),
        fetch_logs=reads_logs or create_autospec(fetch_logs, return_value=[])
    )


def _the_entry_was_recorded_for(recorded: Kept[ReplayEntry],
                                incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        entry = recorded.only()

        if entry.incident_id != incident_id:
            raise AssertionError(
                f"Expected the entry recorded for [{incident_id}], got [{entry.incident_id}]."
            )

        return True

    return assertion


def _the_entry_was_a_call_to(recorded: Kept[ReplayEntry], target: str) -> Assertion[Any]:
    """Which channel answered, and that it is filed as a tool call.

    The type as well as the target, because the two failures are different: a
    retrieval filed as a model call inflates what a run is thought to have spent
    on the model, where a wrong target loses which channel was read at all.
    """
    def assertion(_result: Any) -> bool:
        entry = recorded.only()

        if entry.call_type is not CallType.MCP:
            raise AssertionError(
                f"Expected a [{CallType.MCP}] entry, got [{entry.call_type}]."
            )

        if entry.target != target:
            raise AssertionError(f"Expected a call to [{target}], got [{entry.target}].")

        return True

    return assertion


def _the_entry_asked_about(recorded: Kept[ReplayEntry],
                           window_start: str,
                           window_end: str) -> Assertion[Any]:
    """The window that was actually read, not merely the arguments sent.

    They differ whenever a default was supplied or a clamp applied, and the one
    worth keeping is the window the read tier was given - an entry naming the
    other stands in for a call that was never made.
    """
    def assertion(_result: Any) -> bool:
        asked = recorded.only().request
        actual = (asked.get("window_start"), asked.get("window_end"))

        if actual != (window_start, window_end):
            raise AssertionError(
                f"Expected the entry to ask about [{window_start}] to [{window_end}], "
                f"got {actual}."
            )

        return True

    return assertion


def _the_entry_carries(recorded: Kept[ReplayEntry], said: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        answered = recorded.only().response

        if said not in str(answered):
            raise AssertionError(f"Expected the entry to carry [{said}], got {answered}.")

        return True

    return assertion


def _nothing_was_recorded(recorded: Kept[ReplayEntry]) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        if recorded.taken:
            raise AssertionError(f"Expected nothing recorded, got {recorded.taken}.")

        return True

    return assertion


def _exactly_one_entry_was_recorded(recorded: Kept[ReplayEntry]) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        if len(recorded.taken) != 1:
            raise AssertionError(
                f"Expected exactly one entry recorded, got {len(recorded.taken)}."
            )

        return True

    return assertion
