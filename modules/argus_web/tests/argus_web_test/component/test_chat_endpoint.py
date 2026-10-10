"""The doors the chat platform knocks on, from the outside.

Two of them, because Slack is configured with one address for what is posted in
a channel and another for what is pressed on a message - and both lead to the
same handling. What a person's words and a person's press do to the incident
record, and what each other outcome is answered with: the platform waits three
seconds and retries what it is not answered for, so everything Argus receives
intact is answered as received, and only a forgery is refused.

The platform is stood in through the app's own dependency seam: it is somebody
else's API, and what it says is decided in the adapter's suite. The incident
record is real, because whether the person's word reaches the incident is the
question.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from http import HTTPStatus as HttpStatus
from typing import Any
from unittest.mock import create_autospec
from uuid import uuid4

import httpx2
import pytest
from argus_core import connect_from_env
from argus_core.events import (
    OfferExpired,
    PersonWrote,
    ResolutionOffered,
    StatusChanged,
    WithdrawalOffered,
)
from argus_core.models import (
    Alert,
    IncidentStatus,
    Reference,
    Report,
    ReportChannel,
    a_chat_message,
    a_chat_thread,
)
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_incidents.repository import events, incidents, references
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from argus_web.app import app, chat_platform_of
from chat_platform import (
    ChatDeliveryUnverified,
    ChatPlatformReads,
    Delivery,
    Handshake,
    Pressed,
    Written,
)
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from argus_web_test.framework.assertions import the_response_was
from argus_web_test.framework.observing import observing_the_app, the_span_named

EVENTS_WEBHOOK = "/webhooks/slack/events"
INTERACTIONS_WEBHOOK = "/webhooks/slack/interactions"

DONT_CARE_BODY = b"{}"
SOME_PERSON = "U-some-person"
SOME_WORDS = "rolled the flag back by hand, we're fine"

# The context an incident kept from the span its alert was received in.
SOME_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
SOME_SPAN = "00f067aa0ba902b7"
SOME_TRACE_CONTEXT = {"traceparent": f"00-{SOME_TRACE}-{SOME_SPAN}-01"}

# Which kind of offer an incident was made, for the cases that hold for both.
type OfferKind = type[ResolutionOffered] | type[WithdrawalOffered]


@pytest.mark.component
def test_a_person_writing_in_an_incidents_thread_is_heard_on_that_incident() -> None:
    a_thread, a_message = _a_thread(), _a_message()
    incident_id = _an_incident_told_in(a_thread)

    with _the_platform_saying(Written(thread=a_thread, message=a_message,
                                      person_id=SOME_PERSON, text=SOME_WORDS)), \
            TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(EVENTS_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(all_of(
                the_response_was(HttpStatus.OK),
                _the_incident_heard(incident_id, a_message, SOME_PERSON, SOME_WORDS)
            ))


@pytest.mark.component
def test_the_person_an_offer_was_made_to_pressing_it_resolves_the_incident() -> None:
    some_name = "Some Person"
    a_thread, a_message = _a_thread(), _a_message()
    incident_id = _an_incident_told_in(a_thread, offering=(a_message, SOME_PERSON, some_name))

    with _the_platform_saying(Pressed(thread=a_thread, person_id=SOME_PERSON,
                                      message=a_message)), \
            TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(INTERACTIONS_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(all_of(
                the_response_was(HttpStatus.OK),
                _the_incident_is(incident_id, IncidentStatus.RESOLVED),
                _the_account_says_it_was_reported_as(
                    incident_id,
                    Report(by=some_name, channel=ReportChannel.SLACK, note=SOME_WORDS)
                )
            ))


@pytest.mark.component
def test_the_person_a_withdrawal_offer_was_made_to_pressing_it_withdraws_the_incident() -> None:
    some_name = "Some Person"
    a_thread, a_message = _a_thread(), _a_message()
    incident_id = _an_incident_told_in(a_thread, offering=(a_message, SOME_PERSON, some_name),
                                       offered=WithdrawalOffered)

    with _the_platform_saying(Pressed(thread=a_thread, person_id=SOME_PERSON,
                                      message=a_message)), \
            TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(INTERACTIONS_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(all_of(
                the_response_was(HttpStatus.OK),
                _the_incident_is(incident_id, IncidentStatus.WITHDRAWN),
                _the_account_says_it_was_reported_as(
                    incident_id,
                    Report(by=some_name, channel=ReportChannel.SLACK, note=SOME_WORDS),
                    ending=IncidentStatus.WITHDRAWN
                )
            ))


@pytest.mark.component
@pytest.mark.parametrize(("offered", "span_name"), [(ResolutionOffered, "resolve incident"),
                                                    (WithdrawalOffered, "withdraw incident")],
                         ids=["resolution", "withdrawal"])
def test_an_ending_from_the_thread_continues_the_incidents_trace(offered: OfferKind,
                                                                 span_name: str) -> None:
    # As one from the page does: a person ending it is part of the incident's
    # story, wherever they said it.
    a_thread, a_message = _a_thread(), _a_message()
    incident_id = _an_incident_told_in(a_thread, offering=(a_message, SOME_PERSON, "dont care"),
                                       trace_context=SOME_TRACE_CONTEXT, offered=offered)

    with _the_platform_saying(Pressed(thread=a_thread, person_id=SOME_PERSON,
                                      message=a_message)), \
            observing_the_app() as spans, TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(INTERACTIONS_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(_it_ended_inside_the_trace_it_kept(spans, incident_id, span_name))


@pytest.mark.component
def test_a_press_on_an_offer_that_expired_leaves_the_incident_as_it_was() -> None:
    # The expiry is read from the incident's own account, where the walk that
    # stopped waiting wrote it.
    a_thread, a_message = _a_thread(), _a_message()
    incident_id = _an_incident_told_in(a_thread, offering=(a_message, SOME_PERSON, "dont care"),
                                       expired=True)

    with _the_platform_saying(Pressed(thread=a_thread, person_id=SOME_PERSON,
                                      message=a_message)), \
            TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(INTERACTIONS_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(all_of(
                the_response_was(HttpStatus.OK),
                _the_incident_is(incident_id, IncidentStatus.ACKNOWLEDGED)
            ))


@pytest.mark.component
def test_the_platform_checking_the_address_is_answered_with_its_challenge() -> None:
    some_challenge = "some-challenge"

    with _the_platform_saying(Handshake(challenge=some_challenge)), TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(EVENTS_WEBHOOK, content=DONT_CARE_BODY)) \
            .then(all_of(the_response_was(HttpStatus.OK),
                         _the_challenge_was_answered(some_challenge)))


@pytest.mark.component
@pytest.mark.parametrize("webhook", [EVENTS_WEBHOOK, INTERACTIONS_WEBHOOK])
def test_a_forged_delivery_is_refused_and_logged(webhook: str,
                                                 caplog: pytest.LogCaptureFixture) -> None:
    # The likeliest way to meet a refusal is a deployment holding the wrong
    # secret, and a refusal nobody can see is one nobody can fix.
    with _the_platform_refusing(ChatDeliveryUnverified("forged")), TestClient(app) as client:
        Scenario() \
            .given(calling(lambda: caplog.set_level(logging.WARNING))) \
            .when(lambda: client.post(webhook, content=DONT_CARE_BODY)) \
            .then(all_of(
                the_response_was(HttpStatus.UNAUTHORIZED),
                one_record_was_logged(caplog, "argus_web.app", logging.WARNING,
                                      "chat delivery refused")
            ))


@pytest.mark.component
@pytest.mark.parametrize("webhook", [EVENTS_WEBHOOK, INTERACTIONS_WEBHOOK])
def test_without_a_chat_platform_there_is_no_door(webhook: str) -> None:
    # The platform is optional, and a deployment without one behaves as though
    # the feature did not exist.
    with _no_platform(), TestClient(app) as client:
        Scenario() \
            .when(lambda: client.post(webhook, content=DONT_CARE_BODY)) \
            .then(the_response_was(HttpStatus.NOT_FOUND))


def _a_thread() -> Reference:
    """A thread no other case has used. This suite keeps its rows between
    cases, and a thread shared with an earlier one would find that case's
    incident."""
    return a_chat_thread(ReportChannel.SLACK, "C-some-channel", f"{uuid4().int % 10**10}.000100")


def _a_message() -> Reference:
    """A message no other case has used, for the same reason."""
    return a_chat_message(ReportChannel.SLACK, "C-some-channel", f"{uuid4().int % 10**10}.000200")


def _an_incident_told_in(thread: Reference,
                         offering: tuple[Reference, str, str] | None = None,
                         trace_context: Mapping[str, str] = incidents.NO_TRACE_CONTEXT,
                         expired: bool = False,
                         offered: OfferKind = ResolutionOffered) -> str:
    """An incident whose war room is `thread`, and - where `offering` names a
    message, a person and their name - an offer of the `offered` kind made to
    them about it."""
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert, trace_context)
        references.add(conn, incident_id, [thread])

        if offering is not None:
            message, person_id, person_name = offering
            events.record(conn, offered(incident_id=incident_id, message=message,
                                        person_id=person_id, person_name=person_name,
                                        said=SOME_WORDS))

            if expired:
                events.record(conn, OfferExpired(incident_id=incident_id, message=message))

        conn.commit()

    return incident_id


@contextmanager
def _the_platform_saying(delivery: Delivery) -> Iterator[None]:
    platform = create_autospec(ChatPlatformReads, instance=True)
    platform.channel = ReportChannel.SLACK
    platform.parse_delivery.return_value = delivery

    with _the_platform_being(platform):
        yield


@contextmanager
def _the_platform_refusing(refusal: Exception) -> Iterator[None]:
    platform = create_autospec(ChatPlatformReads, instance=True)
    platform.parse_delivery.side_effect = refusal

    with _the_platform_being(platform):
        yield


@contextmanager
def _no_platform() -> Iterator[None]:
    with _the_platform_being(None):
        yield


@contextmanager
def _the_platform_being(platform: Any) -> Iterator[None]:
    """FastAPI's own seam for standing something in, put back as the block ends."""
    app.dependency_overrides[chat_platform_of] = lambda: platform

    try:
        yield
    finally:
        app.dependency_overrides.pop(chat_platform_of, None)


