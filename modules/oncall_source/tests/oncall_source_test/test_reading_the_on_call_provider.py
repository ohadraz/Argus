from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock

import pytest
from argus_core.config import Settings
from argus_testkit import Assertion, Kept, Scenario, all_of, attempting
from oncall_source import OnCallUnavailable
from oncall_source.pagerduty_adapter import reported_incident
from pagerduty import Error as PagerDutyError

"""Reading the on-call provider - one incident, two resources, one object.

PagerDuty publishes the acknowledgement on the incident and the job title on
the user, so an acknowledgement in Argus's terms is composed from both. That
composition is this module's whole job, and it is what this suite is about;
the arithmetic on top of it belongs to `test_engagement`.

What is injected is the client factory, so the SDK's request path stays real
and only its answers are written. Whether that path reaches PagerDuty correctly
is proven in the e2e stack.
"""

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
                    client_of=_a_factory_recording_into(a_client_was_asked_for))
            )
        ) \
        .then(
            all_of(
                _the_source_said_it_could_not_be_read(),
                _no_client_was_built(a_client_was_asked_for)
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


def _settings_with(api_key: str) -> Settings:
    return Settings(pagerduty_api_key=api_key)


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


class _NoSuchUser(PagerDutyError):
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
            raise _NoSuchUser(f"no such user: {responder}")

        return users[responder]

    client = Mock(rget=Mock(side_effect=rget))

    return lambda *dont_care_args, **dont_care_kwargs: client


def _a_factory_recording_into(kept: Kept[bool]) -> Any:
    def factory(*dont_care_args: Any, **dont_care_kwargs: Any) -> Any:
        kept.take(True)

        raise AssertionError(
            "A client was built for a deployment holding no credential."
        )

    return factory


def _the_source_said_it_could_not_be_read() -> Assertion[Any]:
    def assertion(error: Any) -> bool:
        if not isinstance(error, OnCallUnavailable):
            raise AssertionError(
                f"Expected the source to report that it could not be read, but "
                f"what came back was {error!r}."
            )

        return True

    return assertion


def _no_client_was_built(kept: Kept[bool]) -> Assertion[Any]:
    def assertion(dont_care_error: Any) -> bool:
        if kept.taken:
            raise AssertionError(
                "Expected no request to be prepared without a credential, but a "
                "client was built."
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


