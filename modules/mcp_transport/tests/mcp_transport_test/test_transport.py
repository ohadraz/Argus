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
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import suppress
from queue import Empty
from typing import Any, Final, NamedTuple
from unittest.mock import create_autospec

import httpx2
import pytest
import uvicorn
from argus_testkit.assertions import (
    Assertion,
    all_of,
    an_error_was_raised,
    the_answer_was,
)
from argus_testkit.logs import one_record_was_logged
from argus_testkit.scenario import Scenario, attempting, calling
from core import Fence, Holding, RunLost
from core.models import AcceleratorPinUndo, DeploymentRollbackUndo, UndoDescriptor
from core.telemetry import (
    ARGUS_INCIDENT_ID,
    ERROR_TYPE,
    GEN_AI_TOOL_NAME,
    MCP_CLIENT_OPERATION_DURATION,
    MCP_METHOD_NAME,
)
from mcp.client import Client
from mcp.server.mcpserver import Context
from mcp.shared.exceptions import MCPError
from mcp.types import (
    REQUEST_TIMEOUT,
    CallToolResult,
    InputRequiredResult,
    ListToolsResult,
    Tool,
)
from mcp_transport import (
    LEFT_BEHIND_KNOWN_MARKER,
    LEFT_BEHIND_MARKER,
    PING_SECONDS,
    ActionExhausted,
    Asking,
    AskingBound,
    ChangedSince,
    LostAfterSending,
    McpClient,
    McpToolError,
    McpUnreachable,
    PlatformUnreachable,
    TracedMCPServer,
    WhichAsking,
    a_refusal_saying_what_it_left,
    an_http_client_waiting,
    an_unreachable_platform,
    every_tool_listed,
    serving_a_tool_call,
    what_was_left_behind,
)
from opentelemetry import baggage
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanContext, SpanKind, StatusCode
from pydantic import TypeAdapter
from starlette.applications import Starlette

from mcp_transport_test.framework.observing import Observed, attributes_of, observing
from mcp_transport_test.framework.transport_double import RunningDouble, a_running_double

# Long enough that the call has certainly reached the server, which takes
# milliseconds - and short enough that the test does not sit here.
LONG_ENOUGH_TO_BE_IN_FLIGHT = 0.5
# What the dawdling call would have taken had closing not ended it, and how long
# this waits for it to come back one way or the other.
LONGER_THAN_THE_TEST_WILL_WAIT = 30.0
LONG_ENOUGH_TO_HAVE_COME_BACK = 15.0
# How long the asking, handshake, list or ping a case stalls on waits for its
# answer before the client gives it up - short, so the case does not sit here.
SOON_ENOUGH_TO_GIVE_UP = 0.5
# And every other tool's answer, in every case: longer than any tool here takes,
# the dawdle a closing client ends included, so nothing but what a case stalls
# on meets a bound - not a second asking made slow by a loaded machine.
PATIENT_PAST_ANY_CALL_HERE = 2 * LONGER_THAN_THE_TEST_WILL_WAIT
# Longer still, for the one case whose bound for everything that is not a call
# must be longer than its call bound.
MORE_PATIENT_THAN_ANY_CALL_HERE = 2 * PATIENT_PAST_ANY_CALL_HERE
# How long the double holds a ping in the one case about the ping's own bound:
# halfway between `SOON_ENOUGH_TO_GIVE_UP` and the bound a client given none
# waits (`PING_SECONDS`), so only a client keeping the bound it was given finds
# the session gone - wherever either of them moves.
LONGER_THAN_GIVING_UP_SHORTER_THAN_THE_DEFAULT_PING = (SOON_ENOUGH_TO_GIVE_UP + PING_SECONDS) / 2
# Which askings of a call to a tool a client gives up on soon.
ITS_FIRST_ASKING = frozenset({WhichAsking.FIRST})
ITS_SECOND_ASKING = frozenset({WhichAsking.SECOND})
BOTH_OF_ITS_ASKINGS = frozenset({WhichAsking.FIRST, WhichAsking.SECOND})
# MCP's own names for the requests a case has the double hold, as JSON-RPC
# methods: the handshake, a list of tools, a ping.
A_HANDSHAKE = "initialize"
A_LIST_OF_TOOLS = "tools/list"
A_PING = "ping"
# Sessions a client opened: the first, and the one it opened in place of it.
TWO_SESSIONS = 2
# What a server counts at its first asking, which is the only asking a server
# restarted beneath a client ever heard.
THE_FIRST_ASKING_A_SERVER_HEARD = 1
# A call asked once, and once more over a new session where the first got no
# answer.
BOTH_ASKINGS = 2

SOMETHING = TypeAdapter(list[str])
A_COUNT = TypeAdapter(int)
A_FENCE_HEARD = TypeAdapter(dict[str, object])
AN_ACTION_HEARD = TypeAdapter(dict[str, object])

NOTHING_IS_LISTENING_HERE = "http://127.0.0.1:8199/mcp"
DONT_CARE_TOOL = "say_something"
# Where a server built here and never served would be served.
DONT_CARE_HOST = "127.0.0.1"
DONT_CARE_PORT = 8123
# A tool that, once begun, stays open until a second call has arrived - and how
# long it waits for one before it ends without it: a guard against a hang, never
# waited out by a case that passes, since the second call arrives in
# milliseconds.
A_TOOL_HELD_OPEN = "held_open"
LONG_PAST_ANY_ARRIVAL_SECONDS = 30.0
# How the SDK's client is told to open a session by the `initialize` handshake,
# as `McpClient` opens one - its default speaks to a server in the same process
# without one.
LEGACY_HANDSHAKE: Final = "legacy"
# The double's tools a case names in what it asserts, as well as asks: one that
# counts every asking; one that stalls at every asking; four that stall at the
# first and, at every later one, refuse saying they left nothing, refuse as
# changed since, answer, or refuse as a lost run; one that ends its server's
# process on being asked; and the one that has the server forget a session
# after the next ping it answers.
COUNTING_TOOL = "count_an_asking"
STALLING_TOOL = "stall"
STALLING_THEN_LEAVING_NOTHING_TOOL = "stall_then_refuse_saying_it_left_nothing"
STALLING_THEN_CHANGED_SINCE_TOOL = "stall_then_refuse_as_changed_since"
STALLING_THEN_ANSWERING_TOOL = "stall_then_answer"
STALLING_THEN_LOST_RUN_TOOL = "stall_then_refuse_as_lost_run"
ENDING_THE_SERVER_TOOL = "end_the_server_on_being_asked"
FORGETTING_AFTER_A_PING_TOOL = "forget_a_session_after_the_next_ping"
# What `STALLING_THEN_ANSWERING_TOOL` answers its later askings with.
WHAT_THE_SECOND_ASKING_ANSWERED = ["something"]
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
                client.call(DONT_CARE_TOOL, SOMETHING.validate_python, asking=Asking.READ)
                for _ in range(3)
            ])
        ) \
        .then(
            _every_call_answered(["something"], times=3)
        )


@pytest.mark.component
def test_the_tools_a_server_lists_come_back_in_its_order_as_it_declares_them(
    running_double: RunningDouble
) -> None:
    # The server owns its tools' definitions, and a client reads them rather
    # than keeping copies - every one, as declared: which of them anybody offers
    # a model, and whether it can be, is the offer's to decide.
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, lambda client: client.list_tools())
        ) \
        .then(
            all_of(
                _the_tools_listed_are([
                    "say_something", "refuse", "refuse_without_a_word", "times_refused",
                    "refuse_as_exhausted",
                    "refuse_as_unreachable_platform",
                    "refuse_as_unreachable_platform_mid_action",
                    "refuse_saying_it_left_nothing", "refuse_saying_what_it_left",
                    "refuse_with_what_it_left", "refuse_as_lost_run",
                    "refuse_as_changed_since", "refuse_as_changed_since_after_the_change",
                    "the_fence_i_was_sent", "the_action_i_was_sent", "dawdle",
                    COUNTING_TOOL, STALLING_TOOL, "times_stalled",
                    STALLING_THEN_LEAVING_NOTHING_TOOL, STALLING_THEN_CHANGED_SINCE_TOOL,
                    STALLING_THEN_ANSWERING_TOOL, STALLING_THEN_LOST_RUN_TOOL,
                    "times_asked_stalling_first", ENDING_THE_SERVER_TOOL,
                    FORGETTING_AFTER_A_PING_TOOL, "the_trace_i_am_in"
                ]),
                _the_tool_listed_requires("dawdle", ["seconds"]),
                _the_tool_listed_is_described("refuse_as_exhausted",
                                              "Refuses the way a tier refuses")
            )
        )


