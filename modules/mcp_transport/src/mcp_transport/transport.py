"""How Argus reaches an MCP server, and the one session it keeps to each.

A client is a connection, not a call. `streamable_http_client` and
`ClientSession` are opened once per server and held for the life of the process
that built one, because a tool call used to pay a full HTTP session setup and an
MCP `initialize` for a question that takes milliseconds to answer - up to twelve
of them in one investigation, before Mitigation has verified anything.

A held session needs two things a fresh one got for free, and both are here.

The first is that anyio's cancel scopes belong to the task that entered them, so
a context manager opened on one task and closed on another raises at shutdown,
pointing at this module rather than at whoever closed the client. One long-lived
holder coroutine therefore opens both, publishes the session, waits, and closes
them on its way out; nothing else ever enters or exits them, and what is
submitted from outside is only ever a `call_tool`.

The second is that a dropped connection used to cost one call and now poisons
every call after it - a server restart or an idle timeout would otherwise leave
a worker holding a session nothing can be asked over. So a call that fails on
the transport rebuilds the session once and asks again. A tool that was reached
and reported an error is not that, and is not retried: it answered, and asking a
second time over a new session would turn one refusal into two. Nor is a change
the caller says may be asked only once, where its failure does not prove it
never ran: a restart asked again is a second restart, so that call is lost after
sending, said so, and left to the walk. A caller says which kind of call each
is (`Asking`): a read changes nothing, and is never lost after sending.

Both surfaces run over that one session. `call` blocks the calling thread until
the answer arrives; `acall` awaits it, so a route on a FastAPI loop reaches a
tool without blocking its loop - and without the `RuntimeError` that opening an
event loop per call raised the moment a caller already had one.

Every call is traced across the boundary, both halves here because they are two
halves of one convention. The client makes each call a span and sends that
span's context in the request's `_meta`, as OTel's MCP conventions and MCP's
SEP-414 both say to; `TracedMCPServer` is the server that reads it back and
answers inside the caller's trace. `_meta` rather than an HTTP header because
the session is held: its headers were fixed when it opened, and `_meta`
travels with each call. The SDK traces each request too, on the client's loop:
each call runs there in a copy of its caller's context, so the SDK's span is
this one's child and the trace runs unbroken to the server.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from concurrent.futures import Future
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
from types import TracebackType
from typing import Any, Final, Self
from urllib.parse import urlsplit

import httpx2
import uvicorn
from core import Holding, RunLost
from core.models import UndoDescriptor
from core.telemetry import (
    ERROR_TYPE,
    GEN_AI_EXECUTE_TOOL_OPERATION,
    GEN_AI_OPERATION_NAME,
    GEN_AI_TOOL_NAME,
    MCP_CLIENT_OPERATION_DURATION,
    MCP_METHOD_NAME,
    MCP_TOOLS_CALL_METHOD,
    SERVER_ADDRESS,
    SERVER_PORT,
    UNIT_SECONDS,
)
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import UnexpectedToolError
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_REQUEST,
    CallToolResult,
    InputRequiredResult,
    ListToolsResult,
    PaginatedRequestParams,
    RequestParamsMeta,
    TextContent,
    Tool,
)
from opentelemetry import context, metrics, propagate, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer
from pydantic import TypeAdapter, ValidationError

from mcp_transport.refusals import REFUSAL_KEY, ToolRefusal, ToolRefusalKind, ToolRefused

logger = logging.getLogger(__name__)

# MCP's method for listing a server's tools, as a refusal names what was asked.
_TOOLS_LIST_METHOD: Final = "tools/list"

# Reading the clock a call's duration is measured on, so a test can hand over
# one that reads exactly what it says.
Clock = Callable[[], float]

# The instrumentation scope a call's span and duration are reported under.
_SCOPE = __name__

# MCP's own vocabulary, not Argus's. A tool answering with something that is not
# already a JSON object - a list of log lines, a list of buckets - has it wrapped
# under this key, because structured content has to be an object at the top
# level. A tool answering with a mapping is already one and arrives unwrapped.
STRUCTURED_RESULT_KEY: Final = "result"

# How long `close` waits for the holder to put the session down before it stops
# waiting. Bounded because closing is something a process does on its way out,
# and a server that has stopped answering must not be able to keep it alive.
SHUTDOWN_SECONDS: Final = 5.0

# How long a held session has to answer a ping before a change asked once is
# sent over it. Short, because a live server answers one in milliseconds and
# what is being found out is whether the session is still one: a session found
# gone is replaced before anything is sent, where the call itself, sent over
# it, would end as lost after sending.
PING_SECONDS: Final = 5.0

# How long every request over a session that is not a tool call waits for its
# answer: the handshake that opens the session, a list of its tools - the
# client's own or the one the SDK makes after a session's first call to a tool
# - and the ping's ceiling. None of it is a tool's work, so none of it may take
# as long as the slowest tool: a server that took the connection and never
# finished the handshake would otherwise hold every call waiting on it for the
# whole of the tool bound, and be found unreachable only then. Generous beside
# the milliseconds a live server takes, because a loaded machine is still a
# live one.
NOT_A_CALL_SECONDS: Final = 30.0

# How long an HTTP request waits for everything but a read - connecting,
# writing, a connection from the pool: the SDK's own bound for them
# (`mcp.shared._httpx_utils.MCP_DEFAULT_TIMEOUT`). The read is the answer bound.
_HTTP_SECONDS: Final = 30.0

# The MCP SDK's answer to a request a server turned away as made over a session
# it does not hold - a server restarted beneath a held session answers 404
# before the request reaches anything that could run it. The one failure after
# sending that proves the tool never ran. Two spellings of it, both under
# JSON-RPC's invalid-request code: the server's own error body, which the client
# hands on as it came (mcp 2.3.0, `server/streamable_http_manager.py`,
# `_error_response("Session not found", 404)`; `client/streamable_http.py`
# forwards a JSON-RPC error body), and the client's own words for a 404 that
# carried none. Pinned to that SDK version: its words, as much as its code, are
# what is matched - the code alone is every invalid request there is.
SESSION_GONE_CODE: Final = INVALID_REQUEST
SESSION_NOT_FOUND_WORDS: Final = "Session not found"
SESSION_TERMINATED_WORDS: Final = "Session terminated"


# What a server puts in front of the words of a tool that raised, the tool's
# name in it; the words after it are the tool's. The MCP SDK's own spelling,
# which `TracedMCPServer` keeps: since mcp 2.1 the SDK withholds a crashed
# tool's words, and these are what a person reads of why a change was refused.
TOOL_ERROR_PREFIX: Final = "Error executing tool {name}: "

# A call's `_meta` as the SDK types it, built from the carrier a call fills:
# validated rather than cast, so a key the type cannot hold fails here.
_AS_REQUEST_META: Final = TypeAdapter(RequestParamsMeta)

# Where in a call's `_meta` the claim it is made for is said, as `Fence.spoken`
# says it. In `_meta` rather than a header for the trace's reason: the session
# is held, and its headers were fixed before any run was claimed. Prefixed with
# the project's name, as MCP asks of a key that is not its own.
FENCE_META_KEY: Final = "argus/fence"
# And the action a change is made for, by its row's id, for the same reasons:
# what the write tier marks the change with, so the platform says whose it was.
ACTION_META_KEY: Final = "argus/action"


class McpToolError(RuntimeError):
    """A tool was reached, and it reported a failure.

    Its own type because the retry is built on the distinction: a server that
    said no has been reached, and a second session would carry the same answer.
    Every other failure means the connection, not the answer.

    It carries what the failure left behind, as far as the tool said. A write
    tool can refuse after it has changed something - a suspension that landed
    before the action's own write was refused - and that change is recorded
    nowhere but here. `undo_descriptor` is what the tool said it left, `None`
    where it said nothing; `left_behind_known` is whether the tool said that is
    all of it. The two are apart because they come apart: a change request
    whose answer was lost after an earlier one landed carries the earlier one,
    and nothing may say the estate holds no more than that.

    `left_behind_known` is false unless something said otherwise, which is the
    point of having it: a failure nobody accounted for is not one that changed
    nothing.
    """

    def __init__(self, said: str,
                 undo_descriptor: UndoDescriptor | None = None,
                 left_behind_known: bool = False) -> None:
        super().__init__(said)
        self.undo_descriptor = undo_descriptor
        self.left_behind_known = left_behind_known


class ActionExhausted(McpToolError):
    """A tool was reached, and what it reported is that there is nothing to do.

    The refusal that is an answer. A deployment already as large as Argus may
    make it, an autoscaler already held as still as it can be held - in both the
    tool worked, the estate was read correctly, and the honest report is that the
    action this tier has for the cause is spent. Nothing was changed, so there is
    nothing to undo and nothing to judge, and a caller's next move is to try
    something else rather than to wake somebody.

    A subclass, so that every existing `except McpToolError` keeps catching it and
    the retry reasoning above is unchanged: this is still a server that said no,
    and asking again would still carry the same answer back. What it adds is that
    a caller which cares can tell an exhausted action from a broken platform
    without reading the words of the refusal.

    Recognised here rather than in the tier's own client, because this is the
    point where `is_error` becomes an exception, and a distinction drawn anywhere
    later would be a second reading of the same field.

    What it left behind is known, and is nothing: a refusal of this kind is
    only ever raised before anything was touched.
    """

    def __init__(self, said: str) -> None:
        super().__init__(said, undo_descriptor=None, left_behind_known=True)


class PlatformUnreachable(McpToolError):
    """A tool was reached, and the platform it acts through was not.

    The other refusal that is not a fault of the action. The tier was there, it
    understood what was asked, and the thing it would have asked on Argus's
    behalf did not answer - refused the connection, took longer than the request
    may take, or reported that its own API is unavailable. Nothing was changed,
    so there is nothing to undo and nothing to judge.

    What makes it worth its own type rather than a message is that it is never
    about one action. Five of the seven generic mitigations act through the
    deployment platform, so a platform that is not answering has taken five
    actions away at once - and a caller's right next move is to pass over the
    rest of them and reach for whatever acts through something else, which is a
    different move from either trying again or waking somebody.

    Carries no platform of its own. Which platform an action acts through is a
    property of its kind (`core.models.action`), so a caller holding the
    action it just attempted can already say it - and the name the refusal
    carries, read back onto this, would be a second source for a fact that is
    already derivable, free to disagree with the first. The platform is named in
    what is *said*, for whoever reads the failure.

    It does carry `undo_descriptor`, and that is the one thing a caller cannot
    derive. Four of the five actions through the deployment platform suspend its
    reconciliation before doing what they were asked, so a platform lost after
    that point has taken every action through it away *and* left an application
    un-reconciled. A caller told only the first would pass over the remaining
    candidates believing the estate untouched.

    `None` where nothing landed, which is most of the time. The field means
    "this is what I left behind", not "something may have been left behind" - a
    descriptor invented where none was sent would have the walk record a change
    nobody made.

    The descriptor describes a change this tier *believes* it made, not one the
    platform confirmed: a suspension whose response was lost is reported here
    exactly as one that never landed. Restoring reconciliation to the state it
    is already in costs nothing and fails harmlessly, so the two are
    indistinguishable and it does not matter today. It would matter for a
    descriptor whose undo is not idempotent, and there is none yet.

    A subclass of `McpToolError` for `ActionExhausted`'s reason: a caller that
    does not know about this catches it exactly as it always did.

    Recognised here rather than in the tier's own client, because this is the
    point where `is_error` becomes an exception, and a distinction drawn anywhere
    later would be a second reading of the same field.

    What it left behind is known, whatever it carries: a refusal of this kind
    says what it left, and a failure that may have changed more is never
    refused as this (`an_unreachable_platform`).
    """

    def __init__(self, said: str,
                 undo_descriptor: UndoDescriptor | None = None) -> None:
        super().__init__(said, undo_descriptor=undo_descriptor, left_behind_known=True)


class ChangedSince(McpToolError):
    """A tool was reached, and what it reported is that somebody else has
    changed what the action would change since the action was planned.

    The refusal that is about people rather than the action. The estate is
    neither as the plan found it nor as the plan asked for under this claim's
    own mark, so somebody is acting on the service now - and Argus does not act
    beside them. Nothing was written by the call that was refused, and a
    caller's next move is to hand the incident to a person, which is a different
    move from trying something else or passing over a platform.

    It does carry `undo_descriptor`, for `PlatformUnreachable`'s reason: an
    earlier asking of the same action whose answer was lost may have landed part
    of the change - a suspension, under this claim's mark - and that is recorded
    nowhere but here. `None` where this claim's marks show nothing landed.

    A subclass of `McpToolError` for `ActionExhausted`'s reason: a caller that
    does not know about this catches it exactly as it always did.

    Recognised here rather than in the tier's own client, because this is the
    point where `is_error` becomes an exception, and a distinction drawn anywhere
    later would be a second reading of the same field.

    What it left behind is known, whatever it carries: a refusal of this kind
    is only ever raised before anything was written (`a_change_made_since`).

    `performed` is whether this claim's own change - the value, under this
    claim's mark - had landed before somebody overtook it. A suspension alone is
    not the change, and leaves it false.
    """

    def __init__(self, said: str,
                 undo_descriptor: UndoDescriptor | None = None,
                 performed: bool = False) -> None:
        super().__init__(said, undo_descriptor=undo_descriptor, left_behind_known=True)
        self.performed = performed


class McpUnreachable(RuntimeError):
    """No session to the server could be had at all.

    Not `PlatformUnreachable`, and the difference is what a caller does next. If
    no session can be had, every action is unavailable whatever platform it acts
    through and there is nothing left to narrow to; if a platform is down, the
    actions on the other platform are still there to be tried.
    """


class Asking(Enum):
    """What kind of call a tool call is, which decides what a call whose answer
    was lost comes to.

    A read changes nothing, so however its answer was lost it is asked once
    more, and a second failure is raised as it came. A change may have been
    carried out by an asking whose answer was lost, so where nothing can say
    whether it was, it is `LostAfterSending`: asked once more where a second
    asking finds its own mark and is answered as made (`CHANGE`), and never
    where a second asking would carry it out twice (`CHANGE_ASKED_ONCE`).
    """

    READ = "read"
    CHANGE = "change"
    CHANGE_ASKED_ONCE = "change asked once"


class WhichAsking(Enum):
    """Which asking of a call is being sent: its first, or the one sent again
    over a new session after the first failed
    (`_asked_again_if_the_connection_failed`)."""

    FIRST = "first"
    SECOND = "second"


# How long one asking of a tool waits for its answer, given the tool's name and
# which asking of its call it is.
AskingBound = Callable[[str, WhichAsking], float]


class LostAfterSending(RuntimeError):
    """A change was sent, and no answer came back.

    Neither a tool's refusal - nothing answered - nor an unreachable server -
    something was reached, and may be carrying the call out still. A restart
    and a discard leave no mark a second asking could find, so asking again is
    a second restart; what a caller is told instead is that nothing can say
    whether the call was carried out, and the tool is named for whoever reads
    why.

    Never raised for a read (`Asking.READ`), which changes nothing. Raised for
    a change asked once where the failure does not prove the call never ran
    (`_never_sent`); and for any change whose first asking may have been sent
    and whose second ended in neither an answer nor an answer about the world
    (`ChangedSince`, `RunLost`); and for any change whose second asking failed
    without proving it never ran.
    """


def an_http_client_waiting(answered_within: float) -> httpx2.AsyncClient:
    """The HTTP client a held session is opened over, waiting `answered_within`
    seconds to read.

    A tool written as a plain function says nothing on its stream until it
    returns, so the read timeout is how long a tool's answer may take. Left at
    the client's own five seconds, or the SDK's five minutes, an answer the
    tier is still working on is dropped - and the SDK, which swallows a stream
    that ends, leaves the call waiting for it for ever. Everything that is not
    a read keeps the bound the SDK gives it. Redirects are the SDK's: it follows
    one only within the endpoint's origin, whatever the client says.
    """
    return httpx2.AsyncClient(timeout=httpx2.Timeout(_HTTP_SECONDS, read=answered_within))


class _NothingSent(McpUnreachable):
    """No session to send a call over, said before anything was sent.

    An `McpUnreachable` to every caller; its own type here because it is one
    of the two failures that prove a call never ran (`_never_sent`).
    """


def _never_sent(failed: Exception) -> bool:
    """Whether a failed call is one that certainly never reached its tool.

    Two failures prove it: there was no session to send it over, or the server
    turned it away as made over a session it does not hold - "Session not
    found", or the SDK's "Session terminated" where the server's 404 said
    nothing, which a server restarted beneath a held session answers before
    any tool is asked anything. Any other failure may have come after the tool
    began, a read that timed out among them.
    """
    if isinstance(failed, _NothingSent):
        return True

    return (
        isinstance(failed, MCPError)
        and failed.error.code == SESSION_GONE_CODE
        and failed.error.message in (SESSION_NOT_FOUND_WORDS, SESSION_TERMINATED_WORDS)
    )


def an_exhausted_action(said: str) -> ToolRefusal:
    """A refusal that is an answer: the action is spent.

    For a server to refuse with *before changing anything*, when what it is
    reporting is that the action is spent. Only then: a failure that arrives
    after something was written has left the estate changed, and a caller told
    the action was merely unavailable would be told nothing about the state it
    is now in.
    """
    return ToolRefusal(kind=ToolRefusalKind.EXHAUSTED, said=said)


def an_unreachable_platform(platform: str, said: str,
                            undo_descriptor: UndoDescriptor | None = None) -> ToolRefusal:
    """A refusal saying the platform the action acts through was not there.

    Unlike `an_exhausted_action`, this is *not* restricted to a failure that
    changed nothing: an action that suspended reconciliation and then lost the
    platform passes what it left behind as `undo_descriptor`, and the caller is
    told both facts. Restricting it would mean the walk narrowed itself or not
    depending on which call the outage happened to land on.

    Two clauses replace that restriction, and the second is the load-bearing one.
    A refusal of this kind **says what it left behind**. And an action that may
    have taken effect, and whose effect cannot be established, **is not refused
    as this at all** - not for want of a descriptor, but because every
    verification after it is unreliable: a service that may be restarting makes
    the next action's recovery unattributable, and a hypothesis confirmed
    against it would be confirmed wrongly.

    `platform` is said in the words rather than carried on the exception the
    caller raises, for the reason `PlatformUnreachable` gives: what a caller
    branches on comes from the action's kind, and this is what a person reads.
    """
    return ToolRefusal(kind=ToolRefusalKind.PLATFORM_UNREACHABLE, said=said, platform=platform,
                       left_behind=undo_descriptor)


def a_refusal_saying_what_it_left(said: str,
                                  left_behind: UndoDescriptor | None = None) -> ToolRefusal:
    """A refusal that says the whole of what it left behind.

    For a write tool's own refusal where it can say so: one raised before any
    change was asked for, which left nothing, and one at a change request the
    platform answered it did not handle, which left what the earlier calls
    answered for. Not for a change request whose answer was lost - that one may
    have changed more, and `with_what_it_left` carries what it knows without
    saying it is all.
    """
    return ToolRefusal(kind=ToolRefusalKind.LEFT_BEHIND_KNOWN, said=said,
                       left_behind=left_behind)


def with_what_it_left(said: str, left_behind: UndoDescriptor | None) -> ToolRefusal:
    """A refusal carrying what a failure left behind where it left anything, and
    saying nothing about whether that is all of it.

    A change request whose answer was lost after an earlier change landed has
    that change to report, and no more it can vouch for.
    """
    return ToolRefusal(kind=ToolRefusalKind.UNACCOUNTED, said=said, left_behind=left_behind)


def a_change_made_since(said: str,
                        left_behind: UndoDescriptor | None = None,
                        performed: bool = False) -> ToolRefusal:
    """A refusal of a change somebody else made since the plan.

    For a write tool to refuse with *before writing anything*, when the estate
    is neither as the plan found it nor as the plan asked for under this claim's
    own mark. What it left behind is known, and is `left_behind`: nothing this
    call wrote, and whatever this claim's marks show an earlier asking of it
    landed. `performed` says the change itself was among what landed.
    """
    return ToolRefusal(kind=ToolRefusalKind.CHANGED_SINCE, said=said, left_behind=left_behind,
                       performed=performed)


def a_lost_run(said: str) -> ToolRefusal:
    """A refusal of a change asked for by a lost run.

    For a write tier to refuse with *before changing anything*, when the claim
    the call was made for is one the run has moved past. Only then: a call that
    named no run, or one whose run could not be asked after, is an ordinary
    refusal that says it left nothing - neither says the run was lost, and a
    walk told it was would stop where it should have reached a human.
    """
    return ToolRefusal(kind=ToolRefusalKind.RUN_LOST, said=said)


def _the_words_of(result: CallToolResult) -> str:
    """Everything the tool said, joined, with nothing escaped on the way.

    A failed call comes back as content blocks rather than as a string, and only
    the text ones carry words.
    """
    return " ".join(
        block.text for block in result.content if isinstance(block, TextContent)
    )


def _the_tools_own_words(name: str, spoken: str) -> str:
    """What a tool that failed said, without what its server put in front of it.

    A tool that raises is answered with the exception's words behind
    `TOOL_ERROR_PREFIX`; a tool that said nothing is named, so the failure
    still says whose it was.
    """
    own = spoken.removeprefix(TOOL_ERROR_PREFIX.format(name=name)).strip()

    return own if own else f"[{name}] failed and said nothing"


def _the_refusal_in(name: str, result: CallToolResult) -> ToolRefusal | None:
    """The refusal a failed call carried in its structured content, or `None`
    where it carried none - a tool that raised for a reason nobody foresaw.

    One that will not read is no refusal, and said so in the log: what is in
    hand is already a failure, and it is read as one nobody accounted for
    rather than as one that left nothing."""
    structured = result.structured_content

    if structured is None or REFUSAL_KEY not in structured:
        return None

    try:
        return ToolRefusal.model_validate(structured[REFUSAL_KEY])
    except ValidationError:
        logger.warning("a refusal could not be read", exc_info=True, extra={"tool": name})

        return None


def _a_refusing_answer(refusal: ToolRefusal) -> CallToolResult:
    """The error result a refused call is answered with: the refusal's words for
    whoever reads the content, and the refusal whole for the caller to act on."""
    return CallToolResult(content=[TextContent(type="text", text=refusal.words)],
                          structured_content={REFUSAL_KEY: refusal.model_dump(mode="json")},
                          is_error=True)


class McpClient:
    """One MCP server, reached over one session held open to it.

    Built where a process starts and closed when it ends - a client per tier per
    process, not per call and not per agent. Connecting is deferred to the first
    call, so building one at a composition root reaches nothing and a process
    that never asks a tool anything never opens a socket.

    Safe to share: the session lives on this client's own event loop, in its own
    thread, and callers from any thread or any other loop submit work to it.
    Closing is part of that bargain - a call still in flight when the owner
    closes is failed as `McpUnreachable` rather than left waiting, because a
    tool call carries no deadline of its own and a caller stranded on a session
    that is never coming back would wait for the life of the process.

    Each call is a span, opened on the calling thread rather than on the
    client's loop: the loop's thread has no idea which agent asked, and a span
    opened there would start a trace of its own. `tracer` and `meter` default to
    the process's own, which are no-ops until `telemetry` installs an SDK.

    Each call also says which claim of a run it is made for, where the process
    `holding` one holds it: the write tier makes a change only for the claim
    that holds the run. Read as the call is made rather than when the client is
    built, because one client serves every run its process walks.

    `answered_within` is how many seconds a call waits for its answer before it
    is taken to be lost, and it has no default here: how long the slowest tool
    a server serves may take is the server's tier's to know, so each tier sets
    its own where it builds its client. A call that meets it was sent, and is
    asked again only where asking again is harmless (`call`).

    `answered_within_for` says how long one asking waits for its answer, asked
    for every asking sent with the tool's name and which asking of the call it
    is (`WhichAsking`); left out, every asking waits `answered_within`. It can
    shorten a wait and never lengthen one: `answered_within` is the longest any
    asking waits. Each asking of a call asked again waits its own bound - the
    first's having run out is what has the second asked.

    `not_a_call_within` is how long every request over a session that is not a
    tool call waits (`NOT_A_CALL_SECONDS`): the handshake opening it, and a list
    of its tools - the client's own (`list_tools`) or the SDK's after a
    session's first call to a tool. A session that does not open within it is a
    server unreachable, and a call asked again waits it for its new session on
    top of its two askings' bounds. `pinged_within` is how long the ping before
    a change asked once waits (`PING_SECONDS`), and never longer than
    `not_a_call_within`: a ping whose connection is refused is left unanswered
    by the SDK, not failed, so a session whose server has gone is found gone
    only once this has passed.

    `http_client_waiting` builds the HTTP client each session is opened over,
    handed the longer of `answered_within` and `not_a_call_within` - what it
    reads for is the longest any request over it may wait, and each request's
    own bound is the SDK's to keep; it defaults to `an_http_client_waiting`,
    and is a parameter so that what a session travels over, and that it is
    closed with the session, can be asserted.
    """

    def __init__(self,
                 url: str,
                 answered_within: float,
                 tracer: Tracer | None = None,
                 meter: Meter | None = None,
                 clock: Clock = time.monotonic,
                 holding: Holding | None = None,
                 http_client_waiting: Callable[[float], httpx2.AsyncClient] = (
                     an_http_client_waiting
                 ),
                 answered_within_for: AskingBound | None = None,
                 not_a_call_within: float = NOT_A_CALL_SECONDS,
                 pinged_within: float = PING_SECONDS) -> None:
        self._url = url
        self._answered_within = answered_within
        self._answered_within_for = answered_within_for
        self._not_a_call_within = not_a_call_within
        self._pinged_within = pinged_within
        self._http_client_waiting = http_client_waiting
        self._holding = holding
        self._tracer = tracer if tracer is not None else trace.get_tracer(_SCOPE)
        measured_by = meter if meter is not None else metrics.get_meter(_SCOPE)
        self._duration = measured_by.create_histogram(
            MCP_CLIENT_OPERATION_DURATION, unit=UNIT_SECONDS,
            description="How long a tool call took, refused and failed calls included."
        )
        self._clock = clock
        where = urlsplit(url)
        self._server_address = where.hostname or ""
        self._server_port = where.port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._starting = threading.Lock()
        self._closing = False
        # Everything below belongs to the client's own loop and is read or
        # written under `_cycled` alone. `_generation` counts the sessions this
        # client has published, which is what tells a caller waiting for a
        # rebuild that the one it asked for has actually happened.
        self._session: ClientSession | None = None
        self._failure: BaseException | None = None
        self._generation = 0
        self._cycled = asyncio.Condition()
        self._rebuild = asyncio.Event()

    def call[T](self,
                name: str,
                returns: Callable[[Any], T],
                *,
                asking: Asking,
                **kwargs: object) -> T:
        """Calls one tool and reads its answer as `returns` says it should be.

        Blocks the calling thread, which is what every caller in Argus wants: a
        LangGraph node, an investigation loop and a mitigation's verification are
        all ordinary synchronous code with nothing else to be getting on with.

        `returns` is a callable rather than a `TypeAdapter` so that a type
        already having one parsing door keeps it - `parse_undo_descriptor` is
        passed as it stands, and the union's own adapter stays where it belongs.
        Reading happens on the calling thread, never on the client's loop: that
        loop exists to hold a session, not to validate models.

        `asking` says what kind of call this is (`Asking`), and has no default:
        a call left to one would be a read lost as a change, or a change asked
        as a read. A read is asked once more where its answer was lost, and
        never `LostAfterSending`. A change is asked once more too, since a
        write whose second asking finds its own mark is answered as made. A
        change asked once is a tool a second asking would carry out twice -
        its failures are then asked again only where they prove the call never
        ran, and any other is `LostAfterSending`; and the held session is
        pinged before it is sent, so a session found gone is replaced before
        anything leaves this process. Every other keyword is the tool's own
        argument.
        """
        with self._a_tool_call(name) as meta:
            answer = self._submitted(name, kwargs, meta, asking).result()

        return returns(answer)

    async def acall[T](self,
                       name: str,
                       returns: Callable[[Any], T],
                       *,
                       asking: Asking,
                       **kwargs: object) -> T:
        """The same call, awaited rather than waited on.

        For a caller that already has an event loop - an async route, an async
        node - where `call` would block that loop's thread for the length of a
        retrieval. Nothing in Argus needs this yet, and it is here rather than
        waiting to be needed because the alternative it replaces failed loudly
        and this one would fail quietly. `asking` is `call`'s.
        """
        with self._a_tool_call(name) as meta:
            answer = await asyncio.wrap_future(
                self._submitted(name, kwargs, meta, asking)
            )

        return returns(answer)

    def list_tools(self) -> list[Tool]:
        """Every tool the server serves, as it declares them, in its own order.

        The server owns a tool's definition (MCP, `tools/list`) and a caller
        offers what it declares rather than keeping a copy. Every tool, as
        declared: which of them anybody offers a model, and whether one can be,
        is the offer's to decide - a server may serve a tool no offer could
        carry, and reading it into one here would make the whole list
        unreadable. Every page is read; a list stopped at its first is a part
        of what is served.
        """
        return asyncio.run_coroutine_threadsafe(
            self._listed(), self._running_loop()
        ).result()

    @contextmanager
    def _a_tool_call(self, name: str) -> Generator[dict[str, Any]]:
        """One call's span and duration, and the `_meta` that carries it across.

        Yields the carrier the span's context was injected into, which is what
        the call sends - so a server reading it answers inside this span - and
        the claim held now and the action acted for, where there are. A failure
        is said on the span and in the measurement, then raised on as it was.
        """
        measured: dict[str, str] = {
            MCP_METHOD_NAME: MCP_TOOLS_CALL_METHOD,
            GEN_AI_TOOL_NAME: name
        }

        with self._tracer.start_as_current_span(
            f"{MCP_TOOLS_CALL_METHOD} {name}",
            kind=SpanKind.CLIENT,
            attributes={
                **measured,
                GEN_AI_OPERATION_NAME: GEN_AI_EXECUTE_TOOL_OPERATION,
                SERVER_ADDRESS: self._server_address,
                **({SERVER_PORT: self._server_port} if self._server_port is not None else {})
            },
            set_status_on_exception=False
        ) as span:
            carrier: dict[str, Any] = {}
            propagate.inject(carrier)
            held = self._holding.current() if self._holding is not None else None

            if held is not None:
                carrier[FENCE_META_KEY] = held.spoken()

            acting_for = (
                self._holding.current_action() if self._holding is not None else None
            )

            if acting_for is not None:
                carrier[ACTION_META_KEY] = acting_for

            started_at = self._clock()

            try:
                yield carrier
            except Exception as error:
                _said_on(span, error)
                self._duration.record(self._clock() - started_at,
                                      {**measured, ERROR_TYPE: type(error).__name__})
                raise

            self._duration.record(self._clock() - started_at, measured)

    def close(self) -> None:
        """Puts the session down and stops the loop holding it.

        Idempotent, and a no-op for a client that never connected. The holder is
        asked to finish rather than cancelled, because the session and the HTTP
        stream have to be closed by the task that opened them.
        """
        with self._starting:
            self._closing = True
            loop, thread = self._loop, self._thread
            self._loop, self._thread = None, None

        if loop is None or thread is None:
            return

        loop.call_soon_threadsafe(self._rebuild.set)
        thread.join(timeout=SHUTDOWN_SECONDS)

    def __enter__(self) -> Self:
        return self

    def __exit__(self,
                 exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.close()

    def _submitted(self,
                   name: str,
                   arguments: dict[str, object],
                   meta: dict[str, Any],
                   asking: Asking) -> Future[object]:
        """One tool call, handed to the loop that holds the session - and run
        there in a copy of the calling thread's context, the call's span
        current in it.

        Handed from the calling thread, which is what carries the context
        across: `run_coroutine_threadsafe` schedules the call with
        `call_soon_threadsafe`, which runs it in a copy of the context current
        where it was scheduled. The loop's thread has its own, with no span in
        it, and the SDK opens a span for every request it sends from whatever
        context is current - and writes that span's context into the call's
        `_meta` over the one carried there. Run inside the caller's, the SDK's
        span is the call's child, and the server answers inside the walk's
        trace.
        """
        return asyncio.run_coroutine_threadsafe(
            self._call(name, arguments, meta, asking),
            self._running_loop()
        )

    def _running_loop(self) -> asyncio.AbstractEventLoop:
        """This client's loop, started on first use.

        Under a lock because two agents on two threads asking their first
        question at once would otherwise open two sessions and keep the second.
        """
        with self._starting:
            if self._closing:
                raise McpUnreachable(f"the client for [{self._url}] is closed")

            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._serve,
                    args=(self._loop,),
                    name=f"mcp-client-{self._url}",
                    daemon=True
                )
                self._thread.start()

            return self._loop

    def _serve(self, loop: asyncio.AbstractEventLoop) -> None:
        """The client's thread: its loop, running until the holder finishes.

        And then a little longer. The holder leaving is what tells a waiting
        call there is no session to be had, but a loop stopped the instant it
        returns never runs the calls it just woke - their futures would go
        unresolved, and whoever is blocked on one would stay blocked.
        """
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._hold())
            loop.run_until_complete(self._every_call_still_waiting())
        finally:
            loop.close()

    async def _every_call_still_waiting(self) -> None:
        """Ends the calls left over, so their callers are answered.

        Cancelled rather than waited on, because a call suspended inside the
        session is not woken by that session being taken down - the request it
        is waiting for an answer to simply never gets one, and gathering it
        would wait exactly as long as the caller it was supposed to release.
        Each one turns its cancellation into `McpUnreachable` on the way out.
        """
        waiting = asyncio.all_tasks() - {asyncio.current_task()}

        for call in waiting:
            call.cancel()

        await asyncio.gather(*waiting, return_exceptions=True)

    async def _hold(self) -> None:
        """Opens a session, holds it, and opens another when asked to.

        The whole of this client's contact with the two context managers. One
        pass of the loop is one session's life: opened here, published for
        callers to use, and closed here when a rebuild or a close asks for it -
        which is the only arrangement anyio permits, since a cancel scope exited
        by a task that did not enter it raises rather than closing.

        A session that cannot be opened is published as the failure it was.
        Callers see `McpUnreachable` rather than waiting for a connection that
        is not coming, and the next rebuild request tries again.

        Its HTTP client is one this opens and closes itself, waiting to read as
        long as any answer over it may take (`an_http_client_waiting`): one
        that stopped reading sooner would drop the answer, and the SDK, which
        swallows a read that timed out, would leave its request waiting out its
        own bound for nothing. A tool call over the session waits as long as
        `_ask` says and no longer, and every other request - the handshake
        first - `not_a_call_within`, so neither a call nor a session that got no
        answer waits for ever.
        """
        reads_for = max(self._answered_within, self._not_a_call_within)

        while True:
            try:
                async with (
                    self._http_client_waiting(reads_for) as http_client,
                    streamable_http_client(
                        self._url, http_client=http_client
                    ) as (read, write),
                    ClientSession(
                        read, write, read_timeout_seconds=self._not_a_call_within
                    ) as session
                ):
                    await session.initialize()
                    await self._publish(session, None)
                    await self._rebuild.wait()
                    self._rebuild.clear()
            except Exception as unreachable:
                logger.warning("session could not be opened", exc_info=True,
                               extra={"url": self._url})
                await self._publish(None, unreachable)
                await self._rebuild.wait()
                self._rebuild.clear()

            if self._closing:
                await self._publish(
                    None, McpUnreachable(f"the client for [{self._url}] is closed")
                )
                return

    async def _publish(self,
                       session: ClientSession | None,
                       failure: BaseException | None) -> None:
        """Hands the session this pass opened - or the failure - to the callers."""
        async with self._cycled:
            self._session = session
            self._failure = failure
            self._generation += 1
            self._cycled.notify_all()

    async def _call(self,
                    name: str,
                    arguments: dict[str, object],
                    meta: dict[str, Any],
                    asking: Asking) -> object:
        """One tool call, however it ends - including the client closing under it.

        A cancellation here is the client being closed and nothing else: no
        caller can cancel one of these, since what a caller holds is a future on
        another loop. It arrives as `McpUnreachable`, because what happened is
        that the server became unreachable, and a `CancelledError` surfacing in
        a walk would look like the walk being cancelled instead.
        """
        try:
            return await self._asked_again_if_the_connection_failed(
                name, arguments, meta, asking
            )
        except asyncio.CancelledError:
            if not self._closing:
                raise

            raise McpUnreachable(
                f"the client for [{self._url}] closed while [{name}] was in flight"
            ) from None

    async def _asked_again_if_the_connection_failed(
        self, name: str, arguments: dict[str, object], meta: dict[str, Any], asking: Asking
    ) -> object:
        """One tool call, and the one retry a held session needs.

        The retry is about the connection and nothing else. A tool that reported
        an error was reached, so it is raised as it came - a lost run among them,
        which is lost over every session there is; anything else means the
        session this call was made over is no longer one - which is what a
        restarted server or an idle timeout looks like from here - and the answer
        is a new session rather than a failed incident.

        A read ends there: it changed nothing, so a second failure is raised as
        it came. A change asked once whose failure does not prove it never ran
        may be running still, and is `LostAfterSending` rather than asked again.

        And for a change whose first asking may have been sent, the call ends in
        whatever the second answers for the world: its answer, a `ChangedSince`
        as it came - the tier read the estate after whatever the first did - or
        `RunLost`. Anything else speaks for the second asking alone, while the
        first may be carrying the change out still, so it is `LostAfterSending`.
        So is a second asking of a change that failed without proving it never
        ran, after a first that provably did not: it was sent, and there is no
        third.

        A first asking that waited out its bound is one of the failures asked
        again, since an answer that never came is how a session gone dead looks
        from here too. Each asking waits the bound `answered_within_for` gives
        it as the first or the second, over a session that took
        `not_a_call_within` at most to open.
        """
        try:
            return await self._ask(name, arguments, meta, asking, WhichAsking.FIRST)
        except (McpToolError, RunLost):
            raise
        except Exception as failed:
            if asking is Asking.CHANGE_ASKED_ONCE and not _never_sent(failed):
                raise self._lost_after_sending(name, failed) from failed

            may_have_been_sent = not _never_sent(failed)
            logger.warning("tool call asked again over a new session", exc_info=True,
                           extra={"tool": name})

        await self._rebuilt()

        try:
            return await self._ask(name, arguments, meta, asking, WhichAsking.SECOND)
        except (ChangedSince, RunLost):
            raise
        except McpToolError as refused:
            if asking is not Asking.READ and may_have_been_sent:
                raise self._lost_after_sending(name, refused) from refused

            raise
        except Exception as failed:
            # Either asking of a change may have been sent: the second's own
            # failure is lost after sending where it does not prove it never
            # ran - there is no third asking.
            if asking is not Asking.READ and (may_have_been_sent or not _never_sent(failed)):
                raise self._lost_after_sending(name, failed) from failed

            raise

    def _lost_after_sending(self, name: str, failed: Exception) -> LostAfterSending:
        """`name`'s call, said to be lost after it was sent, with what ended it."""
        return LostAfterSending(
            f"[{name}] was sent to [{self._url}] and its answer never came back, "
            f"so nothing can say whether it was carried out: "
            f"{str(failed) or type(failed).__name__}"
        )

    async def _ask(self,
                   name: str,
                   arguments: dict[str, object],
                   meta: dict[str, Any],
                   asking: Asking,
                   which: WhichAsking) -> object:
        """Calls the tool over whatever session is currently published - one
        found answering first, for a change asked once - as the `which` asking
        of its call, waiting as long as that asking may."""
        session = await self._the_session_for(name)

        if asking is Asking.CHANGE_ASKED_ONCE:
            session = await self._still_answering(session, name)

        waits = self._answered_within

        if self._answered_within_for is not None:
            waits = min(waits, self._answered_within_for(name, which))

        return _answered(name, await session.call_tool(
            name, arguments=arguments, read_timeout_seconds=waits,
            meta=_AS_REQUEST_META.validate_python(meta)
        ))

    async def _still_answering(self, session: ClientSession, asking: str) -> ClientSession:
        """`session`, where it answers a ping within `pinged_within` - or the
        session that replaces it.

        Asked before a change asked once, because a held session whose server
        has gone is found gone only by sending something over it:
        the call itself, sent over it, would end as lost after sending - a write
        server stopped for a moment would hand the next restart Argus asked for
        to a person, over a restart that never left this process. A ping lost
        the same way costs nothing, and nothing has been sent.
        """
        try:
            async with asyncio.timeout(self._pinged_within):
                await session.send_ping()
        except Exception:
            logger.warning("held session did not answer a ping, opened another",
                           exc_info=True, extra={"tool": asking, "url": self._url})
            await self._rebuilt()

            return await self._the_session_for(asking)

        return session

    async def _listed(self) -> list[Tool]:
        """Every tool listed, and the one retry a held session needs - for
        `_asked_again_if_the_connection_failed`'s reason."""
        try:
            return await self._every_tool_listed_now()
        except McpUnreachable:
            raise
        except Exception:
            logger.warning("tools listed again over a new session", exc_info=True,
                           extra={"url": self._url})
            await self._rebuilt()
            return await self._every_tool_listed_now()

    async def _every_tool_listed_now(self) -> list[Tool]:
        """Every tool listed over whatever session is currently published."""
        session = await self._the_session_for(_TOOLS_LIST_METHOD)

        return await every_tool_listed(
            lambda cursor: session.list_tools(
                params=PaginatedRequestParams(cursor=cursor) if cursor else None
            )
        )

    async def _the_session_for(self, asking: str) -> ClientSession:
        """The session currently published, once there is one to use."""
        async with self._cycled:
            await self._cycled.wait_for(
                lambda: self._generation > 0 or self._closing
            )
            session, failure = self._session, self._failure

        if self._closing:
            raise _NothingSent(
                f"the client for [{self._url}] closed while [{asking}] was in flight"
            )

        if session is None:
            raise _NothingSent(f"no session to [{self._url}]") from failure

        return session

    async def _rebuilt(self) -> None:
        """Asks the holder for a new session and waits until it has one.

        Waits on the generation rather than on the session, because a caller that
        woke to find a session cannot tell whether it is the one it asked to have
        replaced. Two calls failing at once ask twice and one extra session is
        opened, which costs a connection and is never wrong.

        A closing client is asked for nothing. The holder that would answer is
        on its way out or already gone, so waiting for a session it will never
        publish is waiting for ever - and `_ask` is about to say so.
        """
        async with self._cycled:
            if self._closing:
                return

            stale = self._generation
            self._rebuild.set()
            await self._cycled.wait_for(
                lambda: self._generation != stale or self._closing
            )


