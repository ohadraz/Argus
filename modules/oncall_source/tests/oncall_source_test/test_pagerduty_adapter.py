"""Reading the on-call provider - one incident, two resources, one object.

PagerDuty publishes the acknowledgement on the incident and the job title on
the user, so an acknowledgement in Argus's terms is composed from both. That
composition is this module's whole job, and it is what this suite is about;
the arithmetic on top of it belongs to `test_engagement`.

It also answers what a person's resolution needs: which keys the incident
carries, which incident carries a key, and what the person wrote when they
resolved it - the last of which PagerDuty keeps only as a note among notes.

What is injected is the client factory, so the SDK's request path stays real
and only its answers are written. Whether that path reaches PagerDuty correctly
is proven in the e2e stack.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock

import pytest
from argus_core.models import ReportChannel
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    a_factory_that_must_not_be_called,
    all_of,
    attempting,
    nothing_was_collected,
    one_record_was_logged,
)
from oncall_source import OnCallUnavailable
from oncall_source.engagement import OnCallSettings
from oncall_source.pagerduty_adapter import (
    ALERT_KEY,
    ALERTS_OF_AN_INCIDENT,
    CONTENT,
    INCIDENT_KEY,
    INCIDENT_LIST,
    NOTES_ON_AN_INCIDENT,
    RESOLUTION_NOTE_PREFIX,
    PagerDuty,
    incident_for,
    keys_of,
    pagerduty_from,
    reported_incident,
    resolution_note,
)
from oncall_source.pagerduty_webhooks import (
    AGENT,
    DATA,
    EVENT,
    EVENT_TYPE,
    RESOLVED_EVENT,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION,
)
from oncall_source.platform import ResolvedWithoutAPerson
from pagerduty import Error as PagerDutyError

SOME_INCIDENT = "incident-1"
SOME_RESPONDER = "responder-1"

# The provider's own paths and field names, spelled out here rather than shared
# with the module under test: the assertion is that Argus reads *these*, and a
# constant imported from the reader would agree with itself whatever it was
# renamed to.
INCIDENTS = "/incidents/"
USERS = "/users/"

CREATED_AT = "created_at"
RESOLVED_AT = "resolved_at"
ACKNOWLEDGEMENTS = "acknowledgements"
AT = "at"
ACKNOWLEDGER = "acknowledger"
ID = "id"
JOB_TITLE = "job_title"


@pytest.mark.unit
def test_without_a_credential_the_provider_is_never_asked() -> None:
    # Two things, and the second is the one that matters. Reporting "could not
    # be read" keeps the minutes absent rather than zero, which is the
    # difference between a response nobody recorded and a response nobody made;
    # not building a client at all is what stops an unconfigured deployment
    # authenticating as nobody against whatever address it happens to hold.
    settings_without_a_key = _settings_with(api_key="")
    a_client_was_asked_for: Kept[bool] = Kept()

    Scenario() \
        .when(
            attempting(
                lambda: reported_incident(
                    SOME_INCIDENT,
                    settings=settings_without_a_key,
                    client_of=a_factory_that_must_not_be_called(a_client_was_asked_for))
            )
        ) \
        .then(
            all_of(
                _the_source_said_it_could_not_be_read(),
                nothing_was_collected(a_client_was_asked_for)
            )
        )


@pytest.mark.unit
def test_an_acknowledgement_is_composed_with_the_title_the_user_resource_holds() -> None:
    # The provider answers who acknowledged and when in one place, and what
    # that person is called in another. Above this module there is one object
    # carrying all three - which is the point of an adapter, and the reason
    # nothing upstream has to know that a title costs a second request.
    some_incident_began_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    some_incident_lasted = timedelta(hours=1)
    some_responder_took_it_after = timedelta(minutes=12)
    some_incident_ended_at = some_incident_began_at + some_incident_lasted
    some_acknowledged_at = some_incident_began_at + some_responder_took_it_after
    some_title = "Senior Software Engineer"

    Scenario() \
        .given(
            a_provider := _a_provider_holding(
                incident=_a_reported_incident(
                    began_at=some_incident_began_at,
                    ended_at=some_incident_ended_at,
                    acknowledged_at={SOME_RESPONDER: some_acknowledged_at}),
                users={SOME_RESPONDER: {JOB_TITLE: some_title}})
        ) \
        .when(
            lambda: reported_incident(SOME_INCIDENT,
                                      settings=_settings_with(api_key="dont care"),
                                      client_of=a_provider)
        ) \
        .then(
            all_of(
                _the_incident_ended_at(some_incident_ended_at),
                _the_responder_acknowledged_at(SOME_RESPONDER, some_acknowledged_at),
                _the_responder_held(SOME_RESPONDER, some_title)
            )
        )


@pytest.mark.unit
def test_a_user_the_provider_will_not_answer_for_leaves_the_title_unknown() -> None:
    # The acknowledgement is already read: someone took the incident at a known
    # moment, and that is what the minutes are made of. Failing the whole
    # reading because the second request failed would throw away a measurement
    # over a description - and would report "nobody could say" about an
    # incident somebody demonstrably responded to.
    dont_care_began_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    dont_care_length = timedelta(hours=1)
    some_responder_took_it_after = timedelta(minutes=12)
    dont_care_ended_at = dont_care_began_at + dont_care_length
    some_acknowledged_at = dont_care_began_at + some_responder_took_it_after

    Scenario() \
        .given(
            a_provider := _a_provider_holding(
                incident=_a_reported_incident(
                    began_at=dont_care_began_at,
                    ended_at=dont_care_ended_at,
                    acknowledged_at={SOME_RESPONDER: some_acknowledged_at}),
                users={})
        ) \
        .when(
            lambda: reported_incident(SOME_INCIDENT,
                                      settings=_settings_with(api_key="dont care"),
                                      client_of=a_provider)
        ) \
        .then(
            all_of(
                _the_responder_acknowledged_at(SOME_RESPONDER, some_acknowledged_at),
                _the_responder_held(SOME_RESPONDER, None)
            )
        )


@pytest.mark.unit
def test_a_user_the_provider_will_not_answer_for_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The reading goes on without the title, and the postmortem prices what it
    # can - so the one place the gap is said is here, with who it was about.
    dont_care_began_at = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)
    dont_care_ended_at = dont_care_began_at + timedelta(hours=1)
    dont_care_acknowledged_at = dont_care_began_at + timedelta(minutes=12)

    Scenario() \
        .given(
            a_provider := _a_provider_holding(
                incident=_a_reported_incident(
                    began_at=dont_care_began_at,
                    ended_at=dont_care_ended_at,
                    acknowledged_at={SOME_RESPONDER: dont_care_acknowledged_at}),
                users={})
        ) \
        .when(
            lambda: reported_incident(SOME_INCIDENT,
                                      settings=_settings_with(api_key="dont care"),
                                      client_of=a_provider)
        ) \
        .then(
            one_record_was_logged(caplog, "oncall_source.pagerduty_adapter", logging.WARNING,
                                  "job title unreadable",
                                  values={"responder_id": SOME_RESPONDER},
                                  failure=PagerDutyError)
        )


@pytest.mark.unit
def test_the_keys_an_incident_carries_are_its_alerts_keys() -> None:
    # Every alert on a PagerDuty incident carries the key its sender stamped
    # on it - several, once incidents were merged into it, because their alerts
    # moved with them. Any one of them may be Argus's.
    Scenario() \
        .given(
            a_provider := _a_provider_answering({
                _the_alerts_of(SOME_INCIDENT): [{ALERT_KEY: "k-1"}, {ALERT_KEY: "k-2"}]
            })
        ) \
        .when(
            lambda: keys_of(SOME_INCIDENT, settings=_settings_with(api_key="dont care"),
                            client_of=a_provider)
        ) \
        .then(
            _it_answers(["k-1", "k-2"])
        )


@pytest.mark.unit
def test_keys_the_provider_will_not_give_are_reported_unreadable() -> None:
    # "Unreadable" and "no keys" are different answers: the first is retried,
    # the second is a platform incident Argus never had.
    Scenario() \
        .given(
            a_provider := _a_provider_answering({})
        ) \
        .when(
            attempting(lambda: keys_of(SOME_INCIDENT,
                                       settings=_settings_with(api_key="dont care"),
                                       client_of=a_provider))
        ) \
        .then(
            _the_source_said_it_could_not_be_read()
        )


@pytest.mark.unit
def test_the_incident_carrying_any_one_of_the_keys_is_found() -> None:
    # PagerDuty finds an incident by any of its alerts' keys, resolved or not
    # (checked against a real account).
    some_key = "k-1"

    Scenario() \
        .given(
            a_provider := _a_provider_answering({}, by_incident_key={
                some_key: [{ID: SOME_INCIDENT}]
            })
        ) \
        .when(
            lambda: incident_for(["some-unknown-key", some_key],
                                 settings=_settings_with(api_key="dont care"),
                                 client_of=a_provider)
        ) \
        .then(
            _it_answers(SOME_INCIDENT)
        )


@pytest.mark.unit
def test_keys_no_incident_carries_find_none() -> None:
    Scenario() \
        .given(
            a_provider := _a_provider_answering({})
        ) \
        .when(
            lambda: incident_for(["some-unknown-key"],
                                 settings=_settings_with(api_key="dont care"),
                                 client_of=a_provider)
        ) \
        .then(
            _it_answers(None)
        )


@pytest.mark.unit
def test_the_resolution_note_is_the_note_pagerduty_marked_as_one() -> None:
    # PagerDuty keeps no field linking a resolution to what the person wrote:
    # the note is a note among the incident's notes, marked only by the prefix
    # PagerDuty writes into it. The prefix is PagerDuty's, not the person's, so
    # it is not part of what they said.
    some_note = "rolled the flag back by hand"

    Scenario() \
        .given(
            a_provider := _a_provider_answering({
                _the_notes_on(SOME_INCIDENT): [
                    {CONTENT: "some note added while it was going on"},
                    {CONTENT: f"{RESOLUTION_NOTE_PREFIX}{some_note}"}
                ]
            })
        ) \
        .when(
            lambda: resolution_note(SOME_INCIDENT,
                                    settings=_settings_with(api_key="dont care"),
                                    client_of=a_provider)
        ) \
        .then(
            _it_answers(some_note)
        )


@pytest.mark.unit
def test_a_resolution_without_a_note_has_none_though_other_notes_exist() -> None:
    # Why "the latest note" - the workaround PagerDuty's own forum accepted -
    # is not used: resolved without a note, it would present something written
    # mid-incident as what the person said when they ended it.
    Scenario() \
        .given(
            a_provider := _a_provider_answering({
                _the_notes_on(SOME_INCIDENT): [
                    {CONTENT: "some note added while it was going on"}
                ]
            })
        ) \
        .when(
            lambda: resolution_note(SOME_INCIDENT,
                                    settings=_settings_with(api_key="dont care"),
                                    client_of=a_provider)
        ) \
        .then(
            _it_answers(None)
        )


@pytest.mark.unit
def test_without_a_credential_there_is_no_platform() -> None:
    # PagerDuty is optional. A deployment that holds no key has no on-call
    # platform at all - which is how "no platform" reaches every caller - and
    # builds no client on the way to saying so.
    a_client_was_asked_for: Kept[bool] = Kept()

    Scenario() \
        .when(
            lambda: pagerduty_from(_settings_with(api_key=""),
                                   webhook_secret="dont care",
                                   client_of=a_factory_that_must_not_be_called(
                                       a_client_was_asked_for))
        ) \
        .then(
            all_of(
                _it_answers(None),
                nothing_was_collected(a_client_was_asked_for)
            )
        )


@pytest.mark.unit
def test_a_report_through_pagerduty_reached_argus_through_pagerduty() -> None:
    Scenario() \
        .when(
            lambda: pagerduty_from(_settings_with(api_key="dont care"),
                                   webhook_secret="dont care")
        ) \
        .then(
            _its_channel_is(ReportChannel.PAGERDUTY)
        )


@pytest.mark.unit
def test_the_platform_reads_a_delivery_under_the_secret_it_was_given() -> None:
    some_secret = "some-signing-secret"
    some_delivery = json.dumps({EVENT: {
        EVENT_TYPE: RESOLVED_EVENT,
        AGENT: None,
        DATA: {ID: SOME_INCIDENT}
    }}).encode()

    Scenario() \
        .given(
            platform := _a_platform(webhook_secret=some_secret)
        ) \
        .when(
            lambda: platform.parse_delivery(some_delivery,
                                           _signed_by(some_secret, some_delivery))
        ) \
        .then(
            _it_answers(ResolvedWithoutAPerson(platform_incident=SOME_INCIDENT,
                                               resolved_by=None))
        )


def _a_platform(webhook_secret: str) -> PagerDuty:
    platform = pagerduty_from(_settings_with(api_key="dont care"), webhook_secret=webhook_secret)

    if platform is None:
        raise AssertionError("Expected a platform to be built for a deployment holding a key.")

    return platform


def _signed_by(secret: str, body: bytes) -> dict[str, str]:
    """PagerDuty's signature: an HMAC-SHA256 of the raw body, in hex, versioned."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    return {SIGNATURE_HEADER: f"{SIGNATURE_VERSION}{digest}"}