@pytest.mark.unit
def test_a_list_of_tools_in_pages_is_read_to_its_last_page() -> None:
    # MCP pages `tools/list`: an answer naming a next cursor has more to come,
    # and a client stopping at the first page offers the model a part of what
    # the server serves.
    some_pages = {
        None: ListToolsResult(tools=[_a_listed_tool("first"), _a_listed_tool("second")],
                              next_cursor="after-second"),
        "after-second": ListToolsResult(tools=[_a_listed_tool("third")])
    }

    async def page(cursor: str | None) -> ListToolsResult:
        return some_pages[cursor]

    Scenario() \
        .when(
            lambda: [tool.name for tool in asyncio.run(every_tool_listed(page))]
        ) \
        .then(
            the_answer_was(["first", "second", "third"])
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
def test_a_refusal_is_said_in_the_tools_own_words(running_double: RunningDouble) -> None:
    """What a tool said when it refused, and nothing the transport wrapped it in.

    The refusal is read by a person - in an escalation's reason, the timeline,
    the postmortem and a Slack line - and it used to arrive as the SDK's own
    "Error executing tool ..." inside the `repr` of a list of content blocks.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, _refusing_once_and_counting)
        ) \
        .then(
            _what_was_raised_said("this tool always refuses")
        )


@pytest.mark.component
def test_a_refusal_without_a_word_still_says_whose_it_was(
    running_double: RunningDouble
) -> None:
    """A tool that refused in no words is named in their place.

    Stripping what the SDK put in front of a refusal leaves nothing where the
    tool said nothing, and an empty reason in an escalation tells a person
    neither what failed nor where to look.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, _refusing_without_a_word)
        ) \
        .then(
            _what_was_raised_said("[refuse_without_a_word] failed and said nothing")
        )


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
def test_a_call_made_while_a_run_is_held_says_which_claim_it_is_made_for(
    running_double: RunningDouble
) -> None:
    # What the write tier decides a change by: a change made for a claim the run
    # has moved past is a second walk acting on somebody else's incident. In
    # each call's `_meta` rather than in a header, because the session is held
    # and its headers were fixed before any run was claimed.
    some_fence = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
    holding = Holding()

    Scenario() \
        .given(
            running_double
        ) \
        .when(
            _asking_while_holding(running_double, holding, some_fence, _the_fence_sent)
        ) \
        .then(
            the_answer_was({"run_id": some_fence.run_id, "epoch": some_fence.epoch})
        )


@pytest.mark.component
def test_each_call_says_the_claim_held_as_it_is_made(running_double: RunningDouble) -> None:
    # A worker's write client is one session for the life of the process, and
    # the process walks one run after another over it. A claim read once, when
    # the session opened, would be the first run's claim said for every run
    # after it.
    some_first_run = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
    some_next_run = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000002", epoch=1)
    holding = Holding()

    Scenario() \
        .given(
            running_double
        ) \
        .when(
            _asking_holding(running_double, holding, lambda client: [
                _the_fence_sent_while_holding(holding, some_first_run, client),
                _the_fence_sent_while_holding(holding, some_next_run, client)
            ])
        ) \
        .then(
            the_answer_was([
                {"run_id": some_first_run.run_id, "epoch": some_first_run.epoch},
                {"run_id": some_next_run.run_id, "epoch": some_next_run.epoch}
            ])
        )


@pytest.mark.component
@pytest.mark.parametrize("holding", [None, Holding()], ids=["no-holding", "nothing-held"])
def test_a_call_made_while_no_run_is_held_names_none(
    holding: Holding | None, running_double: RunningDouble
) -> None:
    # A web route's read, or a worker between runs. The tier answers a change
    # that names no run as an ordinary refusal, so naming none here must not
    # be naming some other run.
    Scenario() \
        .given(
            running_double
        ) \
        .when(
            _asking_holding(running_double, holding, _the_fence_sent)
        ) \
        .then(
            the_answer_was({})
        )


@pytest.mark.component
def test_a_call_made_while_an_action_is_taken_says_which_action_it_is_made_for(
    running_double: RunningDouble
) -> None:
    # What the write tier marks a platform write with: the action row the write
    # is made for, beside the claim it is made under. Read as the call is made,
    # as the claim is, because one client serves every action a walk takes.
    some_fence = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
    some_action_id = "6f1c1d2e-0000-4000-8000-0000000000a1"
    holding = Holding()

    Scenario() \
        .given(
            running_double
        ) \
        .when(
            _asking_while_holding(running_double, holding, some_fence,
                                  lambda client: _the_action_sent_while_acting_for(
                                      holding, some_action_id, client
                                  ))
        ) \
        .then(
            the_answer_was({"action_id": some_action_id})
        )


@pytest.mark.component
def test_a_call_made_while_no_action_is_taken_names_none(running_double: RunningDouble) -> None:
    # A read the walk makes while it holds the run, or a change it makes that is
    # no platform write: naming an action there would put some other action's
    # id on whatever it changes.
    some_fence = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
    holding = Holding()

    Scenario() \
        .given(
            running_double
        ) \
        .when(
            _asking_while_holding(running_double, holding, some_fence, _the_action_sent)
        ) \
        .then(
            the_answer_was({})
        )


@pytest.mark.component
def test_a_refusal_the_server_marked_as_a_lost_run_says_so_and_is_not_asked_again(
    running_double: RunningDouble
) -> None:
    # The walk stops on it, writing nothing more - so it arrives as the walk's
    # own `RunLost` rather than as a tool that broke. And it is not asked again
    # over a new session: the run is lost over every session there is.
    Scenario() \
        .given(
            running_double
        ) \
        .when(
            _asking(running_double, _refusing_as_a_lost_run_and_counting)
        ) \
        .then(all_of(
            _what_was_raised_was(RunLost),
            _the_tool_was_asked(times=1)
        ))


@pytest.mark.component
def test_an_ordinary_refusal_is_not_read_as_a_lost_run(
    running_double: RunningDouble
) -> None:
    # A walk told its run was lost writes nothing more, so a broken tool read as
    # one would end an incident in silence rather than at a human.
    Scenario() \
        .given(
            running_double
        ) \
        .when(
            _asking(running_double, _refusing_once_and_counting)
        ) \
        .then(
            _what_was_raised_was_not(RunLost)
        )


@pytest.mark.component
@pytest.mark.parametrize(
    ("tool", "performed"),
    [("refuse_as_changed_since", False), ("refuse_as_changed_since_after_the_change", True)],
    ids=["suspension-alone", "change-landed"]
)
def test_a_refusal_the_server_marked_as_changed_since_says_so_with_what_it_left(
    tool: str, performed: bool
) -> None:
    """A tool refusing because somebody else changed the estate since the plan.

    The distinction the walk hands an incident to a person on: somebody is
    acting on the service now, and Argus does not act beside them. The marker
    crosses the wire and arrives as a type, for the reason an exhausted action
    does. What an earlier asking of the action left travels with it, because it
    is recorded nowhere else - and whether that included the change itself, since
    the walk records an action whose change landed and was overtaken as
    performed, and one that landed only a suspension as not.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_with(tool))) \
            .then(all_of(
                _what_was_raised_was(ChangedSince),
                _what_it_left_behind_is_known(True),
                _what_it_left_behind_is(WHAT_WAS_LEFT_BEHIND),
                _its_change_is_said_performed(performed)
            ))


@pytest.mark.component
def test_an_ordinary_refusal_is_not_read_as_changed_since(
    running_double: RunningDouble
) -> None:
    # A walk told somebody else changed the estate hands the incident to a
    # person, so a broken tool read as one would escalate while candidates sat
    # untried.
    Scenario() \
        .given(running_double) \
        .when(_asking(running_double, _refusing_once_and_counting)) \
        .then(all_of(
            _what_was_raised_was(McpToolError),
            _what_was_raised_was_not(ChangedSince)
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
def test_a_call_not_to_be_asked_twice_finds_by_its_ping_that_the_server_restarted_and_runs_once(
    running_double: RunningDouble
) -> None:
    """A server restarted beneath a held session is found restarted by the ping
    sent before a call that must not run twice, and the call is sent once, over
    a new session.

    The new server answers the ping over a session it never opened with a 404,
    so the held session is replaced before the call leaves this process. Read
    any other way, a write server's routine restart would end the next restart
    Argus asked for at a human. The count is the new server's own, which heard
    the asking once.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, _counting_once_only_either_side_of_a_restart(running_double))
        ) \
        .then(
            _the_count_is(THE_FIRST_ASKING_A_SERVER_HEARD)
        )


@pytest.mark.component
def test_a_call_not_to_be_asked_twice_turned_away_as_over_a_session_not_held_runs_once(
    running_double: RunningDouble,
    caplog: pytest.LogCaptureFixture
) -> None:
    """A call that must not run twice, turned away over a session the server
    forgot after answering its ping, is asked again over a new session - and
    runs once.

    The one failure after sending that proves the tool never ran: a server
    answers a request over a session it does not hold with a 404, before any
    tool is asked anything, and the SDK says so as "Session terminated". The
    ping went through, so it is the call itself that meets it - which is what a
    server restarted between the ping and the call does.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking(running_double, _counting_once_only_over_a_session_forgotten_after_its_ping)
        ) \
        .then(all_of(
            _the_count_is(THE_FIRST_ASKING_A_SERVER_HEARD),
            one_record_was_logged(caplog, "mcp_transport.transport", logging.WARNING,
                                  "tool call asked again over a new session",
                                  values={"tool": COUNTING_TOOL})
        ))


@pytest.mark.component
def test_a_call_not_to_be_asked_twice_is_asked_again_where_no_session_could_be_had(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Nothing was sent: there was no session to send it over. So the call is
    # asked again over a new one exactly as any call is, and fails as a server
    # that could not be reached - which says nothing was done - rather than as a
    # call lost after it was sent, which says nobody can tell.
    Scenario() \
        .when(
            attempting(_asking_once_only_a_client_at(NOTHING_IS_LISTENING_HERE))
        ) \
        .then(all_of(
            an_error_was_raised(McpUnreachable),
            one_record_was_logged(caplog, "mcp_transport.transport", logging.WARNING,
                                  "tool call asked again over a new session",
                                  values={"tool": DONT_CARE_TOOL},
                                  failure=McpUnreachable)
        ))


@pytest.mark.component
def test_a_call_not_to_be_asked_twice_that_got_no_answer_is_lost_after_sending(
    running_double: RunningDouble
) -> None:
    """A call the server received and never answered is not asked again when
    asking again could do the thing twice.

    A restart and a discard carry no mark a second asking could find, so a
    second asking is a second restart. What the walk is told instead is that
    the call was sent and nothing can say whether it was carried out - a type of
    its own, because it is neither a tool's refusal (nothing answered) nor an
    unreachable server (something was reached). The tool is named in it, for
    whoever reads why the incident was handed over.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_TOOL, ITS_FIRST_ASKING,
                                     _stalling_once_only_and_counting(running_double))
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _what_was_said_names(STALLING_TOOL),
            _the_tool_was_asked(times=1)
        ))


