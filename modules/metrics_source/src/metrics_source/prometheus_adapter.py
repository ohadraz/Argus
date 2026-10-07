"""The one place Prometheus is known by name.

Read through its range-query API - `GET /api/v1/query_range` - one PromQL
expression per bucket field, at a minute's step. Nothing above this module sees
PromQL, Prometheus's envelope, or its errors.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx2
from argus_core import to_iso
from argus_core.models import RULE_READING_FIELD, MetricBucket, RuleReading

from metrics_source.minutes import MetricsSettings, MetricsUnavailable, RuleSeries

# How a request is sent. Injected rather than called outright so that a test
# can see the question asked and write the answer, without a network and
# without monkeypatching a name this module imported.
type Get = Callable[..., httpx2.Response]

# Prometheus's range-query endpoint, after whatever base URL it is reached at.
_THE_RANGE_QUERY_PATH: Final = "/api/v1/query_range"

# The parameters it takes. `step` is a minute, because a minute is what a bucket
# is.
_QUERY: Final = "query"
_START: Final = "start"
_END: Final = "end"
_STEP: Final = "step"
_A_MINUTE_STEP: Final = "60s"

_TIMEOUT_SECONDS: Final = 10.0

# Where the samples are in Prometheus's answer: `data.result[*].values`, each a
# `[unix_seconds, "value"]` pair.
_DATA: Final = "data"
_RESULT: Final = "result"
_VALUES: Final = "values"

# Where a refusal says why.
_ERROR_TYPE: Final = "errorType"
_ERROR: Final = "error"

_A_MINUTE: Final = timedelta(minutes=1)

# The bucket fields counted in whole numbers. Prometheus answers every value as
# a float, so these are rounded on the way in.
_WHOLE_NUMBERS: Final = frozenset({
    "p50_ms", "p95_ms", "p99_ms", "request_volume",
    "memory_used_bytes", "memory_limit_bytes"
})

# What is asked for each field of a bucket. Idiomatic PromQL over the series a
# service conventionally exposes; each answers one value per minute, labelled
# with the end of the minute it describes. Public because a stand-in for
# Prometheus has to answer exactly these and nothing else.
QUERIES: Final[Mapping[str, str]] = {
    "error_rate": (
        'sum(rate(http_requests_total{code=~"5.."}[1m]))'
        " / sum(rate(http_requests_total[1m]))"
    ),
    "p50_ms": 'max(http_request_duration_seconds{quantile="0.5"}) * 1000',
    "p95_ms": 'max(http_request_duration_seconds{quantile="0.95"}) * 1000',
    "p99_ms": 'max(http_request_duration_seconds{quantile="0.99"}) * 1000',
    "request_volume": "sum(increase(http_requests_total[1m]))",
    "memory_used_bytes": "max(max_over_time(process_resident_memory_bytes[1m]))",
    "memory_limit_bytes": "max(container_spec_memory_limit_bytes)",
    "process_start_time_seconds": "max(process_start_time_seconds)",
    "cpu_used_cores": "sum(rate(container_cpu_usage_seconds_total[1m]))",
    "cpu_limit_cores": 'sum(kube_pod_container_resource_limits{resource="cpu"})',
    "cache_hit_ratio": "avg(cache_hit_ratio)"
}


# The fields a bucket cannot be without. The other three - the two limits and
# the hit ratio - are absent from a service that sets no limit or keeps no
# cache, and absent is what `None` says about them.
_EVERY_BUCKET_NEEDS: Final = frozenset(QUERIES) - {
    "memory_limit_bytes", "cpu_limit_cores", "cache_hit_ratio"
}


def buckets_between(started_at: datetime,
                    ended_at: datetime,
                    settings: MetricsSettings,
                    get: Get = httpx2.get,
                    rule_series: RuleSeries | None = None) -> list[MetricBucket]:
    """The service's minute buckets between two instants, as Prometheus
    reports them.

    One query per field, and the answers joined by minute: a sample at `t`
    describes the minute that ended at `t`, so it fills the bucket that began a
    minute earlier. The window is asked for by the ends of its minutes, up to
    the end of the minute it ends in, finished or not - asking is what lets a
    source that can report that minute do so.

    `rule_series` is one more query, the paging rule's own, asked the same way
    and set on each minute it answers for. Where Prometheus refuses it, or it
    answers nothing, the window is served without it: the rule's query is
    whatever somebody wrote into the rule, and a query Argus could not read
    costs the window its sixth series rather than the five every other
    judgement rests on.
    """
    url = f"{settings.prometheus_base_url}{_THE_RANGE_QUERY_PATH}"
    window = {
        _START: str((_the_first_minute_in(started_at) + _A_MINUTE).timestamp()),
        _END: str((_the_minute_of(ended_at) + _A_MINUTE).timestamp()),
        _STEP: _A_MINUTE_STEP
    }
    readings: dict[datetime, dict[str, float]] = defaultdict(dict)

    for field, query in QUERIES.items():
        for minute, value in _samples_in(_asked(get, url, {_QUERY: query, **window})):
            readings[minute][field] = value

    rule_readings = (
        _the_rules_readings(get, url, window, rule_series)
        if rule_series is not None
        else {}
    )

    return [
        MetricBucket.model_validate(
            {
                "bucket_id": to_iso(minute),
                **_as_fields(readings[minute]),
                RULE_READING_FIELD: rule_readings.get(minute)
            }
        )
        for minute in sorted(readings)
        # A minute missing a reading every bucket needs is not reported at all,
        # rather than reported as zero: a bucket of zeros describes a service
        # serving nothing, which is a different incident from one nobody heard
        # about.
        if readings[minute].keys() >= _EVERY_BUCKET_NEEDS
    ]


def _the_rules_readings(get: Get,
                        url: str,
                        window: Mapping[str, str],
                        rule_series: RuleSeries) -> dict[datetime, RuleReading]:
    """The rule's series by minute, or nothing where Prometheus would not
    answer it.

    Nothing too where it answers with more than one series. An unaggregated
    query is answered once for every instance it matches, and which of them
    paged is the rule's own reduction to decide - read as one, the series
    would be whichever the answer happened to list last.
    """
    try:
        answer = _asked(get, url, {_QUERY: rule_series.query, **window})
    except MetricsUnavailable:
        return {}

    if len(answer[_DATA][_RESULT]) > 1:
        return {}

    return {
        minute: RuleReading(value=value, worse_when=rule_series.worse_when)
        for minute, value in _samples_in(answer)
    }


def _samples_in(answer: Any) -> list[tuple[datetime, float]]:
    """Every sample in one answer, each against the minute it describes - the
    minute that ended at the sample's own time."""
    return [
        (datetime.fromtimestamp(float(at), UTC) - _A_MINUTE, float(value))
        for series in answer[_DATA][_RESULT]
        for at, value in series[_VALUES]
    ]


