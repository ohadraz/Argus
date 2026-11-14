"""The double itself: an HTTP server that speaks Anthropic's Messages API.

Two surfaces, deliberately separate:

- `POST /v1/messages` - what the SDK talks to. It never invents an answer. It
  serves what the test seeded, or what was recorded from the real API, and
  fails loudly when it has neither.
- `POST /double-control/*` - what the *test* talks to, to say what should
  happen next - including, with `hold`, *when*: a call held waits until the
  test releases it. Same shape as the Target Service's own scenario control, so
  there is one idea to learn rather than two.

Selecting the double is a one-line change on the caller's side
(`anthropic_base_url`), which is the whole point: nothing in the adapter knows
this file exists.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any, Final

import httpx2
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, model_validator

from anthropic_double import recordings
from anthropic_double.clock import moved_in
from anthropic_double.streaming import SSE_MEDIA_TYPE, as_stream, from_stream

UPSTREAM_BASE_URL = os.environ.get("ANTHROPIC_DOUBLE_UPSTREAM", "https://api.anthropic.com")

# Where the double listens. Not an `argus_core` setting: the double is not
# part of Argus, and Argus's own config should not grow a field describing a
# test fixture. Callers that need to point at it - the harness that starts it,
# the tests that seed it - import these.
DEFAULT_PORT = int(os.environ.get("ANTHROPIC_DOUBLE_PORT", "8091"))
DEFAULT_BASE_URL = f"http://localhost:{DEFAULT_PORT}"

# The `error.type` Anthropic returns for each status the double can be asked to
# produce. Seeding a status without a body gets the canonical shape for it, so
# a test that only cares "this is a 429" does not have to hand-write the
# envelope - and cannot hand-write it slightly wrong.
_ERROR_TYPES: dict[int, str] = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    429: "rate_limit_error",
    500: "api_error",
    529: "overloaded_error",
}

# How often a held call looks again for a release. Short, because the
# test that released it is waiting on the answer, and polling an in-process
# flag costs nothing.
_A_HELD_CALL_LOOKS_EVERY = 0.05

# Headers worth carrying upstream while recording. Everything else - `host`,
# `content-length`, the connection headers - is either wrong for the new
# destination or recomputed by httpx2.
_FORWARDED_HEADERS = ("x-api-key", "authorization", "anthropic-version", "anthropic-beta")

# Anthropic's word for a block that calls a tool: the only blocks whose times
# move on arrival.
_TOOL_USE_TYPE: Final = "tool_use"

# The two settings a stack hands every process, the double among them, to put
# it on the stack's clock. Spelled here rather than imported from
# `argus_core.clock`: the double does not depend on Argus.
_CLOCK_EPOCH_VARIABLE: Final = "SIM_CLOCK_EPOCH"
_CLOCK_SPEED_VARIABLE: Final = "SIM_CLOCK_SPEED"


def _the_stacks_now() -> datetime:
    """The stack's instant, read as every other process of it reads it:
    `epoch + (real - epoch) * speed`, and the real clock where the stack hands
    neither setting.

    Not the real clock regardless. A replay runs every party on the stack's
    clock, the shop included - and the instant a question was expected at is
    in that frame, so a lateness read off the real one would come out short by
    however far the stack has run ahead of it.

    Raises `ValueError` where only one is set, for `argus_core.clock`'s reason.
    """
    epoch = os.environ.get(_CLOCK_EPOCH_VARIABLE)
    speed = os.environ.get(_CLOCK_SPEED_VARIABLE)

    if epoch is None and speed is None:
        return datetime.now(UTC)

    if epoch is None or speed is None:
        raise ValueError(
            f"A simulated clock needs both {_CLOCK_EPOCH_VARIABLE} and "
            f"{_CLOCK_SPEED_VARIABLE}; this environment sets only one."
        )

    return datetime.fromtimestamp(
        float(epoch) + (time.time() - float(epoch)) * float(speed), UTC
    )


class Seed(BaseModel):
    """One queued answer for the next `POST /v1/messages`.

    Three ways to say what should come back, in the order they are checked:
    a stored `recording`, an explicit `body` (how a schema-violating response
    is expressed - no recording of a malformed answer can exist), or a bare
    error `status`, which fills in Anthropic's canonical error envelope.
    """

    recording: str | None = None
    status: int = 200
    body: dict[str, Any] | None = None
    # The recording a `body` was made from - a recorded answer rebased onto
    # this run's world. Not served, the body is; compared, as a recording's own
    # question is, so a rebased answer to a question that has since changed is
    # listed in `/double-control/state` like any other.
    recorded_as: str | None = None
    # When the question this body answers is expected to arrive, and the times
    # in its tool calls - as the body writes them - that move by however much
    # later than that it does arrive. Which times those are is the seeder's to
    # say; the double only moves them. Both or neither.
    arrives_at: datetime | None = None
    moves_on_arrival: list[str] = []
    # How many calls this seed answers before the queue moves on. `None` means
    # "until reset", which is the only honest way to express a condition the
    # SDK retries through: it answers a 429 up to `max_retries` times on its
    # own, so a test seeding one 429 would have its second attempt fall off
    # the end of the queue. A count tied to the SDK's retry setting would be a
    # magic number that breaks when that setting changes.
    repeat: int | None = 1

    @model_validator(mode="after")
    def _must_say_something(self) -> Seed:
        if self.recording is None and self.body is None and self.status == 200:
            raise ValueError(
                "a seed must carry a recording, a body, or a non-200 status - "
                "an empty seed says nothing about what the next call returns"
            )
        if self.recording is not None and self.body is not None:
            raise ValueError("a seed carries either a recording or a body, not both")
        if self.recorded_as is not None and self.body is None:
            raise ValueError("`recorded_as` names the recording a body was made from - "
                             "a seed with no body was made from nothing")
        if self.moves_on_arrival and (self.body is None or self.arrives_at is None):
            raise ValueError("`moves_on_arrival` names times in a body that move from "
                             "`arrives_at` - a seed with times to move needs both")
        if self.repeat is not None and self.repeat < 1:
            raise ValueError("a seed answers at least one call, or `null` for until-reset")
        return self


class RecordRequest(BaseModel):
    """Turns record mode on: the next calls go upstream and are saved.

    `keeps_arrivals` stores beside each answer the instant its question
    arrived. Only for a session that records a set from its first answer: an
    arrival is in the frame of the run that recorded it, and only a whole
    capture's run is the one the set's anchor was taken in.
    """

    name: str
    keeps_arrivals: bool = False


class _State:
    """The double's whole memory, reset between tests via `/double-control/reset`.

    Deliberately in-process and non-persistent. The double is brought up per
    run alongside the other services; a seed surviving a restart would be a
    test leaking into the next one.
    """

    def __init__(self) -> None:
        self.seeds: deque[Seed] = deque()
        self.record_as: str | None = None
        self.recorded: int = 0
        self.keeps_arrivals: bool = False
        # A hold asked for and not yet caught, and a call caught and waiting.
        self.holding: bool = False
        self.held: bool = False
        # The tools the call held was offered, so whoever holds it can tell
        # which call it is - a walk at its ending can still be in Code-Fix.
        self.held_tools: list[str] = []
        # A hold for the first call the queue cannot answer, asked for and not
        # yet caught.
        self.holding_when_dry: bool = False
        # Each recording served to a question other than the one it answered,
        # by name, with the part of the question that differed.
        self.diverged: dict[str, str] = {}

    def reset(self) -> None:
        self.seeds.clear()
        self.record_as = None
        self.recorded = 0
        self.keeps_arrivals = False
        self.holding = False
        self.held = False
        self.held_tools = []
        self.holding_when_dry = False
        self.diverged.clear()

    def catches(self) -> bool:
        """Whether the hold catches the call now arriving - the first to arrive
        after it was asked for, whatever is queued.

        Not "the first with nothing queued", because the queue says nothing
        while recording: it is empty on every call there, and full from the
        start of a replay, so a hold read off it would catch different calls
        in the two - and a recording is only worth replaying if it was
        captured in the order its case drives. That hold is a different one,
        asked for by name - see `catches_when_dry`.
        """
        if not self.holding:
            return False

        self.holding = False
        self.held = True
        return True

    def catches_when_dry(self) -> bool:
        """Whether the hold-when-dry catches the call now arriving - the first
        to find the queue empty.

        For a replay that leaves its last answer to the real model: every call
        before it is answered from the queue, and the one nothing answers is
        held before it is forwarded, so whoever asked can look at the world the
        replay built and decide whether that call is worth paying for.
        """
        if not self.holding_when_dry or self.seeds:
            return False

        self.holding_when_dry = False
        self.held = True
        return True

    def take_next_seed(self) -> Seed:
        """The seed answering this call, consuming one of its repeats.

        A seed with `repeat: null` stays at the head of the queue until the
        next reset, so anything behind it is unreachable - which is the point:
        "the API is refusing every call right now" is a state, not a queue of
        identical events.
        """
        head = self.seeds[0]
        if head.repeat is None:
            return head

        head.repeat -= 1
        if head.repeat == 0:
            self.seeds.popleft()
        return head

    def next_recording_name(self) -> str:
        """Names successive recordings in one record-mode run.

        A tool-using investigation is a conversation, and each of its turns is
        a separate request with its own response - so the second and later
        responses get a numbered suffix rather than overwriting the first.

        How many there are is the model's to decide rather than a configured
        count: it keeps asking for evidence until it answers or the loop's
        budget stops it.
        """
        assert self.record_as is not None
        self.recorded += 1
        if self.recorded == 1:
            return self.record_as
        return f"{self.record_as}-{self.recorded}"


_state = _State()

app = FastAPI(title="anthropic-double")


@app.get("/health")
def health() -> dict[str, str]:
    """Readiness probe, so a test harness can wait for the port to answer."""
    return {"status": "ok"}


@app.post("/double-control/seed")
def seed(seed: Seed) -> dict[str, int]:
    """Queues one answer. Seeds are served first-in-first-out, one per call.

    A queue rather than a single slot, because the thing under test is a loop:
    "low confidence, then confident" is a case that needs two answers lined up
    before the loop starts.
    """
    _state.seeds.append(seed)
    return {"queued": len(_state.seeds)}


@app.post("/double-control/hold")
def hold() -> dict[str, bool]:
    """Holds the next call to arrive until a release.

    For a test whose order is the point: it fires what makes the call, does
    what has to happen before the answer, and only then releases it - so the
    caller cannot get ahead of the test however fast it runs.

    The held call ignores the queue while it waits, and only a release lets
    it go. A seed cannot, because a replay seeds the whole walk up front and a
    recording seeds nothing, and a hold that one of them ended at once and the
    other never did would order a recording differently from its replay.
    Calls other than the held one are answered as they always are.
    """
    _state.holding = True
    return {"holding": True}


@app.post("/double-control/hold-when-dry")
def hold_when_dry() -> dict[str, bool]:
    """Holds the first call to find the queue empty, until a release.

    For a replay whose last answer is recorded afresh: the walk's own answers
    are seeded, and the call none of them answers is the one that would be
    forwarded and paid for. Held, it can be looked at first - and refused with
    a reset, which costs nothing, where a forwarded call has already been paid.

    A hold of its own rather than `hold` read differently: `hold` catches the
    next call whatever is queued, for the reason `_State.catches` gives, and a
    case relying on that must not find it changed.
    """
    _state.holding_when_dry = True
    return {"holding_when_dry": True}


@app.post("/double-control/release")
def release() -> dict[str, bool]:
    """Lets the held call go, and with it any hold not yet caught.

    The call released is answered as though it had just arrived: the next
    seed, or the real API while recording, or the refusal a call with neither
    gets.
    """
    released = _state.held
    _state.holding = False
    _state.holding_when_dry = False
    _state.held = False
    _state.held_tools = []
    return {"released": released}


@app.post("/double-control/record")
def record(request: RecordRequest) -> dict[str, str]:
    """Forwards subsequent calls to the real API and saves what comes back.

    Recording is a proxy rather than a separate script on purpose: the request
    that gets recorded is then, by construction, exactly the request the
    adapter sends - prompt, schema transform and all. A script that rebuilt
    the request would be recording its own idea of it.
    """
    _state.record_as = request.name
    _state.recorded = 0
    _state.keeps_arrivals = request.keeps_arrivals
    return {"recording_as": request.name}


@app.post("/double-control/reset")
def reset() -> dict[str, str]:
    """Clears the queue, leaves record mode, and ends a hold - a call held is
    refused, so no case leaves one hanging into the next."""
    _state.reset()
    return {"status": "reset"}


@app.get("/double-control/state")
def state() -> dict[str, Any]:
    """What the double is currently holding - queued seeds, record mode, store."""
    return {
        "queued": len(_state.seeds),
        "recording_as": _state.record_as,
        "recorded": _state.recorded,
        "holding": _state.holding,
        "holding_when_dry": _state.holding_when_dry,
        "held": _state.held,
        "held_tools": _state.held_tools,
        "diverged": _state.diverged,
        "available_recordings": recordings.available(),
    }


def _error_body(status: int) -> dict[str, Any]:
    return {
        "type": "error",
        "error": {
            "type": _ERROR_TYPES.get(status, "api_error"),
            "message": f"seeded {status} from the anthropic double",
        },
    }


def _the_part_that_differs(recorded: dict[str, Any], asked: dict[str, Any]) -> str | None:
    """Which part of the question a recorded answer was given to differs from
    the question now asked - `None` where neither does.

    Two parts, compared two ways, because a replay never asks exactly the
    question its recording answered. The brief carries the run's own instants,
    incident id and measured figures, so a run that changed nothing still asks
    with different numbers in it - and a comparison that counted those would
    report every recording stale on every run.

    So everything but the conversation - the instructions, the tools, the
    model, its budget and its effort - is compared exactly: those differ only
    where the code changed. Every field rather than a list of them, so a field
    the adapter starts sending tomorrow shows as a difference instead of
    passing unread; only what says how a question travels, and cannot change
    its answer, is left out.

    The conversation is compared with every id and digit masked out: what is
    left is the wording of the brief and which lines it holds, which differ
    where a sentence changed or the run took a different branch - and either
    is a different question.
    """
    def all_but_the_conversation(body: dict[str, Any]) -> dict[str, Any]:
        return {field: value for field, value in body.items()
                if field != _THE_CONVERSATION and field not in _HOW_IT_TRAVELS}

    if all_but_the_conversation(recorded) != all_but_the_conversation(asked):
        return "instructions"

    if _masked(recorded.get(_THE_CONVERSATION)) != _masked(asked.get(_THE_CONVERSATION)):
        return "conversation"

    return None


# The field of a Messages API request that holds the conversation.
_THE_CONVERSATION: Final = "messages"

# The fields that say how a question travels and cannot change its answer:
# streamed or not, and where the cache breakpoints sit.
_HOW_IT_TRAVELS: Final = frozenset({"stream", "cache_control"})

# What a run writes into a question differently every time it runs, masked out
# of the conversation before it is compared: an id - a uuid, whose groups can be
# all letters, or a run of hex long enough to be a commit - and any digit, which
# takes an instant, a measured figure, a count and a port with it.
_RUN_SPECIFIC: Final = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|\b[0-9a-f]{7,40}\b"
    r"|\d+"
)

# A span of time, masked whole before its digits are: which units it names, and
# whether each is said in the singular, are run timing as much as its digits are
# - a span landing on a whole minute drops its seconds, one landing on a single
# second says "second", and one under a second says neither.
_A_SPAN: Final = re.compile(
    r"\b\d+ (?:day|hour|minute|second)s?(?: \d+ (?:day|hour|minute|second)s?)*\b"
    r"|\bless than a second\b"
)


# A day as a reader says one - "Oct 16" - masked whole before its digits are:
# the shift follows the day a replay runs, so its month moves as its digits
# do. Only beside a day number, so "May" as a word is still compared.
_A_DAY: Final = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}\b"
)


# A run of rows that are nothing but masked figures - a metrics table, one
# minute a line - said as one row, after the digits are masked. How many
# minutes a read covers is run timing too: a walk reading one minute later
# than its recording holds one more row, and the question is the same one.
# Matched in the dumped text, where a line ends in an escaped newline, and
# only from a line's start: a line that merely ends in figures is not a row.
_A_RUN_OF_ROWS: Final = re.compile(r"(?<=\\n)(?:[-.,:TZ ]*#[-#.,:TZ ]*\\n)+")


def _masked(conversation: Any) -> str:
    """A conversation as one canonical text, with everything a run writes
    differently each time masked out."""
    said = json.dumps(conversation, sort_keys=True)
    said = _RUN_SPECIFIC.sub("#", _A_SPAN.sub("#", _A_DAY.sub("#", said)))
    return _A_RUN_OF_ROWS.sub(r"#\\n", said)


def _moved_on_arrival(seed: Seed, body: dict[str, Any]) -> dict[str, Any]:
    """A seeded body with the times its seed marks moved by how much later than
    expected its question arrived - in its tool calls only, never its prose.

    Moved here, as the answer is served, because only here is the arrival
    known: a replay seeds the whole walk up front, before any question has
    been asked.
    """
    if seed.arrives_at is None or not seed.moves_on_arrival:
        return body

    late_by = _the_stacks_now() - seed.arrives_at
    marked = frozenset(seed.moves_on_arrival)

    return {**body, "content": [
        {**block, "input": moved_in(block.get("input") or {}, late_by, marked)}
        if block.get("type") == _TOOL_USE_TYPE else block
        for block in body.get("content", [])
    ]}


def _serve(seed: Seed, streaming: bool = False, asked: dict[str, Any] | None = None) -> Response:
    """One seeded answer, said whichever way the caller asked for it.

    Only a real answer can be streamed. An error is an error in both shapes -
    the SDK reads a non-200 as a failure before it looks for events - so a
    seeded status keeps the body it always had.

    A recorded answer is still served when the question it answered has since
    changed - a replay is not the place a stale recording fails, the case's own
    assertions are - but the name goes on the list `/double-control/state`
    reports, which is what a partial re-record is chosen from.
    """
    # A body rebased from a recording is compared as that recording: the
    # question it answered is the recording's, whatever instants it now names.
    named = seed.recording or seed.recorded_as
    if named is not None and asked is not None:
        recorded_question = recordings.load_question(named)
        if recorded_question is not None:
            differs = _the_part_that_differs(recorded_question, asked)
            if differs is not None:
                _state.diverged[named] = differs

    if seed.recording is not None:
        answered = recordings.load(seed.recording)
        if streaming:
            return StreamingResponse(as_stream(answered), media_type=SSE_MEDIA_TYPE)
        return JSONResponse(status_code=200, content=answered)

    body = (_moved_on_arrival(seed, seed.body) if seed.body is not None
            else _error_body(seed.status))
    if streaming and seed.status == 200:
        return StreamingResponse(as_stream(body), media_type=SSE_MEDIA_TYPE)

    return JSONResponse(status_code=seed.status, content=body)


async def _record_upstream(request: Request, streaming: bool) -> Response:
    """Passes one call through to the real API and stores the response.

    Forwarded exactly as it arrived, streamed or not, because the request that
    gets recorded has to be the request the adapter sends - and Code-Fix's is
    streamed, since the SDK will not carry a whole-file answer any other way.
    What comes back on that transport is a run of events rather than a
    message, so it is assembled back into one here: a recording is the
    message the model ended up sending, whichever way it arrived, which is
    what lets a stored answer serve a streamed reader and an unstreamed one
    alike.

    Read as a stream rather than as a body, which is also what keeps the
    timeout honest. Ten minutes bounding a whole generation is a bound a
    large answer can reach by being large; ten minutes bounding the gap
    between two events is a bound only a stall reaches.

    Where the session keeps arrivals, the instant the question arrived is
    stored beside it - on the stack's clock, and taken here, where a replay's
    `_moved_on_arrival` takes its own, after any hold, so the two are read at
    the same point of a call.
    """
    arrived = _the_stacks_now()
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() in _FORWARDED_HEADERS
    }
    sent = await request.body()

    async with httpx2.AsyncClient(base_url=UPSTREAM_BASE_URL, timeout=600.0) as client:
        if not streaming:
            upstream = await client.post("/v1/messages", content=sent, headers=headers)
            answered: dict[str, Any] = upstream.json()
            status = upstream.status_code
        else:
            async with client.stream(
                "POST", "/v1/messages", content=sent, headers=headers
            ) as response:
                events = await response.aread()
            status = response.status_code
            # A refusal comes back as a body on both transports: the API says
            # no before it says anything else, so there is no stream to read.
            answered = (
                from_stream(events.decode()) if status == 200 else json.loads(events)
            )

    if status != 200:
        return JSONResponse(status_code=status, content=answered)

    # The question beside the answer, as it was forwarded: what a later replay
    # is compared with to tell whether this answer is still to the point.
    name = _state.next_recording_name()
    recordings.save(name, answered)
    recordings.save_question(name, json.loads(sent))
    if _state.keeps_arrivals:
        recordings.save_arrival(name, arrived)

    # Said back the way it was asked for, exactly as a seeded answer is. What
    # is stored is the assembled message either way - but a caller that asked
    # to be streamed is parsing events, and handing it a body is handing it a
    # stream with nothing in it. Code-Fix is that caller on every call it
    # makes, which is why nothing it did survived a recording run.
    if streaming:
        return StreamingResponse(as_stream(answered), media_type=SSE_MEDIA_TYPE)

    return JSONResponse(status_code=status, content=answered)


@app.post("/v1/messages")
async def messages(request: Request) -> Response:
    """The one route the SDK calls. Seeded answer, or recorded one, or a loud 400.

    There is no default response. A test that forgot to seed gets an error
    naming what it forgot, not a plausible hypothesis - a double that guesses
    is a double that can make a broken investigation look like a working one.
    A test that asked for a hold gets the next call to arrive held until it
    releases it, in record mode as in replay.

    Whether the caller asked to be streamed changes only how the answer is
    said, never which answer it is. Code-Fix streams because its answers are
    whole files and the SDK will not carry one that large any other way; a
    recording is the assembled message either way, so the same stored body
    serves both and nothing about the evidence depends on the transport.

    Recording forwards the question as it arrived, streamed or not, because
    the request that gets recorded has to be the request the adapter sends.
    What comes back on a stream is reassembled into the message it was before
    it is stored - a stored transport would have to be read back by code that
    would then be the only reader of a shape nothing else uses.
    """
    asked: dict[str, Any] = json.loads(await request.body())
    streaming = bool(asked.get("stream"))

    # Held: wait for the test to release - or reset, which releases too. The
    # answer is chosen only after, so a seed queued while waiting is the one
    # this call takes.
    if _state.catches() or _state.catches_when_dry():
        _state.held_tools = [tool["name"] for tool in asked.get("tools", [])]
        while _state.held:
            await asyncio.sleep(_A_HELD_CALL_LOOKS_EVERY)

    if _state.seeds:
        return _serve(_state.take_next_seed(), streaming, asked)

    if _state.record_as is not None:
        return await _record_upstream(request, streaming)

    return JSONResponse(
        status_code=400,
        content={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": (
                    "the anthropic double has nothing queued: POST /double-control/seed "
                    "before the call under test, or /double-control/record to capture a "
                    "real response. Stored recordings: "
                    f"{', '.join(recordings.available()) or 'none'}"
                ),
            },
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="localhost", port=DEFAULT_PORT)
