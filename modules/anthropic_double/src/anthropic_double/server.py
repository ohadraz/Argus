"""The double itself: an HTTP server that speaks Anthropic's Messages API.

Two surfaces, deliberately separate:

- `POST /v1/messages` - what the SDK talks to. It never invents an answer. It
  serves what the test seeded, or what was recorded from the real API, and
  fails loudly when it has neither.
- `POST /double-control/*` - what the *test* talks to, to say what should
  happen next. Same shape as the Target Service's own scenario control, so
  there is one idea to learn rather than two.

Selecting the double is a one-line change on the caller's side
(`anthropic_base_url`), which is the whole point: nothing in the adapter knows
this file exists.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

from anthropic_double import recordings

UPSTREAM_BASE_URL = os.environ.get("ANTHROPIC_DOUBLE_UPSTREAM", "https://api.anthropic.com")

# Where the double listens. Not an `argus_core` setting: the double is not
# part of Argus, and Argus's own config should not grow a field describing a
# test fixture. Callers that need to point at it - the harness that starts it,
# the tests that seed it - import these.
DEFAULT_PORT = 8091
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

# Headers worth carrying upstream while recording. Everything else - `host`,
# `content-length`, the connection headers - is either wrong for the new
# destination or recomputed by httpx.
_FORWARDED_HEADERS = ("x-api-key", "authorization", "anthropic-version", "anthropic-beta")


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
        if self.repeat is not None and self.repeat < 1:
            raise ValueError("a seed answers at least one call, or `null` for until-reset")
        return self


class RecordRequest(BaseModel):
    """Turns record mode on: the next calls go upstream and are saved."""

    name: str


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

    def reset(self) -> None:
        self.seeds.clear()
        self.record_as = None
        self.recorded = 0

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

        The investigation loop makes up to `investigation_max_iterations`
        calls, and each one is a distinct response worth keeping - so the
        second and later calls get a numbered suffix rather than overwriting
        the first.
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
    return {"recording_as": request.name}


@app.post("/double-control/reset")
def reset() -> dict[str, str]:
    """Clears the queue and leaves record mode."""
    _state.reset()
    return {"status": "reset"}


@app.get("/double-control/state")
def state() -> dict[str, Any]:
    """What the double is currently holding - queued seeds, record mode, store."""
    return {
        "queued": len(_state.seeds),
        "recording_as": _state.record_as,
        "recorded": _state.recorded,
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


def _serve(seed: Seed) -> JSONResponse:
    if seed.recording is not None:
        return JSONResponse(status_code=200, content=recordings.load(seed.recording))
    body = seed.body if seed.body is not None else _error_body(seed.status)
    return JSONResponse(status_code=seed.status, content=body)


async def _record_upstream(request: Request) -> JSONResponse:
    """Passes one call through to the real API and stores the response."""
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() in _FORWARDED_HEADERS
    }
    async with httpx.AsyncClient(base_url=UPSTREAM_BASE_URL, timeout=600.0) as client:
        upstream = await client.post(
            "/v1/messages", content=await request.body(), headers=headers
        )

    body: dict[str, Any] = upstream.json()
    if upstream.status_code == 200:
        recordings.save(_state.next_recording_name(), body)
    return JSONResponse(status_code=upstream.status_code, content=body)


@app.post("/v1/messages")
async def messages(request: Request) -> JSONResponse:
    """The one route the SDK calls. Seeded answer, or recorded one, or a loud 400.

    There is no default response. A test that forgot to seed gets an error
    naming what it forgot, not a plausible hypothesis - a double that guesses
    is a double that can make a broken investigation look like a working one.
    """
    if _state.seeds:
        return _serve(_state.take_next_seed())

    if _state.record_as is not None:
        return await _record_upstream(request)

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