async def every_tool_listed(
    page: Callable[[str | None], Awaitable[ListToolsResult]]
) -> list[Tool]:
    """Every tool a server lists, page after page, in the order it lists them.

    MCP pages `tools/list`: an answer naming a next cursor has more to come,
    and `page` is asked for the page after it until one names none.
    """
    listed: list[Tool] = []
    cursor: str | None = None

    while True:
        answered = await page(cursor)
        listed.extend(answered.tools)
        cursor = answered.next_cursor

        if not cursor:
            return listed


def _answered(name: str, result: CallToolResult) -> object:
    """What the tool said, unwrapped, or the error it reported instead.

    An error is raised saying what a person reads - in an escalation's reason,
    the timeline, the postmortem and a Slack line - and carrying what the
    caller acts on, both from the refusal the server answered with
    (`_the_refusal_in`). A failure that carried none is a tool that raised for
    a reason nobody foresaw, which said nothing about the estate.
    """
    if result.is_error:
        refusal = _the_refusal_in(name, result)

        if refusal is None:
            raise McpToolError(_the_tools_own_words(name, _the_words_of(result)))

        said = refusal.words

        match refusal.kind:
            # The walk's own exception rather than a kind of tool error,
            # because what it means is not about the tool: the walk is to stop.
            case ToolRefusalKind.RUN_LOST:
                raise RunLost(said)
            case ToolRefusalKind.EXHAUSTED:
                raise ActionExhausted(said)
            case ToolRefusalKind.PLATFORM_UNREACHABLE:
                raise PlatformUnreachable(said, refusal.left_behind)
            case ToolRefusalKind.CHANGED_SINCE:
                raise ChangedSince(said, refusal.left_behind, performed=refusal.performed)
            case _:
                # Any refusal may carry what it left, the unaccounted ones too:
                # a change request whose answer was lost still reports the
                # suspension before it.
                raise McpToolError(said, undo_descriptor=refusal.left_behind,
                                   left_behind_known=refusal.left_behind_known)

    structured = result.structured_content

    if structured is None:
        return None

    return structured.get(STRUCTURED_RESULT_KEY, structured)


