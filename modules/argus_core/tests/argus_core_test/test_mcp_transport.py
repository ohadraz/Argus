"""What a held MCP session promises, and what it must not get wrong.

The transport stopped being a function that opens a connection and became an
object that keeps one, which buys a session per process instead of a session per
tool call and costs two properties a fresh connection had for nothing: that a
second call works at all, and that a connection lost between calls is somebody
else's problem. Both are asserted here, against a real MCP server this suite can
take away and put back.

And it is traced, both halves of it. A call is a span on the side that asked,
measured, and carrying its context to the far side in the request's `_meta`;
the server answers inside it. The client's half is watched through an SDK's
in-memory tracer and meter handed to it; the server's half is reported by the
double itself, which is the only party that knows which trace it answered in.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from queue import Empty
from typing import Any, NamedTuple

import pytest
from argus_core.mcp_transport import (
    ActionExhausted,
    McpClient,
    McpToolError,
    McpUnreachable,
    PlatformUnreachable,
    an_unreachable_platform,
    serving_a_tool_call,
    what_was_left_behind,
)
from argus_core.models import AcceleratorPinUndo, DeploymentRollbackUndo, UndoDescriptor
from argus_core.telemetry import (
    ERROR_TYPE,
    GEN_AI_TOOL_NAME,
    MCP_CLIENT_OPERATION_DURATION,
    MCP_METHOD_NAME,
)
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanContext, SpanKind, StatusCode
from pydantic import TypeAdapter

from argus_core_test.framework.observing import Observed, attributes_of, observing
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
# The platform the double's refusal names. A value the test owns rather than the
# production spelling imported, because what is asserted is that whatever the
# tier names travels intact - not that both sides agree with one constant.
PLATFORM = "some-deployment-platform"
# What the double leaves behind when it loses the platform mid-action, and the
# words it says about it. A real descriptor rather than an invented shape,
# because what is asserted is that this exact value survives the crossing - and a
# shape production never produces would prove nothing about the one it does.
WHAT_THE_TIER_SAID = "stopped answering after reconciliation was suspended"
WHAT_WAS_LEFT_BEHIND = DeploymentRollbackUndo(
    application="some-application",
    was_on_history_id=41,
    was_on_revision="0f1e2d3",
    was_syncing_itself=True
)


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
def test_a_refusal_the_server_marked_as_exhausted_says_so_to_the_caller() -> None:
    """A tool refusing because there is nothing left to do is its own answer.

    The distinction a walk acts on. A tier that cannot make a deployment larger
    than it already is has not failed - it has answered - and a caller that read
    that as a failure would wake a human while the explanation that actually
    caused the incident sat untried further down the list. So the marker crosses
    the wire and arrives as a type, because the alternative is matching on the
    words of a sentence somebody will rewrite.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_as_exhausted)) \
            .then(_what_was_raised_was(ActionExhausted))


@pytest.mark.component
def test_an_ordinary_refusal_is_not_read_as_an_exhausted_action(
    running_double: RunningDouble
) -> None:
    """A broken tool is still a broken tool.

    The other half, and the one that decides whether the first is worth having: a
    transport that read every refusal as exhausted would satisfy the test above
    and quietly turn every platform outage into a candidate being skipped.
    """
    Scenario() \
        .given(running_double) \
        .when(_asking(running_double, _refusing_once_and_counting)) \
        .then(all_of(
            _what_was_raised_was(McpToolError),
            _what_was_raised_was_not(ActionExhausted)
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
def test_a_refusal_the_server_marked_as_an_unreachable_platform_says_so() -> None:
    """A tool that could not reach the platform it acts through is its own answer.

    The distinction the walk narrows itself on. Five of the seven generic
    mitigations act through one deployment platform, so a platform that is not
    answering has taken five actions away at once - and a caller that read that
    as this one action failing would escalate while a flag it could revert in
    seconds sat untried. The marker crosses the wire and arrives as a type, for
    the reason an exhausted action does: the alternative is matching on the words
    of a sentence somebody will rewrite.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_as_an_unreachable_platform)) \
            .then(all_of(
                _what_was_raised_was(PlatformUnreachable),
                _what_was_said_names(PLATFORM)
            ))


@pytest.mark.component
def test_an_ordinary_refusal_is_not_read_as_an_unreachable_platform(
    running_double: RunningDouble
) -> None:
    """A broken tool is still a broken tool.

    The other half, and the one that decides whether the first is worth having: a
    transport that read every refusal as an unreachable platform would pass the
    test above and quietly have the walk write off four actions whenever one tool
    was merely broken.
    """
    Scenario() \
        .given(running_double) \
        .when(_asking(running_double, _refusing_once_and_counting)) \
        .then(all_of(
            _what_was_raised_was(McpToolError),
            _what_was_raised_was_not(PlatformUnreachable)
        ))


@pytest.mark.component
def test_an_unreachable_platform_is_not_reported_as_an_unreachable_server() -> None:
    """A reachable server whose platform is down is not a server that is gone.

    They look alike and mean opposite things. If the write server is gone, every
    action is unavailable whatever platform it acts through and there is nothing
    left to narrow to; if a platform is down, the actions on the other platform
    are still there to be tried. The types cannot collapse - one is an
    `McpToolError` and the other a `RuntimeError` - so what this holds is the
    reporting: the platform is named when it is the platform, and not named when
    the session itself could not be had.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_as_an_unreachable_platform)) \
            .then(all_of(
                _what_was_raised_was_not(McpUnreachable),
                _what_was_said_names(PLATFORM)
            ))


