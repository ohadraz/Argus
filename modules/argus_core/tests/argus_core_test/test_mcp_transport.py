"""What a held MCP session promises, and what it must not get wrong.

The transport stopped being a function that opens a connection and became an
object that keeps one, which buys a session per process instead of a session per
tool call and costs two properties a fresh connection had for nothing: that a
second call works at all, and that a connection lost between calls is somebody
else's problem. Both are asserted here, against a real MCP server this suite can
take away and put back.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from queue import Empty
from typing import NamedTuple

import pytest
from argus_core.mcp_transport import McpClient, McpToolError, McpUnreachable
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from pydantic import TypeAdapter

from argus_core_test.framework.transport_double import RunningDouble, a_running_double

# Long enough that the call has certainly reached the server, which takes
# milliseconds - and short enough that the test does not sit here.
LONG_ENOUGH_TO_BE_IN_FLIGHT = 0.5
# What the dawdling call would have taken had closing not ended it, and how long
# this waits for it to come back one way or the other.
LONGER_THAN_THE_TEST_WILL_WAIT = 30.0
LONG_ENOUGH_TO_HAVE_COME_BACK = 15.0

SOMETHING = TypeAdapter(list[str])
A_COUNT = TypeAdapter(int)

NOTHING_IS_LISTENING_HERE = "http://127.0.0.1:8199/mcp"
DONT_CARE_TOOL = "say_something"


@pytest.fixture
def running_double() -> Iterator[RunningDouble]:
    """A real MCP server for the length of one test, restartable mid-test."""
    with a_running_double() as double:
        yield double


@pytest.mark.component
def test_one_session_answers_every_call_made_over_it(
    running_double: RunningDouble
) -> None:
    """Three calls, one client, and no connection opened between them.

    The whole reason the transport holds a session: an investigation makes up to
    a dozen tool calls, and each one used to pay an HTTP setup and an MCP
    handshake to ask a question that takes milliseconds to answer.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, lambda client: [
                client.call("say_something", SOMETHING.validate_python)
                for _ in range(3)
            ])
        ) \
        .then(
            _every_call_answered(["something"], times=3)
        )


@pytest.mark.component
def test_a_tool_that_refused_is_raised_rather_than_asked_again(
    running_double: RunningDouble
) -> None:
    """A refusal is an answer, and answers are not retried.

    The distinction the retry is built on. A tool that reported an error was
    reached, so a second session would carry the same refusal back - and for a
    write tool, asking twice is doing the thing twice. The count comes from the
    server's own process, which is the only place that can say how many times it
    was actually asked.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, _refusing_once_and_counting)
        ) \
        .then(all_of(
            _what_was_raised_was(McpToolError),
            _the_tool_was_asked(times=1)
        ))


@pytest.mark.component
def test_the_session_still_serves_calls_after_a_tool_refused(
    running_double: RunningDouble
) -> None:
    """A refusal leaves the connection where it was.

    The other half of the rule above: a tool error must not be read as the
    session having failed, or every refused write would throw away a connection
    that was working perfectly.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, _refusing_then_asking_something_else)
        ) \
        .then(
            _the_answer_is(["something"])
        )


@pytest.mark.component
def test_a_call_is_answered_after_the_server_it_was_held_to_restarted(
    running_double: RunningDouble
) -> None:
    """The failure a per-call connection could not have.

    A worker holds its sessions for as long as it lives, so a server restarted
    beneath it - a deploy, an idle timeout, a crash - would otherwise poison
    every tool call that worker makes for the rest of its life. One rebuild, and
    the incident being walked never learns anything happened.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, _asking_either_side_of_a_restart(running_double))
        ) \
        .then(
            _the_answer_is(["something"])
        )


@pytest.mark.component
def test_a_server_that_cannot_be_reached_is_reported_as_unreachable() -> None:
    """Nothing listening is `McpUnreachable`, not a hang and not a tool error.

    A caller acts on the difference: a tool that refused said something about
    the world, and a server that was never reached said nothing at all.
    """
    Scenario() \
        .given(NOTHING_IS_LISTENING_HERE) \
        .when(
            attempting(_asking_a_client_at(NOTHING_IS_LISTENING_HERE))
        ) \
        .then(
            an_error_was_raised(McpUnreachable)
        )


@pytest.mark.component
def test_a_caller_that_already_has_an_event_loop_is_answered_rather_than_crashed(
    running_double: RunningDouble
) -> None:
    """The hard failure the old transport was one async caller away from.

    Opening an event loop per call raises `RuntimeError` when the caller already
    has one, which is every route in `argus_web`. Nothing there reaches a tool
    today; the day something does, it gets an answer.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _awaiting(running_double, "say_something")
        ) \
        .then(
            _the_answer_is(["something"])
        )


