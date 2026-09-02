from __future__ import annotations

from unittest.mock import Mock, create_autospec

import pytest
from agent_investigator.retrieval import fetch_logs
from agent_investigator.tools import LOGS_TOOL, METRICS_TOOL
from argus_core.models.transcript import ToolResult
from argus_testkit import Assertion, Scenario, all_of

from ..framework.assertions.tool_results import the_result_answers, the_result_failed
from ..framework.builders.dispatcher import a_call_to, a_dispatcher

"""What is true of a call whichever channel ends up serving it.

Three things, and none of them is about evidence: a result answers exactly the
call it was made for, a call nothing can serve still comes back, and a window
that was already read is not read twice. The first two failing leaves the
model waiting on a reply it will never recognise, which is a silence rather
than an error; the third is what keeps a model that has run out of ideas from
spending the whole budget re-reading what it has.
"""


@pytest.mark.unit
def test_a_result_answers_the_call_it_was_made_for() -> None:
    # Without the id the result answers nothing. True of every result, which
    # is why it is tested once rather than in each channel's own file.
    some_call_id = "toolu_01ABC"

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher()
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(METRICS_TOOL, call_id=some_call_id))
        ) \
        .then(
            the_result_answers(some_call_id)
        )


@pytest.mark.unit
def test_a_tool_the_investigator_does_not_offer_comes_back_as_something_to_fix() -> None:
    # A model that invented a tool name has misunderstood something, and the
    # correction is cheap - but only if it is told. Silently ignoring the call
    # would leave it waiting on a result that never comes.
    a_tool_that_is_not_offered = "delete_everything"

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher()
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(a_tool_that_is_not_offered))
        ) \
        .then(
            the_result_failed()
        )


@pytest.mark.unit
def test_a_window_that_was_already_read_is_not_read_again() -> None:
    # Serving it a second time would spend a retrieval and a turn's worth of
    # tokens to hand the model back what is already in front of it. Said out
    # loud rather than answered with the same lines, because the useful reply
    # to "read this again" is that there is nothing further there - which is a
    # reason to widen the window or to answer.
    some_window_start = "2026-08-29T21:50:00Z"
    some_window_end = "2026-08-29T22:05:00Z"
    some_fetch_logs = create_autospec(fetch_logs, return_value=[])

    def the_same_window_again() -> ToolResult:
        return some_dispatcher.dispatch(
            a_call_to(LOGS_TOOL,
                      window_start=some_window_start,
                      window_end=some_window_end)
        )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_logs=some_fetch_logs),
            the_same_window_again
        ) \
        .when(
            the_same_window_again
        ) \
        .then(
            all_of(
                the_result_failed(),
                _the_channel_was_read_once(some_fetch_logs),
                _the_result_says_it_was_already_read()
            )
        )


def _the_channel_was_read_once(reader: Mock) -> Assertion[ToolResult]:
    """The second ask cost nothing: the first read is the only one."""
    def assertion(dont_care_result: ToolResult) -> bool:
        if reader.call_count != 1:
            raise AssertionError(
                f"Expected the window to have been read once, and it was read "
                f"{reader.call_count} time(s)."
            )

        return True

    return assertion


def _the_result_says_it_was_already_read() -> Assertion[ToolResult]:
    """A refusal the model cannot act on is a turn wasted."""
    def assertion(result: ToolResult) -> bool:
        if "already read" not in result.content.lower():
            raise AssertionError(
                f"Expected the result to say the window was already read, "
                f"got [{result.content}]."
            )

        return True

    return assertion