@pytest.mark.component
def test_a_call_that_got_no_answer_ends_at_the_bound_its_client_was_given(
    running_double: RunningDouble
) -> None:
    """A client given nothing but its own bound gives a call that got no answer
    up once it has waited that long - not later, and not never.

    The point of the bound. A tool answers nothing on its stream until it
    returns, and the SDK swallows a stream that ends, so a call nothing bounds
    waits for an answer for ever. Every tier's client is built this way, with
    one bound for every asking.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_bounded_only_by(running_double, SOON_ENOUGH_TO_GIVE_UP,
                                    _stalling_once_only_and_counting(running_double))
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _the_tool_was_asked(times=1)
        ))


@pytest.mark.component
def test_a_server_that_never_answers_the_handshake_is_unreachable_at_the_handshake_s_bound(
    running_double: RunningDouble
) -> None:
    """A server that took the connection and never answered the handshake is
    found unreachable once the handshake has waited its own bound - not the
    bound a tool's answer waits, and not never.

    A tool's bound is as long as the tier's slowest tool may take - the write
    tier's is twelve minutes - and a handshake is no tool's work. A read is
    asked again over a new session, whose handshake waits its own bound too:
    both are held here, and nothing was sent.
    """
    Scenario() \
        .given(
            running_double,
            calling(lambda: running_double.hold_the_next(
                A_HANDSHAKE, times=TWO_SESSIONS, seconds=LONGER_THAN_THE_TEST_WILL_WAIT
            ))
        ) \
        .when(
            _asking_with_no_patience_for_what_is_not_a_call(running_double, _asking_once)
        ) \
        .then(all_of(
            _what_was_raised_was(McpUnreachable),
            _the_double_held(running_double, A_HANDSHAKE, times=TWO_SESSIONS)
        ))


@pytest.mark.component
def test_a_list_of_tools_that_got_no_answer_ends_at_the_bound_for_what_is_not_a_call(
    running_double: RunningDouble
) -> None:
    """A list of a server's tools that got no answer ends once it has waited
    the bound for everything that is not a tool call - as the handshake does,
    and not at the bound a tool's answer waits.

    A list is no tool's work either, the SDK's own after a session's first call
    to a tool included. The list is asked again over a new session, whose list
    is held too; that session's handshake waits the same short bound, so on a
    loaded machine the second asking may end at the handshake instead - either
    way it ends, and it is the list that was held.
    """
    Scenario() \
        .given(
            running_double,
            calling(lambda: running_double.hold_the_next(
                A_LIST_OF_TOOLS, times=TWO_SESSIONS, seconds=LONGER_THAN_THE_TEST_WILL_WAIT
            ))
        ) \
        .when(
            _asking_with_no_patience_for_what_is_not_a_call(running_double, _listing)
        ) \
        .then(all_of(
            _a_failure_came_back(),
            _the_double_held_some(running_double, A_LIST_OF_TOOLS)
        ))


@pytest.mark.component
def test_a_bound_for_one_asking_never_waits_past_the_client_s_own(
    running_double: RunningDouble
) -> None:
    """A bound given for one asking can shorten its wait and never lengthen it:
    the bound a client was built with is the longest any asking waits.

    The tier sets that bound as the longest its slowest tool may take, and an
    asking let past it would wait on an answer the tier has given up on.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_bounded_by_and_told_to_wait_longer(
                running_double, _stalling_once_only_and_counting(running_double)
            )
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _the_tool_was_asked(times=1)
        ))


@pytest.mark.component
def test_a_change_asked_once_whose_ping_waited_out_its_bound_is_sent_over_a_new_session(
    running_double: RunningDouble
) -> None:
    """The ping before a change asked once waits the bound its client was
    given, and a session whose ping waited it out is replaced before the change
    is sent - which is then sent once, and answered.

    The ping is held here longer than that bound and shorter than the bound a
    client given none waits, so a client keeping only the default would find
    the same session answering and send the change over it.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience_for_a_ping(
                running_double, _counting_once_only_after_a_ping_held(running_double)
            )
        ) \
        .then(all_of(
            _the_count_is(THE_FIRST_ASKING_A_SERVER_HEARD),
            _the_double_saw(running_double, A_HANDSHAKE, times=TWO_SESSIONS)
        ))


@pytest.mark.component
def test_a_call_awaited_not_to_be_asked_twice_that_got_no_answer_is_lost_after_sending(
    running_double: RunningDouble
) -> None:
    # The awaited surface takes the same word and keeps it the same way: a
    # caller on an event loop is not a caller that may restart twice.
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_TOOL, ITS_FIRST_ASKING,
                                     _stalling_awaited_once_only_and_counting(running_double))
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _the_tool_was_asked(times=1)
        ))


@pytest.mark.component
def test_a_call_not_to_be_asked_twice_over_a_session_whose_server_stopped_is_unreachable(
    running_double: RunningDouble
) -> None:
    """A held session whose server has gone is found gone before the call is
    sent, and the call fails as a server that could not be reached.

    Sent, its POST is refused at the connection, which takes the transport down
    and leaves the call to end as a call lost after it was sent - so a write
    server stopped for a moment would hand the next restart Argus asked for to
    a person, over a restart that never left this process. Nothing was sent,
    and an unreachable server says exactly that.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience_for_a_ping(
                running_double, _asking_once_only_after_the_server_stopped(running_double)
            )
        ) \
        .then(all_of(
            _what_was_raised_was(McpUnreachable),
            _what_was_raised_was_not(LostAfterSending)
        ))


@pytest.mark.unit
def test_a_held_session_s_http_client_waits_to_read_as_long_as_an_answer_may() -> None:
    # A tool written as a plain function says nothing on its stream until it
    # returns. Read with httpx's own five seconds, or the SDK's five minutes,
    # an answer the tier is still working on is dropped - and the SDK, which
    # swallows a stream that ends, leaves the call waiting for it for ever.
    some_bound = 690.0

    Scenario() \
        .when(
            lambda: an_http_client_waiting(some_bound)
        ) \
        .then(
            _it_waits_to_read_for(some_bound)
        )


@pytest.mark.component
def test_a_held_session_is_opened_over_an_http_client_waiting_its_bound_and_closed_with_it(
    running_double: RunningDouble
) -> None:
    # Built and then handed to the SDK, or the SDK builds one of its own that
    # waits five minutes to read: an answer slower than that is dropped, and
    # the call is left waiting for it for ever. So the session's requests travel
    # over the client this built for the bound, and closing puts it down.
    Scenario() \
        .given(
            running_double,
            opened := _HttpClientsOpened()
        ) \
        .when(
            _asking_over(running_double, opened, DONT_CARE_TOOL)
        ) \
        .then(all_of(
            _one_was_opened_waiting(opened, PATIENT_PAST_ANY_CALL_HERE),
            _the_session_travelled_over_it(opened, running_double.url),
            _it_was_closed_with_the_client(opened)
        ))


@pytest.mark.component
def test_a_held_session_s_http_client_waits_as_long_as_what_is_not_a_call_where_that_is_longer(
    running_double: RunningDouble
) -> None:
    # A tier may set its call bound under the bound for everything that is not
    # a call. An HTTP client reading only for the call bound would then drop a
    # handshake's answer the session is still waiting for - and the SDK, which
    # swallows a read that timed out, would leave the handshake waiting out its
    # whole bound for an answer already gone.
    Scenario() \
        .given(
            running_double,
            opened := _HttpClientsOpened()
        ) \
        .when(
            _asking_over_with_more_patience_for_what_is_not_a_call(
                running_double, opened, DONT_CARE_TOOL
            )
        ) \
        .then(
            _one_was_opened_waiting(opened, MORE_PATIENT_THAN_ANY_CALL_HERE)
        )


