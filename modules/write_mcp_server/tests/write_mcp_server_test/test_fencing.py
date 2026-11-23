"""The write tier making a change only for the claim that holds the run.

A walk paused past its lease wakes holding a claim the run has moved past, and
its next change to the world would be a second walk acting on an incident
somebody else is walking. The database refuses that walk's writes; this is the
same refusal for its changes - asked of the run before the change is made, and
the run held still until it is done.

Driven over a real MCP session held in memory, because what a change is told by
is the request's `_meta`, and only a request carries one. The run itself is a
stand-in: whether a claim still holds it is the runs repository's to answer,
and is asked of a real database in that repository's own suite. So is the
check the holds are opened behind, whether the database has its schema: asked
of a real one in `postgres`' suite.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Final

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    attempting,
    one_record_was_logged,
    the_same_error_reached_the_caller,
)
from core import DatabaseSettings, Fence
from incident_record.repository import runs
from mcp.client import Client
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, InputRequiredResult, RequestParamsMeta, TextContent
from mcp_transport import (
    ACTION_META_KEY,
    FENCE_META_KEY,
    LEFT_BEHIND_KNOWN_MARKER,
    RUN_LOST_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    an_unreachable_platform,
)
from pydantic import TypeAdapter
from write_mcp_server.fencing import FencedMCPServer, HoldForAChange, holds_in_the_database

from write_mcp_server_test.framework.marks import marked_are

SOME_FENCE = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
SOME_DATABASE = DatabaseSettings(database_url="postgresql://some-database.invalid/argus")
SOME_ACTION_ID = "6f1c1d2e-0000-4000-8000-0000000000a1"
WHAT_THE_CHANGE_ANSWERS = ["changed"]
DONT_CARE_WHY = "another change for the run is still being made"
# Where a tier built here would be served, which nothing here does.
DONT_CARE_HOST = "127.0.0.1"
DONT_CARE_PORT = 8199
# How long a change held open waits for the call after it to arrive before it
# goes on without it: a guard against a hang, never waited out by a case that
# passes - the second call arrives in milliseconds.
LONG_PAST_ANY_ARRIVAL_SECONDS = 30.0

# How the SDK's client is told to open a session by the `initialize` handshake,
# as the tier's own client opens one - its default speaks to a server in the
# same process without one.
LEGACY_HANDSHAKE: Final = "legacy"
# A call's `_meta` as the SDK types it, built from the map a case writes, as the
# transport builds it: validated rather than cast.
_AS_REQUEST_META: Final = TypeAdapter(RequestParamsMeta)


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
def test_a_change_while_another_for_its_run_is_in_flight_is_refused_but_not_as_leaving_nothing(
) -> None:
    # The claim still holds the run, so not a lost run: the walk goes on. And
    # not said to have left nothing, though this tool never ran - the change
    # still in flight may have landed, and a walk told nothing was left would
    # record nothing to put back for it.
    made: list[str] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_with_a_change_in_flight())
        ) \
        .when(
            lambda: _asked(server, "make_a_change", _sent(SOME_FENCE))
        ) \
        .then(all_of(
            _refused(as_a_lost_run=False),
            _not_refused_with(LEFT_BEHIND_KNOWN_MARKER),
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
def test_a_change_asked_while_another_is_being_made_waits_for_the_run_to_be_let_go() -> None:
    # What the client does when a change's answer is lost: it asks again over a
    # new session, and the first asking may still be being made. The second
    # waits its turn - the whole of the first, its hold and its tool - and is
    # then made for a run that is free, where it finds its own mark. Let into
    # its hold while the first still held the run, it would be refused as a
    # change in flight, and the walk would record as unknown a change that was
    # made.
    made: list[str] = []

    Scenario() \
        .given(
            server := _a_tier_answering_once_both_are_asked(
                made, _a_hold_kept_for_one_change_at_a_time(made)
            )
        ) \
        .when(
            lambda: _both_asked(server, "make_a_change_once_both_are_asked", _sent(SOME_FENCE))
        ) \
        .then(all_of(
            _every_call_answered_with(WHAT_THE_CHANGE_ANSWERS, times=2),
            _happened_in_order(made, ["held", "changed", "let go"] * 2)
        ))


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
            one_record_was_logged(caplog, "mcp_transport.transport", logging.WARNING,
                                  "tool call failed", values={"tool": "make_a_change"})
        )


@pytest.mark.unit
def test_a_marked_change_naming_its_action_is_made() -> None:
    made: list[str] = []
    asked: list[Fence] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_answering(True, asked))
        ) \
        .when(
            lambda: _asked(server, "make_a_marked_change",
                           _sent(SOME_FENCE, acting_for=SOME_ACTION_ID))
        ) \
        .then(all_of(
            _answered_with(WHAT_THE_CHANGE_ANSWERS),
            _the_change_was_made(made, times=1),
            _the_run_was_asked_about(asked, [SOME_FENCE])
        ))


@pytest.mark.unit
@pytest.mark.parametrize("action", [None, 42], ids=["no-action", "not-an-action"])
def test_a_marked_change_naming_no_action_is_refused_before_the_run_is_asked_after(
    action: object
) -> None:
    # Made unmarked, it would be a write on the platform nobody could tell from a
    # person's - so it is not made. A caller that forgot to say which action it
    # is taking is a bug rather than a lost run, and it says it left nothing,
    # because the tool never ran. Refused before the hold is asked for, because
    # the hold is a connection and a run kept still for a change never made.
    made: list[str] = []
    asked: list[Fence] = []
    meta = _sent(SOME_FENCE) if action is None else {
        **_sent(SOME_FENCE), ACTION_META_KEY: action
    }

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_answering(True, asked))
        ) \
        .when(
            lambda: _asked(server, "make_a_marked_change", meta)
        ) \
        .then(all_of(
            _refused(as_a_lost_run=False),
            _refused_with(LEFT_BEHIND_KNOWN_MARKER),
            _the_change_was_made(made, times=0),
            _the_run_was_asked_about(asked, [])
        ))


@pytest.mark.unit
def test_an_unmarked_change_naming_no_action_is_made() -> None:
    # A branch, a pull request, a flag: changes whose own record says whose they
    # were, and which are not refused for naming no action.
    made: list[str] = []

    Scenario() \
        .given(
            server := _a_tier_making(made, _a_hold_answering(True))
        ) \
        .when(
            lambda: _asked(server, "make_a_change", _sent(SOME_FENCE))
        ) \
        .then(all_of(
            _answered_with(WHAT_THE_CHANGE_ANSWERS),
            _the_change_was_made(made, times=1)
        ))


@pytest.mark.unit
def test_only_the_changes_registered_as_marked_are_marked() -> None:
    Scenario() \
        .given(
            server := _a_tier_making([], _a_hold_answering(True))
        ) \
        .when(
            lambda: server.marked
        ) \
        .then(
            marked_are({"make_a_marked_change"})
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


@pytest.mark.unit
def test_the_holds_are_not_opened_on_a_database_that_is_refused() -> None:
    # Opened as the tier starts, so a database with no schema stops the tier
    # before it serves a call - rather than at its first change, which is a
    # change asked for in the middle of an incident.
    some_refusal = RuntimeError("dont care")

    Scenario() \
        .when(
            attempting(lambda: _entered(holds_in_the_database(
                SOME_DATABASE, required=_refusing_with(some_refusal)
            )))
        ) \
        .then(
            the_same_error_reached_the_caller(some_refusal)
        )


@pytest.mark.unit
def test_the_database_asked_about_is_the_one_the_holds_are_opened_on() -> None:
    # The check is worth nothing if it can answer about a different database
    # than the one each change is held on.
    asked_about: list[DatabaseSettings] = []

    Scenario() \
        .when(
            lambda: _entered(holds_in_the_database(SOME_DATABASE, required=asked_about.append))
        ) \
        .then(
            _the_database_was_asked_about(asked_about, [SOME_DATABASE])
        )


def _entered(holds: AbstractContextManager[HoldForAChange]) -> None:
    """The holds opened and closed again, no change made."""
    with holds:
        pass


def _refusing_with(refusal: Exception) -> Callable[[DatabaseSettings], None]:
    """A check that refuses every database with `refusal`."""
    def required(dont_care_settings: DatabaseSettings) -> None:
        raise refusal

    return required


def _the_database_was_asked_about(asked_about: list[DatabaseSettings],
                                  expected: list[DatabaseSettings]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if asked_about != expected:
            raise AssertionError(
                f"Expected the schema asked after on {expected}, and it was asked after on "
                f"{asked_about}."
            )

        return True

    return assertion


def _a_tier_making(made: list[str], hold: HoldForAChange) -> FencedMCPServer:
    """A tier with a change, which says it was made into `made`, the same change
    marked, a change whose platform is not there, and a read."""
    server = FencedMCPServer("some-tier", hold_for_a_change=hold,
                             host=DONT_CARE_HOST, port=DONT_CARE_PORT)

    @server.change()
    def make_a_change() -> list[str]:
        made.append("changed")

        return WHAT_THE_CHANGE_ANSWERS

    @server.change(marked=True)
    def make_a_marked_change() -> list[str]:
        made.append("changed")

        return WHAT_THE_CHANGE_ANSWERS

    @server.change()
    def make_a_change_the_platform_misses() -> list[str]:
        raise RuntimeError(an_unreachable_platform("some-platform", "did not answer"))

    @server.tool()
    def read_something() -> list[str]:
        return ["read"]

    return server


class _CountingArrivals(FencedMCPServer):
    """A tier that counts each call as it arrives - before it waits its turn -
    and says when a second has."""

    def __init__(self, hold: HoldForAChange) -> None:
        super().__init__("some-tier", hold_for_a_change=hold,
                         host=DONT_CARE_HOST, port=DONT_CARE_PORT)
        self.a_second_arrived = threading.Event()
        self._arrived = 0

    async def call_tool(self,
                        name: str,
                        arguments: dict[str, Any],
                        context: Context[Any, Any] | None = None
                        ) -> CallToolResult | InputRequiredResult:
        self._arrived += 1

        if self._arrived == 2:
            self.a_second_arrived.set()

        return await super().call_tool(name, arguments, context)


def _a_tier_answering_once_both_are_asked(made: list[str],
                                          hold: HoldForAChange) -> FencedMCPServer:
    """A tier with a change that, once made, is held open until a second call
    has arrived - and says it was made into `made`."""
    server = _CountingArrivals(hold)

    @server.change()
    def make_a_change_once_both_are_asked() -> list[str]:
        server.a_second_arrived.wait(LONG_PAST_ANY_ARRIVAL_SECONDS)
        made.append("changed")

        return WHAT_THE_CHANGE_ANSWERS

    return server


def _a_hold_kept_for_one_change_at_a_time(made: list[str]) -> HoldForAChange:
    """A run held for one change at a time, as the database holds it: asked
    for while another change holds it, it is refused as a change in flight."""
    holding = False

    @contextmanager
    def hold(dont_care_fence: Fence) -> Generator[bool]:
        nonlocal holding

        if holding:
            raise runs.ChangeInFlight(DONT_CARE_WHY)

        holding = True
        made.append("held")

        try:
            yield True
        finally:
            holding = False
            made.append("let go")

    return hold


def _a_hold_answering(still_held: bool, asked: list[Fence] | None = None) -> HoldForAChange:
    """A run held or not by whichever claim asks - each asked about kept in
    `asked`, where it is given."""
    @contextmanager
    def hold(fence: Fence) -> Generator[bool]:
        if asked is not None:
            asked.append(fence)

        yield still_held

    return hold


def _a_hold_recording_into(made: list[str]) -> HoldForAChange:
    @contextmanager
    def hold(dont_care_fence: Fence) -> Generator[bool]:
        made.append("held")

        try:
            yield True
        finally:
            made.append("let go")

    return hold


def _a_hold_that_cannot_be_had() -> HoldForAChange:
    @contextmanager
    def hold(dont_care_fence: Fence) -> Generator[bool]:
        raise RuntimeError("the database is not answering")

    return hold


def _a_hold_with_a_change_in_flight() -> HoldForAChange:
    """A run already held for another change, which this one cannot have."""
    @contextmanager
    def hold(dont_care_fence: Fence) -> Generator[bool]:
        raise runs.ChangeInFlight(DONT_CARE_WHY)

    return hold


def _a_hold_that_cannot_be_let_go() -> HoldForAChange:
    @contextmanager
    def hold(dont_care_fence: Fence) -> Generator[bool]:
        yield True

        raise RuntimeError("the database went away before the commit")

    return hold


def _sent(held: Fence, acting_for: str | None = None) -> dict[str, Any]:
    """The `_meta` a walk's call carries: the claim it is made under, and the
    action it is taken for where it names one."""
    sent: dict[str, Any] = {FENCE_META_KEY: held.spoken()}

    if acting_for is not None:
        sent[ACTION_META_KEY] = acting_for

    return sent


def _asked(server: FencedMCPServer, tool: str, meta: dict[str, Any] | None) -> CallToolResult:
    """One call over a real MCP session held in memory, opened by the handshake
    the tier's own client opens one with, carrying `meta`."""
    async def over_a_session() -> CallToolResult:
        async with Client(server, mode=LEGACY_HANDSHAKE) as session:
            return await _sent_over(session, tool, meta)

    return asyncio.run(over_a_session())


