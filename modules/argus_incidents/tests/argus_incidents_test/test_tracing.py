"""Work on an incident, done inside the trace its alert arrived in.

An incident keeps the trace context its alert came with. Whatever is done to
it afterwards continues that context: each walk, each unwind, a withdrawal.
That is what makes an incident one trace from the alert onwards, however many
processes and hours it spans.

While the work runs, the incident's id is in the baggage, so every log record
written inside it says whose incident it was, and so does every tool call it
makes into a server.

An SDK's in-memory exporter, handed in as the tracer, so every span can be read
back and nothing is installed globally.
"""

from __future__ import annotations

import pytest
from argus_core.telemetry import ARGUS_INCIDENT_ID, ERROR_TYPE
from argus_incidents import inside_the_incidents_trace
from argus_testkit import Assertion, Scenario, all_of
from opentelemetry import baggage, propagate
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode, Tracer

SOME_INCIDENT = "4f0c2a1e-5b6d-4c3e-9a8b-7d6e5f4c3b2a"
SOME_WORK = "some work"
THE_ALERTS_SPAN = "receive alert"


@pytest.mark.unit
def test_work_on_an_incident_continues_the_trace_its_alert_arrived_in() -> None:
    Scenario() \
        .given(
            spans := InMemorySpanExporter(),
            a_tracer := _a_tracer_into(spans),
            the_alerts_context := _a_context_the_alert_arrived_in(a_tracer)
        ) \
        .when(
            lambda: _worked_on(SOME_INCIDENT, the_alerts_context, a_tracer)
        ) \
        .then(
            _the_work_is_a_child_of_the_alerts_span(spans)
        )


@pytest.mark.unit
def test_work_on_an_incident_that_kept_no_trace_starts_one_of_its_own() -> None:
    # Started outside any trace - by a test, a script. Its work is traced all
    # the same, from the work.
    Scenario() \
        .given(
            spans := InMemorySpanExporter(),
            a_tracer := _a_tracer_into(spans)
        ) \
        .when(
            lambda: _worked_on(SOME_INCIDENT, {}, a_tracer)
        ) \
        .then(
            _the_work_started_a_trace(spans)
        )


@pytest.mark.unit
def test_the_work_names_its_incident() -> None:
    Scenario() \
        .given(
            spans := InMemorySpanExporter(),
            a_tracer := _a_tracer_into(spans)
        ) \
        .when(
            lambda: _worked_on(SOME_INCIDENT, {}, a_tracer)
        ) \
        .then(
            _the_work_carries(ARGUS_INCIDENT_ID, SOME_INCIDENT, spans)
        )


@pytest.mark.unit
def test_the_incident_is_in_the_baggage_while_the_work_runs_and_not_after() -> None:
    # In the baggage rather than handed to every call: a log line written deep
    # inside an agent, or inside a tool call on the far side of a server, says
    # whose incident it was without anybody passing it down. And gone after,
    # so the next incident's work is not stamped with this one's.
    Scenario() \
        .given(
            spans := InMemorySpanExporter(),
            a_tracer := _a_tracer_into(spans)
        ) \
        .when(
            lambda: _the_baggage_during_and_after(SOME_INCIDENT, a_tracer)
        ) \
        .then(
            _the_baggage_held(during=SOME_INCIDENT, after=None)
        )


@pytest.mark.unit
def test_work_that_fails_is_said_on_its_span_and_raised_on() -> None:
    Scenario() \
        .given(
            spans := InMemorySpanExporter(),
            a_tracer := _a_tracer_into(spans)
        ) \
        .when(
            lambda: _worked_on(SOME_INCIDENT, {}, a_tracer, raising=ValueError("some failure"))
        ) \
        .then(
            all_of(
                _what_came_out_was_a(ValueError),
                _the_work_failed_with(ValueError, spans)
            )
        )


def _a_tracer_into(spans: InMemorySpanExporter) -> Tracer:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(spans))

    return provider.get_tracer(__name__)


