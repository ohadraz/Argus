"""A Prometheus, in-process, serving one `MetricsState` in Prometheus's own shapes.

The ports' suite runs the Prometheus adapter against this through its `get`
seam, beside the in-memory double built from the same seed. So this answers
the one route the adapter asks - a range query - in the shapes
`test_prometheus_adapter.py` pins on the wire. Every word of Prometheus's it
speaks, every query a minute's field is read by among them, is imported from
the adapter, so the two cannot spell one differently; whether each means what
the adapter takes it to is a contract question.

How a held minute is said: for each of its fields, one sample stamped at the
end of the minute it describes, its value as text - none for a field the
minute does not have. A held series beyond those is said the same way, as one
series. Asked between two moments, every sample stamped at or between them is
answered, at a minute's step.

Behaviours of Prometheus's the adapter only reads: a query it holds no series
for is refused with a 400 and its error envelope, as a query Prometheus cannot
evaluate is; and so is a range whose end is before its start, in Prometheus's
own words for it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx2
from core import parse_iso
from metrics_source.prometheus_adapter import (
    A_MINUTE_STEP,
    DATA,
    END,
    ERROR,
    ERROR_TYPE,
    QUERIES,
    QUERY,
    RANGE_QUERY_PATH,
    RESULT,
    START,
    STEP,
    VALUES,
)
from metrics_source.prometheus_settings import PrometheusSettings
from metrics_source_double import MetricsState

# Where the stand-in is addressed. Nothing listens there: `get` answers.
_BASE_URL: Final = "http://prometheus.invalid"

# The words of Prometheus's envelope the adapter never reads - whether the
# query succeeded, what shape its result has, the labels of each series, and
# its word for a query it cannot evaluate, which the adapter carries on in its
# failure as it came. Declared here, once, for every suite of the adapter's
# that answers as Prometheus does.
STATUS: Final = "status"
SUCCESS: Final = "success"
AN_ERROR: Final = "error"
RESULT_TYPE: Final = "resultType"
MATRIX: Final = "matrix"
METRIC: Final = "metric"
BAD_DATA: Final = "bad_data"

# What it says, as its `queryRange` handler says it (web/api/v1/api.go), to a
# range whose end is before its start.
_END_BEFORE_START: Final = 'invalid parameter "end": end timestamp must not be before start time'

_A_MINUTE: Final = timedelta(minutes=1)

# Each field a minute is read by, by the query that reads it.
_FIELDS: Final = {query: field for field, query in QUERIES.items()}


def prometheus_settings() -> PrometheusSettings:
    """The adapter's settings, addressed at the stand-in."""
    return PrometheusSettings(prometheus_base_url=_BASE_URL)


class PrometheusWorld:
    """Prometheus, holding `state`, as the adapter's `get` asks it.

    `unreachable` builds one nothing reaches: every request fails as one that
    never arrived.
    """

    def __init__(self, state: MetricsState, *, unreachable: bool = False) -> None:
        for held in state.series:
            if held.query in _FIELDS:
                raise ValueError(f"a series is held under [{held.query}], which a minute's "
                                 f"own field is read by: one query, one answer")

        self._series: dict[str, list[tuple[datetime, float]]] = {
            query: [
                (parse_iso(bucket.bucket_id), value)
                for bucket in state.minutes
                if (value := getattr(bucket, field)) is not None
            ]
            for query, field in _FIELDS.items()
        }
        self._series.update({held.query: list(held.readings) for held in state.series})
        self._unreachable = unreachable

    def get(self,
            url: str,
            *,
            params: dict[str, str],
            **dont_care_options: Any) -> httpx2.Response:
        """A range query's answer, its timeout passed over."""
        request = httpx2.Request("GET", url, params=params)

        if self._unreachable:
            raise httpx2.ConnectError("Prometheus is not reachable", request=request)

        if url != f"{_BASE_URL}{RANGE_QUERY_PATH}":
            return httpx2.Response(404, text="404 page not found", request=request)

        held = self._series.get(params[QUERY])

        start = datetime.fromtimestamp(float(params[START]), UTC)
        end = datetime.fromtimestamp(float(params[END]), UTC)

        if end < start:
            return _refused(_END_BEFORE_START, request)

        if params[STEP] != A_MINUTE_STEP:
            return _refused(f"this stand-in answers at a step of {A_MINUTE_STEP} alone, "
                            f"not [{params[STEP]}]", request)

        if held is None:
            return _refused(f"parse error: [{params[QUERY]}] is no query this "
                            f"Prometheus can evaluate", request)

        values = [
            [(minute + _A_MINUTE).timestamp(), str(value)]
            for minute, value in sorted(held)
            if start <= minute + _A_MINUTE <= end
        ]

        # A series with no sample in the range is left out of the result, as
        # Prometheus leaves it out.
        return httpx2.Response(200, json={STATUS: SUCCESS, DATA: {
            RESULT_TYPE: MATRIX,
            RESULT: [{METRIC: {}, VALUES: values}] if values else []
        }}, request=request)


def _refused(why: str, request: httpx2.Request) -> httpx2.Response:
    """A query Prometheus will not evaluate, in its error envelope."""
    return httpx2.Response(400, json={STATUS: AN_ERROR, ERROR_TYPE: BAD_DATA, ERROR: why},
                           request=request)