@pytest.mark.component
def test_a_server_that_could_not_be_reached_names_no_platform() -> None:
    """And the other direction: nothing was reached, so nothing is known.

    Separate from the test above it rather than folded in, because this one needs
    no server and that one needs a running double - and a single test that both
    starts a double and points at a dead port would be two arrangements holding
    one claim.
    """
    Scenario() \
        .given(NOTHING_IS_LISTENING_HERE) \
        .when(attempting(_asking_a_client_at(NOTHING_IS_LISTENING_HERE))) \
        .then(all_of(
            an_error_was_raised(McpUnreachable),
            _nothing_was_said_about_a_platform()
        ))


@pytest.mark.component
def test_a_platform_lost_after_something_landed_carries_what_it_left_behind() -> None:
    """The failure that is both: the platform is gone and the estate changed.

    Four of the five actions through this platform change something before the
    thing they were asked for - they suspend its reconciliation first, because it
    refuses otherwise. A platform that stops answering after that point has taken
    every action through it away *and* left an application un-reconciled, and a
    caller has to be told both: it narrows itself on the first, and something has
    to put back the second.

    Carried on the failure because there is nowhere else. A tool that failed
    returns no structured content, so the one string a failure may carry is the
    only channel there is - which is the problem the marker already solved, doing
    a little more work.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(
                double, _refusing_as_an_unreachable_platform_that_changed_something
            )) \
            .then(all_of(
                _what_was_raised_was(PlatformUnreachable),
                _what_it_left_behind_is(WHAT_WAS_LEFT_BEHIND),
                _what_was_said_names(PLATFORM)
            ))


@pytest.mark.component
def test_a_platform_lost_before_anything_landed_carries_nothing_to_put_back() -> None:
    """The ordinary case, and the one that says the field means something.

    Most of the time the platform is gone before the first write, so there is
    nothing to put back and the failure says so by carrying nothing. A transport
    that filled this in regardless would have every walk record a change nobody
    made.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_as_an_unreachable_platform)) \
            .then(all_of(
                _what_was_raised_was(PlatformUnreachable),
                _it_left_nothing_behind()
            ))


@pytest.mark.unit
def test_a_descriptor_recording_that_there_was_nothing_before_survives_the_crossing(
) -> None:
    # "There was no pin" is a fact a descriptor records, in a field with no
    # default. Encoded as though it were absent, the descriptor stops parsing on
    # the far side, and a suspension it records arrives as nothing left behind -
    # an application sitting un-reconciled that no withdrawal will put back.
    left_behind = AcceleratorPinUndo(
        application="some-application",
        was_pinned_to=None,
        pinned_to="some-card",
        was_syncing_itself=True
    )

    Scenario() \
        .given(left_behind) \
        .when(lambda: what_was_left_behind(
            an_unreachable_platform(PLATFORM, WHAT_THE_TIER_SAID, left_behind)
        )) \
        .then(_it_came_back_as(left_behind))


