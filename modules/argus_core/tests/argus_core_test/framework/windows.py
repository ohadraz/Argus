"""A window of minutes the service could actually have reported.

Every calm fixture in this suite is a constant - the one input the departure
rule's floors were built for, and the one shape a real service never produces.
What a shop reports is quantised and jittery: an error rate measured over a
couple of hundred requests moves in half-percent steps and lands on a different
one most minutes, and latency read off a mixture of a fast path and a slow one
has three quantiles that each wobble on their own.

A rule tested only against constants is a rule tested against the case it
already handles. These builders produce the other kind, seeded so that a failure
is reproducible: the same seed is the same window, minute for minute, and a test
that goes red goes red every time.

The figures are the Target Service's rather than invented here - a sample of two
hundred, a baseline near one percent, a cache carrying nine pages in ten at
around twenty-five milliseconds and recomputing the rest at around two hundred.
Copied rather than imported, because the shop is another repository: a fixture
that reached into it would fail for reasons about that repository, and the point
of these numbers is the *shape* they give a series, not their exact values.
"""
from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import to_iso_minute

# How many requests a minute's figures are measured over, and so how coarse the
# error rate is: two hundred requests report 1.0% and 1.5% and nothing between.
A_MINUTES_SAMPLE = 200

# What the shop fails without anything being wrong, and how far that drifts.
A_QUIET_ERROR_RATE = 0.01
THE_ERROR_RATE_WOBBLES_BY = 0.005

# The two paths a page takes, and how much of the traffic takes the fast one.
# The median falls inside the cached population and the p95 and the p99 inside
# the recomputed one - which is why three quantiles read off this mixture cannot
# be written down as one baseline and a multiplier, and why a fixture that does
# write them that way is testing a service nobody runs.
PAGES_SERVED_FROM_CACHE = 0.9
A_CACHED_PAGE_MS = 25
A_RECOMPUTED_PAGE_MS = 195
THE_PAGE_LATENCY_WOBBLES_BY_MS = 12

A_QUIET_HEAP_BYTES = 440 * 1024**2
THE_HEAP_WOBBLES_BY_BYTES = 12 * 1024**2
THE_HEAP_LIMIT_BYTES = 2 * 1024**3

_WINDOW_STARTS_AT = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)


def a_quiet_window_of(minutes: int, seed: int) -> list[MetricBucket]:
    """`minutes` consecutive minutes of a service with nothing wrong with it.

    Quiet rather than flat, which is the whole point: no two minutes report the
    same error rate, the median moves a millisecond or two either way, and the
    tail sits a few milliseconds above the p95 instead of a hundred and fifty.

    `seed` is required and has no default, so that a window is named by the test
    that uses it rather than shared with every other one. A test wanting several
    unrelated quiet windows asks for several seeds.
    """
    entropy = random.Random(seed)

    return [
        a_quiet_minute_at(
            to_iso_minute(_WINDOW_STARTS_AT + timedelta(minutes=offset)), entropy
        )
        for offset in range(minutes)
    ]


def a_quiet_minute_at(bucket_id: str, entropy: random.Random) -> MetricBucket:
    """One minute of ordinary traffic, measured the way the service measures it.

    The error rate is counted rather than chosen - a request either failed or it
    did not, and the rate is what is left after dividing by the sample - so it
    is quantised by construction and no test has to remember to quantise it.

    The three quantiles are read off the latencies actually served, for the same
    reason. A mixture of a fast path and a slow one is not a distribution
    anybody can write down, and every rule in `argus_core.anomaly` is asked
    about exactly that mixture in production.
    """
    failures = sum(
        1
        for _ in range(A_MINUTES_SAMPLE)
        if entropy.random() < A_QUIET_ERROR_RATE + entropy.uniform(
            -THE_ERROR_RATE_WOBBLES_BY, THE_ERROR_RATE_WOBBLES_BY
        )
    )
    served = sorted(_a_page_served(entropy) for _ in range(A_MINUTES_SAMPLE))

    return MetricBucket(
        bucket_id=bucket_id,
        error_rate=round(failures / A_MINUTES_SAMPLE, 4),
        p50_ms=_the_quantile_at(served, 0.50),
        p95_ms=_the_quantile_at(served, 0.95),
        p99_ms=_the_quantile_at(served, 0.99),
        request_volume=A_MINUTES_SAMPLE,
        memory_used_bytes=A_QUIET_HEAP_BYTES + entropy.randint(
            -THE_HEAP_WOBBLES_BY_BYTES, THE_HEAP_WOBBLES_BY_BYTES
        ),
        memory_limit_bytes=THE_HEAP_LIMIT_BYTES,
        process_start_time_seconds=_WINDOW_STARTS_AT.timestamp()
    )


def with_the_error_rate_raised(window: Sequence[MetricBucket],
                               to: float,
                               over: range) -> list[MetricBucket]:
    """The same window with `over`'s minutes failing at about `to`.

    About, not exactly: the minute keeps its own noise and is lifted by it, so
    an incident staged this way has the internal spread a real one has. A stretch
    of identical incident minutes is the same fiction as a stretch of identical
    quiet ones, one level up.
    """
    return [
        bucket.model_copy(update={"error_rate": round(to + bucket.error_rate, 4)})
        if offset in over
        else bucket
        for offset, bucket in enumerate(window)
    ]


def _a_page_served(entropy: random.Random) -> int:
    """How long one page took, in whichever of the two paths it took."""
    from_cache = entropy.random() < PAGES_SERVED_FROM_CACHE
    unwobbled = A_CACHED_PAGE_MS if from_cache else A_RECOMPUTED_PAGE_MS

    return unwobbled + entropy.randint(
        -THE_PAGE_LATENCY_WOBBLES_BY_MS, THE_PAGE_LATENCY_WOBBLES_BY_MS
    )


def _the_quantile_at(served: Sequence[int], quantile: float) -> int:
    """The latency at `quantile` of an already-sorted minute, by nearest rank -
    the rule the service itself reports its quantiles by."""
    return served[round(quantile * (len(served) - 1))]