def _said_on(span: Span, error: Exception) -> None:
    """A failed call, said on its span as the class of what went wrong.

    The class rather than the message, as `error.type` asks: which of the ways
    a call can fail this was is what a reader of a trace filters on, and the
    wording belongs to whoever raised it.
    """
    span.set_attribute(ERROR_TYPE, type(error).__name__)
    span.set_status(Status(StatusCode.ERROR, str(error)))


@contextmanager
def serving_a_tool_call(name: str,
                        meta: Mapping[str, Any] | None,
                        tracer: Tracer | None = None) -> Generator[Span]:
    """The server's half: a span for one tool call, inside the caller's trace.

    `meta` is the request's `_meta`, where the client put its span's context.
    A request that brought none - a client that does not send it - is served
    all the same, under a trace of its own; telemetry decides nothing about
    whether a tool answers. A tool that raises is said on the span and raised
    on, so the server still turns it into an error result. Said as what the
    tool raised: the SDK wraps a tool's crash in `UnexpectedToolError`, and
    which of a tool's refusals this was is what a reader of a trace filters on.
    """
    callers = propagate.extract(dict(meta) if meta is not None else {})
    serving = tracer if tracer is not None else trace.get_tracer(_SCOPE)
    # Attached, not only handed to the span as its parent: the caller's context
    # carries its baggage too - whose incident, which run - and only an
    # attached context is one the tool and its log lines can read it from.
    continued = context.attach(callers)

    try:
        with serving.start_as_current_span(
            f"{MCP_TOOLS_CALL_METHOD} {name}",
            kind=SpanKind.SERVER,
            attributes={
                MCP_METHOD_NAME: MCP_TOOLS_CALL_METHOD,
                GEN_AI_TOOL_NAME: name,
                GEN_AI_OPERATION_NAME: GEN_AI_EXECUTE_TOOL_OPERATION
            },
            set_status_on_exception=False
        ) as span:
            try:
                yield span
            except Exception as error:
                logger.warning("tool call failed", exc_info=True, extra={"tool": name})
                _said_on(span, _what_the_tool_raised(error))
                raise
    finally:
        context.detach(continued)