def _both_asked(server: FencedMCPServer,
                tool: str,
                meta: dict[str, Any]) -> list[CallToolResult]:
    """`tool` asked twice at once over one session, each call carrying `meta` -
    the second sent while the first is still being answered."""
    async def over_a_session() -> list[CallToolResult]:
        async with Client(server, mode=LEGACY_HANDSHAKE) as session:
            return list(await asyncio.gather(_sent_over(session, tool, meta),
                                             _sent_over(session, tool, meta)))

    return asyncio.run(over_a_session())


async def _sent_over(session: Client,
                     tool: str,
                     meta: dict[str, Any] | None) -> CallToolResult:
    return await session.call_tool(
        tool, {}, meta=_AS_REQUEST_META.validate_python(meta) if meta is not None else None
    )


def _the_words_of(result: CallToolResult) -> str:
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


def _answered_with(expected: list[str]) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        structured = result.structured_content or {}

        if result.is_error or structured.get("result") != expected:
            raise AssertionError(
                f"Expected the call answered with {expected}, got "
                f"[{_the_words_of(result)}] (an error: {result.is_error})."
            )

        return True

    return assertion


def _every_call_answered_with(expected: list[str],
                              times: int) -> Assertion[list[CallToolResult]]:
    def assertion(results: list[CallToolResult]) -> bool:
        said = [(result.is_error, (result.structured_content or {}).get("result"))
                for result in results]

        if said != [(False, expected)] * times:
            raise AssertionError(
                f"Expected {times} calls each answered with {expected}, and they said "
                f"(an error, the answer) {said}: {[_the_words_of(each) for each in results]}."
            )

        return True

    return assertion


def _refused(as_a_lost_run: bool) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        said = _the_words_of(result)

        if not result.is_error or (RUN_LOST_MARKER in said) is not as_a_lost_run:
            raise AssertionError(
                f"Expected the call refused {"as" if as_a_lost_run else "but not as"} a "
                f"lost run, got [{said}] (an error: {result.is_error})."
            )

        return True

    return assertion


def _refused_with(marker: str) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        said = _the_words_of(result)

        if not result.is_error or marker not in said:
            raise AssertionError(
                f"Expected the call refused with [{marker}], got [{said}] (an error: "
                f"{result.is_error})."
            )

        return True

    return assertion


def _not_refused_with(marker: str) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        said = _the_words_of(result)

        if marker in said:
            raise AssertionError(
                f"Expected the call answered without [{marker}], got [{said}] (an error: "
                f"{result.is_error})."
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
