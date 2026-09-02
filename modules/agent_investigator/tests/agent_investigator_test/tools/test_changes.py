from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock, create_autospec

import pytest
from agent_investigator.retrieval import fetch_change_events
from agent_investigator.tools import CHANGES_TOOL
from argus_core.config import get_settings
from argus_core.models.transcript import ToolResult
from argus_core.timestamps import parse_iso, to_iso
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting

from ..framework.builders.dispatcher import A_SERVICE, AN_ONSET, a_call_to, a_dispatcher

"""The change channel: what changed, over a window the logs could not afford.

The channel most likely to produce a cause and most likely to produce a wrong
one, since a change is the only thing in the evidence shaped like an actor.
Hence a default window that stops at the onset, and hence the one failure in
this package that is not the model's to recover from.
"""


@pytest.mark.unit
def test_a_change_call_naming_no_window_ends_at_the_onset() -> None:
    # A change made after the incident began did not begin it, so the default
    # window stops there. Offering later changes invites attribution by mere
    # proximity, which is the one mistake this channel is most likely to
    # produce.
    some_fetch_changes = create_autospec(fetch_change_events, return_value=[])
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
def test_a_change_source_that_cannot_be_reached_fails_the_investigation() -> None:
    # The one retrieval failure that is not the model's to recover from.
    # "Nothing changed" is a conclusion something will act on, so a source
    # that could not be read must not arrive looking like a source that was
    # read and found empty.
    some_fetch_changes = create_autospec(
        fetch_change_events, side_effect=RuntimeError("the change source is down")
    )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_changes=some_fetch_changes)
        ) \
        .when(
            attempting(lambda: some_dispatcher.dispatch(a_call_to(CHANGES_TOOL)))
        ) \
        .then(
            an_error_was_raised(RuntimeError)
        )


def _the_changes_read_were(reader: Mock,
                           window_start: str,
                           window_end: str) -> Assertion[ToolResult]:
    """The window the change channel was actually asked for, and for whom."""
    def assertion(dont_care_result: ToolResult) -> bool:
        reader.assert_called_once_with(A_SERVICE, window_start, window_end)

        return True

    return assertion