@pytest.mark.component
def test_what_a_person_reads_is_not_the_payload() -> None:
    """The descriptor travels in the words and must not be read as words.

    Whatever encodes it is in the same string a human is shown - the timeline,
    the postmortem, a Slack line - so the sentence has to survive being carried
    on. Asserted here rather than left to whoever strips the marker, because the
    encoding is this module's and a caller cannot strip what it was never told
    about.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(
                double, _refusing_as_an_unreachable_platform_that_changed_something
            )) \
            .then(all_of(
                _what_was_said_names(PLATFORM),
                _what_was_said_names(WHAT_THE_TIER_SAID)
            ))


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


@pytest.mark.component
def test_a_tool_call_is_a_client_span_named_for_the_tool(
    running_double: RunningDouble
) -> None:
    # The MCP conventions' name, `{method} {tool}`, and its kind: a call out of
    # this process to a server somewhere else.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _asking_while_observed(running_double, observed, DONT_CARE_TOOL)
        ) \
        .then(
            _the_tool_call_span_is(observed,
                                   named=f"tools/call {DONT_CARE_TOOL}",
                                   kind=SpanKind.CLIENT,
                                   carrying={MCP_METHOD_NAME: "tools/call",
                                             GEN_AI_TOOL_NAME: DONT_CARE_TOOL})
        )


@pytest.mark.component
def test_a_tool_call_is_made_inside_the_span_that_asked_for_it(
    running_double: RunningDouble
) -> None:
    # Opened on the calling thread rather than on the client's own loop. The
    # loop's thread has no idea which agent asked, and a span opened there
    # would start a trace of its own - every tool call an orphan.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _asking_while_observed(running_double, observed, DONT_CARE_TOOL,
                                           inside="some-agent")
        ) \
        .then(
            _the_tool_call_was_made_under(observed, "some-agent")
        )


@pytest.mark.component
def test_a_refused_tool_call_is_an_error_span_naming_what_was_raised(
    running_double: RunningDouble
) -> None:
    # The class, not the message: which of the ways a call can fail this was
    # is what a reader of a trace filters on.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            attempting(
                lambda: _asking_while_observed(running_double, observed, "refuse")
            )
        ) \
        .then(
            all_of(
                an_error_was_raised(McpToolError),
                _the_tool_call_failed_with(observed, "McpToolError")
            )
        )


@pytest.mark.component
def test_a_tool_call_is_measured_for_how_long_it_took(
    running_double: RunningDouble
) -> None:
    # On an injected clock, so the duration is exact rather than whatever the
    # double happened to take.
    some_seconds_taken = 0.25

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _asking_while_observed(running_double, observed, DONT_CARE_TOOL,
                                           clock=_a_clock_reading(0.0, some_seconds_taken))
        ) \
        .then(
            _one_duration_of(observed, some_seconds_taken, for_tool=DONT_CARE_TOOL)
        )


@pytest.mark.component
def test_the_server_answers_inside_the_callers_trace(
    running_double: RunningDouble
) -> None:
    # The whole reason the context travels in `_meta`. The server's span is a
    # child of the client's, in the caller's trace - so what a server did, and
    # every line it logged doing it, is found from the walk that asked.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _asking_while_observed(running_double, observed, "the_trace_i_am_in")
        ) \
        .then(
            _the_server_answered_under_the_client_span(observed)
        )


@pytest.mark.unit
def test_a_call_arriving_with_a_trace_is_served_inside_it() -> None:
    some_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    some_parent_span_id = "00f067aa0ba902b7"

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _served_while_observed(
                observed, {"traceparent": f"00-{some_trace_id}-{some_parent_span_id}-01"}
            )
        ) \
        .then(
            _the_server_span_continued(observed, some_trace_id, some_parent_span_id)
        )


@pytest.mark.unit
def test_a_call_arriving_with_no_trace_is_served_under_one_of_its_own() -> None:
    # A client that sends no context is still answered. Telemetry decides
    # nothing about whether a tool runs.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _served_while_observed(observed, None)
        ) \
        .then(
            _the_server_span_started_a_trace(observed)
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


def _what_was_raised_was_not(
    excluded: type[BaseException]
) -> Assertion[_Attempt]:
    """The failure was of the general kind and not the particular one.

    Needed because the particular kind is a subclass of the general one, so
    asserting the general kind alone cannot catch the failure that matters here:
    a transport reading every refusal as exhausted would pass every test above
    and would have the walk skip a candidate whenever a server was merely
    broken.
    """
    def assertion(attempt: _Attempt) -> bool:
        if isinstance(attempt.raised, excluded):
            raise AssertionError(
                f"Expected the failure not to be a {excluded.__name__}, and it "
                f"was: {attempt.raised!r}."
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
                "The call in flight never came back: closing stranded it."
            ) from None

    return step


def _refusing_as_exhausted(client: McpClient) -> _Attempt:
    try:
        client.call("refuse_as_exhausted", SOMETHING.validate_python)
    except Exception as refusal:
        return _Attempt(raised=refusal)

    return _Attempt()


def _refusing_as_an_unreachable_platform(client: McpClient) -> _Attempt:
    try:
        client.call("refuse_as_unreachable_platform", SOMETHING.validate_python)
    except Exception as refusal:
        return _Attempt(raised=refusal)

    return _Attempt()


def _what_was_said_names(platform: str) -> Assertion[_Attempt]:
    """The platform is in the words, for whoever reads the failure.

    Asserted separately from the type because the two carry different halves: the
    type is what a walk branches on, and the words are what a person reads. A
    platform named only in the type would leave the message saying which action
    failed and not which platform took it away.
    """
    def assertion(attempt: _Attempt) -> bool:
        if platform not in str(attempt.raised):
            raise AssertionError(
                f"Expected the failure to name {platform!r}, "
                f"and it said: {attempt.raised!r}."
            )

        return True

    return assertion


def _nothing_was_said_about_a_platform() -> Assertion[Exception | None]:
    """A server that was never reached names no platform, because none is known.

    The half that makes the claim above worth having. A transport that reported
    every unreachable thing the same way would satisfy every assertion about the
    platform and tell a walk that its four platform actions were gone when what
    was actually gone was the write server and all five with it.

    Takes what `attempting` yields - an `Exception | None` - rather than an
    `_Attempt`, because the step it judges is the one that points at a dead port
    and has no client to come back through.
    """
    def assertion(raised: Exception | None) -> bool:
        if PLATFORM in str(raised):
            raise AssertionError(
                f"Expected a server that could not be reached to name no "
                f"platform, and it said: {raised!r}."
            )

        return True

    return assertion


def _refusing_as_an_unreachable_platform_that_changed_something(
    client: McpClient
) -> _Attempt:
    try:
        client.call(
            "refuse_as_unreachable_platform_mid_action", SOMETHING.validate_python
        )
    except Exception as refusal:
        return _Attempt(raised=refusal)

    return _Attempt()


def _what_it_left_behind_is(expected: UndoDescriptor) -> Assertion[_Attempt]:
    """The descriptor arrived, and arrived as itself.

    Compared as a value rather than checked for presence, because the whole point
    of carrying it is that somebody can act on it: a descriptor that survived the
    crossing with a field lost would put back something other than what was
    changed, and would look right in every assertion short of this one.
    """
    def assertion(attempt: _Attempt) -> bool:
        carried = getattr(attempt.raised, "undo_descriptor", None)

        if carried != expected:
            raise AssertionError(
                f"Expected the failure to carry {expected!r} as what it left "
                f"behind, it carries {carried!r}."
            )

        return True

    return assertion


def _it_left_nothing_behind() -> Assertion[_Attempt]:
    """Nothing to put back, said as nothing rather than as an empty something.

    The half that keeps the claim above meaningful. A transport that invented a
    descriptor where none was sent would satisfy a presence check, and the walk
    would then record a change nobody made against an action that changed
    nothing.
    """
    def assertion(attempt: _Attempt) -> bool:
        carried = getattr(attempt.raised, "undo_descriptor", None)

        if carried is not None:
            raise AssertionError(
                f"Expected the failure to carry nothing to put back, it carries "
                f"{carried!r}."
            )

        return True

    return assertion


def _it_came_back_as(
    expected: UndoDescriptor
) -> Assertion[UndoDescriptor | None]:
    def assertion(read_back: UndoDescriptor | None) -> bool:
        if read_back != expected:
            raise AssertionError(
                f"Expected {expected!r} to be read back as itself, and it was read "
                f"back as {read_back!r}."
            )

        return True

    return assertion


def _asking_while_observed(double: RunningDouble,
                           observed: Observed,
                           tool: str,
                           inside: str | None = None,
                           clock: Any = None) -> object:
    """One call through a client reporting to `observed`, inside a span if named.

    The client is told the test's tracer and meter, where it would otherwise
    take the process's own - which here is the API's no-op.
    """
    def ask() -> object:
        with _a_client_reporting_to(double, observed, clock) as client:
            return client.call(tool, lambda answer: answer)

    if inside is None:
        return ask()

    with observed.tracer.start_as_current_span(inside):
        return ask()


def _a_client_reporting_to(double: RunningDouble,
                           observed: Observed,
                           clock: Any) -> McpClient:
    if clock is None:
        return McpClient(double.url, tracer=observed.tracer, meter=observed.meter)

    return McpClient(double.url, tracer=observed.tracer, meter=observed.meter, clock=clock)


def _served_while_observed(observed: Observed, meta: dict[str, str] | None) -> None:
    """The server's half alone: one tool call served under whatever `meta` carried."""
    with serving_a_tool_call(DONT_CARE_TOOL, meta, tracer=observed.tracer):
        pass