@pytest.mark.component
def test_a_change_that_may_be_asked_again_and_got_no_answer_either_time_is_lost_after_sending(
    running_double: RunningDouble
) -> None:
    """A change that may be asked again is asked once more where it got no
    answer - and where that asking got none either, it is lost after sending.

    A write whose second asking finds its own mark is answered as made, so
    asking again is how a lost answer is recovered. But the first asking was
    sent, and may be carrying the change out still; a change no asking answered
    says nothing can say whether it was carried out, as a change asked once
    does, rather than raising the second asking's own failure.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_TOOL, BOTH_OF_ITS_ASKINGS,
                                     _stalling_and_counting(running_double))
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _the_tool_was_asked(times=BOTH_ASKINGS)
        ))


@pytest.mark.component
def test_a_read_that_got_no_answer_either_time_raises_the_second_asking_s_failure(
    running_double: RunningDouble
) -> None:
    """A read is asked once more where it got no answer, as a change that may be
    asked again is - and where that asking got none either, it fails as the
    second asking failed, not as lost after sending.

    A read changes nothing: there is nothing out there that nobody can account
    for, so nothing for "nothing can say whether it was carried out" to say.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_TOOL, BOTH_OF_ITS_ASKINGS,
                                     _stalling_and_counting(running_double, kind=Asking.READ))
        ) \
        .then(all_of(
            _what_was_raised_was_the_sdk_s_timeout(),
            _what_was_raised_was_not(LostAfterSending),
            _the_tool_was_asked(times=BOTH_ASKINGS)
        ))


@pytest.mark.component
def test_a_change_that_may_be_asked_again_sent_and_unanswered_whose_server_then_went_is_lost(
    running_double: RunningDouble
) -> None:
    """A change sent and left unanswered, whose server is gone by its second
    asking, is lost after sending - not a server that could not be reached.

    The second asking proves nothing was sent that time; the first was sent,
    and the server may have carried it out before it went. An unreachable
    server says nothing was done, which nobody here knows.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, ENDING_THE_SERVER_TOOL, ITS_FIRST_ASKING,
                                     _asking_a_server_that_ends_on_being_asked)
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _what_was_raised_was_not(McpUnreachable)
        ))


@pytest.mark.component
def test_a_call_unanswered_and_then_refused_saying_it_left_nothing_is_lost_after_sending(
    running_double: RunningDouble
) -> None:
    """A call whose first asking got no answer, and whose second the tier
    refused before changing anything, is lost after sending.

    The refusal speaks for the second asking alone: the first was sent, and may
    be carrying the change out still. Raised as it came, it would tell the walk
    nothing was left behind by a call that may have left a change.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_THEN_LEAVING_NOTHING_TOOL,
                                     ITS_FIRST_ASKING,
                                     _refused_after_a_stall(STALLING_THEN_LEAVING_NOTHING_TOOL))
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _what_was_raised_was_not(McpToolError)
        ))


@pytest.mark.component
def test_a_call_unanswered_and_then_refused_as_changed_since_is_raised_as_it_came(
    running_double: RunningDouble
) -> None:
    """A call whose first asking got no answer, and whose second found
    somebody else acting on the service, is the refusal the second asking got,
    carrying what it left.

    Changed since is an answer about the world, whichever asking it came to:
    the tier read the estate after whatever the first asking did, and says what
    of this claim's it found landed. The walk escalates on it, as it does on
    the first asking's.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_THEN_CHANGED_SINCE_TOOL,
                                     ITS_FIRST_ASKING,
                                     _refused_after_a_stall(STALLING_THEN_CHANGED_SINCE_TOOL))
        ) \
        .then(all_of(
            _what_was_raised_was(ChangedSince),
            _what_it_left_behind_is(WHAT_WAS_LEFT_BEHIND),
            _what_was_raised_was_not(LostAfterSending)
        ))


@pytest.mark.component
def test_a_call_unanswered_and_then_answered_comes_back_with_the_second_asking_s_answer(
    running_double: RunningDouble
) -> None:
    """A call whose first asking got no answer, and whose second was answered,
    is that answer - asked twice, and lost neither time.

    The second asking is how a lost answer is recovered: a write whose second
    asking finds its own change answers as made, and that answer is the call's.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_THEN_ANSWERING_TOOL,
                                     ITS_FIRST_ASKING,
                                     _asked_after_a_stall_and_counting(
                                         running_double, STALLING_THEN_ANSWERING_TOOL))
        ) \
        .then(all_of(
            _the_answer_is(WHAT_THE_SECOND_ASKING_ANSWERED),
            _the_tool_was_asked(times=BOTH_ASKINGS)
        ))


@pytest.mark.component
def test_a_call_unanswered_and_then_refused_as_a_lost_run_is_the_lost_run(
    running_double: RunningDouble
) -> None:
    """A call whose first asking got no answer, and whose second was refused
    because the run had moved on, is the walk's own `RunLost`.

    The run is lost whatever the first asking did, and the walk stops on it
    writing nothing more - as it does on a first asking refused so.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_THEN_LOST_RUN_TOOL,
                                     ITS_FIRST_ASKING,
                                     _asked_after_a_stall_and_counting(
                                         running_double, STALLING_THEN_LOST_RUN_TOOL))
        ) \
        .then(all_of(
            _what_was_raised_was(RunLost),
            _the_tool_was_asked(times=BOTH_ASKINGS)
        ))


@pytest.mark.component
def test_a_call_whose_first_asking_never_ran_and_whose_second_got_no_answer_is_lost(
    running_double: RunningDouble
) -> None:
    """A call that may be asked again, turned away over a session the restarted
    server never opened, and asked again over a new one that got no answer, is
    lost after sending - asked once.

    The first asking provably never ran: the server answered "Session
    terminated" before any tool was asked anything. The second was sent and may
    be running still, which is all a lost call ever says.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_TOOL, ITS_SECOND_ASKING,
                                     _stalling_after_a_restart_and_counting(running_double))
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _the_tool_was_asked(times=THE_FIRST_ASKING_A_SERVER_HEARD)
        ))


@pytest.mark.component
def test_a_call_not_to_be_asked_twice_turned_away_and_then_unanswered_is_lost_asked_once(
    running_double: RunningDouble
) -> None:
    """The same for a call that must not run twice: turned away over a session
    the server forgot after answering its ping, asked again over a new one, and
    left unanswered there - lost after sending, and asked once.

    Asking again was safe because the first asking never ran; the second was
    sent, so it is not asked a third time.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _asking_with_no_patience(running_double, STALLING_TOOL, ITS_SECOND_ASKING,
                                     _stalling_once_only_over_a_session_forgotten(running_double))
        ) \
        .then(all_of(
            _what_was_raised_was(LostAfterSending),
            _the_tool_was_asked(times=THE_FIRST_ASKING_A_SERVER_HEARD)
        ))


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
def test_a_refusal_saying_it_left_nothing_is_known_to_have_changed_nothing() -> None:
    """A tier that refused before it asked for anything to change says so.

    The refusal is still an ordinary one - the platform answered and said no, so
    nothing is narrowed and nothing is spent - but a caller can now tell it from
    a failure nobody can account for, and say the estate is as it was.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_with("refuse_saying_it_left_nothing"))) \
            .then(all_of(
                _what_was_raised_was(McpToolError),
                _what_was_raised_was_not(ActionExhausted),
                _what_was_raised_was_not(PlatformUnreachable),
                _what_it_left_behind_is_known(True),
                _it_left_nothing_behind()
            ))


@pytest.mark.component
def test_a_refusal_saying_what_it_left_carries_it_and_is_known() -> None:
    """A tier refused the action's own write after suspending reconciliation.

    The application is sitting un-reconciled, and the refusal is the only record
    of it - so it travels on the failure, and the failure says that is all.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_with("refuse_saying_what_it_left"))) \
            .then(all_of(
                _what_was_raised_was(McpToolError),
                _what_was_raised_was_not(PlatformUnreachable),
                _what_it_left_behind_is_known(True),
                _what_it_left_behind_is(WHAT_WAS_LEFT_BEHIND)
            ))


@pytest.mark.component
def test_a_refusal_that_may_have_changed_more_still_carries_what_it_knows_it_left() -> None:
    """A tier whose change request may have landed, after one that surely did.

    Not known: the request whose answer was lost may be taking effect this
    second. What the earlier calls answered for is still carried, because the
    suspension they report is in place either way and something has to put it
    back.
    """
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_with("refuse_with_what_it_left"))) \
            .then(all_of(
                _what_was_raised_was(McpToolError),
                _what_was_raised_was_not(PlatformUnreachable),
                _what_it_left_behind_is_known(False),
                _what_it_left_behind_is(WHAT_WAS_LEFT_BEHIND)
            ))


@pytest.mark.component
def test_an_ordinary_refusal_is_not_known_to_have_changed_nothing(
    running_double: RunningDouble
) -> None:
    """A tool that raised for a reason nobody foresaw has said nothing about the
    estate, and is not taken to have said it was untouched."""
    Scenario() \
        .given(running_double) \
        .when(_asking(running_double, _refusing_once_and_counting)) \
        .then(all_of(
            _what_it_left_behind_is_known(False),
            _it_left_nothing_behind()
        ))


@pytest.mark.component
@pytest.mark.parametrize(
    "tool", ["refuse_as_exhausted", "refuse_as_unreachable_platform"],
    ids=["exhausted", "unreachable platform"]
)
def test_a_refusal_marked_for_its_kind_is_known_to_say_what_it_left(tool: str) -> None:
    """Both markers already promise it: an exhausted action is spent before
    anything is touched, and a platform is only marked unreachable where the
    tier can say what it left behind."""
    with a_running_double() as double:
        Scenario() \
            .given(double) \
            .when(_asking(double, _refusing_with(tool))) \
            .then(_what_it_left_behind_is_known(True))


@pytest.mark.unit
def test_a_refusal_says_it_is_known_before_the_descriptor_it_carries() -> None:
    # The descriptor runs to the end of the message, which is how it is read
    # back: anything after it would be read as part of it.
    Scenario() \
        .given(WHAT_WAS_LEFT_BEHIND) \
        .when(lambda: a_refusal_saying_what_it_left(WHAT_THE_TIER_SAID, WHAT_WAS_LEFT_BEHIND)) \
        .then(all_of(
            _the_marker_comes_before_the_payload(),
            _it_reads_back_as(WHAT_WAS_LEFT_BEHIND)
        ))


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
    has one, which is every route in `web_app`. Nothing there reaches a tool
    today; the day something does, it gets an answer.
    """
    Scenario() \
        .given(running_double) \
        .when(
            _awaiting(running_double, DONT_CARE_TOOL)
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


@pytest.mark.unit
def test_a_call_arriving_with_baggage_is_served_with_it() -> None:
    # The incident and the run a walk put in its baggage cross with the call,
    # so a line the server logs while answering says whose incident it was.
    some_incident = "4f0c2a1e-5b6d-4c3e-9a8b-7d6e5f4c3b2a"

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: _the_baggage_while_served(observed, {
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "baggage": f"{ARGUS_INCIDENT_ID}={some_incident}"
            })
        ) \
        .then(
            _the_server_saw(ARGUS_INCIDENT_ID, some_incident)
        )