def _the_incident_heard(incident_id: str,
                        message: Reference,
                        person_id: str,
                        text: str) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        with connect_from_env() as conn:
            recorded = events.get_by_incident(conn, incident_id)

        ingested = [(event.message, event.person_id, event.text) for event in recorded
                 if isinstance(event, PersonWrote)]

        if ingested != [(message, person_id, text)]:
            raise AssertionError(
                f"Expected the incident to have ingested {person_id} say [{text}] once, "
                f"got {ingested}."
            )

        return True

    return assertion


def _the_incident_is(incident_id: str,
                     status: IncidentStatus) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
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


def _the_account_says_it_was_reported_as(
    incident_id: str,
    expected: Report,
    ending: IncidentStatus = IncidentStatus.RESOLVED
) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        with connect_from_env() as conn:
            recorded = events.get_by_incident(conn, incident_id)

        reported = [event.reported for event in recorded
                    if isinstance(event, StatusChanged) and event.to_status == ending]

        if reported != [expected]:
            raise AssertionError(
                f"Expected one [{ending}] reported as [{expected}], got {reported}."
            )

        return True

    return assertion


def _the_challenge_was_answered(expected: str) -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        answered = response.json().get("challenge")

        if answered != expected:
            raise AssertionError(
                f"Expected the challenge [{expected}] answered, got [{answered}]."
            )

        return True

    return assertion


def _it_ended_inside_the_trace_it_kept(
    spans: InMemorySpanExporter, incident_id: str, span_name: str
) -> Assertion[httpx2.Response]:
    def assertion(_response: httpx2.Response) -> bool:
        ended = the_span_named(spans, span_name)
        parent = ended.parent
        continued = (f"{parent.trace_id:032x}", f"{parent.span_id:016x}") if parent else None
        named = (ended.attributes or {}).get(ARGUS_INCIDENT_ID)

        if continued != (SOME_TRACE, SOME_SPAN) or named != incident_id:
            raise AssertionError(
                f"Expected the [{span_name}] span to continue the trace the incident "
                f"kept, [{SOME_TRACE}/{SOME_SPAN}], and to name [{incident_id}]; it "
                f"continued [{continued}] and named [{named}]."
            )

        return True

    return assertion
