from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from argus_core.ids import UuidStr, new_id

"""Every external call, written down well enough to replay it (spec §4 principle 6).

The three records Argus keeps are not the same record. The incident tables say
what it *concluded* - which candidate was blamed, what was done, where the
incident ended. The event stream (`events.py`) says what it *did*, in order,
for a human to read. This says what it *spent*: one row per call that left the
process, carrying the request that was sent and the answer that came back.

The distinction that earns it a table of its own is granularity and audience.
An event is a sentence about the investigation and is read by a page; an entry
here is a call and is read by the eval tier, which needs to re-examine a run
without re-spending the tokens or re-hitting the systems that produced it. That
is only possible if the entry stands in *for* the call rather than describing
it, which is why the payloads are stored whole.

Shaped after `events.py` throughout, because the two solve the same problem:
something must be written down about work that must not depend on the writing
succeeding. `Recorder` is that file's `Publisher`, `record` is its `publish`,
and `Replay` is its `Narrator` - an incident bound once so that nothing below
has to carry an id it has no other use for.
"""

_logger = logging.getLogger(__name__)


class CallType(StrEnum):
    """What kind of thing was called (spec §11.1's `call_type`).

    Two, because there are two ways out of this process: a model answers, and a
    tool server does. They are distinguished rather than merged because what it
    means to replay them differs - a model call is charged for and is
    non-deterministic, a tool call is neither and is re-runnable against a
    system that may have moved on.
    """

    LLM = "llm"
    MCP = "mcp"


class ReplayEntry(BaseModel):
    """One call out of this process, and everything needed to stand in for it.

    `request` and `response` are stored whole rather than summarised. A summary
    answers questions someone thought of when they wrote it; the point of this
    table is the question nobody thought of yet, asked months later against a
    run nobody wants to pay for twice.

    `target` names what was called - the model id, or the tool - and is a plain
    string rather than an enum: what Argus can call is configuration, and a
    vocabulary here would need a migration every time a model is switched.

    What a call *cost* is deliberately not here. No API returns a price, so any
    figure would come from a rate card copied into this repo - correct until
    the vendor changes it, wrong silently afterwards, and wrong in a column
    someone would later sum with confidence. The token counts inside `response`
    are the durable fact; a price is a rate applied to them by whoever is
    asking, at whatever the rate is then.

    `at` is taken here rather than accepted, as an event's is: the moment
    belongs to the call, not to whenever a row reached the database.
    """

    id: UuidStr = Field(default_factory=new_id)
    incident_id: UuidStr
    call_type: CallType
    target: str
    request: dict[str, Any]
    response: dict[str, Any]
    latency_ms: int
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Recorder(Protocol):
    """Where an entry goes. Says nothing about how it gets there.

    A database today, and whatever an eval harness wants tomorrow. The point of
    the Protocol is that the instrumented client handing entries over cannot
    tell which, and so never grows a reason to care.
    """

    # Positional-only, as `Publisher` is: a recorder is called with the entry
    # and nothing else, so any single-argument function is one whatever it
    # named its parameter.
    def __call__(self, entry: ReplayEntry, /) -> None: ...


def nobody(entry: ReplayEntry) -> None:
    """The default: recording that reaches no one.

    A call is made whether or not anything is keeping the receipt, and behaves
    identically either way - easiest to guarantee when the ordinary default is
    that nothing is.
    """


def record(entry: ReplayEntry, recorder: Recorder = nobody) -> None:
    """Hands one entry to a recorder, and cannot fail.

    The same swallowed exception as `publish`, for the same reason and with the
    same narrow licence: the receipt is never part of the work. An incident that
    would have resolved must resolve even when nothing could write down what it
    spent, so a recorder having a bad day costs the log a row and costs the
    investigation nothing.

    Logged at warning rather than silently, so a log that has stopped recording
    is discoverable before an eval run is planned around rows that are not
    there.
    """
    try:
        recorder(entry)
    except Exception:
        _logger.warning("could not record the %s call to %s for incident %s",
                        entry.call_type, entry.target, entry.incident_id, exc_info=True)


class Replay:
    """Every call one incident made, recorded in one place.

    The incident is bound here rather than passed at each call, which is the
    whole reason this class exists. An `LLMClient`'s business is talking to a
    model; an incident id in its signature would be Argus's domain reaching
    into an adapter, and one call site forgetting to pass it would orphan a row
    nothing can join back to the run it belongs to.

    Nothing here can fail, exactly as `Narrator` cannot: `record` swallows a
    recorder's exception, and a `Replay` with no recorder reaches nobody by
    design.
    """

    def __init__(self, incident_id: str, recorder: Recorder = nobody) -> None:
        self._incident_id = incident_id
        self._recorder = recorder

    def record(self,
               call_type: CallType,
               target: str,
               request: dict[str, Any],
               response: dict[str, Any],
               latency_ms: int) -> None:
        """Writes down one call this incident made.

        Keyword arguments by shape rather than convention: five values of which
        two are dictionaries is exactly the signature a positional call gets
        subtly wrong, and a request stored as a response is a row that reads
        correctly and replays nothing.
        """
        record(
            ReplayEntry(
                incident_id=self._incident_id,
                call_type=call_type,
                target=target,
                request=request,
                response=response,
                latency_ms=latency_ms
            ),
            self._recorder
        )