@pytest.mark.unit
def test_a_server_answers_one_call_at_a_time() -> None:
    # As every Argus server always has: no tool here was written to share its
    # state with another running beside it, and the SDK runs each one on a
    # worker thread of its own. A second call, sent while the first is still
    # being answered, begins once the first has ended.
    answered: list[str] = []

    Scenario() \
        .given(
            server := _a_server_held_open_until_a_second_call(answered)
        ) \
        .when(
            lambda: _two_calls_at_once(server, A_TOOL_HELD_OPEN)
        ) \
        .then(
            _happened_in_order(answered, ["began", "ended"] * 2)
        )


@pytest.mark.unit
def test_a_server_is_served_with_its_logging_left_to_the_root() -> None:
    # uvicorn's own logging config gives its loggers handlers of their own and
    # stops them propagating, so nothing it said reached the root - nor, since
    # the root is where telemetry listens, a server's `logs.jsonl`. Served
    # without it, its records go wherever every other record goes.
    Scenario() \
        .given(
            a_server := TracedMCPServer("some-server", host="127.0.0.1", port=8123),
            run := create_autospec(uvicorn.run)
        ) \
        .when(
            lambda: a_server.serve(run=run)
        ) \
        .then(
            _it_was_served_with_its_logging_left_to_the_root(run, "127.0.0.1", 8123)
        )


@pytest.mark.component
def test_a_session_that_could_not_be_opened_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Every attempt, each naming where it was aimed: a server that is down and
    # a client pointed at the wrong address look identical from the caller's
    # side, and the address is what tells them apart.
    Scenario() \
        .when(
            attempting(_asking_a_client_at(NOTHING_IS_LISTENING_HERE))
        ) \
        .then(
            _every_attempt_to_open_a_session_was_logged(caplog, NOTHING_IS_LISTENING_HERE)
        )


@pytest.mark.component
def test_a_call_asked_again_over_a_new_session_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Recovered from, usually - a restarted server, an idle timeout - and so
    # never seen by the walk. Which is exactly why it is said here: a server
    # restarting every few minutes is otherwise invisible.
    Scenario() \
        .when(
            attempting(_asking_a_client_at(NOTHING_IS_LISTENING_HERE))
        ) \
        .then(
            one_record_was_logged(caplog, "mcp_transport.transport", logging.WARNING,
                                  "tool call asked again over a new session",
                                  values={"tool": DONT_CARE_TOOL},
                                  failure=McpUnreachable)
        )


@pytest.mark.unit
def test_a_tool_that_raised_is_logged_as_a_warning_by_the_server(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The one place every failed tool call on both servers passes through, so
    # a server's log says what it refused without each tool saying it.
    some_tool = "roll_back_deployment"

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            attempting(lambda: _served_raising(observed, some_tool, RuntimeError("refused")))
        ) \
        .then(
            one_record_was_logged(caplog, "mcp_transport.transport", logging.WARNING,
                                  "tool call failed",
                                  values={"tool": some_tool},
                                  failure=RuntimeError)
        )


class _CountingArrivals(TracedMCPServer):
    """A server that counts each call as it arrives - before it waits its turn
    - and says when a second has."""

    def __init__(self) -> None:
        super().__init__("some-server", host=DONT_CARE_HOST, port=DONT_CARE_PORT)
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


def _a_server_held_open_until_a_second_call(answered: list[str]) -> TracedMCPServer:
    """A server with one tool that, once begun, stays open until a second call
    has arrived - and says when it began and ended into `answered`."""
    server = _CountingArrivals()

    @server.tool(name=A_TOOL_HELD_OPEN)
    def held_open() -> list[str]:
        answered.append("began")
        server.a_second_arrived.wait(LONG_PAST_ANY_ARRIVAL_SECONDS)
        answered.append("ended")

        return ["answered"]

    return server


def _two_calls_at_once(server: TracedMCPServer, tool: str) -> list[CallToolResult]:
    """`tool` asked twice at once over one session held in memory - the second
    sent while the first is still being answered."""
    async def over_a_session() -> list[CallToolResult]:
        async with Client(server, mode=LEGACY_HANDSHAKE) as session:
            return list(await asyncio.gather(session.call_tool(tool, {}),
                                             session.call_tool(tool, {})))

    return asyncio.run(over_a_session())


def _happened_in_order(happened: list[str], expected: list[str]) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        if happened != expected:
            raise AssertionError(f"Expected {expected} in that order, got {happened}.")

        return True

    return assertion


def _a_listed_tool(name: str) -> Tool:
    return Tool(name=name, description="dont care what it does",
                input_schema={"type": "object", "properties": {}})


def _the_tools_listed_are(expected: list[str]) -> Assertion[list[Tool]]:
    def assertion(listed: list[Tool]) -> bool:
        names = [tool.name for tool in listed]

        if names != expected:
            raise AssertionError(f"Expected the server's tools listed as {expected}, "
                                 f"got {names}.")

        return True

    return assertion


def _the_tool_listed_requires(name: str, required: list[str]) -> Assertion[list[Tool]]:
    def assertion(listed: list[Tool]) -> bool:
        declared = _the_tool_named(listed, name).input_schema.get("required")

        if declared != required:
            raise AssertionError(
                f"Expected [{name}] to require {required}, got {declared}."
            )

        return True

    return assertion


def _the_tool_listed_is_described(name: str, words: str) -> Assertion[list[Tool]]:
    def assertion(listed: list[Tool]) -> bool:
        described = _the_tool_named(listed, name).description or ""

        if words not in described:
            raise AssertionError(f"Expected [{name}] described with [{words}], got "
                                 f"[{described}].")

        return True

    return assertion


def _the_tool_named(listed: list[Tool], name: str) -> Tool:
    found = [tool for tool in listed if tool.name == name]

    if len(found) != 1:
        raise AssertionError(f"Expected one tool named [{name}], got {len(found)}.")

    return found[0]


def _served_raising(observed: Observed, tool: str, error: Exception) -> None:
    """The server's half alone: one tool call that raised while it was served."""
    with serving_a_tool_call(tool, None, tracer=observed.tracer):
        raise error


def _every_attempt_to_open_a_session_was_logged(caplog: pytest.LogCaptureFixture,
                                                url: str) -> Assertion[Any]:
    """At least one attempt said, and every one that was said naming `url`.

    Not exactly one: a call opens a session, finds it failed, and opens another
    before it gives up - and how many attempts that is belongs to the retry,
    not to what each attempt says.
    """
    def assertion(_raised: Any) -> bool:
        said = [
            record for record in caplog.records
            if record.name == "mcp_transport.transport"
            and record.levelno == logging.WARNING
            and record.getMessage() == "session could not be opened"
        ]
        aimed_at = [getattr(record, "url", None) for record in said]

        if not said or set(aimed_at) != {url}:
            raise AssertionError(
                f"Expected every attempt to open a session to be logged as a warning "
                f"naming [{url}], and the attempts logged named {aimed_at}."
            )

        return True

    return assertion


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
        client.call("refuse", SOMETHING.validate_python, asking=Asking.READ)
    except Exception as refusal:
        return _Attempt(
            raised=refusal,
            asked=client.call("times_refused", A_COUNT.validate_python, asking=Asking.READ)
        )

    return _Attempt(asked=client.call("times_refused", A_COUNT.validate_python, asking=Asking.READ))


def _refusing_without_a_word(client: McpClient) -> _Attempt:
    try:
        client.call("refuse_without_a_word", SOMETHING.validate_python, asking=Asking.READ)
    except Exception as refusal:
        return _Attempt(raised=refusal)

    return _Attempt()


def _refusing_as_a_lost_run_and_counting(client: McpClient) -> _Attempt:
    try:
        client.call("refuse_as_lost_run", SOMETHING.validate_python, asking=Asking.READ)
    except Exception as refusal:
        return _Attempt(
            raised=refusal,
            asked=client.call("times_refused", A_COUNT.validate_python, asking=Asking.READ)
        )

    return _Attempt(asked=client.call("times_refused", A_COUNT.validate_python, asking=Asking.READ))


