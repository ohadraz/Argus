"""The unit a series is in, as its metric's name carries it (Prometheus's
naming convention).

The fallback where a rule's panel names none. Prometheus hard-codes no unit;
its convention is a metric in base units with the unit as a suffix of its name -
`_seconds`, `_bytes`, `_ratio`. So a name says the unit of the metric, and the
series is in it only while nothing between the two changed it: an aggregation
across series or over time keeps it, and a rescale, a rate, a derivative or a
count does not. Anything this does not know keeps is no unit at all, never the
name's.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from read_mcp_server.units import the_unit_its_name_carries


@pytest.mark.unit
@pytest.mark.parametrize(("query", "unit"), [
    ("http_request_duration_seconds", "s"),
    ('max(http_request_duration_seconds{quantile="0.95"})', "s"),
    ("sum by (service) (http_request_duration_seconds)", "s"),
    ("max(max_over_time(process_resident_memory_bytes[1m]))", "bytes"),
    ('quantile_over_time(0.95, http_request_duration_seconds{quantile="0.5"}[5m])', "s"),
    ("avg(some_confident_ratio)", "percentunit"),
    ("histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))",
     "s"),
    ("histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
     "s")
], ids=["bare", "aggregated", "aggregated-by-a-label", "over-time", "a-quantile-over-time",
        "a-ratio", "a-histogram-quantile", "a-histogram-quantile-grouped-after"])
def test_a_series_that_keeps_its_metric_s_unit_is_in_it(query: str, unit: str) -> None:
    Scenario() \
        .when(lambda: the_unit_its_name_carries(query)) \
        .then(the_answer_was(unit))


@pytest.mark.unit
@pytest.mark.parametrize("query", [
    'max(http_request_duration_seconds{quantile="0.95"}) * 1000',
    "rate(process_cpu_seconds_total[1m])",
    "deriv(process_resident_memory_bytes[5m])",
    "count(http_request_duration_seconds)",
    'sum(rate(http_requests_total{code=~"5.."}[1m])) / sum(rate(http_requests_total[1m]))',
    "max(some_count)"
], ids=["rescaled", "a-rate", "a-derivative", "a-count", "a-ratio-of-two-rates",
        "a-name-carrying-no-unit"])
def test_a_series_that_changed_its_metric_s_unit_or_names_none_has_none(query: str) -> None:
    # The name says seconds, and a series rescaled to milliseconds, a rate per
    # second or a count of series is not in seconds: unknown, not wrong.
    Scenario() \
        .when(lambda: the_unit_its_name_carries(query)) \
        .then(the_answer_was(None))