def _the_alerts_of(incident_id: str) -> str:
    return ALERTS_OF_AN_INCIDENT.format(incident_id=incident_id)


def _the_notes_on(incident_id: str) -> str:
    return NOTES_ON_AN_INCIDENT.format(incident_id=incident_id)


def _a_provider_answering(by_path: Mapping[str, Any],
                          by_incident_key: Mapping[str, Any] | None = None) -> Any:
    """A client factory answering these paths, and the incident list by key.

    A path it holds no answer for raises the vendor's own error, which is what
    a real 404 does through this SDK; a key no incident carries lists none,
    which is what the real list does.
    """
    incidents_by_key = by_incident_key or {}

    def rget(path: str, *dont_care_args: Any,
             params: Mapping[str, Any] | None = None, **dont_care_kwargs: Any) -> Any:
        if path == INCIDENT_LIST and params is not None:
            return incidents_by_key.get(params[INCIDENT_KEY], [])

        if path not in by_path:
            raise _NotFound(f"nothing at {path}")

        return by_path[path]

    client = Mock(rget=Mock(side_effect=rget))

    return lambda *dont_care_args, **dont_care_kwargs: client


def _it_answers(expected: object) -> Assertion[object]:
    def assertion(answer: object) -> bool:
        if answer != expected:
            raise AssertionError(f"Expected [{expected!r}], got [{answer!r}].")

        return True

    return assertion