def _the_fence_sent(client: McpClient) -> object:
    return client.call("the_fence_i_was_sent", A_FENCE_HEARD.validate_python, asking=Asking.READ)


def _the_fence_sent_while_holding(holding: Holding, held: Fence, client: McpClient) -> object:
    with holding.of(held):
        return _the_fence_sent(client)


def _the_action_sent(client: McpClient) -> object:
    return client.call("the_action_i_was_sent", AN_ACTION_HEARD.validate_python, asking=Asking.READ)


def _the_action_sent_while_acting_for(holding: Holding,
                                      action_id: str,
                                      client: McpClient) -> object:
    with holding.acting_for(action_id):
        return _the_action_sent(client)


def _asking_while_holding[T](double: RunningDouble,
                             holding: Holding,
                             held: Fence,
                             ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """`_asking`, with `held` held by the process for the length of the call."""
    def step() -> T:
        with (
            McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                      holding=holding) as client,
            holding.of(held)
        ):
            return ask(client)

    return step


def _asking_holding[T](double: RunningDouble,
                       holding: Holding | None,
                       ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """`_asking`, by a client handed `holding` - or handed none."""
    def step() -> T:
        with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                       holding=holding) as client:
            return ask(client)

    return step


def _refusing_then_asking_something_else(client: McpClient) -> _Attempt:
    with suppress(McpToolError):
        client.call("refuse", SOMETHING.validate_python, asking=Asking.READ)

    return _Attempt(answer=client.call(DONT_CARE_TOOL, SOMETHING.validate_python,
                                       asking=Asking.READ))


def _asking_either_side_of_a_restart(
    double: RunningDouble
) -> Callable[[McpClient], _Attempt]:
    def both_calls(client: McpClient) -> _Attempt:
        client.call(DONT_CARE_TOOL, SOMETHING.validate_python, asking=Asking.READ)
        double.restart()

        return _Attempt(answer=client.call(DONT_CARE_TOOL, SOMETHING.validate_python,
                                           asking=Asking.READ))

    return both_calls


def _asking[T](double: RunningDouble,
               ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """One client to the double, held for one `when` and closed after it."""
    def step() -> T:
        with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE) as client:
            return ask(client)

    return step


def _asking_a_client_at(url: str) -> Callable[[], object]:
    def step() -> object:
        with McpClient(url, answered_within=PATIENT_PAST_ANY_CALL_HERE) as client:
            return client.call(DONT_CARE_TOOL, SOMETHING.validate_python, asking=Asking.READ)

    return step


def _asking_once_only_a_client_at(url: str) -> Callable[[], object]:
    def step() -> object:
        with McpClient(url, answered_within=PATIENT_PAST_ANY_CALL_HERE) as client:
            return client.call(DONT_CARE_TOOL, SOMETHING.validate_python,
                               asking=Asking.CHANGE_ASKED_ONCE)

    return step


def _asking_with_no_patience[T](double: RunningDouble,
                                tool: str,
                                askings: frozenset[WhichAsking],
                                ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """`_asking`, by a client that takes the askings in `askings` of a call to
    `tool` to be lost once each has waited `SOON_ENOUGH_TO_GIVE_UP` for its
    answer - and waits as `_asking`'s does for everything else, so the asking a
    case stalls on is the only one that can meet the short bound."""
    def step() -> T:
        with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                       answered_within_for=_giving_up_soon_on(tool, askings)) as client:
            return ask(client)

    return step


def _giving_up_soon_on(tool: str, askings: frozenset[WhichAsking]) -> AskingBound:
    """`SOON_ENOUGH_TO_GIVE_UP` for the askings in `askings` of a call to
    `tool`, and `PATIENT_PAST_ANY_CALL_HERE` for every other."""
    def waits(name: str, which: WhichAsking) -> float:
        if name == tool and which in askings:
            return SOON_ENOUGH_TO_GIVE_UP

        return PATIENT_PAST_ANY_CALL_HERE

    return waits


def _asking_bounded_by_and_told_to_wait_longer[T](
    double: RunningDouble,
    ask: Callable[[McpClient], T]
) -> Callable[[], T]:
    """`_asking`, by a client built with `SOON_ENOUGH_TO_GIVE_UP` as its bound
    and told every asking may wait `PATIENT_PAST_ANY_CALL_HERE`."""
    def step() -> T:
        with McpClient(double.url, answered_within=SOON_ENOUGH_TO_GIVE_UP,
                       answered_within_for=lambda _, __: PATIENT_PAST_ANY_CALL_HERE) as client:
            return ask(client)

    return step


def _asking_with_no_patience_for_a_ping[T](double: RunningDouble,
                                          ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """`_asking`, by a client that takes a held session to be gone once the ping
    before a change asked once has waited `SOON_ENOUGH_TO_GIVE_UP` - a ping over
    a session whose server has gone is never answered, refused or not."""
    def step() -> T:
        with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                       pinged_within=SOON_ENOUGH_TO_GIVE_UP) as client:
            return ask(client)

    return step


def _asking_with_no_patience_for_what_is_not_a_call(
    double: RunningDouble,
    ask: Callable[[McpClient], object]
) -> Callable[[], _Attempt]:
    """`ask` made on a daemon thread, by a client whose every request that is
    not a tool call - the handshake, a list of tools - is given up once it has
    waited `SOON_ENOUGH_TO_GIVE_UP`, and which waits for a tool's answer past
    anything here."""
    def step() -> _Attempt:
        with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                       not_a_call_within=SOON_ENOUGH_TO_GIVE_UP) as client:
            return _on_a_daemon_thread(lambda: ask(client))

    return step


def _asking_once(client: McpClient) -> object:
    """`DONT_CARE_TOOL`, asked as a read."""
    return client.call(DONT_CARE_TOOL, SOMETHING.validate_python, asking=Asking.READ)


def _listing(client: McpClient) -> object:
    """Every tool the server lists."""
    return client.list_tools()


def _counting_once_only_after_a_ping_held(double: RunningDouble) -> Callable[[McpClient], _Attempt]:
    """A session opened, the double told to hold the next ping it is sent for
    `LONGER_THAN_GIVING_UP_SHORTER_THAN_THE_DEFAULT_PING`, and `COUNTING_TOOL`
    asked as a call not to be asked twice - which pings first."""
    def asking(client: McpClient) -> _Attempt:
        client.call(DONT_CARE_TOOL, SOMETHING.validate_python, asking=Asking.READ)
        double.hold_the_next(A_PING, times=1,
                             seconds=LONGER_THAN_GIVING_UP_SHORTER_THAN_THE_DEFAULT_PING)

        try:
            return _Attempt(answer=client.call(COUNTING_TOOL, A_COUNT.validate_python,
                                               asking=Asking.CHANGE_ASKED_ONCE))
        except Exception as failed:
            return _Attempt(raised=failed)

    return asking


def _asking_bounded_only_by[T](double: RunningDouble,
                               seconds: float,
                               ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """`_asking`, by a client given `seconds` as its bound and nothing else - as
    every tier builds its own."""
    def step() -> T:
        with McpClient(double.url, answered_within=seconds) as client:
            return ask(client)

    return step


def _counting_once_only_either_side_of_a_restart(
    double: RunningDouble
) -> Callable[[McpClient], _Attempt]:
    """One asking over a session, the server restarted beneath it, and one more
    over the session the client still holds - neither to be asked twice."""
    def both_askings(client: McpClient) -> _Attempt:
        client.call(COUNTING_TOOL, A_COUNT.validate_python, asking=Asking.CHANGE_ASKED_ONCE)
        double.restart()

        try:
            return _Attempt(answer=client.call(COUNTING_TOOL, A_COUNT.validate_python,
                                               asking=Asking.CHANGE_ASKED_ONCE))
        except Exception as failed:
            return _Attempt(raised=failed)

    return both_askings


def _counting_once_only_over_a_session_forgotten_after_its_ping(client: McpClient) -> _Attempt:
    """The server told to forget the session its next ping is answered over,
    and one asking not to be asked twice - which pings first, over the session
    the client holds."""
    client.call(FORGETTING_AFTER_A_PING_TOOL, SOMETHING.validate_python, asking=Asking.READ)

    try:
        return _Attempt(answer=client.call(COUNTING_TOOL, A_COUNT.validate_python,
                                           asking=Asking.CHANGE_ASKED_ONCE))
    except Exception as failed:
        return _Attempt(raised=failed)


def _times_stalled_on(double: RunningDouble) -> int:
    """How many askings of `STALLING_TOOL` the double counted, asked by a client
    of its own that waits past any answer here - so a slow count is an answer,
    never a failure of the case it is counted for."""
    with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE) as counting:
        return counting.call("times_stalled", A_COUNT.validate_python, asking=Asking.READ)


def _on_a_daemon_thread(call: Callable[[], object]) -> _Attempt:
    """`call` made on a daemon thread, and waited for no longer than
    `LONG_ENOUGH_TO_HAVE_COME_BACK` - for `_closing_while_a_call_is_in_flight`'s
    reason: a client that strands a stalled call fails the case, rather than
    holding the test thread, and the suite, for ever."""
    answered: queue.Queue[_Attempt] = queue.Queue()

    def call_and_report() -> None:
        try:
            answered.put(_Attempt(answer=call()))
        except Exception as failed:
            answered.put(_Attempt(raised=failed))

    threading.Thread(target=call_and_report, daemon=True).start()

    try:
        return answered.get(timeout=LONG_ENOUGH_TO_HAVE_COME_BACK)
    except Empty:
        raise AssertionError("The stalled call never came back: it was stranded.") from None


