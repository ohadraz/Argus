"""Work on an incident, done inside the trace its alert arrived in.

An incident keeps the trace context its alert came with (`start_incident`).
Whatever is done to it afterwards continues that context: each walk, each
unwind, a withdrawal. That is what makes an incident one trace from the alert
onwards, however many processes and hours it spans.

While the work runs, the incident's id is in the baggage too. Every log record
written inside the work is stamped from there, and every tool call it makes
carries it into the server that answers.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Final

from argus_core.telemetry import ARGUS_INCIDENT_ID, ERROR_TYPE
from opentelemetry import baggage, context, propagate, trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer

# The instrumentation scope this work's spans are reported under.
_SCOPE: Final = __name__


@contextmanager
def inside_the_incidents_trace(incident_id: str,
                               trace_context: Mapping[str, str],
                               span: str,
                               kind: SpanKind = SpanKind.INTERNAL,
                               tracer: Tracer | None = None) -> Iterator[Span]:
    """A span for some work on the incident, continuing the trace it keeps.

    `trace_context` is what the incident kept, as the propagator wrote it. An
    empty one - an incident started outside any trace - gives the work a
    trace of its own. The incident's id is in the baggage until the work ends,
    and gone after it.

    Work that raises is said on the span, as the class of what went wrong, and
    raised on: telemetry decides nothing about how a failure is handled.

    `tracer` defaults to the process's own, looked up when the work starts.
    """
    continued = propagate.extract(dict(trace_context))
    named = context.attach(baggage.set_baggage(ARGUS_INCIDENT_ID, incident_id, continued))
    working = tracer if tracer is not None else trace.get_tracer(_SCOPE)

    try:
        with working.start_as_current_span(
            span,
            kind=kind,
            attributes={ARGUS_INCIDENT_ID: incident_id},
            set_status_on_exception=False
        ) as current:
            try:
                yield current
            except Exception as error:
                current.set_attribute(ERROR_TYPE, type(error).__name__)
                current.set_status(Status(StatusCode.ERROR, str(error)))
                raise
    finally:
        context.detach(named)