def _its_channel_is(expected: ReportChannel) -> Assertion[PagerDuty | None]:
    def assertion(platform: PagerDuty | None) -> bool:
        if platform is None:
            raise AssertionError(
                "Expected a platform for a deployment holding a key, got none."
            )

        if platform.channel is not expected:
            raise AssertionError(
                f"Expected reports through it to have come through [{expected}], "
                f"got [{platform.channel}]."
            )

        return True

    return assertion


def _settings_with(api_key: str) -> OnCallSettings:
    """The slice this reader runs under.

    Only the credential matters here; the client is injected, so no address is
    ever dialled and no certificate is ever checked.
    """
    dont_care_base_url = ""
    dont_care_verify_tls = True

    return OnCallSettings(
        pagerduty_api_key=api_key,
        pagerduty_base_url=dont_care_base_url,
        pagerduty_verify_tls=dont_care_verify_tls
    )


def _a_reported_incident(began_at: datetime,
                         ended_at: datetime,
                         acknowledged_at: Mapping[str, datetime]) -> dict[str, Any]:
    """One incident in the provider's own shape - instants as text, and an
    acknowledgement naming its acknowledger rather than carrying them."""
    return {
        CREATED_AT: began_at.isoformat(),
        RESOLVED_AT: ended_at.isoformat(),
        ACKNOWLEDGEMENTS: [
            {AT: at.isoformat(), ACKNOWLEDGER: {ID: responder}}
            for responder, at in acknowledged_at.items()
        ]
    }


