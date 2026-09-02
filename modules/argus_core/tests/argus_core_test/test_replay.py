from __future__ import annotations

from typing import Any

import pytest
from argus_core.replay import CallType, Replay, ReplayEntry
from argus_testkit import Assertion, Scenario

from argus_core_test.framework.replay import (
    a_recorder_that_keeps_what_it_is_given,
    the_entry_took,
    the_entry_was_recorded_for,
)

"""Every external call, written down well enough to replay (spec §4 principle 6).

The incident tables record what Argus concluded and the event stream records
what it did. This records the calls it made to find out: one row per call to a
model or a tool server, carrying the request that was sent, the answer that
came back, and how long it took.

It exists so a benchmark run does not have to re-spend tokens or re-hit a real
system to be re-examined - which means the entry has to be complete enough to
stand in for the call, not merely to describe it.

What a call cost is deliberately absent. No API returns a price, so a cost here
could only come from a rate card copied into this repo, correct until the
vendor moves it and silently wrong after. The token counts inside the recorded
response are the durable fact; pricing them is the reader's job, at whatever
the rate is when they ask.

This file is the seam alone - that an entry is built, reaches a recorder, and
cannot take the call down with it. What a wrapped model client actually puts in
one is `llm/test_recorded_client.py`.
"""

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"
SOME_MODEL = "claude-opus-5"

DONT_CARE_LATENCY_MS = 1


@pytest.mark.unit
def test_a_recorded_call_names_the_incident_it_was_made_for() -> None:
    # The incident is bound into the recorder rather than passed at each call.
    # A model client's business is talking to a model; an incident id in its
    # signature would be Argus's domain leaking into an adapter, and one call
    # site forgetting to pass it would orphan a row nothing can join back.
    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: Replay(SOME_INCIDENT_ID, recorded.take).record(
                call_type=CallType.LLM,
                target=SOME_MODEL,
                request={"dont": "care"},
                response={"dont": "care"},
                latency_ms=DONT_CARE_LATENCY_MS
            )
        ) \
        .then(
            the_entry_was_recorded_for(recorded, SOME_INCIDENT_ID)
        )


@pytest.mark.unit
def test_a_recorded_call_carries_how_long_it_took() -> None:
    # The one thing about a call that only the caller can know. What was asked
    # and what came back are both in the payloads; how long it took is measured
    # around them and is gone the moment the call returns.
    some_latency_ms = 4820

    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: Replay(SOME_INCIDENT_ID, recorded.take).record(
                call_type=CallType.LLM,
                target=SOME_MODEL,
                request={"dont": "care"},
                response={"dont": "care"},
                latency_ms=some_latency_ms
            )
        ) \
        .then(
            the_entry_took(recorded, some_latency_ms)
        )


@pytest.mark.unit
def test_a_recorder_that_fails_does_not_fail_the_call_it_was_recording() -> None:
    # The one exception this codebase swallows, for the same reason `publish`
    # swallows one: an incident that would have resolved must resolve even when
    # nothing could write down what it did. A replay log is evidence about the
    # work, never a participant in it.
    Scenario() \
        .given(
            a_recorder_that_raises := _a_recorder_that_cannot_write()
        ) \
        .when(
            lambda: Replay(SOME_INCIDENT_ID, a_recorder_that_raises.take).record(
                call_type=CallType.LLM,
                target=SOME_MODEL,
                request={"dont": "care"},
                response={"dont": "care"},
                latency_ms=DONT_CARE_LATENCY_MS
            )
        ) \
        .then(
            _nothing_was_raised()
        )


class _UnwritableLog:
    """A recorder that cannot write.

    Local to this file, unlike the collector: only the seam has a reason to be
    handed a recorder that fails, because only the seam promises to survive one.

    An object rather than a bare function because `Scenario.given` runs a
    callable step - handed the function itself, it would call the recorder
    instead of arranging it.
    """

    def take(self, entry: ReplayEntry) -> None:
        raise RuntimeError("the replay log is unreachable")


def _a_recorder_that_cannot_write() -> _UnwritableLog:
    return _UnwritableLog()


def _nothing_was_raised() -> Assertion[Any]:
    """Reached only if `record` returned, which is the whole assertion."""
    def assertion(_result: Any) -> bool:
        return True

    return assertion
