"""The write tier making a change only for the claim that holds the run.

A walk paused past its lease wakes holding a claim the run has moved past, and
its next change to the world would be a second walk acting on an incident
somebody else is walking. The database refuses that walk's writes; this is the
same refusal for its changes - asked of the run before the change is made, and
the run held still until it is done.

Driven over a real MCP session held in memory, because what a change is told by
is the request's `_meta`, and only a request carries one. The run itself is a
stand-in: whether a claim still holds it is the runs repository's to answer,
and is asked of a real database in that repository's own suite.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from argus_core import Fence
from argus_core.mcp_transport import (
    FENCE_META_KEY,
    LEFT_BEHIND_KNOWN_MARKER,
    RUN_LOST_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    an_unreachable_platform,
)
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent
from write_mcp_server.fencing import FencedFastMCP, HoldForAChange

SOME_FENCE = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
WHAT_THE_CHANGE_ANSWERS = ["changed"]


@pytest.mark.unit
def test_a_change_for_the_claim_holding_the_run_is_made() -> None:
    # And the run is asked about the claim the call named, which is the whole of
    # the check: a hold asked about any other claim answers for somebody else.
    made: list[str] = []
    asked: list[Fence] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_answering(True, asked))
        ) \
        .when(
            lambda: _asked(server, "make_a_change", _sent(SOME_FENCE))
        ) \
        .then(all_of(
            _answered_with(WHAT_THE_CHANGE_ANSWERS),
            _the_change_was_made(made, times=1),
            _the_run_was_asked_about(asked, [SOME_FENCE])
        ))


@pytest.mark.unit
def test_a_change_for_a_claim_the_run_moved_past_is_refused_as_a_lost_run_and_not_made() -> None:
    made: list[str] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_answering(False))
        ) \
        .when(
            lambda: _asked(server, "make_a_change", _sent(SOME_FENCE))
        ) \
        .then(all_of(
            _refused(as_a_lost_run=True),
            _the_change_was_made(made, times=0)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("meta", [None, {FENCE_META_KEY: "not-a-fence"}],
                         ids=["no-fence", "not-a-fence"])
def test_a_change_naming_no_run_is_refused_but_not_as_a_lost_run(
    meta: dict[str, Any] | None
) -> None:
    # A caller that forgot to say which claim it acts for is a bug rather than a
    # walk that lost its run, and a walk told its run was lost writes nothing
    # more - so a forgetful caller told that would end in silence. And it says
    # it left nothing, because the tool never ran.
    made: list[str] = []
    asked: list[Fence] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_answering(True, asked))
        ) \
        .when(
            lambda: _asked(server, "make_a_change", meta)
        ) \
        .then(all_of(
            _refused(as_a_lost_run=False),
            _refused_with(LEFT_BEHIND_KNOWN_MARKER),
            _the_change_was_made(made, times=0),
            _the_run_was_asked_about(asked, [])
        ))


@pytest.mark.unit
def test_a_change_whose_run_could_not_be_checked_is_refused_but_not_as_a_lost_run() -> None:
    # The run may be held for all anybody knows. Refused, because a change made
    # unchecked is the one this exists to stop; and not as a lost run, because
    # nothing said it was. It says it left nothing: the tool never ran.
    made: list[str] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_that_cannot_be_had())
        ) \
        .when(
            lambda: _asked(server, "make_a_change", _sent(SOME_FENCE))
        ) \
        .then(all_of(
            _refused(as_a_lost_run=False),
            _refused_with(LEFT_BEHIND_KNOWN_MARKER),
            _the_change_was_made(made, times=0)
        ))


@pytest.mark.unit
def test_the_run_is_held_for_as_long_as_the_change_is_being_made() -> None:
    # Checked and then let go, the run could be taken back between the check
    # and the change - and a change made for a lost claim is what was checked
    # against.
    made: list[str] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_recording_into(made))
        ) \
        .when(
            lambda: _asked(server, "make_a_change", _sent(SOME_FENCE))
        ) \
        .then(
            _happened_in_order(made, ["held", "changed", "let go"])
        )


@pytest.mark.unit
def test_a_change_that_failed_is_answered_with_its_own_failure_and_lets_the_run_go(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The walk tells one failure from another by its marker - a platform that
    # was not there is passed over, a lost run stops the walk - so the change's
    # own failure has to come back as itself. And the run is let go on the way
    # out, as after a change that was made.
    made: list[str] = []
    caplog.set_level(logging.WARNING)

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_recording_into(made))
        ) \
        .when(
            lambda: _asked(server, "make_a_change_the_platform_misses", _sent(SOME_FENCE))
        ) \
        .then(all_of(
            _refused_with(UNREACHABLE_PLATFORM_MARKER),
            _refused(as_a_lost_run=False),
            _happened_in_order(made, ["held", "let go"]),
            _nothing_was_logged_saying("the change was made and its run could not be let go",
                                       caplog)
        ))


@pytest.mark.unit
def test_a_change_made_is_answered_even_where_its_hold_could_not_be_let_go(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The world was changed. Answering with a failure would have the walk
    # record nothing to put back for a change that is there.
    made: list[str] = []
    caplog.set_level(logging.WARNING)

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_that_cannot_be_let_go())
        ) \
        .when(
            lambda: _asked(server, "make_a_change", _sent(SOME_FENCE))
        ) \
        .then(all_of(
            _answered_with(WHAT_THE_CHANGE_ANSWERS),
            _the_change_was_made(made, times=1),
            one_record_was_logged(caplog, "write_mcp_server.fencing", logging.WARNING,
                                  "the change was made and its run could not be let go",
                                  values={"tool": "make_a_change"})
        ))


@pytest.mark.unit
def test_a_change_refused_for_a_lost_run_is_said_inside_the_call_it_refused(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Said where every other failed call is, so the line carries the trace of
    # the walk that asked - the one thing that says which walk was stale.
    made: list[str] = []
    caplog.set_level(logging.WARNING)

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_answering(False))
        ) \
        .when(
            lambda: _asked(server, "make_a_change", _sent(SOME_FENCE))
        ) \
        .then(
            one_record_was_logged(caplog, "argus_core.mcp_transport", logging.WARNING,
                                  "tool call failed", values={"tool": "make_a_change"})
        )


@pytest.mark.unit
def test_a_read_is_answered_without_asking_after_any_run() -> None:
    # A read changes nothing a second walk could get wrong, and is asked by
    # whoever needs it, holding a run or not.
    made: list[str] = []
    asked: list[Fence] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_answering(True, asked))
        ) \
        .when(
            lambda: _asked(server, "read_something", None)
        ) \
        .then(all_of(
            _answered_with(["read"]),
            _the_run_was_asked_about(asked, [])
        ))


def _a_tier_making(made: list[str], hold: HoldForAChange) -> FencedFastMCP:
    """A tier with a change, which says it was made into `made`, a change whose
    platform is not there, and a read."""
    server = FencedFastMCP("some-tier", hold_for_a_change=hold)

    @server.change()
    def make_a_change() -> list[str]:
        made.append("changed")

        return WHAT_THE_CHANGE_ANSWERS

    @server.change()
    def make_a_change_the_platform_misses() -> list[str]:
        raise RuntimeError(an_unreachable_platform("some-platform", "did not answer"))

    @server.tool()
    def read_something() -> list[str]:
        return ["read"]

    return server


def _a_hold_answering(still_held: bool, asked: list[Fence] | None = None) -> HoldForAChange:
    """A run held or not by whichever claim asks - each asked about kept in
    `asked`, where it is given."""
    @contextmanager
    def hold(fence: Fence) -> Iterator[bool]:
        if asked is not None:
            asked.append(fence)

        yield still_held

    return hold


def _a_hold_recording_into(made: list[str]) -> HoldForAChange:
    @contextmanager
    def hold(dont_care_fence: Fence) -> Iterator[bool]:
        made.append("held")

        try:
            yield True
        finally:
            made.append("let go")

    return hold


def _a_hold_that_cannot_be_had() -> HoldForAChange:
    @contextmanager
    def hold(dont_care_fence: Fence) -> Iterator[bool]:
        raise RuntimeError("the database is not answering")

    return hold


def _a_hold_that_cannot_be_let_go() -> HoldForAChange:
    @contextmanager
    def hold(dont_care_fence: Fence) -> Iterator[bool]:
        yield True

        raise RuntimeError("the database went away before the commit")

    return hold


def _sent(held: Fence) -> dict[str, Any]:
    return {FENCE_META_KEY: held.spoken()}


def _asked(server: FencedFastMCP, tool: str, meta: dict[str, Any] | None) -> CallToolResult:
    async def over_a_session() -> CallToolResult:
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool(tool, {}, meta=meta)

    return asyncio.run(over_a_session())


def _the_words_of(result: CallToolResult) -> str:
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


def _answered_with(expected: list[str]) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        structured = result.structuredContent or {}

        if result.isError or structured.get("result") != expected:
            raise AssertionError(
                f"Expected the call answered with {expected}, got "
                f"[{_the_words_of(result)}] (an error: {result.isError})."
            )

        return True

    return assertion


def _refused(as_a_lost_run: bool) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        said = _the_words_of(result)

        if not result.isError or (RUN_LOST_MARKER in said) is not as_a_lost_run:
            raise AssertionError(
                f"Expected the call refused {"as" if as_a_lost_run else "but not as"} a "
                f"lost run, got [{said}] (an error: {result.isError})."
            )

        return True

    return assertion


def _refused_with(marker: str) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        said = _the_words_of(result)

        if not result.isError or marker not in said:
            raise AssertionError(
                f"Expected the call refused with [{marker}], got [{said}] (an error: "
                f"{result.isError})."
            )

        return True

    return assertion


def _the_run_was_asked_about(asked: list[Fence], expected: list[Fence]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if asked != expected:
            raise AssertionError(
                f"Expected the run asked about {expected}, and it was asked about {asked}."
            )

        return True

    return assertion


def _nothing_was_logged_saying(message: str,
                               caplog: pytest.LogCaptureFixture) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        said = [record for record in caplog.records if record.getMessage() == message]

        if said:
            raise AssertionError(
                f"Expected nothing logged saying [{message}], and it was said "
                f"{len(said)} time(s)."
            )

        return True

    return assertion


def _the_change_was_made(made: list[str], times: int) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if made.count("changed") != times:
            raise AssertionError(
                f"Expected the change made {times} time(s), and it was made "
                f"{made.count("changed")}."
            )

        return True

    return assertion


def _happened_in_order(made: list[str], expected: list[str]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if made != expected:
            raise AssertionError(f"Expected {expected} in that order, got {made}.")

        return True

    return assertion