class _NotFound(PagerDutyError):
    """The vendor's own error, raised without its untyped constructor.

    The SDK's `Error.__init__` carries no annotations, so calling it from typed
    code is a mypy error rather than a style question. Subclassing and setting
    what the base sets keeps this a real PagerDuty error - which is what the
    adapter catches - without the untyped call.
    """

    def __init__(self, message: str) -> None:
        self.msg = message
        self.response = None
        Exception.__init__(self, message)


def _a_provider_holding(incident: Mapping[str, Any],
                        users: Mapping[str, Mapping[str, Any]]) -> Any:
    """A client factory answering these resources, and failing on any other.

    Stood in by hand rather than by `create_autospec`, because what is stood in
    for is one method whose answer depends on the path it is given - which is a
    behaviour rather than a signature, and a spec would assert nothing about
    it. A user the provider does not hold raises the vendor's own error, which
    is what a real 404 does through this SDK.
    """
    def rget(path: str, *dont_care_args: Any, **dont_care_kwargs: Any) -> Any:
        if not path.startswith(USERS):
            return incident

        responder = path.removeprefix(USERS)

        if responder not in users:
            raise _NotFound(f"no such user: {responder}")

        return users[responder]

    client = Mock(rget=Mock(side_effect=rget))

    return lambda *dont_care_args, **dont_care_kwargs: client