def _a_clock_reading(*seconds: float) -> Any:
    """A clock that reads each of these in turn, so a duration is exact."""
    readings = iter(seconds)

    def clock() -> float:
        return next(readings)

    return clock


def _the_tool_call_span(observed: Observed) -> ReadableSpan:
    """The one span the client made - whichever other span the test opened around it."""
    calls = [span for span in observed.spans() if span.kind is SpanKind.CLIENT]

    if len(calls) != 1:
        raise AssertionError(
            f"Expected one tool-call span, and there were {len(calls)} among "
            f"{[span.name for span in observed.spans()]}."
        )

    return calls[0]


def _the_tool_call_span_is(observed: Observed,
                           named: str,
                           kind: SpanKind,
                           carrying: dict[str, str]) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        span = _the_tool_call_span(observed)
        carried = dict(span.attributes or {})
        wrong = {key: (wanted, carried.get(key))
                 for key, wanted in carrying.items() if carried.get(key) != wanted}

        if (span.name, span.kind) != (named, kind) or wrong:
            raise AssertionError(
                f"Expected a [{kind.name}] span named [{named}] carrying {carrying}, got a "
                f"[{span.kind.name}] span named [{span.name}] where {wrong} differed "
                f"(expected, got)."
            )

        return True

    return assertion


