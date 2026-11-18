"""The mark a platform write is made under, read off the call that asked for it.

The action id is the walk's, and arrives in the call's `_meta` beside the fence;
the moment is the tier's own, because the tier is what writes. A call that names
no action has no mark to give, and says so rather than having one made up for
it - a write marked with an action nobody took is worse than one left unmarked.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting, the_answer_was
from core import Fence
from core.mcp_transport import ACTION_META_KEY, FENCE_META_KEY
from deployment_platform import Mark
from write_mcp_server.marking import the_mark_in

SOME_FENCE = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
SOME_ACTION_ID = "6f1c1d2e-0000-4000-8000-0000000000a1"
SOME_MOMENT = datetime(2026, 11, 18, 13, 5, tzinfo=UTC)


@pytest.mark.unit
def test_the_mark_names_the_action_the_call_named_at_the_moment_it_is_written() -> None:
    Scenario() \
        .given(
            meta := {FENCE_META_KEY: SOME_FENCE.spoken(), ACTION_META_KEY: SOME_ACTION_ID}
        ) \
        .when(
            lambda: the_mark_in(meta, now=lambda: SOME_MOMENT)
        ) \
        .then(
            the_answer_was(Mark(action_id=SOME_ACTION_ID, written_at=SOME_MOMENT))
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "meta",
    [None, {FENCE_META_KEY: SOME_FENCE.spoken()}, {ACTION_META_KEY: 42}],
    ids=["no-meta", "no-action", "not-an-action"]
)
def test_a_call_naming_no_action_has_no_mark(meta: dict[str, Any] | None) -> None:
    Scenario() \
        .given(
            meta
        ) \
        .when(
            attempting(lambda: the_mark_in(meta, now=lambda: SOME_MOMENT))
        ) \
        .then(
            an_error_was_raised(ValueError)
        )


@pytest.mark.unit
def test_the_moment_a_mark_is_written_at_is_said_in_utc_by_default() -> None:
    # The tier's own clock, in the zone the platform's own timestamps are in -
    # so the mark reads beside them without anybody converting either.
    Scenario() \
        .given(
            meta := {FENCE_META_KEY: SOME_FENCE.spoken(), ACTION_META_KEY: SOME_ACTION_ID}
        ) \
        .when(
            lambda: the_mark_in(meta)
        ) \
        .then(
            _written_at_in_utc()
        )


def _written_at_in_utc() -> Assertion[Mark]:
    def assertion(mark: Mark) -> bool:
        offset = mark.written_at.utcoffset()

        if offset != timedelta(0):
            raise AssertionError(
                f"Expected the mark written at a moment in UTC, got [{mark.written_at}] "
                f"(offset [{offset}])."
            )

        return True

    return assertion