def _stalling_once_only_and_counting(double: RunningDouble) -> Callable[[McpClient], _Attempt]:
    def stalling(client: McpClient) -> _Attempt:
        attempt = _on_a_daemon_thread(lambda: client.call(
            STALLING_TOOL, SOMETHING.validate_python, asking=Asking.CHANGE_ASKED_ONCE,
            seconds=LONGER_THAN_THE_TEST_WILL_WAIT
        ))

        return attempt._replace(asked=_times_stalled_on(double))

    return stalling


def _stalling_awaited_once_only_and_counting(
    double: RunningDouble
) -> Callable[[McpClient], _Attempt]:
    def stalling(client: McpClient) -> _Attempt:
        async def from_inside_a_loop() -> object:
            return await client.acall(STALLING_TOOL, SOMETHING.validate_python,
                                      asking=Asking.CHANGE_ASKED_ONCE,
                                      seconds=LONGER_THAN_THE_TEST_WILL_WAIT)

        attempt = _on_a_daemon_thread(lambda: asyncio.run(from_inside_a_loop()))

        return attempt._replace(asked=_times_stalled_on(double))

    return stalling


def _stalling_and_counting(double: RunningDouble,
                           kind: Asking = Asking.CHANGE) -> Callable[[McpClient], _Attempt]:
    """`STALLING_TOOL` asked as `kind` of call - a change that may be asked
    again, unless a case names a read - with how many askings the double
    counted."""
    def stalling(client: McpClient) -> _Attempt:
        attempt = _on_a_daemon_thread(lambda: client.call(
            STALLING_TOOL, SOMETHING.validate_python, asking=kind,
            seconds=LONGER_THAN_THE_TEST_WILL_WAIT
        ))

        return attempt._replace(asked=_times_stalled_on(double))

    return stalling


def _refused_after_a_stall(tool: str) -> Callable[[McpClient], _Attempt]:
    """`tool` asked once, as a change that may be asked again: its first asking
    stalls past what the client waits, and its second is refused."""
    def asking(client: McpClient) -> _Attempt:
        return _on_a_daemon_thread(lambda: client.call(
            tool, SOMETHING.validate_python, asking=Asking.CHANGE,
            seconds=LONGER_THAN_THE_TEST_WILL_WAIT
        ))

    return asking


def _times_asked_stalling_first_on(double: RunningDouble) -> int:
    """How many askings the double's tools that stall at the first counted,
    asked as `_times_stalled_on` asks."""
    with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE) as counting:
        return counting.call("times_asked_stalling_first", A_COUNT.validate_python,
                             asking=Asking.READ)


def _asked_after_a_stall_and_counting(double: RunningDouble,
                                      tool: str) -> Callable[[McpClient], _Attempt]:
    """`tool` asked once, as a change that may be asked again: its first asking
    stalls past what the client waits, and its second is answered or refused -
    with how many askings the double counted."""
    def asking(client: McpClient) -> _Attempt:
        attempt = _on_a_daemon_thread(lambda: client.call(
            tool, SOMETHING.validate_python, asking=Asking.CHANGE,
            seconds=LONGER_THAN_THE_TEST_WILL_WAIT
        ))

        return attempt._replace(asked=_times_asked_stalling_first_on(double))

    return asking


def _stalling_after_a_restart_and_counting(
    double: RunningDouble
) -> Callable[[McpClient], _Attempt]:
    """A session opened, the server restarted beneath it, and `STALLING_TOOL`
    asked over it as a change that may be asked again: turned away there, and
    asked again over a new session where it stalls."""
    def asking(client: McpClient) -> _Attempt:
        client.call(DONT_CARE_TOOL, SOMETHING.validate_python, asking=Asking.READ)
        double.restart()
        attempt = _on_a_daemon_thread(lambda: client.call(
            STALLING_TOOL, SOMETHING.validate_python, asking=Asking.CHANGE,
            seconds=LONGER_THAN_THE_TEST_WILL_WAIT
        ))

        return attempt._replace(asked=_times_stalled_on(double))

    return asking


def _stalling_once_only_over_a_session_forgotten(
    double: RunningDouble
) -> Callable[[McpClient], _Attempt]:
    """The server told to forget the session its next ping is answered over, and
    `STALLING_TOOL` asked as a call not to be asked twice: its ping answered,
    the call turned away over the forgotten session, and asked again over a new
    one where it stalls."""
    def asking(client: McpClient) -> _Attempt:
        client.call(FORGETTING_AFTER_A_PING_TOOL, SOMETHING.validate_python, asking=Asking.READ)
        attempt = _on_a_daemon_thread(lambda: client.call(
            STALLING_TOOL, SOMETHING.validate_python, asking=Asking.CHANGE_ASKED_ONCE,
            seconds=LONGER_THAN_THE_TEST_WILL_WAIT
        ))

        return attempt._replace(asked=_times_stalled_on(double))

    return asking


def _asking_a_server_that_ends_on_being_asked(client: McpClient) -> _Attempt:
    """`ENDING_THE_SERVER_TOOL` asked as a change that may be asked again: its
    server is gone the moment it has the asking, so the second asking finds no
    server."""
    return _on_a_daemon_thread(lambda: client.call(ENDING_THE_SERVER_TOOL,
                                                   SOMETHING.validate_python,
                                                   asking=Asking.CHANGE))


def _asking_once_only_after_the_server_stopped(
    double: RunningDouble
) -> Callable[[McpClient], _Attempt]:
    """One asking over a session, the server stopped beneath it, and one more
    over the session the client still holds - not to be asked twice."""
    def both_askings(client: McpClient) -> _Attempt:
        client.call(DONT_CARE_TOOL, SOMETHING.validate_python, asking=Asking.READ)
        double.stop()

        try:
            return _Attempt(answer=client.call(DONT_CARE_TOOL, SOMETHING.validate_python,
                                               asking=Asking.CHANGE_ASKED_ONCE))
        except Exception as failed:
            return _Attempt(raised=failed)

    return both_askings


def _it_waits_to_read_for(seconds: float) -> Assertion[httpx2.AsyncClient]:
    def assertion(http_client: httpx2.AsyncClient) -> bool:
        waits = http_client.timeout.read

        if waits != seconds:
            raise AssertionError(
                f"Expected the HTTP client to wait [{seconds}]s to read, it waits [{waits}]s."
            )

        return True

    return assertion


class _HttpClientsOpened:
    """Every HTTP client a held session was opened over: each as the
    transport's own `an_http_client_waiting` builds it, what it was asked to
    wait, and every request it carried."""

    def __init__(self) -> None:
        self.waiting: list[float] = []
        self.clients: list[httpx2.AsyncClient] = []
        self.carried: list[str] = []

    def __call__(self, answered_within: float) -> httpx2.AsyncClient:
        self.waiting.append(answered_within)
        http_client = an_http_client_waiting(answered_within)
        http_client.event_hooks = {"request": [self._carrying], "response": []}
        self.clients.append(http_client)

        return http_client

    async def _carrying(self, request: httpx2.Request) -> None:
        self.carried.append(str(request.url))


def _asking_over(double: RunningDouble,
                 opened: _HttpClientsOpened,
                 tool: str) -> Callable[[], object]:
    """One call, by a client whose sessions are opened over what `opened`
    builds, closed once it is answered."""
    def step() -> object:
        with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                       http_client_waiting=opened) as client:
            return client.call(tool, SOMETHING.validate_python, asking=Asking.READ)

    return step


def _asking_over_with_more_patience_for_what_is_not_a_call(
    double: RunningDouble,
    opened: _HttpClientsOpened,
    tool: str
) -> Callable[[], object]:
    """`_asking_over`, by a client whose bound for everything that is not a
    call, `MORE_PATIENT_THAN_ANY_CALL_HERE`, is longer than its call bound."""
    def step() -> object:
        with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                       not_a_call_within=MORE_PATIENT_THAN_ANY_CALL_HERE,
                       http_client_waiting=opened) as client:
            return client.call(tool, SOMETHING.validate_python, asking=Asking.READ)

    return step


def _one_was_opened_waiting(opened: _HttpClientsOpened, seconds: float) -> Assertion[object]:
    def assertion(dont_care_answer: object) -> bool:
        if opened.waiting != [seconds]:
            raise AssertionError(
                f"Expected one HTTP client opened, waiting [{seconds}]s to read, and the "
                f"ones opened were asked to wait {opened.waiting}."
            )

        return True

    return assertion


def _the_session_travelled_over_it(opened: _HttpClientsOpened, url: str) -> Assertion[object]:
    def assertion(dont_care_answer: object) -> bool:
        if not opened.carried or set(opened.carried) != {url}:
            raise AssertionError(
                f"Expected the session's requests carried to [{url}] over the HTTP client "
                f"opened for it, and it carried {opened.carried}."
            )

        return True

    return assertion


def _it_was_closed_with_the_client(opened: _HttpClientsOpened) -> Assertion[object]:
    def assertion(dont_care_answer: object) -> bool:
        still_open = [http_client for http_client in opened.clients if not http_client.is_closed]

        if still_open:
            raise AssertionError(
                f"Expected every HTTP client opened closed with the client, and "
                f"{len(still_open)} of {len(opened.clients)} were still open."
            )

        return True

    return assertion