def _what_the_tool_raised(error: Exception) -> Exception:
    """`error`, unwrapped where the SDK wrapped a tool's crash around it."""
    if isinstance(error, UnexpectedToolError) and isinstance(error.__cause__, Exception):
        return error.__cause__

    return error


class TracedMCPServer(MCPServer):
    """An MCP server that answers every tool call inside its caller's trace,
    one call at a time.

    One override, of the SDK server's own public `call_tool` - the method its
    low-level server dispatches every tool call to - so a server built from
    this is traced whole, and a tool added to it tomorrow is traced without
    anybody remembering to. The tool itself, and every log line it writes, run
    inside the server span, which is what gives a line in a server's
    `logs.jsonl` the trace id of the walk that asked. The SDK's own server span
    stands beside it, as the SDK traces every request it serves.

    One call at a time, as every Argus server has always served them: the SDK
    runs a plain-function tool on a worker thread, where it used to run on the
    server's loop and hold it, and no tool here was written to share its state
    with another running beside it. Each call waits for the one before it to
    end - its span, its fence and its tool - before any of its own begins.

    Served where `host` and `port` say (`serve`), and `host` is what the app is
    built for: the SDK guards a server built for a loopback host against DNS
    rebinding, as it did when the host was its own setting.
    """

    def __init__(self, name: str, *, host: str, port: int, **settings: Any) -> None:
        super().__init__(name, **settings)
        self._host = host
        self._port = port
        # A lock per loop rather than one: an asyncio lock waited on is bound to
        # the loop that waited, and a server is served on one loop in a process
        # but may be asked from several, one after another, in a suite. Kept
        # for the server's life: a served server has one loop, and a suite's
        # server holds one lock per loop it was asked from.
        self._one_call_at_a_time: dict[asyncio.AbstractEventLoop, asyncio.Lock] = {}

    async def call_tool(self,
                        name: str,
                        arguments: dict[str, Any],
                        context: Context | None = None) -> CallToolResult | InputRequiredResult:
        """Calls the tool, once every call before it has ended, inside a span
        continuing whatever trace the request carried.

        A refusal - this server's own, raised bare, or a tool's, which the SDK
        wraps as the cause of an `UnexpectedToolError` - is answered with the
        error result that carries it (`_a_refusing_answer`): its words for
        whoever reads them, and the refusal whole for the caller to act on.

        Any other crash is answered as the SDK answered it until mcp 2.1: its
        own words, behind `TOOL_ERROR_PREFIX` - the SDK now withholds them, and
        they are what a person reads of why a change failed. Both are answered
        here, outside the span, so the span and the log line have seen the
        call fail first. A tool's deliberate `ToolError` the SDK answers in
        words already.
        """
        meta = _the_meta_of(context)

        async with self._a_turn():
            try:
                with serving_a_tool_call(name, meta):
                    return await self.answer(name, arguments, meta, context)
            except ToolRefused as refused:
                return _a_refusing_answer(refused.refusal)
            except UnexpectedToolError as crashed:
                if isinstance(crashed.__cause__, ToolRefused):
                    return _a_refusing_answer(crashed.__cause__.refusal)

                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text=f"{TOOL_ERROR_PREFIX.format(name=name)}{crashed.__cause__}"
                    )],
                    is_error=True
                )

    async def answer(self,
                     name: str,
                     arguments: dict[str, Any],
                     meta: Mapping[str, Any] | None,
                     context: Context | None) -> CallToolResult | InputRequiredResult:
        """What a call is answered with, inside its span: the tool's own answer.

        The one place a server built from this decides more about a call than
        the SDK does, so that whatever it refuses is refused inside the caller's
        trace - and said there, as any tool that raised is. `meta` is the
        request's `_meta`, already read; `context` is the request's, handed on
        to the tool.
        """
        return await super().call_tool(name, arguments, context)

    def serve(self, run: Callable[..., None] = uvicorn.run) -> None:
        """Serves this server over streamable HTTP until the process is stopped.

        What `run(transport="streamable-http")` does, without uvicorn's own
        logging config. That config gives uvicorn's loggers handlers of their
        own and stops them propagating, so nothing uvicorn said reached the
        root - and the root is where telemetry listens. The SDK builds its
        `uvicorn.Config` inside `run`, where nobody can reach it, so the app it
        would have served is served here instead; the app carries the session
        manager's lifespan, which is everything `run` added to it.

        A session is never closed for being idle, as it never was before mcp
        1.30: a client holds one for the life of its process, and a call it
        makes after a quiet half hour is a call, not a stranger's.

        `run` defaults to uvicorn's own; a parameter so that what is served,
        and how, can be asserted without serving it.
        """
        run(self.streamable_http_app(host=self._host, session_idle_timeout=None),
            host=self._host,
            port=self._port,
            log_config=None)

    @asynccontextmanager
    async def _a_turn(self) -> AsyncGenerator[None]:
        """This call's turn: held until the call ends, once every call before
        it on this loop has ended."""
        loop = asyncio.get_running_loop()
        lock = self._one_call_at_a_time.get(loop)

        if lock is None:
            lock = self._one_call_at_a_time[loop] = asyncio.Lock()

        async with lock:
            yield


def _the_meta_of(context: Context | None) -> Mapping[str, Any] | None:
    """The request's `_meta`, read as a plain map - or `None` where the request
    carried none, or no request context reached the call."""
    if context is None:
        return None

    meta = context.request_context.meta

    return dict(meta) if meta is not None else None
