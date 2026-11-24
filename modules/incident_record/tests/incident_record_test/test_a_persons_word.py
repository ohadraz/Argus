"""A person ending an incident, whichever door they said it through.

The page, a chat thread and the on-call platform all end an incident this one
way: the incident is looked up, the ending is made inside the trace the
incident kept, and a refusal is said there too. What each door answers is its
own, so the outcome comes back as a value - no such incident, refused, or
ended - for the door to answer in its own terms.

Against a real database, since whether an ending moves the incident is the
row's to say; and with a tracer whose spans can be read back, handed in, so
nothing is installed globally.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator
from typing import Final

import pytest
from argus_testkit import Assertion, Scenario, all_of
from core import utc_now
from core.models import Alert, IncidentStatus, Report, ReportChannel
from core.telemetry import ARGUS_INCIDENT_ID
from incident_record import (
    AtAPersonsWord,
    EndedAsSaid,
    NoSuchIncident,
    PersonsEnding,
    Refused,
    at_a_persons_word_over,
)
from incident_record.repository import incidents
from opentelemetry import baggage
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Tracer
from postgres import connect_from_env

# The logger a refusal is said on.
THE_ROLES_LOGGER: Final = "incident_record.a_persons_word"

# The context an incident kept from the span its alert was received in, as the
# propagator wrote it: a trace, and the span within it.
SOME_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SOME_SPAN = "00f067aa0ba902b7"
SOME_TRACE_CONTEXT = {"traceparent": f"00-{SOME_TRACE}-{SOME_SPAN}-01"}

DONT_CARE_REPORT = Report(by="some person", channel=ReportChannel.ARGUS_UI)
SOME_ID_THAT_NEVER_EXISTED = "00000000-0000-0000-0000-000000000000"

# One of the two endings, asked of the role.
type Ending = Callable[[AtAPersonsWord], Callable[[str, Report], PersonsEnding]]


def _resolving(word: AtAPersonsWord) -> Callable[[str, Report], PersonsEnding]:
    return word.resolve


def _withdrawing(word: AtAPersonsWord) -> Callable[[str, Report], PersonsEnding]:
    return word.withdraw


ENDING_IDS: Final = ["resolution", "withdrawal"]


@pytest.mark.component
@pytest.mark.parametrize(("ending", "ended_as"),
                         [(_resolving, IncidentStatus.RESOLVED),
                          (_withdrawing, IncidentStatus.WITHDRAWN)],
                         ids=ENDING_IDS)
def test_a_running_incident_ends_as_the_person_said(a_clean_database: None,
                                                    ending: Ending,
                                                    ended_as: IncidentStatus) -> None:
    Scenario() \
        .given(
            incident_id := _a_running_incident()
        ) \
        .when(
            lambda: ending(at_a_persons_word_over(connect_from_env))(incident_id, DONT_CARE_REPORT)
        ) \
        .then(all_of(
            _it_answered(EndedAsSaid(incident_id)),
            _the_incident_is(incident_id, ended_as)
        ))


@pytest.mark.component
@pytest.mark.parametrize("ending", [_resolving, _withdrawing], ids=ENDING_IDS)
def test_an_incident_that_already_ended_refuses_and_stays_as_it_ended(a_clean_database: None,
                                                                      ending: Ending) -> None:
    # Withdrawn already: a second press, or one on an incident somebody ended
    # some other way while the page was open. That ending stands.
    Scenario() \
        .given(
            incident_id := _a_withdrawn_incident()
        ) \
        .when(
            lambda: ending(at_a_persons_word_over(connect_from_env))(incident_id, DONT_CARE_REPORT)
        ) \
        .then(all_of(
            _it_answered(Refused(incident_id)),
            _the_incident_is(incident_id, IncidentStatus.WITHDRAWN)
        ))


@pytest.mark.component
@pytest.mark.parametrize(("ending", "its_refusal"),
                         [(_resolving, "resolution refused"),
                          (_withdrawing, "withdrawal refused")],
                         ids=ENDING_IDS)
def test_a_refusal_is_said_inside_the_incidents_trace(a_clean_database: None,
                                                      noted: _Noted,
                                                      ending: Ending,
                                                      its_refusal: str) -> None:
    # Somebody pressed and nothing changed. The door tells them; the log is
    # where whoever they ask next finds that it happened - and said inside the
    # trace, the line carries the incident it is about.
    Scenario() \
        .given(
            incident_id := _a_withdrawn_incident()
        ) \
        .when(
            lambda: ending(at_a_persons_word_over(connect_from_env))(incident_id, DONT_CARE_REPORT)
        ) \
        .then(
            _it_was_said_once_about(noted, its_refusal, incident_id)
        )


@pytest.mark.component
@pytest.mark.parametrize("ending", [_resolving, _withdrawing], ids=ENDING_IDS)
def test_an_incident_nobody_has_is_no_such_incident_and_makes_no_span(a_clean_database: None,
                                                                      ending: Ending) -> None:
    # Nothing to end, and no trace to end it in: the door answers that there is
    # no such incident, and nothing is said about one.
    Scenario() \
        .given(
            spans := InMemorySpanExporter(),
            a_tracer := _a_tracer_into(spans)
        ) \
        .when(
            lambda: ending(at_a_persons_word_over(connect_from_env, a_tracer))(
                SOME_ID_THAT_NEVER_EXISTED, DONT_CARE_REPORT)
        ) \
        .then(all_of(
            _it_answered(NoSuchIncident(SOME_ID_THAT_NEVER_EXISTED)),
            _no_span_was_made(spans)
        ))


@pytest.mark.component
@pytest.mark.parametrize(("ending", "its_span"),
                         [(_resolving, "resolve incident"),
                          (_withdrawing, "withdraw incident")],
                         ids=ENDING_IDS)
def test_an_ending_continues_the_trace_the_incident_kept(a_clean_database: None,
                                                         ending: Ending,
                                                         its_span: str) -> None:
    # A person ending the incident is part of its story, wherever they said it,
    # so it is part of the incident's trace.
    Scenario() \
        .given(
            spans := InMemorySpanExporter(),
            a_tracer := _a_tracer_into(spans),
            incident_id := _a_running_incident()
        ) \
        .when(
            lambda: ending(at_a_persons_word_over(connect_from_env, a_tracer))(
                incident_id, DONT_CARE_REPORT)
        ) \
        .then(
            _the_span_continued_the_kept_trace(spans, its_span, incident_id)
        )


class _Noted(logging.Handler):
    """Every line the role says, with the incident the baggage held as it was
    said - which is what stamps a line with its incident wherever the process
    is set up to."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[tuple[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append((record.getMessage(), baggage.get_baggage(ARGUS_INCIDENT_ID)))


