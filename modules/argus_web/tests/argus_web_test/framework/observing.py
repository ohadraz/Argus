"""Reading back the spans `argus_web` made, without installing anything globally.

The app takes its tracer through a FastAPI dependency, `tracer_of`. Overriding
that dependency is FastAPI's own seam for standing something in, and it hands
the routes a tracer whose every finished span lands in an in-memory exporter.
The override is put back as the block ends, so no other case is traced into
this one's exporter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from argus_web.app import app, tracer_of
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@contextmanager
def observing_the_app() -> Iterator[InMemorySpanExporter]:
    """The app's spans, readable as each one ends, for as long as the block runs."""
    spans = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(spans))
    app.dependency_overrides[tracer_of] = lambda: provider.get_tracer(__name__)

    try:
        yield spans
    finally:
        app.dependency_overrides.pop(tracer_of, None)


def the_span_named(spans: InMemorySpanExporter, name: str) -> ReadableSpan:
    """The one finished span by that name, or a failure saying what there was instead."""
    found = [span for span in spans.get_finished_spans() if span.name == name]

    if len(found) != 1:
        raise AssertionError(
            f"Expected one span named [{name}], and the spans were "
            f"{[span.name for span in spans.get_finished_spans()]}."
        )

    return found[0]
