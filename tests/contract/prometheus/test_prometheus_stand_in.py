"""Whether the stand-in still answers as Prometheus does.

Every suite that reads a service's minutes reads them from the Target Service's
stand-in at `/prometheus`, which knows the adapter's expressions word for word
and parses none of them. So nothing those suites prove says the expressions are
PromQL at all, or that what a real Prometheus answers to them is something the
adapter can read. That is checked here, the one way it can be: the same window
asked of both through the adapter, and the two answers required to read the
same.

Read the same, and equal where equal is possible. A real Prometheus works a
rate out of the counters it scraped, where the stand-in hands back the figure
the shop wrote for that minute, so a rate or a latency will not agree to the
digit. A figure that holds still from minute to minute - a limit, the instant
the process started - has no arithmetic between the shop and the answer, and
does: a units slip on either side shows there and nowhere else. Beyond that,
what everything depends on is that a minute comes back at all, with the same
fields filled, and that a refusal comes back as one.

A rule's own series is asked the same way, and needs it more. Its query is not
the adapter's but whatever the rule evaluates, handed over verbatim, and a source
that will not run it leaves the readings off and serves the window anyway - so a
query that is not PromQL, or names a gauge the shop does not expose, would fail
silently everywhere but here.

The real half has to be given data, and a scrape is how a real Prometheus gets
it. So the shop is seeded, Prometheus scrapes it every five seconds (see
`docker-compose.yml`), and the first minute it can answer for is the first one
it watched end. That is the one wait in here - up to a minute and a half, paid
once for the module and shared by every case that reads a window - and no clock
can be injected into it, because the clock is Prometheus's.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from argus_core import get_settings
from argus_core.models import MetricBucket, WorseWhen
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from metrics_source import MetricsSettings, MetricsUnavailable, RuleSeries
from metrics_source.prometheus_adapter import buckets_between

# Where each half answers. The real one is the `prometheus` service in Argus's
# `docker-compose.yml`, published there on 9090 and read by nothing but this
# suite. The stand-in, and the shop it stands in for, are wherever Argus itself
# is configured to find them.
THE_REAL_ONE = "http://localhost:9090"
THE_STAND_IN = get_settings().prometheus_base_url
THE_SHOP = get_settings().target_service_url

# A generated scenario, because a generated one goes on writing a minute every
# minute and fills every field a bucket has - so the counters the rates are
# worked out from keep moving while Prometheus watches.
A_SCENARIO_THAT_GOES_ON_REPORTING = "resource-leak"

# How long after seeding a minute has to end for Prometheus to have scraped the
# shop at least twice inside it. A rate over a minute needs two samples in the
# minute, and at a five-second interval twenty seconds holds three.
TIME_TO_SCRAPE_TWICE = timedelta(seconds=20)

# Past the end of that minute, so the scrape at its edge has been written.
A_MOMENT_TO_WRITE_IT = timedelta(seconds=2)

# How far back the window asked for starts. Far enough to hold the first minute
# Prometheus watched end, whenever in a minute the shop was seeded.
A_FEW_MINUTES = timedelta(minutes=5)

A_MINUTE = timedelta(minutes=1)

# The fields a real Prometheus answers from a scraped gauge with nothing worked
# out in between, and that the seeded scenario never moves - nothing in this
# suite restarts or scales the shop. So a minute's reading of each is the
# shop's own figure on both sides, and the two have to be equal.
FIGURES_THAT_HOLD_STILL = ("memory_limit_bytes", "cpu_limit_cores", "process_start_time_seconds")

# The expressions the shop's own alert rules evaluate, as Grafana hands them
# over in a rule's definition: the categoriser's confident share, and the share
# of its limit the heap is using. Restated rather than imported, because the
# shop is another repository and these are the words that cross between the two.
THE_CATEGORISER_RULES_QUERY = "avg(categoriser_confident_ratio)"
THE_MEMORY_RULES_QUERY = (
    "max(max_over_time(process_resident_memory_bytes[1m]))"
    " / max(container_spec_memory_limit_bytes)"
)

# Which way a rule calls worse. The source never reads it - it rides back on each
# reading as it was handed in - so either is the same question to both halves.
DONT_CARE_DIRECTION: WorseWhen = "above"

# What Prometheus calls a query it will not run. The one part of a refusal the
# adapter carries into what it raises, and so the part a reader acts on.
BAD_DATA = "bad_data"


@pytest.fixture(scope="module")
def a_window_prometheus_watched() -> None:
    """The shop seeded, and the first minute a real Prometheus can answer for
    waited out - once, for every case that reads a window."""
    _until_prometheus_has_watched_a_minute_end_since(
        _the_shop_was_seeded_with(A_SCENARIO_THAT_GOES_ON_REPORTING)
    )


@pytest.mark.contract
def test_a_window_prometheus_watched_reads_as_the_stand_in_reads_it(
    a_window_prometheus_watched: None
) -> None:
    # The whole of the happy path. Each field of a bucket is its own
    # expression, and a minute comes back only if every field it cannot be
    # without was answered - so one minute back from a real Prometheus says
    # each of those expressions parsed, ran, and answered a matrix the adapter
    # read. The comparison then says no field the stand-in fills is one a real
    # Prometheus would leave empty, and that the figures which hold still are
    # the same figures.
    Scenario() \
        .when(lambda: buckets_between(*_the_last_few_minutes(), _settings_for(THE_REAL_ONE))) \
        .then(all_of(
            _some_minute_came_back(),
            _it_reads_as(at_the_stand_in := buckets_between(
                *_the_last_few_minutes(), _settings_for(THE_STAND_IN)
            )),
            _its_still_figures_are_the_stand_ins(at_the_stand_in)
        ))


@pytest.mark.contract
@pytest.mark.parametrize(
    "rules_query",
    [THE_CATEGORISER_RULES_QUERY, THE_MEMORY_RULES_QUERY],
    ids=["categoriser", "memory"]
)
def test_a_rules_series_prometheus_watched_reads_as_the_stand_in_reads_it(
    a_window_prometheus_watched: None,
    rules_query: str
) -> None:
    # The series a rule evaluates, asked of both halves as one more query. The
    # rule's series coming back at all from a real Prometheus says the
    # expression is PromQL over a gauge the shop exposes; the comparison says
    # the stand-in fills it for the minutes Prometheus does. Not the same
    # figure: a gauge read at a minute's end is whichever scrape landed last,
    # and the stand-in answers the minute's own row.
    Scenario() \
        .when(lambda: buckets_between(
            *_the_last_few_minutes(), _settings_for(THE_REAL_ONE),
            rule_series=RuleSeries(rules_query, DONT_CARE_DIRECTION)
        )) \
        .then(all_of(
            _the_rules_series_came_back(),
            _it_reads_as(buckets_between(
                *_the_last_few_minutes(), _settings_for(THE_STAND_IN),
                rule_series=RuleSeries(rules_query, DONT_CARE_DIRECTION)
            ))
        ))


@pytest.mark.contract
def test_a_window_that_ends_before_it_starts_is_refused_as_the_stand_in_refuses_it() -> None:
    # The refusal the adapter reads. Prometheus answers a query it will not run
    # with an error status and an envelope naming the fault, and the adapter
    # carries that name into what it raises. A stand-in refusing in any other
    # shape would have every suite reading a different error from the one a
    # real source produces.
    Scenario() \
        .given(started_at := datetime.now(UTC), ended_at := started_at - A_FEW_MINUTES) \
        .when(attempting(
            lambda: buckets_between(started_at, ended_at, _settings_for(THE_REAL_ONE))
        )) \
        .then(all_of(
            an_error_was_raised(MetricsUnavailable),
            the_error_mentioned(BAD_DATA),
            _it_was_refused_as(attempting(
                lambda: buckets_between(started_at, ended_at, _settings_for(THE_STAND_IN))
            )())
        ))


def _the_shop_was_seeded_with(scenario_id: str) -> datetime:
    """Stages a scenario, and says when - the instant Prometheus's watch of
    it starts from."""
    httpx2.post(
        f"{THE_SHOP}/scenario/seed", json={"scenario_id": scenario_id}, timeout=10.0
    ).raise_for_status()

    return datetime.now(UTC)


def _until_prometheus_has_watched_a_minute_end_since(seeded_at: datetime) -> None:
    """Waits out the first minute a real Prometheus can answer for.

    That is the first to end at least two scrapes after the shop was seeded.
    Before it, a rate over the minute has one sample or none to work from and
    Prometheus answers nothing for it - which is Prometheus being right, not
    the adapter being wrong, and not what this suite asks.
    """
    the_first_minute_watched = (
        (seeded_at + TIME_TO_SCRAPE_TWICE).replace(second=0, microsecond=0) + A_MINUTE
    )
    still_to_go = the_first_minute_watched + A_MOMENT_TO_WRITE_IT - datetime.now(UTC)

    time.sleep(max(still_to_go.total_seconds(), 0.0))


def _the_last_few_minutes() -> tuple[datetime, datetime]:
    """A window ending now, as `buckets_between` takes one."""
    now = datetime.now(UTC)

    return now - A_FEW_MINUTES, now


def _settings_for(base_url: str) -> MetricsSettings:
    """Refuses a stand-in configured as the real one: the two halves would
    then be one Prometheus compared with itself, which passes and proves
    nothing."""
    if base_url == THE_STAND_IN == THE_REAL_ONE:
        raise AssertionError(
            f"Expected PROMETHEUS_BASE_URL to name the stand-in, it names the real "
            f"Prometheus [{THE_REAL_ONE}]."
        )

    return MetricsSettings(prometheus_base_url=base_url)


def _some_minute_came_back() -> Assertion[list[MetricBucket]]:
    def assertion(buckets: list[MetricBucket]) -> bool:
        if not buckets:
            raise AssertionError(
                "Expected Prometheus to answer for a minute it watched end, it answered "
                "for none: a field every bucket needs went unanswered in every minute."
            )

        return True

    return assertion


def _the_rules_series_came_back() -> Assertion[list[MetricBucket]]:
    """That some minute carries the rule's reading.

    Needed beside the comparison rather than left to it: a source that will not
    run the rule's query leaves the readings off and serves the window, so two
    halves that both refused would read as two halves that agree.
    """
    def assertion(buckets: list[MetricBucket]) -> bool:
        if not any(bucket.rule_reading is not None for bucket in buckets):
            raise AssertionError(
                f"Expected Prometheus to answer the rule's query for some minute, it "
                f"answered for none of {[bucket.bucket_id for bucket in buckets]}: the "
                f"query is not one it will run, or names a series the shop does not "
                f"expose."
            )

        return True

    return assertion


def _it_reads_as(at_the_stand_in: list[MetricBucket]) -> Assertion[list[MetricBucket]]:
    """The two answers, as the adapter reads them.

    Minute by minute, for the minutes both answered for: the same fields
    filled. Not the same figures - a rate Prometheus worked out of two scrapes
    and a figure the shop wrote down are never the same number. The ones that
    can be are `_its_still_figures_are_the_stand_ins`.
    """
    def assertion(from_prometheus: list[MetricBucket]) -> bool:
        stood_in = {bucket.bucket_id: _the_fields_filled_in(bucket) for bucket in at_the_stand_in}
        both_answered = [bucket for bucket in from_prometheus if bucket.bucket_id in stood_in]

        if not both_answered:
            raise AssertionError(
                f"Expected the stand-in to answer for a minute Prometheus answered for "
                f"{[bucket.bucket_id for bucket in from_prometheus]}, "
                f"it answered for {sorted(stood_in)}."
            )

        for bucket in both_answered:
            real = _the_fields_filled_in(bucket)
            stand_in = stood_in[bucket.bucket_id]

            if real != stand_in:
                raise AssertionError(
                    f"Expected minute [{bucket.bucket_id}] filled as the stand-in fills it, "
                    f"Prometheus left {sorted(stand_in - real)} empty "
                    f"and filled {sorted(real - stand_in)} the stand-in did not."
                )

        return True

    return assertion


def _its_still_figures_are_the_stand_ins(
    at_the_stand_in: list[MetricBucket]
) -> Assertion[list[MetricBucket]]:
    """For the minutes both answered for, each figure that holds still is the
    same figure on both sides."""
    def assertion(from_prometheus: list[MetricBucket]) -> bool:
        stood_in = {bucket.bucket_id: bucket for bucket in at_the_stand_in}

        for bucket in from_prometheus:
            if bucket.bucket_id not in stood_in:
                continue

            for field in FIGURES_THAT_HOLD_STILL:
                real = getattr(bucket, field)
                stand_in = getattr(stood_in[bucket.bucket_id], field)

                if real != stand_in:
                    raise AssertionError(
                        f"Expected [{field}] in minute [{bucket.bucket_id}] to be the "
                        f"stand-in's [{stand_in}], Prometheus answered [{real}]."
                    )

        return True

    return assertion


def _it_was_refused_as(at_the_stand_in: Exception | None) -> Assertion[Exception | None]:
    """The two refusals, as the adapter reads them: the same error, naming the
    same fault. Not the same sentence - the wording after the fault's name is
    whoever refused's own, and the stand-in deliberately does not copy it."""
    def assertion(from_prometheus: Exception | None) -> bool:
        real = (type(from_prometheus).__name__, BAD_DATA in str(from_prometheus))
        stood_in = (type(at_the_stand_in).__name__, BAD_DATA in str(at_the_stand_in))

        if real != stood_in:
            raise AssertionError(
                f"Expected the stand-in to refuse as Prometheus did {real}, "
                f"it refused {stood_in}: [{at_the_stand_in}]."
            )

        return True

    return assertion


def _the_fields_filled_in(bucket: MetricBucket) -> frozenset[str]:
    return frozenset(bucket.model_dump(exclude_none=True))
