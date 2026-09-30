"""The change channel: what changed, over a window the logs could not afford.

The channel most likely to produce a cause and most likely to produce a wrong
one, since a change is the only thing in the evidence shaped like an actor.
Hence a default window that stops at the onset, and hence a failure that has to
say which silence it is rather than coming back as an empty history.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock, call, create_autospec

import pytest
from agent_investigator.retrieval import ChangeFetcher
from agent_investigator.tools import CHANGES_TOOL
from argus_core import get_settings, parse_iso, to_iso
from argus_core.models import ToolResult
from argus_testkit import Assertion, Scenario, all_of

from agent_investigator_test.framework.assertions.tool_results import the_result_failed
from agent_investigator_test.framework.builders.dispatcher import (
    A_SERVICE,
    AN_ONSET,
    a_call_to,
    a_dispatcher,
)


@pytest.mark.unit
def test_a_change_call_naming_no_window_ends_at_the_onset() -> None:
    # A change made after the incident began did not begin it, so the default
    # window stops there. Offering later changes invites attribution by mere
    # proximity, which is the one mistake this channel is most likely to
    # produce.
    some_fetch_changes = create_autospec(ChangeFetcher, instance=True, return_value=[])
    the_default_start = to_iso(
        parse_iso(AN_ONSET)
        - timedelta(minutes=get_settings().change_lookback_minutes)
    )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_changes=some_fetch_changes)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(CHANGES_TOOL))
        ) \
        .then(
            _the_changes_read_were(some_fetch_changes, the_default_start, AN_ONSET)
        )


@pytest.mark.unit
def test_a_change_source_that_cannot_be_reached_is_reported_rather_than_raised() -> None:
    # "Nothing changed" is a conclusion something will act on, so a source that
    # could not be read must not arrive looking like a source that was read and
    # found empty. That is what `get_change_events` raises for, and for a while
    # it was also why this channel let the exception through to the loop - which
    # is a different claim and a worse one: the investigation ended, every minute
    # already read was paid for and thrown away, and nothing on the page said
    # why.
    #
    # A failed result keeps the whole of the distinction the raising exists for.
    # It comes back marked as something to recover from, and says in as many
    # words that the window could not be read and that this is not the same as
    # there having been nothing in it - so nothing downstream can take it for a
    # history. What it no longer does is spend the rest of the investigation on
    # the difference.
    some_fetch_changes = create_autospec(
        ChangeFetcher, instance=True, side_effect=RuntimeError("the change source is down")
    )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_changes=some_fetch_changes)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(CHANGES_TOOL))
        ) \
        .then(all_of(
            the_result_failed(),
            _the_result_says_the_window_could_not_be_read()
        ))


def _the_changes_read_were(reader: Mock,
                           window_start: str,
                           window_end: str) -> Assertion[ToolResult]:
    """The window the change channel was actually asked for, and for whom.

    Compared against `call_args` rather than through `assert_called_once_with`,
    which does not survive a spec built from a `Protocol`: `self` is left on the
    signature, so every comparison fails while printing identically.
    """
    def assertion(dont_care_result: ToolResult) -> bool:
        if reader.call_count != 1 or reader.call_args != call(
            A_SERVICE, window_start, window_end
        ):
            raise AssertionError(
                f"Expected the changes to be read once for [{A_SERVICE}] over "
                f"[{window_start}..{window_end}], and they were read "
                f"{reader.call_count} time(s) as {reader.call_args}."
            )

        return True

    return assertion


def _the_result_says_the_window_could_not_be_read() -> Assertion[ToolResult]:
    """Says which silence this is, in the text the model actually reads.

    The whole of what raising protected. Failed alone leaves a model free to read
    "no changes" into it, and a window nobody could ask about must never stand in
    for a window with nothing in it.
    """
    def assertion(result: ToolResult) -> bool:
        if "could not be read" not in result.content:
            raise AssertionError(
                f"Expected the result to say the window could not be read, so "
                f"that nothing takes it for a window with nothing in it, got "
                f"[{result.content}]."
            )

        return True

    return assertion
