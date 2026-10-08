"""Watching what the walk reported, without installing anything globally.

An SDK's in-memory exporter and reader, handed to the code under test as its
tracer and meter where it would otherwise take the process's own - which in a
test is OTel's no-op, and reports nothing to anyone.

The same rig as `argus_core`'s suite keeps for the model and tool calls, kept
again here rather than shared: a suite cannot import another suite, and the one
place both could reach is `argus_testkit`, which would then carry an SDK into
every suite in the workspace for the two that read spans.
"""

from __future__ import annotations

from typing import Any

from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    HistogramDataPoint,
    InMemoryMetricReader,
    NumberDataPoint,
)
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer


class Observed:
    """A tracer and a meter whose every span and point can be read back.

    Spans are exported as each one ends, so a span is readable the moment the
    step that made it returns - with no flush to remember.
    """

    def __init__(self) -> None:
        self._spans = InMemorySpanExporter()
        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(self._spans))
        self.tracer: Tracer = tracer_provider.get_tracer(__name__)

        self._reader = InMemoryMetricReader()
        self.meter: Meter = MeterProvider(metric_readers=[self._reader]).get_meter(__name__)

    def spans(self) -> list[ReadableSpan]:
        return list(self._spans.get_finished_spans())

    def only_span(self) -> ReadableSpan:
        finished = self.spans()

        if len(finished) != 1:
            raise AssertionError(
                f"Expected exactly one span, and there were {len(finished)}: "
                f"{[span.name for span in finished]}."
            )

        return finished[0]

    def histogram_points_of(self, metric: str) -> list[HistogramDataPoint]:
        return [point for point in self._points_of(metric)
                if isinstance(point, HistogramDataPoint)]

    def counter_points_of(self, metric: str) -> list[NumberDataPoint]:
        return [point for point in self._points_of(metric)
                if isinstance(point, NumberDataPoint)]

    def _points_of(self, metric: str) -> list[Any]:
        collected = self._reader.get_metrics_data()

        if collected is None:
            return []

        return [
            point
            for resource in collected.resource_metrics
            for scope in resource.scope_metrics
            for recorded in scope.metrics
            if recorded.name == metric
            for point in recorded.data.data_points
        ]


def observing() -> Observed:
    return Observed()


def attributes_of(point: HistogramDataPoint | NumberDataPoint) -> dict[str, Any]:
    return dict(point.attributes or {})