@pytest.fixture
def noted() -> Generator[_Noted]:
    """A handler on the role's logger for as long as the case runs, taken off
    after it so no other case's lines are noted into this one."""
    handler = _Noted()
    logger = logging.getLogger(THE_ROLES_LOGGER)
    was_at = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(was_at)


def _a_running_incident() -> str:
    """An incident being worked, which kept the trace its alert arrived in."""
    dont_care_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        return incidents.create(conn, dont_care_alert, trace_context=SOME_TRACE_CONTEXT,
                                at=utc_now())


def _a_withdrawn_incident() -> str:
    """An incident a person already withdrew, which kept the trace its alert
    arrived in."""
    incident_id = _a_running_incident()

    with connect_from_env() as conn:
        incidents.withdraw(conn, incident_id, at=utc_now())

    return incident_id


def _a_tracer_into(spans: InMemorySpanExporter) -> Tracer:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(spans))

    return provider.get_tracer(__name__)


def _it_answered(expected: PersonsEnding) -> Assertion[PersonsEnding]:
    def assertion(answered: PersonsEnding) -> bool:
        if answered != expected:
            raise AssertionError(f"Expected the ending to answer [{expected}], got [{answered}].")

        return True

    return assertion


def _the_incident_is(incident_id: str, status: IncidentStatus) -> Assertion[PersonsEnding]:
    def assertion(_answered: PersonsEnding) -> bool:
        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected status [{status!r}], got [{incident.status!r}]."
            )

        return True

    return assertion


def _it_was_said_once_about(noted: _Noted,
                            line: str,
                            incident_id: str) -> Assertion[PersonsEnding]:
    def assertion(_answered: PersonsEnding) -> bool:
        said = [each for each in noted.lines if each[0] == line]

        if said != [(line, incident_id)]:
            raise AssertionError(
                f"Expected [{line}] said once, inside the trace of incident "
                f"[{incident_id}], and it was said as {said}"
            )

        return True

    return assertion


def _no_span_was_made(spans: InMemorySpanExporter) -> Assertion[PersonsEnding]:
    def assertion(_answered: PersonsEnding) -> bool:
        made = [span.name for span in spans.get_finished_spans()]

        if made:
            raise AssertionError(f"Expected no span for an incident nobody has, got {made}")

        return True

    return assertion


def _the_span_continued_the_kept_trace(spans: InMemorySpanExporter,
                                       name: str,
                                       incident_id: str) -> Assertion[PersonsEnding]:
    def assertion(_answered: PersonsEnding) -> bool:
        found = [span for span in spans.get_finished_spans() if span.name == name]

        if len(found) != 1:
            raise AssertionError(
                f"Expected one span named [{name}], and the spans were "
                f"{[span.name for span in spans.get_finished_spans()]}"
            )

        parent = found[0].parent
        continued = (f"{parent.trace_id:032x}", f"{parent.span_id:016x}") if parent else None
        named = (found[0].attributes or {}).get(ARGUS_INCIDENT_ID)

        if continued != (SOME_TRACE, SOME_SPAN) or named != incident_id:
            raise AssertionError(
                f"Expected the [{name}] span to continue the trace the incident kept, "
                f"[{SOME_TRACE}/{SOME_SPAN}], and to name [{incident_id}]; it "
                f"continued [{continued}] and named [{named}]."
            )

        return True

    return assertion
