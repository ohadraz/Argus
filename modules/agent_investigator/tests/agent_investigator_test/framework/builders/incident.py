"""The incident an investigation is about: the alert, and the minutes around it.

One incident, built the same way everywhere, so that a window named in one
test file means the same thing in the next. The error rates are what make a
minute anomalous or not - the onset is measured from them, and every default
retrieval window is anchored on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from argus_core.models import Alert, MetricBucket

# Long enough for the anomaly detector to have a baseline to depart from.
CALM_MINUTES = 10

CALM_ERROR_RATE = 0.01
CALM_P50_MS = 80
CALM_P95_MS = 200
CALM_P99_MS = 350

DONT_CARE_REQUEST_VOLUME = 1000
# Flat across every window here: these incidents are about the error rate, and
# a leak is the one shape none of them stages.
CALM_MEMORY_BYTES = 440 * 1024**2
DONT_CARE_STARTED_AT = 1_756_000_000.0
# What the shop's cores are doing when nothing is wrong: a quarter of the three
# replicas it is sized for. Named beside the heap's calm figure because it is the
# same kind of fact, and because a case that pins the row the model reads has to
# name these columns without repeating their values.
CALM_CPU_CORES = 0.77
CALM_CPU_CAPACITY_CORES = 3.0

WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
AN_ALERT_TIME = datetime(2026, 8, 20, 11, 8, tzinfo=UTC)
# Far outside the window, because that is the case a stated onset exists for: a
# check that reconciles stored values against the records behind them finds what
# went wrong long after the writing did, and the minute it dates is one no
# retrievable series covers. A week is what a weekly check implies.
# How long a shop that stopped reporting got to report first, and therefore where
# its window stops. Shorter than the calm stretch above, so the last row lands
# well before the alert - which is the whole of the evidence that anything is
# missing, since nothing in front of the model says what time it is now.
MINUTES_BEFORE_THE_SHOP_WENT_QUIET = 6
# The minute an absence began: the first one with no reading, which is the minute
# after the last one that has a reading. Not the last minute that reported - that
# one is a minute the shop was well and said so.
A_STATED_ONSET_OF_AN_ABSENCE = WINDOW_START + timedelta(
    minutes=MINUTES_BEFORE_THE_SHOP_WENT_QUIET
)
A_STATED_ONSET = WINDOW_START - timedelta(days=7)

A_SERVICE = "kuki"


def an_alert(started_at: datetime | None = AN_ALERT_TIME,
             stated_onset: datetime | None = None,
             stale_entry_keys: tuple[str, ...] | None = None) -> Alert:
    """The alert that opened the incident.

    `started_at` is a parameter because its absence is a real case - an alert
    that never said when it fired - and it decides where a default log window
    ends.

    `stated_onset` is absent by default because almost every alert leaves it so,
    and because leaving it so is what keeps these builders describing the
    ordinary incident: a rule watching a series reports a minute the loop
    measures for itself, and the measurement wins wherever there is one. An
    alert states one only where it knows something no series carries, so a test
    that wants the stated minute used has to hand the loop a window with nothing
    in it as well.

    `stale_entry_keys` is absent for a different reason: not that it is rare,
    but that it is the one field on an alert the model must never be shown. It
    is a parameter so a case can put real addresses on the alert and watch them
    not arrive. The count goes with them because the model refuses a pair that
    does not account for itself.
    """
    return Alert(
        service=A_SERVICE,
        alert_name="HighErrorRate",
        started_at=started_at,
        stated_onset=stated_onset,
        stale_entry_keys=stale_entry_keys,
        stale_entries_found=None if stale_entry_keys is None else len(stale_entry_keys)
    )


def a_window_that_starts_calm() -> list[MetricBucket]:
    """Minutes with a locatable onset: a calm baseline, then a departure."""
    return a_window_of([CALM_ERROR_RATE] * CALM_MINUTES + [0.09, 0.18])


def a_window_that_starts_mid_incident() -> list[MetricBucket]:
    """Already elevated at its earliest minute, so the onset is only a lower
    bound - the incident began before anything Argus can see."""
    return a_window_of([0.30, 0.28, 0.25, 0.21, 0.20, 0.19])


def a_window_that_stops_reporting() -> list[MetricBucket]:
    """Calm minutes that simply stop, well before the alert fired.

    The shape of a monitoring blind spot, and not a short window: the minutes
    before the onset are all there and all ordinary, and every minute from the
    onset on is missing rather than flat or zeroed. Nothing departs anywhere,
    because the minutes that would have departed are the absent ones.
    """
    return a_window_of([CALM_ERROR_RATE] * MINUTES_BEFORE_THE_SHOP_WENT_QUIET)


def a_steady_window() -> list[MetricBucket]:
    """No minute departs from the baseline, so there is no onset to find."""
    return a_window_of([CALM_ERROR_RATE] * (CALM_MINUTES + 2))


def a_window_of(error_rates: list[float],
                cache_hit_ratios: list[float | None] | None = None) -> list[MetricBucket]:
    """Minutes carrying these error rates, and nothing else worth noticing.

    `cache_hit_ratios` is the one reading here that can genuinely be absent,
    and it is a parameter because absent and zero are different facts: a
    service consulting no cache has no hit ratio, and a cache answering
    nothing has one of zero. Anything rendering the window has to keep those
    apart, and a builder that could only produce one of them could not ask.
    """
    ratios = cache_hit_ratios if cache_hit_ratios is not None else [None] * len(error_rates)

    return [
        MetricBucket(
            bucket_id=_the_minute_at(offset),
            error_rate=error_rate,
            p50_ms=CALM_P50_MS,
            p95_ms=CALM_P95_MS,
            p99_ms=CALM_P99_MS,
            request_volume=DONT_CARE_REQUEST_VOLUME,
            memory_used_bytes=CALM_MEMORY_BYTES,
            process_start_time_seconds=DONT_CARE_STARTED_AT,
            cpu_used_cores=CALM_CPU_CORES,
            cpu_limit_cores=CALM_CPU_CAPACITY_CORES,
            cache_hit_ratio=ratio
        )
        for offset, (error_rate, ratio) in enumerate(zip(error_rates, ratios, strict=True))
    ]


def the_onset_of(buckets: list[MetricBucket]) -> str:
    """The minute a window's first departure lands in.

    Derived from the buckets rather than restated as a constant, so a test
    asserting what the model was told about the onset cannot drift from the
    window it was given.
    """
    calm = [bucket for bucket in buckets if bucket.error_rate <= CALM_ERROR_RATE]

    return buckets[len(calm)].bucket_id


def _the_minute_at(offset: int) -> str:
    return (WINDOW_START + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
