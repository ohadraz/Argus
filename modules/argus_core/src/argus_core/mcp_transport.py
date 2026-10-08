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
second time over a new session would turn one refusal into two.

Both surfaces run over that one session. `call` blocks the calling thread until
the answer arrives; `acall` awaits it, so a route on a FastAPI loop reaches a
tool without blocking its loop - and without the `RuntimeError` that opening an
event loop per call raised the moment a caller already had one.

Every call is traced across the boundary, both halves here because they are two
halves of one convention. The client makes each call a span and sends that
span's context in the request's `_meta`, as OTel's MCP conventions and MCP's
SEP-414 both say to; `TracedFastMCP` is the server that reads it back and
answers inside the caller's trace. `_meta` rather than an HTTP header because
the session is held: its headers were fixed when it opened, and `_meta`
travels with each call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future
from contextlib import contextmanager, suppress
from types import TracebackType
from typing import Any, Final, Self
from urllib.parse import urlsplit

import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ContentBlock, TextContent
from opentelemetry import context, metrics, propagate, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer

from argus_core.models.undo_descriptor import UndoDescriptor, parse_undo_descriptor
from argus_core.telemetry import (
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

logger = logging.getLogger(__name__)

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


# What a server puts at the front of a refusal it wants recognised as an answer
# rather than as a fault - see `an_exhausted_action`. A token rather than a
# phrasing, because the alternative is every caller matching on the words of a
# sentence somebody will rewrite; and prefixed with the project's own name so that
# nothing a tool says by accident can be read as saying this.
EXHAUSTED_ACTION_MARKER: Final = "argus:action-exhausted"

# The same convention for the other thing a write tool can report without having
# failed at what it was asked: that the platform it acts through was not there to
# be asked. Its own token rather than a second reading of the one above, because
# the two mean opposite things to a caller - one action is spent, against every
# action through that platform being unavailable.
UNREACHABLE_PLATFORM_MARKER: Final = "argus:platform-unreachable"

# What precedes the description of a change a failing action left behind, where
# it left one. Its own token rather than a position in the sentence, because what
# follows the marker above is prose somebody will rewrite and a payload found by
# counting words is a payload lost the first time one is added.
#
# The descriptor follows it as plain JSON, read out of the content block's own
# text rather than out of the `repr` of it that the failure's message is built
# from. The distinction is not cosmetic: a `repr` escapes a quote, so a revision
# message with an apostrophe in it arrives as `o\'brien` and no longer parses -
# and the payload is only ever inside a `repr` because one line below chose to
# display it that way. Read where it is structured and the problem is not there
# to be encoded around.
LEFT_BEHIND_MARKER: Final = "argus:left-behind="


class McpToolError(RuntimeError):
    """A tool was reached, and it reported a failure.

    Its own type because the retry is built on the distinction: a server that
    said no has been reached, and a second session would carry the same answer.
    Every other failure means the connection, not the answer.
    """


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
    point where `isError` becomes an exception, and a distinction drawn anywhere
    later would be a second reading of the same field.
    """


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
    property of its kind (`argus_core.models.action`), so a caller holding the
    action it just attempted can already say it - and a name parsed back out of
    a marker would be a second source for a fact that is already derivable, free
    to disagree with the first. The platform is named in what is *said*, for
    whoever reads the failure.

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
    point where `isError` becomes an exception, and a distinction drawn anywhere
    later would be a second reading of the same field.
    """

    def __init__(self, said: str,
                 undo_descriptor: UndoDescriptor | None = None) -> None:
        super().__init__(said)
        self.undo_descriptor = undo_descriptor


class McpUnreachable(RuntimeError):
    """No session to the server could be had at all.

    Not `PlatformUnreachable`, and the difference is what a caller does next. If
    no session can be had, every action is unavailable whatever platform it acts
    through and there is nothing left to narrow to; if a platform is down, the
    actions on the other platform are still there to be tried.
    """


def an_exhausted_action(said: str) -> str:
    """`said`, marked so a caller recognises a refusal that is an answer.

    For a server to wrap the words of a refusal it raises *before changing
    anything*, when what it is reporting is that the action is spent. Only then:
    a failure that arrives after something was written has left the estate
    changed, and a caller told the action was merely unavailable would be told
    nothing about the state it is now in.

    Here rather than in the server that uses it, because the marker it applies and
    the exception it becomes are two halves of one convention, and two packages
    holding a copy each is how a wire word comes to be spelled two ways.
    """
    return f"{EXHAUSTED_ACTION_MARKER} {said}"


def an_unreachable_platform(platform: str, said: str,
                            undo_descriptor: UndoDescriptor | None = None) -> str:
    """`said`, marked so a caller recognises a platform that was not there.

    For a tool to wrap the words of a failure it raises when the platform it acts
    through did not answer. Unlike `an_exhausted_action`, this is *not* restricted
    to a failure that changed nothing: an action that suspended reconciliation and
    then lost the platform passes what it left behind as `undo_descriptor`, and
    the caller is told both facts. Restricting it would mean the walk narrowed
    itself or not depending on which call the outage happened to land on.

    Two clauses replace that restriction, and the second is the load-bearing one.
    A marked failure **says what it left behind**. And an action that may have
    taken effect, and whose effect cannot be established, **does not mark at all**
    - not for want of a descriptor, but because every verification after it is
    unreliable: a service that may be restarting makes the next action's recovery
    unattributable, and a hypothesis confirmed against it would be confirmed
    wrongly.

    `platform` is named in the message rather than carried on the exception, for
    the reason `PlatformUnreachable` gives: what a caller branches on comes from
    the action's kind, and this is what a person reads.
    """
    marked = f"{UNREACHABLE_PLATFORM_MARKER} {platform} {said}"

    if undo_descriptor is None:
        return marked

    return (
        f"{marked} {LEFT_BEHIND_MARKER}"
        f"{undo_descriptor.model_dump_json()}"
    )


def what_was_left_behind(spoken: str) -> UndoDescriptor | None:
    """The descriptor a failure carried, or `None` where it carried none.

    Given what the tool actually *said* - the content block's own text - and not
    a `repr` of it. A `repr` escapes the quotes inside, so a revision message
    with an apostrophe would arrive as `o\\'brien` and stop being JSON.

    The descriptor runs to the end of the message, because JSON is not
    self-terminating in a way a split can find: an object with a space inside it
    would be cut in half by taking the first word. Nothing follows it, which is
    what makes that safe, and what `an_unreachable_platform` guarantees by
    appending it last.

    A payload that will not parse is treated as no payload rather than raised on.
    What is in hand at this point is already a failure, and replacing a caller's
    "the platform did not answer" with "the descriptor did not parse" would lose
    the fact the caller acts on in order to report one it cannot.
    """
    _, _, payload = spoken.partition(LEFT_BEHIND_MARKER)

    if not payload:
        return None

    with suppress(Exception):
        return parse_undo_descriptor(json.loads(payload))

    return None


def _the_words_of(result: CallToolResult) -> str:
    """Everything the tool said, joined, with nothing escaped on the way.

    A failed call comes back as content blocks rather than as a string, and only
    the text ones carry words. Anything else it returned is not a sentence and
    has no marker in it.
    """
    return " ".join(
        block.text for block in result.content if isinstance(block, TextContent)
    )


def without_the_payload(said: str) -> str:
    """`said` with the encoded descriptor taken out of it.

    Because the same string is what a person reads - in the timeline, in the
    postmortem, in a Slack line - and a paragraph of base64 in the middle of a
    sentence tells them nothing the outcome beside it has not already said.

    Here rather than at each caller, because the encoding is this module's and a
    caller cannot strip what it was never told the shape of.
    """
    before, _, _ = said.partition(LEFT_BEHIND_MARKER)

    return before.strip()


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
    the process's own, which are no-ops until `argus_telemetry` installs an SDK.
    """

    def __init__(self,
                 url: str,
                 tracer: Tracer | None = None,
                 meter: Meter | None = None,
                 clock: Clock = time.monotonic) -> None:
        self._url = url
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
        """
        with self._a_tool_call(name) as meta:
            answer = self._submitted(name, kwargs, meta).result()

        return returns(answer)

    async def acall[T](self,
                       name: str,
                       returns: Callable[[Any], T],
                       **kwargs: object) -> T:
        """The same call, awaited rather than waited on.

        For a caller that already has an event loop - an async route, an async
        node - where `call` would block that loop's thread for the length of a
        retrieval. Nothing in Argus needs this yet, and it is here rather than
        waiting to be needed because the alternative it replaces failed loudly
        and this one would fail quietly.
        """
        with self._a_tool_call(name) as meta:
            answer = await asyncio.wrap_future(self._submitted(name, kwargs, meta))

        return returns(answer)

    @contextmanager
    def _a_tool_call(self, name: str) -> Iterator[dict[str, Any]]:
        """One call's span and duration, and the `_meta` that carries it across.

        Yields the carrier the span's context was injected into, which is what
        the call sends - so a server reading it answers inside this span. A
        failure is said on the span and in the measurement, then raised on as
        it was.
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
                   meta: dict[str, Any]) -> Future[object]:
        """One tool call, handed to the loop that holds the session."""
        return asyncio.run_coroutine_threadsafe(
            self._call(name, arguments, meta), self._running_loop()
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
        """
        while True:
            try:
                async with (
                    streamable_http_client(self._url) as (read, write, _),
                    ClientSession(read, write) as session,
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
                    meta: dict[str, Any]) -> object:
        """One tool call, however it ends - including the client closing under it.

        A cancellation here is the client being closed and nothing else: no
        caller can cancel one of these, since what a caller holds is a future on
        another loop. It arrives as `McpUnreachable`, because what happened is
        that the server became unreachable, and a `CancelledError` surfacing in
        a walk would look like the walk being cancelled instead.
        """
        try:
            return await self._asked_again_if_the_connection_failed(name, arguments, meta)
        except asyncio.CancelledError:
            if not self._closing:
                raise

            raise McpUnreachable(
                f"the client for [{self._url}] closed while [{name}] was in flight"
            ) from None

    async def _asked_again_if_the_connection_failed(
        self, name: str, arguments: dict[str, object], meta: dict[str, Any]
    ) -> object:
        """One tool call, and the one retry a held session needs.

        The retry is about the connection and nothing else. A tool that reported
        an error was reached, so it is raised as it came; anything else means the
        session this call was made over is no longer one - which is what a
        restarted server or an idle timeout looks like from here - and the answer
        is a new session rather than a failed incident.
        """
        try:
            return await self._ask(name, arguments, meta)
        except McpToolError:
            raise
        except Exception:
            logger.warning("tool call asked again over a new session", exc_info=True,
                           extra={"tool": name})
            await self._rebuilt()
            return await self._ask(name, arguments, meta)

    async def _ask(self,
                   name: str,
                   arguments: dict[str, object],
                   meta: dict[str, Any]) -> object:
        """Calls the tool over whatever session is currently published."""
        async with self._cycled:
            await self._cycled.wait_for(
                lambda: self._generation > 0 or self._closing
            )
            session, failure = self._session, self._failure

        if self._closing:
            raise McpUnreachable(
                f"the client for [{self._url}] closed while [{name}] was in flight"
            )

        if session is None:
            raise McpUnreachable(f"no session to [{self._url}]") from failure

        return _answered(name, await session.call_tool(name, arguments=arguments, meta=meta))

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


def _answered(name: str, result: CallToolResult) -> object:
    """What the tool said, unwrapped, or the error it reported instead."""
    if result.isError:
        said = f"MCP tool call [{name}] failed: {result.content!r}"
        # What the tool said, rather than how the line above displays it. The
        # two differ by a `repr`, which escapes the quotes inside a payload and
        # would have a descriptor carrying an apostrophe arrive as something
        # that is no longer JSON. The markers are looked for here for the same
        # reason: one reading of one string, not one of each.
        spoken = _the_words_of(result)

        if EXHAUSTED_ACTION_MARKER in spoken:
            raise ActionExhausted(said)

        if UNREACHABLE_PLATFORM_MARKER in spoken:
            raise PlatformUnreachable(said, what_was_left_behind(spoken))

        raise McpToolError(said)

    structured = result.structuredContent

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
                        tracer: Tracer | None = None) -> Iterator[Span]:
    """The server's half: a span for one tool call, inside the caller's trace.

    `meta` is the request's `_meta`, where the client put its span's context.
    A request that brought none - a client that does not send it - is served
    all the same, under a trace of its own; telemetry decides nothing about
    whether a tool answers. A tool that raises is said on the span and raised
    on, so FastMCP still turns it into the error result it always did.
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
                _said_on(span, error)
                raise
    finally:
        context.detach(continued)


class TracedFastMCP(FastMCP):
    """A FastMCP server that answers every tool call inside its caller's trace.

    One override, of FastMCP's own public `call_tool` - the method its
    low-level server dispatches every tool call to - so a server built from
    this is traced whole, and a tool added to it tomorrow is traced without
    anybody remembering to. The tool itself, and every log line it writes, run
    inside the server span, which is what gives a line in a server's
    `logs.jsonl` the trace id of the walk that asked.
    """

    async def call_tool(self,
                        name: str,
                        arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        """Calls the tool, inside a span continuing whatever trace the request carried."""
        request = self.get_context().request_context
        meta = request.meta.model_dump() if request.meta is not None else None

        with serving_a_tool_call(name, meta):
            return await super().call_tool(name, arguments)

    def serve(self, run: Callable[..., None] = uvicorn.run) -> None:
        """Serves this server over streamable HTTP until the process is stopped.

        What `run(transport="streamable-http")` does, without uvicorn's own
        logging config. That config gives uvicorn's loggers handlers of their
        own and stops them propagating, so nothing uvicorn said reached the
        root - and the root is where telemetry listens. FastMCP builds its
        `uvicorn.Config` inside `run`, where nobody can reach it, so the app it
        would have served is served here instead; the app carries the session
        manager's lifespan, which is everything `run` added to it.

        `run` defaults to uvicorn's own; a parameter so that what is served,
        and how, can be asserted without serving it.
        """
        run(self.streamable_http_app(),
            host=self.settings.host,
            port=self.settings.port,
            log_config=None)