def _the_tool_call_was_made_under(observed: Observed, asked_by: str) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        call = _the_tool_call_span(observed)
        asking = [span for span in observed.spans() if span.name == asked_by]
        parent = call.parent.span_id if call.parent is not None else None

        if len(asking) != 1 or parent != _the_context_of(asking[0]).span_id:
            raise AssertionError(
                f"Expected the tool call to be a child of [{asked_by}], and its parent "
                f"was [{parent}] among {[span.name for span in observed.spans()]}."
            )

        return True

    return assertion


def _the_tool_call_failed_with(observed: Observed, error_type: str) -> Assertion[Exception | None]:
    def assertion(_raised: Exception | None) -> bool:
        span = _the_tool_call_span(observed)
        said = (span.status.status_code, (span.attributes or {}).get(ERROR_TYPE))

        if said != (StatusCode.ERROR, error_type):
            raise AssertionError(
                f"Expected the tool call's span to have failed with [{error_type}], "
                f"and it said {said}."
            )

        return True

    return assertion


def _one_duration_of(observed: Observed, seconds: float, for_tool: str) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        points = [
            point for point in observed.points_of(MCP_CLIENT_OPERATION_DURATION)
            if attributes_of(point).get(GEN_AI_TOOL_NAME) == for_tool
        ]

        if [(point.count, point.sum) for point in points] != [(1, seconds)]:
            raise AssertionError(
                f"Expected one call to [{for_tool}] measured at [{seconds}]s, and the "
                f"points were {[(point.count, point.sum) for point in points]}."
            )

        return True

    return assertion


def _the_server_answered_under_the_client_span(observed: Observed) -> Assertion[object]:
    """That the double's own span sat in the client's trace, as the client span's child."""
    def assertion(answer: object) -> bool:
        call = _the_context_of(_the_tool_call_span(observed))
        expected = {"trace_id": format(call.trace_id, "032x"),
                    "parent_span_id": format(call.span_id, "016x")}

        if answer != expected:
            raise AssertionError(
                f"Expected the server to answer under the client's span {expected}, "
                f"and it said {answer}."
            )

        return True

    return assertion


def _the_server_span_continued(observed: Observed,
                               trace_id: str,
                               parent_span_id: str) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        span = observed.only_span()
        parent = span.parent
        said = (span.kind,
                format(_the_context_of(span).trace_id, "032x"),
                format(parent.span_id, "016x") if parent is not None else None)

        if said != (SpanKind.SERVER, trace_id, parent_span_id):
            raise AssertionError(
                f"Expected a SERVER span in trace [{trace_id}] under [{parent_span_id}], "
                f"and it was (kind, trace, parent) {said}."
            )

        return True

    return assertion


def _the_server_span_started_a_trace(observed: Observed) -> Assertion[object]:
    def assertion(_result: object) -> bool:
        span = observed.only_span()

        if span.parent is not None:
            raise AssertionError(
                f"Expected a call that brought no trace to start one, and its span "
                f"had a parent [{span.parent.span_id:016x}]."
            )

        return True

    return assertion


def _the_context_of(span: ReadableSpan) -> SpanContext:
    """A finished span's own context - which the SDK types as optional and never leaves out."""
    context = span.get_span_context()

    if context is None:
        raise AssertionError(
            f"Expected the span [{span.name}] to carry a context, and it had none."
        )

    return context
