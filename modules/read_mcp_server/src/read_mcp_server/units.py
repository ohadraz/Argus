"""The unit a series is in, as its metric's name carries it.

Prometheus hard-codes no unit. Its naming convention is a metric in base units
with the unit as a suffix of its name - `_seconds`, `_bytes`, `_ratio` - so a
name says the unit of the metric, and the series a query makes of it is in that
unit only while nothing between the two changed it. An aggregation across
series or over time keeps it; a rescale, a rate, a derivative or a count does
not, and neither does any function this does not know. So what is followed is
an allowlist, from the outside in, and anything off it is no unit rather than
the name's - a level said in the wrong unit is wrong by its scale.

The fallback, where the rule's panel names no unit. Said as Grafana names a
unit, so the two routes answer in one vocabulary.
"""

from __future__ import annotations

import re
from typing import Final

# Each base-unit suffix the convention lists, and Grafana's id for that unit.
_UNIT_OF_A_SUFFIX: Final = {
    "_seconds": "s",
    "_bytes": "bytes",
    "_ratio": "percentunit"
}

# What a histogram's buckets are named: the measured metric with this after it.
_BUCKET_SUFFIX: Final = "_bucket"

# A grouping clause, before or after an aggregation's argument.
_GROUPING: Final = r"(?:(?:by|without)\s*\([^)]*\)\s*)?"

# Wrappers that leave the series in the unit of what they wrap. An aggregation
# is matched up to its argument's opening bracket and closed by counting, since
# a grouping clause after it ends in a bracket too: matched by pattern alone,
# `sum(rate(x[5m])) by (le)` reads its argument as running to the last one.
_AN_AGGREGATION_OPENING: Final = re.compile(rf"^(?:max|min|avg|sum)\s*{_GROUPING}\(")
_ONLY_A_GROUPING: Final = re.compile(rf"^\s*{_GROUPING}$")
_OVER_TIME: Final = re.compile(
    r"^(?:avg|min|max|last)_over_time\s*\((?P<inner>.*)\[[^\]]+\]\s*\)$", re.DOTALL
)
_A_QUANTILE_OVER_TIME: Final = re.compile(
    r"^quantile_over_time\s*\(\s*[\d.]+\s*,(?P<inner>.*)\[[^\]]+\]\s*\)$", re.DOTALL
)
_A_HISTOGRAM_QUANTILE: Final = re.compile(
    r"^histogram_quantile\s*\(\s*[\d.]+\s*,(?P<inner>.*)\)$", re.DOTALL
)

# Inside a histogram quantile only: the buckets are counters, and a rate of
# them is still bucketed by the measured metric's unit.
_A_RATE_OF_BUCKETS: Final = re.compile(
    r"^(?:rate|irate|increase)\s*\((?P<inner>.*)\[[^\]]+\]\s*\)$", re.DOTALL
)

# The metric itself, with or without a selector.
_A_METRIC: Final = re.compile(r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)\s*(?:\{[^}]*\})?$")


def the_unit_its_name_carries(query: str) -> str | None:
    """The unit of the series `query` makes, as its metric's name carries it,
    or `None` where something between the two may have changed it, or the
    name carries none."""
    inner, in_a_histogram = query.strip(), False

    while True:
        unwrapped = _unwrapped(inner, in_a_histogram)

        if unwrapped is None:
            break

        inner, entered_a_histogram = unwrapped
        in_a_histogram = in_a_histogram or entered_a_histogram

    metric = _A_METRIC.match(inner)

    if metric is None:
        return None

    name = metric["name"]

    if in_a_histogram:
        if not name.endswith(_BUCKET_SUFFIX):
            return None

        name = name.removesuffix(_BUCKET_SUFFIX)

    return next((unit for suffix, unit in _UNIT_OF_A_SUFFIX.items() if name.endswith(suffix)),
                None)


def _unwrapped(query: str, in_a_histogram: bool) -> tuple[str, bool] | None:
    """What one unit-keeping wrapper wraps, and whether it was a histogram's
    quantile - or `None` where `query` is wrapped in nothing this keeps."""
    aggregated = _an_aggregations_argument(query)

    if aggregated is not None:
        return aggregated.strip(), False

    for wrapper in (_OVER_TIME, _A_QUANTILE_OVER_TIME):
        found = wrapper.match(query)

        if found is not None:
            return found["inner"].strip(), False

    found = _A_HISTOGRAM_QUANTILE.match(query)

    if found is not None:
        return found["inner"].strip(), True

    if in_a_histogram:
        found = _A_RATE_OF_BUCKETS.match(query)

        if found is not None:
            return found["inner"].strip(), False

    return None


def _an_aggregations_argument(query: str) -> str | None:
    """What a unit-keeping aggregation aggregates, or `None` where `query` is
    not one aggregation whole - `sum(a) / sum(b)` is two."""
    opening = _AN_AGGREGATION_OPENING.match(query)

    if opening is None:
        return None

    depth = 0

    for at in range(opening.end() - 1, len(query)):
        depth += {"(": 1, ")": -1}.get(query[at], 0)

        if depth == 0:
            if _ONLY_A_GROUPING.match(query[at + 1:]) is None:
                return None

            return query[opening.end():at]

    return None