def _the_count_is(expected: int) -> Assertion[_Attempt]:
    def assertion(attempt: _Attempt) -> bool:
        if attempt.raised is not None:
            raise AssertionError(
                f"Expected the server to count [{expected}], but {attempt.raised!r} was raised."
            )

        if attempt.answer != expected:
            raise AssertionError(
                f"Expected the server to count [{expected}], it counted [{attempt.answer}]."
            )

        return True

    return assertion


def _awaiting(double: RunningDouble, tool: str) -> Callable[[], _Attempt]:
    """The same call, made from inside a running event loop."""
    async def from_inside_a_loop(client: McpClient) -> _Attempt:
        return _Attempt(answer=await client.acall(tool, SOMETHING.validate_python,
                                                  asking=Asking.READ))

    def step() -> _Attempt:
        with McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE) as client:
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


def _what_was_raised_was_the_sdk_s_timeout() -> Assertion[_Attempt]:
    """The SDK's own failure for an answer not come back in time: an `MCPError`
    whose code is MCP's request timeout (`mcp/shared/jsonrpc_dispatcher.py`,
    `send_request`)."""
    def assertion(attempt: _Attempt) -> bool:
        raised = attempt.raised

        if not isinstance(raised, MCPError) or raised.error.code != REQUEST_TIMEOUT:
            raise AssertionError(
                f"Expected the SDK's timeout raised - MCPError with code "
                f"[{REQUEST_TIMEOUT}] - got {raised!r}."
            )

        return True

    return assertion


def _what_was_raised_said(expected: str) -> Assertion[_Attempt]:
    def assertion(attempt: _Attempt) -> bool:
        said = None if attempt.raised is None else str(attempt.raised)

        if said != expected:
            raise AssertionError(
                f"Expected the refusal to say [{expected}], and it said [{said}]."
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


def _a_failure_came_back() -> Assertion[_Attempt]:
    def assertion(attempt: _Attempt) -> bool:
        if attempt.raised is None:
            raise AssertionError(
                f"Expected a failure to come back, the answer [{attempt.answer}] did."
            )

        return True

    return assertion


def _the_double_held(double: RunningDouble, method: str, times: int) -> Assertion[_Attempt]:
    """The double held `times` requests whose method is `method` - read off its
    control route, so reading it opens no session an armed hold could hold."""
    def assertion(_: _Attempt) -> bool:
        held = double.requests_held(method)

        if held != times:
            raise AssertionError(
                f"Expected the server to have held [{times}] [{method}] request(s), "
                f"it held [{held}]."
            )

        return True

    return assertion


def _the_double_held_some(double: RunningDouble, method: str) -> Assertion[_Attempt]:
    """The double held at least one request whose method is `method`."""
    def assertion(_: _Attempt) -> bool:
        held = double.requests_held(method)

        if held == 0:
            raise AssertionError(
                f"Expected the server to have held a [{method}] request, it held none."
            )

        return True

    return assertion


def _the_double_saw(double: RunningDouble, method: str, times: int) -> Assertion[_Attempt]:
    """The double was sent `times` requests whose method is `method`."""
    def assertion(_: _Attempt) -> bool:
        seen = double.requests_seen(method)

        if seen != times:
            raise AssertionError(
                f"Expected the server to have been sent [{times}] [{method}] request(s), "
                f"it was sent [{seen}]."
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
        client = McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE)
        # Opened before the thread starts, so what the close races is a call
        # over a session rather than the opening of one.
        client.call(DONT_CARE_TOOL, SOMETHING.validate_python, asking=Asking.READ)
        answered: queue.Queue[_Attempt] = queue.Queue()

        def call_and_report() -> None:
            try:
                answered.put(_Attempt(answer=client.call(
                    "dawdle",
                    SOMETHING.validate_python,
                    asking=Asking.READ,
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
        client.call("refuse_as_exhausted", SOMETHING.validate_python, asking=Asking.READ)
    except Exception as refusal:
        return _Attempt(raised=refusal)

    return _Attempt()


def _refusing_as_an_unreachable_platform(client: McpClient) -> _Attempt:
    try:
        client.call("refuse_as_unreachable_platform", SOMETHING.validate_python, asking=Asking.READ)
    except Exception as refusal:
        return _Attempt(raised=refusal)

    return _Attempt()


def _what_was_said_names(name: str) -> Assertion[_Attempt]:
    """`name` is in the words, for whoever reads the failure - the platform
    that went, or the tool whose answer was lost.

    Asserted separately from the type because the two carry different halves: the
    type is what a walk branches on, and the words are what a person reads. A
    name carried only by the type would leave the message saying something
    failed and not what.
    """
    def assertion(attempt: _Attempt) -> bool:
        if name not in str(attempt.raised):
            raise AssertionError(
                f"Expected the failure to name {name!r}, "
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
            "refuse_as_unreachable_platform_mid_action", SOMETHING.validate_python,
            asking=Asking.READ
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


def _refusing_with(tool: str) -> Callable[[McpClient], _Attempt]:
    def ask(client: McpClient) -> _Attempt:
        try:
            client.call(tool, SOMETHING.validate_python, asking=Asking.READ)
        except Exception as refusal:
            return _Attempt(raised=refusal)

        return _Attempt()

    return ask


def _what_it_left_behind_is_known(expected: bool) -> Assertion[_Attempt]:
    """Whether the failure says it carries the whole of what it left behind."""
    def assertion(attempt: _Attempt) -> bool:
        if not isinstance(attempt.raised, McpToolError):
            raise AssertionError(
                f"Expected a tool's refusal, and what was raised was {attempt.raised!r}."
            )

        if attempt.raised.left_behind_known is not expected:
            raise AssertionError(
                f"Expected the refusal to say what it left behind is "
                f"{'known' if expected else 'not known'}, and it said "
                f"left_behind_known={attempt.raised.left_behind_known}: "
                f"[{attempt.raised}]."
            )

        return True

    return assertion


def _its_change_is_said_performed(expected: bool) -> Assertion[_Attempt]:
    """Whether a changed-since refusal arrived saying the action's own change had
    landed before somebody overtook it."""
    def assertion(attempt: _Attempt) -> bool:
        if not isinstance(attempt.raised, ChangedSince):
            raise AssertionError(
                f"Expected a changed-since refusal, and what was raised was {attempt.raised!r}."
            )

        if attempt.raised.performed is not expected:
            raise AssertionError(
                f"Expected the refusal to say the change was "
                f"{'performed' if expected else 'not performed'}, and it said "
                f"performed={attempt.raised.performed}: [{attempt.raised}]."
            )

        return True

    return assertion


def _the_marker_comes_before_the_payload() -> Assertion[str]:
    def assertion(said: str) -> bool:
        marker = said.find(LEFT_BEHIND_KNOWN_MARKER)
        payload = said.find(LEFT_BEHIND_MARKER)

        if marker < 0 or payload < 0 or marker > payload:
            raise AssertionError(
                f"Expected [{LEFT_BEHIND_KNOWN_MARKER}] and then "
                f"[{LEFT_BEHIND_MARKER}], and the refusal said [{said}]."
            )

        return True

    return assertion


def _it_reads_back_as(expected: UndoDescriptor) -> Assertion[str]:
    def assertion(said: str) -> bool:
        return _it_came_back_as(expected)(what_was_left_behind(said))

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
            return client.call(tool, lambda answer: answer, asking=Asking.READ)

    if inside is None:
        return ask()

    with observed.tracer.start_as_current_span(inside):
        return ask()


def _a_client_reporting_to(double: RunningDouble,
                           observed: Observed,
                           clock: Any) -> McpClient:
    if clock is None:
        return McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                         tracer=observed.tracer, meter=observed.meter)

    return McpClient(double.url, answered_within=PATIENT_PAST_ANY_CALL_HERE,
                     tracer=observed.tracer, meter=observed.meter, clock=clock)


def _served_while_observed(observed: Observed, meta: dict[str, str] | None) -> None:
    """The server's half alone: one tool call served under whatever `meta` carried."""
    with serving_a_tool_call(DONT_CARE_TOOL, meta, tracer=observed.tracer):
        pass


def _the_baggage_while_served(observed: Observed, meta: dict[str, str]) -> dict[str, object]:
    """What the baggage held while one tool call was served under `meta`."""
    with serving_a_tool_call(DONT_CARE_TOOL, meta, tracer=observed.tracer):
        return dict(baggage.get_all())


def _the_server_saw(key: str, expected: str) -> Assertion[dict[str, object]]:
    def assertion(held: dict[str, object]) -> bool:
        if held.get(key) != expected:
            raise AssertionError(
                f"Expected the server to hold [{key}] as [{expected}] in its baggage "
                f"while it served the call, and it held {held}."
            )

        return True

    return assertion


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


def _it_was_served_with_its_logging_left_to_the_root(run: Any,
                                                      host: str,
                                                      port: int) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        served = [
            call for call in run.call_args_list
            if len(call.args) == 1 and isinstance(call.args[0], Starlette)
            and call.kwargs == {"host": host, "port": port, "log_config": None}
        ]

        if len(run.call_args_list) != 1 or len(served) != 1:
            raise AssertionError(
                f"Expected the server's app to be served once on {host}:{port}, with "
                f"uvicorn's logging config left off, and it was served "
                f"{run.call_args_list}."
            )

        return True

    return assertion
