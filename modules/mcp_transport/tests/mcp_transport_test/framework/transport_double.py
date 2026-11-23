"""A one-tool MCP server the transport's own test starts, kills and restarts.

Two things in one file, because they are two halves of one fixture: the server
itself, which is run as `python -m mcp_transport_test.framework.transport_double`,
and the handle a test drives it by. It stands in for `argus-read-mcp` and
`argus-write-mcp` alike - neither is what the transport is about, and depending
on either would make the transport's suite wait on an agent's server.

It is a real MCP server rather than a stub, because what is under test is the
session: an HTTP transport, an `initialize` handshake, and a server that can be
taken away underneath one. Nothing smaller can be wrong in the way this exists
to catch.

It is also a traced one - a `TracedMCPServer`, with an SDK installed in its own
process - because the other half of the transport is that a call arrives inside
its caller's trace, and only a server on the far side of a real session can say
which trace it found itself in.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

import uvicorn
from argus_testkit import a_free_port
from core import Fence
from core.models import DeploymentRollbackUndo
from mcp.server.mcpserver import Context
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp_transport import (
    ACTION_META_KEY,
    FENCE_META_KEY,
    TracedMCPServer,
    a_change_made_since,
    a_lost_run,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
    an_unreachable_platform,
    with_what_it_left,
)
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# How long a started double has to answer before it is taken to hang. A guard
# against a hang and nothing tighter: a process that fails to start is seen
# exiting and said at once, and on a machine loaded by every suite at once a
# start that takes a second idle has been measured at many times that.
STARTUP_TIMEOUT_SECONDS = 180.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0
# How long the server, asked to stop, gives a request still in hand before it
# cancels it - a whole number, as uvicorn takes it.
GRACEFUL_SHUTDOWN_SECONDS = 1
POLL_SECONDS = 0.2
# How long one knock on a starting double waits for its answer before knocking
# again.
KNOCK_TIMEOUT_SECONDS = 1.0
# How long a test's own call to the double's control routes waits: past any
# answer, since they answer at once and are never held.
CONTROL_TIMEOUT_SECONDS = 30.0

# Counted in the server's own process, and asked for over MCP like anything
# else. It is what lets a test say a refusal was *not* retried: a client that
# quietly asked again would leave two here where the test made one call.
_times_refused = 0
# The same, for the askings a call that may not be asked twice must not repeat:
# one tool that counts every asking it answers, and one that counts each asking
# before it stalls past whatever a client will wait for.
_times_counted = 0
_times_stalled = 0
# The askings of the tools that stall at their first asking and answer or refuse
# every later one, counted together: a server serves one test, and one test asks
# one.
_times_asked_stalling_first = 0
# Whether the next ping answered ends its session, and every session ended so:
# a server that forgot them answers whatever arrives over one with the 404 a
# server answers a session it does not hold.
_forgetting_after_the_next_ping = False
# The requests over MCP to hold before passing them on, by JSON-RPC method: how
# many more of each, and for how long - a server that took the connection and
# has not answered. And every request seen and held, by method. Armed and read
# over the double's own control routes rather than over MCP, because a session
# opened to arm or read them has a handshake of its own that an armed hold
# would hold.
_to_hold: dict[str, tuple[int, float]] = {}
_seen: Counter[str] = Counter()
_held: Counter[str] = Counter()
# What this process was started to answer its control route with, so the handle
# that started it can tell it from any other copy of the double on the port.
_token = ""
# What a tool refusing as a lost run says, as a write tier refuses one.
A_NEWER_CLAIM_HOLDS_THE_RUN: Final = "a newer claim holds this run"
_sessions_forgotten: set[bytes] = set()

# How the session a request is made over is named - the SDK's own header - as
# ASGI hands headers over: bytes.
_SESSION_HEADER: Final = MCP_SESSION_ID_HEADER.encode()
# What a server says to a request over a session it does not hold, in the SDK's
# own words and code (mcp 2.3.0, `server/streamable_http_manager.py`,
# `_error_response`: a JSON-RPC error with no request id).
_SESSION_NOT_FOUND = (
    b'{"jsonrpc":"2.0","id":null,'
    b'"error":{"code":-32600,"message":"Session not found"}}'
)
# Where the double listens: this machine alone.
_HOST: Final = "127.0.0.1"
_A_PING: Final = "ping"
# Where the double's own control routes are, beside `/mcp` and never reaching
# the SDK: one that arms a hold (`hold_the_next`), and one that says what was
# seen and held (`requests_seen`, `requests_held`).
_HOLDING_PATH: Final = "/double-control/holding"
_REQUESTS_PATH: Final = "/double-control/requests"

# What the refusals that changed something leave behind: one suspension, as the
# rollback's shape leaves it.
_A_SUSPENSION = DeploymentRollbackUndo(
    application="some-application",
    was_on_history_id=41,
    was_on_revision="0f1e2d3",
    was_syncing_itself=True
)


def build_double(port: int) -> TracedMCPServer:
    """The server: one tool that answers, one that refuses, one that counts."""
    server = TracedMCPServer("transport-double", host=_HOST, port=port)

    @server.tool()
    def say_something() -> list[str]:
        return ["something"]

    @server.tool()
    def refuse() -> list[str]:
        global _times_refused
        _times_refused += 1

        raise RuntimeError("this tool always refuses")

    @server.tool()
    def refuse_without_a_word() -> list[str]:
        """Refuses with an exception that carries no message.

        What the SDK then answers is its own prefix and nothing after it, which
        is the one refusal a transport stripping that prefix is left with no
        words for.
        """
        raise RuntimeError()

    @server.tool()
    def times_refused() -> int:
        return _times_refused

    @server.tool()
    def refuse_as_exhausted() -> list[str]:
        """Refuses the way a tier refuses an action it has no room left to take.

        Marked with the transport's own marker rather than said in words that
        sound exhausted, because the marker is what a client recognises: a
        refusal a caller had to read prose to classify would be one that
        classified differently the day somebody rephrased it.

        Raised through the server's own helper, so this double refuses exactly
        the way `argus-write-mcp` refuses rather than the way a test imagines it
        does.
        """
        raise RuntimeError(an_exhausted_action("this tool has nothing left to do"))

    @server.tool()
    def refuse_as_unreachable_platform() -> list[str]:
        """Refuses the way a tier refuses when the platform is not answering.

        Raised through the server's own helper for `refuse_as_exhausted`'s
        reason: this double refuses exactly the way `argus-write-mcp` refuses
        rather than the way a test imagines it does. The platform is named in
        what is said, because naming it is the tier's job and a double that
        left it out would let a transport that dropped the name pass.
        """
        raise RuntimeError(an_unreachable_platform(
            "some-deployment-platform", "did not answer"
        ))

    @server.tool()
    def refuse_as_unreachable_platform_mid_action() -> list[str]:
        """Refuses the way a tier refuses when the platform went after a write.

        The rollback's shape: reconciliation was suspended, which is itself a
        change, and the platform stopped answering before the revision moved. So
        what is reported is an unreachable platform *and* the descriptor that
        puts the suspension back.
        """
        raise RuntimeError(an_unreachable_platform(
            "some-deployment-platform",
            "stopped answering after reconciliation was suspended",
            undo_descriptor=_A_SUSPENSION
        ))

    @server.tool()
    def refuse_saying_it_left_nothing() -> list[str]:
        """Refuses the way a tier refuses before it has asked for any change -
        a read the platform answered with a no."""
        raise RuntimeError(a_refusal_saying_what_it_left(
            "could not read some-application"
        ))

    @server.tool()
    def refuse_saying_what_it_left() -> list[str]:
        """Refuses the way a tier refuses an action's own write that the
        platform answered with a no, after suspending reconciliation."""
        raise RuntimeError(a_refusal_saying_what_it_left(
            "the rollback was refused after reconciliation was suspended",
            _A_SUSPENSION
        ))

    @server.tool()
    def refuse_with_what_it_left() -> list[str]:
        """Refuses the way a tier refuses an action's own write whose answer was
        lost, after suspending reconciliation: what it left is carried, and not
        said to be all of it."""
        raise RuntimeError(with_what_it_left(
            "the rollback's answer was lost after reconciliation was suspended",
            _A_SUSPENSION
        ))

    @server.tool()
    def refuse_as_lost_run() -> list[str]:
        """Refuses the way the write tier refuses a change for a claim the run
        has moved past.

        Counted with the other refusals, because what a client must not do with
        this one either is ask again: a lost run is lost over a new session too.
        """
        global _times_refused
        _times_refused += 1

        raise RuntimeError(a_lost_run(A_NEWER_CLAIM_HOLDS_THE_RUN))

    @server.tool()
    def refuse_as_changed_since() -> list[str]:
        """Refuses the way a tier refuses a change somebody else made since the
        plan, where an earlier asking of it landed only the suspension before it:
        what it left is carried, and the change itself is not said performed.

        Raised through the server's own helper for `refuse_as_exhausted`'s
        reason.
        """
        raise RuntimeError(a_change_made_since(
            "some-application was changed by somebody else since it was planned",
            _A_SUSPENSION
        ))

    @server.tool()
    def refuse_as_changed_since_after_the_change() -> list[str]:
        """Refuses as `refuse_as_changed_since` does, where the earlier asking
        landed the change itself before somebody overtook it - so the refusal
        says it was performed."""
        raise RuntimeError(a_change_made_since(
            "some-application was changed by somebody else after Argus changed it",
            _A_SUSPENSION,
            performed=True
        ))

    @server.tool()
    def the_fence_i_was_sent(ctx: Context[Any, Any]) -> dict[str, object]:
        """Which claim the call said it was made for, as the write tier hears it -
        or nothing, where it said none."""
        meta = ctx.request_context.meta
        spoken = (dict(meta) if meta is not None else {}).get(FENCE_META_KEY)
        heard = Fence.heard(spoken) if isinstance(spoken, str) else None

        return {} if heard is None else {"run_id": heard.run_id, "epoch": heard.epoch}

    @server.tool()
    def the_action_i_was_sent(ctx: Context[Any, Any]) -> dict[str, object]:
        """Which action the call said it was made for, as the write tier hears
        it - or nothing, where it said none."""
        meta = ctx.request_context.meta
        spoken = (dict(meta) if meta is not None else {}).get(ACTION_META_KEY)

        return {"action_id": spoken} if isinstance(spoken, str) else {}

    @server.tool()
    async def dawdle(seconds: float) -> list[str]:
        """Still working when a test decides to close the client on it."""
        await asyncio.sleep(seconds)

        return ["eventually"]

    @server.tool()
    def count_an_asking() -> int:
        """Counts each asking it answers, and answers with the count so far.

        Counted in this process, so a server restarted beneath a client starts
        again from nothing: an asking its stale session sent and the new server
        turned away is one this never counted.
        """
        global _times_counted
        _times_counted += 1

        return _times_counted

    @server.tool()
    async def stall(seconds: float) -> list[str]:
        """Counted, and then still working long after a client stopped waiting
        for it - a call the server received and may yet carry out."""
        global _times_stalled
        _times_stalled += 1
        await asyncio.sleep(seconds)

        return ["eventually"]

    @server.tool()
    def times_stalled() -> int:
        return _times_stalled

    @server.tool()
    async def stall_then_refuse_saying_it_left_nothing(seconds: float) -> list[str]:
        """Stalls at its first asking, as a write whose answer is lost, and
        refuses at every later one saying it left nothing - a second asking the
        tier turned away before it changed anything."""
        await _stalling_at_the_first_asking(seconds)

        raise RuntimeError(a_refusal_saying_what_it_left(
            "could not read some-application"
        ))

    @server.tool()
    async def stall_then_refuse_as_changed_since(seconds: float) -> list[str]:
        """Stalls at its first asking, and refuses at every later one as
        `refuse_as_changed_since` does - a second asking that found somebody
        else acting on the service since the plan."""
        await _stalling_at_the_first_asking(seconds)

        raise RuntimeError(a_change_made_since(
            "some-application was changed by somebody else since it was planned",
            _A_SUSPENSION
        ))

    @server.tool()
    async def stall_then_answer(seconds: float) -> list[str]:
        """Stalls at its first asking, as a write whose answer is lost, and
        answers every later one - a second asking that found the change made."""
        await _stalling_at_the_first_asking(seconds)

        return ["something"]

    @server.tool()
    async def stall_then_refuse_as_lost_run(seconds: float) -> list[str]:
        """Stalls at its first asking, and refuses every later one as
        `refuse_as_lost_run` does - a second asking made after the run moved on."""
        await _stalling_at_the_first_asking(seconds)

        raise RuntimeError(a_lost_run(A_NEWER_CLAIM_HOLDS_THE_RUN))

    @server.tool()
    def times_asked_stalling_first() -> int:
        return _times_asked_stalling_first

    @server.tool()
    def end_the_server_on_being_asked() -> list[str]:
        """Ends this server's process before answering - a server gone the
        moment it had a call, with no answer on its way. Nothing is counted: a
        count would die with the process.

        Ended from inside the asking rather than stopped from outside, so no
        test has to watch for the asking to have arrived before it stops it."""
        os._exit(0)

    @server.tool()
    def forget_a_session_after_the_next_ping() -> list[str]:
        """Has the server forget the session the next ping it answers was made
        over, once.

        The ping is answered, so a client that pings before it sends finds its
        session answering; whatever it sends over that session next is answered
        404 "Session not found", as a server restarted between the two would
        answer it - turned away before any tool is asked anything.
        """
        global _forgetting_after_the_next_ping
        _forgetting_after_the_next_ping = True

        return ["the next ping's session will be forgotten"]

    @server.tool()
    def the_trace_i_am_in() -> dict[str, str]:
        """Which trace this call was answered in, and which span it answered under.

        Read off the span current inside the tool, which is the server's own -
        so its parent is whatever the request said it was called from. Hex, as
        OTLP spells ids, so a test compares them with the client's own spans
        without converting either.
        """
        span = trace.get_current_span()
        parent = span.parent if isinstance(span, ReadableSpan) else None

        return {
            "trace_id": format(span.get_span_context().trace_id, "032x"),
            "parent_span_id": format(parent.span_id, "016x") if parent is not None else ""
        }

    return server


async def _stalling_at_the_first_asking(seconds: float) -> None:
    """Counts one asking, and stalls `seconds` where it is the first."""
    global _times_asked_stalling_first
    _times_asked_stalling_first += 1

    if _times_asked_stalling_first == 1:
        await asyncio.sleep(seconds)


class _ForgettingSessionsAfterAPing:
    """The server's app behind a door that forgets a session when armed to
    (`forget_a_session_after_the_next_ping`).

    In front of the SDK's session manager rather than inside it, because a
    client meets nothing more than this: a 404 over a session the server
    answered a ping over a moment before.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        global _forgetting_after_the_next_ping

        session = dict(scope["headers"]).get(_SESSION_HEADER) if scope["type"] == "http" else None

        if session is not None and session in _sessions_forgotten:
            await Response(_SESSION_NOT_FOUND, status_code=404,
                           media_type="application/json")(scope, receive, send)
            return

        if not _forgetting_after_the_next_ping or session is None or scope["method"] != "POST":
            await self._app(scope, receive, send)
            return

        body, receive_again = await _read_whole(receive)
        asked = json.loads(body) if body else None

        # Forgotten before the ping is passed on, so nothing sent over the
        # session once the ping is answered can arrive before it is forgotten.
        if isinstance(asked, dict) and asked.get("method") == _A_PING:
            _sessions_forgotten.add(session)
            _forgetting_after_the_next_ping = False

        await self._app(scope, receive_again, send)