@pytest.mark.component
def test_a_call_in_flight_when_the_client_closes_is_failed_rather_than_stranded(
    running_double: RunningDouble
) -> None:
    """Closing must not leave a caller on another thread waiting for ever.

    The client says it is safe to share, so a second thread may be inside a call
    when whoever owns the client closes it. The holder serving that call is gone
    by the time it looks again, and a tool call carries no deadline of its own -
    so a caller left waiting on a session that is never coming back waits for
    the life of the process.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _closing_while_a_call_is_in_flight(running_double)
        ) \
        .then(
            _what_was_raised_was(McpUnreachable)
        )


class _Attempt(NamedTuple):
    """What a call produced - an answer, or what was raised instead.

    Both, because the tests that expect a failure also ask what the client could
    still do afterwards, and an exception escaping `when` would take the rest of
    the step with it.
    """

    answer: object = None
    raised: BaseException | None = None
    asked: int | None = None


def _refusing_once_and_counting(client: McpClient) -> _Attempt:
    try:
        client.call("refuse", SOMETHING.validate_python)
    except Exception as refusal:
        return _Attempt(
            raised=refusal,
            asked=client.call("times_refused", A_COUNT.validate_python)
        )

    return _Attempt(asked=client.call("times_refused", A_COUNT.validate_python))


def _refusing_then_asking_something_else(client: McpClient) -> _Attempt:
    with suppress(McpToolError):
        client.call("refuse", SOMETHING.validate_python)

    return _Attempt(answer=client.call("say_something", SOMETHING.validate_python))


def _asking_either_side_of_a_restart(
    double: RunningDouble
) -> Callable[[McpClient], _Attempt]:
    def both_calls(client: McpClient) -> _Attempt:
        client.call("say_something", SOMETHING.validate_python)
        double.restart()

        return _Attempt(answer=client.call("say_something", SOMETHING.validate_python))

    return both_calls


def _asking[T](double: RunningDouble,
               ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """One client to the double, held for one `when` and closed after it."""
    def step() -> T:
        with McpClient(double.url) as client:
            return ask(client)

    return step


def _asking_a_client_at(url: str) -> Callable[[], object]:
    def step() -> object:
        with McpClient(url) as client:
            return client.call(DONT_CARE_TOOL, SOMETHING.validate_python)

    return step


def _awaiting(double: RunningDouble, tool: str) -> Callable[[], _Attempt]:
    """The same call, made from inside a running event loop."""
    async def from_inside_a_loop(client: McpClient) -> _Attempt:
        return _Attempt(answer=await client.acall(tool, SOMETHING.validate_python))

    def step() -> _Attempt:
        with McpClient(double.url) as client:
            return asyncio.run(from_inside_a_loop(client))

    return step


def _every_call_answered(expected: list[str], times: int) -> Assertion[list[list[str]]]:
    def assertion(answers: list[list[str]]) -> bool:
        if answers != [expected] * times:
            raise AssertionError(
                f"Expected {times} answers of {expected}, got {answers}."
            )

        return True

    return assertion


def _the_answer_is(expected: list[str]) -> Assertion[_Attempt]:
    def assertion(attempt: _Attempt) -> bool:
        if attempt.raised is not None:
            raise AssertionError(
                f"Expected the answer {expected}, but {attempt.raised!r} was raised."
            )

        if attempt.answer != expected:
            raise AssertionError(
                f"Expected the answer {expected}, got {attempt.answer}."
            )

        return True

    return assertion


def _what_was_raised_was(expected: type[BaseException]) -> Assertion[_Attempt]:
    def assertion(attempt: _Attempt) -> bool:
        if not isinstance(attempt.raised, expected):
            raise AssertionError(
                f"Expected {expected.__name__} to be raised, got {attempt.raised!r}."
            )

        return True

    return assertion


def _the_tool_was_asked(times: int) -> Assertion[_Attempt]:
    def assertion(attempt: _Attempt) -> bool:
        if attempt.asked != times:
            raise AssertionError(
                f"Expected the tool to have been asked {times} time(s), "
                f"the server counted {attempt.asked}."
            )

        return True

    return assertion


def _closing_while_a_call_is_in_flight(
    double: RunningDouble
) -> Callable[[], _Attempt]:
    """Starts a call on another thread, then closes the client under it.

    The call is made on a daemon thread rather than through an executor, so that
    a client which does strand it fails this test instead of holding the whole
    suite open at interpreter exit.
    """
    def step() -> _Attempt:
        client = McpClient(double.url)
        # Opened before the thread starts, so what the close races is a call
        # over a session rather than the opening of one.
        client.call("say_something", SOMETHING.validate_python)
        answered: queue.Queue[_Attempt] = queue.Queue()

        def call_and_report() -> None:
            try:
                answered.put(_Attempt(answer=client.call(
                    "dawdle",
                    SOMETHING.validate_python,
                    seconds=LONGER_THAN_THE_TEST_WILL_WAIT
                )))
            except Exception as failed:
                answered.put(_Attempt(raised=failed))

        threading.Thread(target=call_and_report, daemon=True).start()
        time.sleep(LONG_ENOUGH_TO_BE_IN_FLIGHT)
        client.close()

        try:
            return answered.get(timeout=LONG_ENOUGH_TO_HAVE_COME_BACK)
        except Empty:
            raise AssertionError(
                "the call in flight never came back: closing stranded it"
            ) from None

    return step