def _asked(get: Get, url: str, params: Mapping[str, str]) -> Any:
    """One query's answer, or `MetricsUnavailable` saying why there is none.

    Prometheus refuses a query with a status and an envelope naming the fault;
    its reason travels on in the error, since it is the one thing a reader can
    act on. The transport's own errors stop here too, so nothing above this
    module learns which library asked.
    """
    try:
        response = get(url, params=params, timeout=_TIMEOUT_SECONDS)
    except httpx2.HTTPError as error:
        raise MetricsUnavailable(f"Prometheus could not be reached: {error}") from error

    if response.is_error:
        raise MetricsUnavailable(
            f"Prometheus refused the query with {response.status_code}: "
            f"{_the_reason_in(response)}"
        )

    return response.json()


def _the_reason_in(response: httpx2.Response) -> str:
    """Prometheus's own account of a refusal - its `errorType` and `error` - or
    the body as it came, where the body is not its envelope."""
    try:
        envelope = response.json()

        return f"{envelope[_ERROR_TYPE]}: {envelope[_ERROR]}"
    except (ValueError, KeyError, TypeError):
        return response.text


def _the_minute_of(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def _the_first_minute_in(moment: datetime) -> datetime:
    """The first minute to begin at or after `moment` - one that began before
    it is not in a window starting there."""
    minute = _the_minute_of(moment)

    return minute if minute == moment else minute + _A_MINUTE


def _as_fields(reading: Mapping[str, float]) -> dict[str, float | int]:
    """One minute's readings, the whole-number fields rounded.

    Rounded rather than truncated: `* 1000` on a float answers
    119.99999999999999 for a latency measured as 120.
    """
    return {
        field: round(value) if field in _WHOLE_NUMBERS else value
        for field, value in reading.items()
    }