class _HoldingRequestsWhenTold:
    """The server's app behind a door that counts every request over MCP by its
    method, and holds the next ones of a method before passing them on when
    told to - and that answers the two control routes that tell and ask it.

    In front of the SDK rather than inside it, because what it holds - the
    handshake, a list of tools, a ping - is the SDK's own and answered before
    any tool is asked anything: what a client meets is a connection taken and
    no answer to its request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        if scope["path"] == _HOLDING_PATH:
            body, _ = await _read_whole(receive)
            told = json.loads(body)
            _to_hold[told["method"]] = (told["times"], told["seconds"])
            await JSONResponse({})(scope, receive, send)
            return

        if scope["path"] == _REQUESTS_PATH:
            await JSONResponse(
                {"token": _token, "seen": _seen, "held": _held}
            )(scope, receive, send)
            return

        if scope["method"] != "POST":
            await self._app(scope, receive, send)
            return

        body, receive_again = await _read_whole(receive)
        asked = json.loads(body) if body else None
        method = asked.get("method") if isinstance(asked, dict) else None

        if isinstance(method, str):
            _seen[method] += 1
            times, seconds = _to_hold.get(method, (0, 0.0))

            if times > 0:
                _to_hold[method] = (times - 1, seconds)
                _held[method] += 1
                await asyncio.sleep(seconds)

        await self._app(scope, receive_again, send)


async def _read_whole(receive: Receive) -> tuple[bytes, Receive]:
    """A request's whole body, and a `receive` that hands it over again before
    whatever arrives after it."""
    chunks: list[bytes] = []
    more = True

    while more:
        message = await receive()
        chunks.append(message.get("body", b""))
        more = bool(message.get("more_body", False))

    body = b"".join(chunks)
    handed_over = False

    async def receive_again() -> Message:
        nonlocal handed_over

        if handed_over:
            return await receive()

        handed_over = True

        return {"type": "http.request", "body": body, "more_body": False}

    return body, receive_again


class RunningDouble:
    """The double as a test drives it: up, down, and up again on the same port.

    Restarting on the same address is the whole point. A client holding a
    session to a server that went away has to notice and open another, and the
    only way to find out whether it does is to take the server away.
    """

    def __init__(self, port: int) -> None:
        self._port = port
        self._process: subprocess.Popen[bytes] | None = None
        self._token = ""

    @property
    def url(self) -> str:
        """Where the double serves MCP, in the form a client is given."""
        return f"http://127.0.0.1:{self._port}/mcp"

    def hold_the_next(self, method: str, times: int, seconds: float) -> None:
        """Has the next `times` requests over MCP whose JSON-RPC method is
        `method` held `seconds` before the server is handed them."""
        told = json.dumps({"method": method, "times": times, "seconds": seconds}).encode()
        urllib.request.urlopen(
            urllib.request.Request(self._control(_HOLDING_PATH), data=told, method="POST"),
            timeout=CONTROL_TIMEOUT_SECONDS
        ).close()

    def requests_seen(self, method: str) -> int:
        """How many requests whose JSON-RPC method is `method` the server has
        been sent since it started, held ones included."""
        return int(self._requests(CONTROL_TIMEOUT_SECONDS)["seen"].get(method, 0))

    def requests_held(self, method: str) -> int:
        """How many requests whose JSON-RPC method is `method` were held."""
        return int(self._requests(CONTROL_TIMEOUT_SECONDS)["held"].get(method, 0))

    def start(self) -> None:
        """Starts the server and waits until it is answering - and stops it
        again where waiting fails, so a server that never answered is not left
        holding the port.

        Each process is started with a token of its own to answer its control
        route with. Not its process id: on Windows a venv's `python.exe` starts
        the interpreter as a child of its own, so the id `Popen` has is not the
        server's."""
        if self._process is not None:
            return

        self._token = uuid.uuid4().hex
        self._process = subprocess.Popen(
            [sys.executable, "-m", __name__, str(self._port), self._token],
            env={**os.environ, "PYTHONPATH": str(_suite_root())}
        )

        try:
            self._wait_until_listening()
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        """Stops the server and waits for it to give the port back - killing
        it where it has not stopped once asked to."""
        if self._process is None:
            return

        self._process.terminate()

        try:
            self._process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)

        self._process = None

    def restart(self) -> None:
        """Takes the server away and puts another in its place.

        The same address, a new process, and therefore no memory of any session
        a client still believes it holds.
        """
        self.stop()
        self.start()

    def __enter__(self) -> Self:
        self.start()

        return self

    def __exit__(self,
                 exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.stop()

    def _control(self, path: str) -> str:
        return f"http://127.0.0.1:{self._port}{path}"

    def _requests(self, timeout: float) -> dict[str, Any]:
        """What the control route answers: the token the process answering was
        started with, and the requests it saw and held."""
        with urllib.request.urlopen(self._control(_REQUESTS_PATH), timeout=timeout) as answered:
            counted: dict[str, Any] = json.loads(answered.read())

        return counted

    def _wait_until_listening(self) -> None:
        """Waits until the server answers, and says at once that it never will
        where its process has ended."""
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            ended_with = self._process.poll() if self._process is not None else None

            if ended_with is not None:
                raise RuntimeError(
                    f"the transport double for {self.url} ended with [{ended_with}] "
                    f"before it answered"
                )

            try:
                # Its own control route, answered with the token this process
                # was started with: any other answer on the port says only that
                # something is listening there - on a machine whose WSL forwards
                # its own listeners to this one's loopback, another suite's
                # double, or one a killed run left behind - while this one may
                # have failed to take the port.
                if self._requests(KNOCK_TIMEOUT_SECONDS).get("token") == self._token:
                    return

                # Another copy of the double answered: this one has not, and
                # will be seen ending if it could not take the port.
                time.sleep(POLL_SECONDS)
            except (urllib.error.HTTPError, ValueError):
                # Something that is no double answered on the port - refusing,
                # or with something that is not JSON: this double has not, and
                # will be seen ending if it could not take the port.
                time.sleep(POLL_SECONDS)
            except OSError:
                # Not answering yet: refused, or taken and not answered within
                # the knock's second - which `urlopen` raises bare, not as a
                # `URLError`, and which a loaded machine's server does.
                time.sleep(POLL_SECONDS)

        raise TimeoutError(
            f"the transport double at {self.url} did not answer within "
            f"{STARTUP_TIMEOUT_SECONDS} seconds"
        )


@contextmanager
def a_running_double() -> Generator[RunningDouble]:
    """One double, running for the length of one test, on a port the operating
    system handed out rather than one written here - a written one is shared by
    every copy of this suite running at once, a second checkout's or a WSL
    run's, and one copy's client then talks to the other's double."""
    with RunningDouble(a_free_port()) as double:
        yield double


def _suite_root() -> Path:
    """`modules/mcp_transport/tests`, which is what makes this importable by name.

    The suite is a package tree rather than an installed distribution, so a
    subprocess told to run one of its modules has to be told where the tree is.
    """
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    # An SDK of the double's own, exporting nowhere: what makes the server's
    # span a real one with a parent to report, rather than the API's no-op.
    trace.set_tracer_provider(TracerProvider())
    # Served as `TracedMCPServer.serve` serves it, behind the doors that can
    # hold a request and forget a session. Asked to stop, it gives a request it
    # is still holding a moment and then cancels it: uvicorn would otherwise
    # wait for every one with no limit at all.
    _token = sys.argv[2]
    port = int(sys.argv[1])
    double = build_double(port)
    uvicorn.run(_HoldingRequestsWhenTold(
                    _ForgettingSessionsAfterAPing(
                        double.streamable_http_app(host=_HOST, session_idle_timeout=None)
                    )
                ),
                timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
                host=_HOST,
                port=port,
                log_level=double.settings.log_level.lower())
