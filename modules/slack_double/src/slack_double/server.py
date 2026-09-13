"""The double itself: an HTTP server that speaks Slack's Web API.

Two surfaces, deliberately separate, and the same arrangement `anthropic_double`
already has:

- `POST /api/chat.postMessage` - what the Slack SDK talks to. Unlike the
  Anthropic double it invents its answer, because Slack's is inventable: a
  message id is a timestamp and nothing about it had to be a model's. What it
  will not invent is a failure, which is always the test's to ask for.
- `POST /double-control/*`, `GET /double-control/*` - what the *test* talks to,
  to say what should happen next and to read back what was posted.

Selecting the double is a one-line change on the caller's side (the SDK's base
URL), which is the point: nothing in the Communicator knows this file exists.

Every message is kept rather than counted. What a test wants to know is not
"was something posted" but "what would a human have seen" - which channel, in
which thread, in what order - and a double that only tallied calls could not
answer it.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

# Where the double listens. Not an `argus_core` setting, for the reason the
# Anthropic double's port is not: the double is not part of Argus, and Argus's
# own config should not grow a field describing a test fixture.
DEFAULT_PORT: Final = int(os.environ.get("SLACK_DOUBLE_PORT", "8094"))
DEFAULT_BASE_URL: Final = f"http://localhost:{DEFAULT_PORT}"

# Slack's own vocabulary, named here because this is the module that writes it.
_OK_FIELD: Final = "ok"
_ERROR_FIELD: Final = "error"
_CHANNEL_ARG: Final = "channel"
_TEXT_ARG: Final = "text"
_THREAD_TS_ARG: Final = "thread_ts"

# The status Slack answers a throttled caller with, and the header carrying how
# long to wait. The one failure that is *not* an `ok: false` body - every other
# error is a 200 whose payload says no.
_RATE_LIMITED_STATUS: Final = 429
_RETRY_AFTER_HEADER: Final = "Retry-After"
_RATE_LIMITED_ERROR: Final = "rate_limited"

# A Slack message id is an epoch second and six more digits, unique within a
# channel. Counted rather than clocked, so that two messages a millisecond
# apart are still two ids, and so a test reading them back gets the order it
# posted in.
_FIRST_TS_SECOND: Final = 1789000000
_TS_FRACTION_WIDTH: Final = 6


class Seed(BaseModel):
    """One queued failure for the next `chat.postMessage`.

    Only failures are seeded. A success needs no description - the double
    already knows what a posted message looks like - and a seed that could
    describe one would be a way of asserting the double's own behaviour instead
    of the Communicator's.

    `retry_after` is meaningful only with `rate_limited`, which is the one
    failure Slack expresses as a status rather than a payload.
    """

    error: str = _RATE_LIMITED_ERROR
    retry_after: int | None = None
    # How many calls this seed answers before the queue moves on. `None` means
    # "until reset", which is how a test says "Slack is down right now" rather
    # than "Slack refused once" - a condition, not an event.
    repeat: int | None = 1

    @model_validator(mode="after")
    def _must_describe_a_refusal(self) -> Seed:
        if not self.error:
            raise ValueError(
                "a seed names the error Slack answers with - an empty one says "
                "nothing about what the next call does"
            )
        if self.retry_after is not None and self.error != _RATE_LIMITED_ERROR:
            raise ValueError(
                f"retry_after belongs to {_RATE_LIMITED_ERROR!r}, which is the only "
                f"failure Slack answers with a status - got error={self.error!r}"
            )
        if self.repeat is not None and self.repeat < 1:
            raise ValueError("a seed answers at least one call, or `null` for until-reset")

        return self


class Posted(BaseModel):
    """One message the double accepted, as a test reads it back.

    `thread_ts` is what makes this worth keeping: an update posted to the
    channel and an update posted into the incident's thread are the difference
    between interrupting a workspace and not, and they are otherwise identical.
    """

    channel: str
    text: str
    thread_ts: str | None
    ts: str


class _State:
    """The double's whole memory, emptied between tests via `/double-control/reset`.

    In-process and non-persistent, like the Anthropic double's: the double is
    brought up per run alongside the other services, and a message surviving a
    restart would be one test leaking into the next.
    """

    def __init__(self) -> None:
        self.seeds: deque[Seed] = deque()
        self.posted: list[Posted] = []
        self.messages_sent = 0

    def reset(self) -> None:
        self.seeds.clear()
        self.posted.clear()
        self.messages_sent = 0

    def take_next_seed(self) -> Seed:
        """The seed answering this call, consuming one of its repeats.

        A seed with `repeat: null` stays at the head of the queue until reset,
        so anything behind it is unreachable - which is the point: "Slack is
        refusing everything right now" is a state, not a queue of identical
        events.
        """
        head = self.seeds[0]
        if head.repeat is None:
            return head

        head.repeat -= 1
        if head.repeat == 0:
            self.seeds.popleft()

        return head

    def next_ts(self) -> str:
        """The id of the next message, in the shape Slack writes one."""
        self.messages_sent += 1
        second = _FIRST_TS_SECOND + self.messages_sent

        return f"{second}.{self.messages_sent:0{_TS_FRACTION_WIDTH}d}"


_state = _State()

app = FastAPI(title="slack-double")


@app.get("/health")
def health() -> dict[str, str]:
    """Readiness probe, so a test harness can wait for the port to answer."""
    return {"status": "ok"}


@app.post("/double-control/reset")
def reset() -> dict[str, str]:
    """Clears the queued failures and everything posted so far."""
    _state.reset()

    return {"status": "reset"}


@app.post("/double-control/seed")
def seed(seed: Seed) -> dict[str, int]:
    """Queues one refusal. Seeds are served first-in-first-out, one per call.

    A queue rather than a single slot, because what is under test is a walk:
    "the war room fails to open, and the update after it succeeds" is a case
    that needs two answers lined up before the incident starts.
    """
    _state.seeds.append(seed)

    return {"queued": len(_state.seeds)}


@app.get("/double-control/posted")
def posted() -> dict[str, Any]:
    """Every message the double accepted, in the order it accepted them."""
    return {"posted": [message.model_dump() for message in _state.posted]}


@app.get("/double-control/state")
def state() -> dict[str, Any]:
    """What the double is currently holding - queued failures and messages."""
    return {"queued": len(_state.seeds), "posted": len(_state.posted)}


@app.post("/api/chat.postMessage")
async def chat_post_message(request: Request) -> JSONResponse:
    """The one Slack route the Communicator calls.

    Answers a seeded refusal where one is queued, and otherwise accepts the
    message and answers as Slack does. Accepting by default is the opposite of
    the Anthropic double's silence-is-an-error rule, and for the opposite
    reason: there, an unseeded call means a test forgot to say what the model
    concluded, which nothing can guess; here it means a message was posted, and
    what Slack answers is the same every time.
    """
    # Read before anything is decided, a refusal included. A handler that
    # answers without consuming the request leaves the server to close the
    # connection with the body unread, and the client sees the post aborted
    # rather than refused - a different answer entirely, and an intermittent
    # one, since it depends on how much of the body was already buffered.
    arguments = await _arguments_in(request)

    if _state.seeds:
        return _refused(_state.take_next_seed())

    channel = str(arguments.get(_CHANNEL_ARG) or "")
    if not channel:
        return _an_error("invalid_arguments")

    message = Posted(
        channel=channel,
        text=str(arguments.get(_TEXT_ARG) or ""),
        thread_ts=_a_thread_reference(arguments.get(_THREAD_TS_ARG)),
        ts=_state.next_ts()
    )
    _state.posted.append(message)

    return JSONResponse(
        status_code=200,
        content={
            _OK_FIELD: True,
            _CHANNEL_ARG: message.channel,
            "ts": message.ts,
            "message": {
                _TEXT_ARG: message.text,
                "ts": message.ts,
                "type": "message",
                **({_THREAD_TS_ARG: message.thread_ts} if message.thread_ts else {})
            }
        }
    )


async def _arguments_in(request: Request) -> dict[str, Any]:
    """One call's arguments, however the SDK chose to encode them.

    Both shapes, because the choice is the SDK's rather than the caller's: it
    form-encodes a simple payload and sends JSON for one carrying structure. A
    double that read only the shape it happened to be tested with would pass
    every suite and fail the first time a message grew a block.
    """
    if request.headers.get("content-type", "").startswith("application/json"):
        decoded: dict[str, Any] = await request.json()

        return decoded

    return dict(await request.form())


def _a_thread_reference(given: Any) -> str | None:
    """The parent this message replies to, or nothing.

    Empty is the same as absent. A form encoding carries an omitted argument as
    an empty string, and a reply to `""` is not a reply - left as it arrived it
    would read back as a threaded message that is in no thread.
    """
    said = str(given or "")

    return said or None


def _refused(seed: Seed) -> JSONResponse:
    """A seeded failure, said the way Slack says that one.

    Rate limiting is a status with a header and every other refusal is a 200
    whose body says no - which is why `ok` exists at all, and why a caller that
    only checked the status would read a refusal as a delivered message.
    """
    if seed.error == _RATE_LIMITED_ERROR:
        headers = (
            {_RETRY_AFTER_HEADER: str(seed.retry_after)}
            if seed.retry_after is not None
            else {}
        )

        return JSONResponse(
            status_code=_RATE_LIMITED_STATUS,
            content={_OK_FIELD: False, _ERROR_FIELD: _RATE_LIMITED_ERROR},
            headers=headers
        )

    return _an_error(seed.error)


def _an_error(error: str) -> JSONResponse:
    """A refusal in Slack's ordinary shape: a 200 whose payload says no."""
    return JSONResponse(status_code=200, content={_OK_FIELD: False, _ERROR_FIELD: error})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="localhost", port=DEFAULT_PORT)