def _a_context_the_alert_arrived_in(tracer: Tracer) -> dict[str, str]:
    """The carrier an intake span leaves behind, as the propagator writes it."""
    carrier: dict[str, str] = {}

    with tracer.start_as_current_span(THE_ALERTS_SPAN):
        propagate.inject(carrier)

    return carrier


def _worked_on(incident_id: str,
               trace_context: dict[str, str],
               tracer: Tracer,
               raising: BaseException | None = None) -> BaseException | None:
    """Some work done inside the incident's trace. Returns whatever came out of it."""
    try:
        with inside_the_incidents_trace(incident_id, trace_context, SOME_WORK, tracer=tracer):
            if raising is not None:
                raise raising
    except BaseException as came_out:
        return came_out

    return None


def _the_baggage_during_and_after(incident_id: str,
                                  tracer: Tracer) -> tuple[object, object]:
    with inside_the_incidents_trace(incident_id, {}, SOME_WORK, tracer=tracer):
        during = baggage.get_baggage(ARGUS_INCIDENT_ID)

    return during, baggage.get_baggage(ARGUS_INCIDENT_ID)


def _named(spans: InMemorySpanExporter, name: str) -> ReadableSpan:
    found = [span for span in spans.get_finished_spans() if span.name == name]

    if len(found) != 1:
        raise AssertionError(
            f"Expected one span named [{name}], and the spans were "
            f"{[span.name for span in spans.get_finished_spans()]}."
        )

    return found[0]


def _the_work_is_a_child_of_the_alerts_span(spans: InMemorySpanExporter) -> Assertion[object]:
    def assertion(_returned: object) -> bool:
        alert = _named(spans, THE_ALERTS_SPAN).get_span_context()
        work = _named(spans, SOME_WORK)
        parent = work.parent

        if alert is None or parent is None or (parent.trace_id, parent.span_id) != (
            alert.trace_id, alert.span_id
        ):
            raise AssertionError(
                f"Expected the work's span to be a child of the alert's span "
                f"[{alert}], and its parent was [{parent}]."
            )

        return True

    return assertion


def _the_work_started_a_trace(spans: InMemorySpanExporter) -> Assertion[object]:
    def assertion(_returned: object) -> bool:
        parent = _named(spans, SOME_WORK).parent

        if parent is not None:
            raise AssertionError(
                f"Expected work on an incident that kept no trace to start one, "
                f"and its span had a parent [{parent}]."
            )

        return True

    return assertion


def _the_work_carries(key: str, expected: str, spans: InMemorySpanExporter) -> Assertion[object]:
    def assertion(_returned: object) -> bool:
        actual = (_named(spans, SOME_WORK).attributes or {}).get(key)

        if actual != expected:
            raise AssertionError(
                f"Expected the work's span to carry [{key}] as [{expected}], "
                f"and it carried [{actual}]."
            )

        return True

    return assertion


def _the_baggage_held(during: str, after: None) -> Assertion[tuple[object, object]]:
    def assertion(held: tuple[object, object]) -> bool:
        if held != (during, after):
            raise AssertionError(
                f"Expected the baggage to hold the incident [{during}] during the "
                f"work and [{after}] after it, and it held {held}."
            )

        return True

    return assertion


def _what_came_out_was_a(kind: type[BaseException]) -> Assertion[BaseException | None]:
    def assertion(came_out: BaseException | None) -> bool:
        if not isinstance(came_out, kind):
            raise AssertionError(
                f"Expected the failure to go on past the work as a [{kind.__name__}], "
                f"and [{came_out!r}] came out."
            )

        return True

    return assertion


def _the_work_failed_with(kind: type[BaseException],
                          spans: InMemorySpanExporter) -> Assertion[object]:
    def assertion(_returned: object) -> bool:
        work = _named(spans, SOME_WORK)
        said = (work.status.status_code, (work.attributes or {}).get(ERROR_TYPE))

        if said != (StatusCode.ERROR, kind.__name__):
            raise AssertionError(
                f"Expected the work's span to say it failed with [{kind.__name__}], "
                f"and it said {said}."
            )

        return True

    return assertion