def _the_source_said_it_could_not_be_read() -> Assertion[Any]:
    def assertion(error: Any) -> bool:
        if not isinstance(error, OnCallUnavailable):
            raise AssertionError(
                f"Expected the source to report that it could not be read, but "
                f"what came back was {error!r}."
            )

        return True

    return assertion


def _the_incident_ended_at(ended_at: datetime) -> Assertion[Any]:
    def assertion(incident: Any) -> bool:
        if incident.ended_at != ended_at:
            raise AssertionError(
                f"Expected the incident to have ended at [{ended_at}], but what "
                f"was reported was [{incident.ended_at}]."
            )

        return True

    return assertion


def _the_responder_acknowledged_at(responder_id: str, at: datetime) -> Assertion[Any]:
    def assertion(incident: Any) -> bool:
        acknowledged = _acknowledgements_by(incident, responder_id)

        if not acknowledged:
            raise AssertionError(
                f"Expected an acknowledgement by [{responder_id}], but the "
                f"incident reported none by them."
            )

        if acknowledged[0].at != at:
            raise AssertionError(
                f"Expected [{responder_id}] to have acknowledged at [{at}], but "
                f"what was reported was [{acknowledged[0].at}]."
            )

        return True

    return assertion


def _the_responder_held(responder_id: str, title: str | None) -> Assertion[Any]:
    def assertion(incident: Any) -> bool:
        acknowledged = _acknowledgements_by(incident, responder_id)

        if not acknowledged:
            raise AssertionError(
                f"Expected an acknowledgement by [{responder_id}], but the "
                f"incident reported none by them."
            )

        if acknowledged[0].job_title != title:
            raise AssertionError(
                f"Expected [{responder_id}] to have been reported holding "
                f"[{title}], but what was reported was "
                f"[{acknowledged[0].job_title}]."
            )

        return True

    return assertion


def _acknowledgements_by(incident: Any, responder_id: str) -> list[Any]:
    return [acknowledgement for acknowledgement in incident.acknowledgements
            if acknowledgement.responder_id == responder_id]


