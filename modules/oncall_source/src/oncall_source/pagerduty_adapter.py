"""The one place PagerDuty is known by name.

The provider is read through its own SDK rather than a hand-built request, so
what the demo exercises is what a real account would: the library's request
building, its authentication header, its error vocabulary. Aiming it is one
setting - the seam sits *below* the SDK, exactly as it does for the Anthropic
and Stripe clients - which is what makes the Target Service's endpoints a
stand-in rather than a second implementation.

Nothing above this module imports `pagerduty`, and nothing above it sees a
PagerDuty error: a provider that cannot be read leaves here as
`OnCallUnavailable`, which is the vocabulary the rest of Argus answers in.

One thing the SDK will not do is speak plain HTTP - it refuses any base URL
that is not `https://`. That is right for a real account and is why the stand-in
answers TLS on a port of its own, with a certificate it mints at startup;
whether that certificate is checked is a setting, true everywhere but against
the demo on this machine.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Final

from argus_core.config import Settings, get_settings
from argus_core.timestamps import parse_iso
from pagerduty import Error as PagerDutyError
from pagerduty import RestApiV2Client

from oncall_source.engagement import (
    Acknowledgement,
    OnCallUnavailable,
    ReportedIncident,
)

# How a client is built. Injected rather than constructed outright so that a
# test can assert the case that matters most here - that a deployment holding
# no credential builds nothing at all - without a network, and without
# monkeypatching a name this module imported.
type ClientOf = Callable[..., RestApiV2Client]

# The resources this reads. Paths rather than URLs: the client joins them to
# whichever base address it was built with, which is the whole point of aiming
# that address at the demo. Two of them, because a title is held on the person
# and not on the acknowledgement they made.
_AN_INCIDENT: Final = "/incidents/{incident_id}"
_A_USER: Final = "/users/{responder_id}"

# How an incident is reported. `acknowledgements` carries one entry per
# acknowledgement - not per person - each naming when it happened and who made
# it, and PagerDuty publishes no matching moment for letting an incident go.
_ACKNOWLEDGEMENTS: Final = "acknowledgements"
_ACKNOWLEDGED_AT: Final = "at"
_ACKNOWLEDGER: Final = "acknowledger"
_ID: Final = "id"

# What a person is called, on the person. Free text an administrator typed:
# nothing here parses it, and whatever comes to price these minutes will have
# to match it rather than assume a taxonomy.
_JOB_TITLE: Final = "job_title"

# When the incident began and ended. `resolved_at` is absent from an incident
# that has not resolved, and `last_status_change_at` is the moment it last
# moved - which for an incident Argus is writing up is that same resolution.
_CREATED_AT: Final = "created_at"
_RESOLVED_AT: Final = "resolved_at"
_LAST_STATUS_CHANGE_AT: Final = "last_status_change_at"


def reported_incident(incident_id: str,
                      settings: Settings | None = None,
                      client_of: ClientOf = RestApiV2Client) -> ReportedIncident:
    """One incident as the on-call provider holds it.

    Raises `OnCallUnavailable` for anything the provider fails to answer, and
    for a deployment holding no credential at all. The distinction the caller
    needs is between "nobody acknowledged it" and "nobody could say", and an
    exception is the only way a reading can say the second.
    """
    settings = settings or get_settings()

    if not settings.pagerduty_api_key:
        raise OnCallUnavailable(
            "no on-call credential is configured, so who responded cannot be "
            "read"
        )

    client = client_of(
        settings.pagerduty_api_key,
        verify=settings.pagerduty_verify_tls,
        **({"base_url": settings.pagerduty_base_url}
           if settings.pagerduty_base_url
           else {})
    )

    try:
        reported = client.rget(_AN_INCIDENT.format(incident_id=incident_id))
    except PagerDutyError as error:
        raise OnCallUnavailable(
            f"the on-call provider could not be read: {error}"
        ) from error

    return _as_an_incident(reported, client)


def _as_an_incident(reported: Mapping[str, Any],
                    client: RestApiV2Client) -> ReportedIncident:
    """One incident as PagerDuty reported it, read into Argus's own object.

    Each acknowledgement costs a second request, for the title of the person
    who made it. One per acknowledgement rather than one per person: an
    incident carries one or two of them, and deduplicating here would put the
    rule about who counts as a responder in two places.

    An acknowledgement whose acknowledger the provider did not name is dropped
    rather than counted: it would be a responder nobody can tell apart from
    another, which is the one thing the count depends on.
    """
    return ReportedIncident(
        began_at=_began_at(reported),
        ended_at=_ended_at(reported),
        acknowledgements=[
            Acknowledgement(
                at=parse_iso(str(acknowledgement[_ACKNOWLEDGED_AT])),
                responder_id=str(acknowledgement[_ACKNOWLEDGER][_ID]),
                job_title=_title_held_by(
                    str(acknowledgement[_ACKNOWLEDGER][_ID]), client)
            )
            for acknowledgement in reported.get(_ACKNOWLEDGEMENTS, [])
            if acknowledgement.get(_ACKNOWLEDGER, {}).get(_ID)
        ]
    )


def _title_held_by(responder_id: str, client: RestApiV2Client) -> str | None:
    """What the provider calls this person, or nothing.

    Nothing covers both a person with no title on record and a lookup the
    provider refused, because neither can be printed and neither can be priced.
    Failing the whole reading over the second would throw away a measurement
    already made - somebody acknowledged this incident at a known moment - in
    exchange for a description.
    """
    try:
        user = client.rget(_A_USER.format(responder_id=responder_id))
    except PagerDutyError:
        return None

    title = user.get(_JOB_TITLE)

    return str(title) if title else None


def _began_at(reported: Mapping[str, Any]) -> datetime:
    """When the provider says the incident began.

    Carried rather than computed from: it is what makes the wait before anyone
    acknowledged legible to whoever reads a reported incident.
    """
    began_at = reported.get(_CREATED_AT)

    if not began_at:
        raise OnCallUnavailable(
            "the on-call provider reported an incident with no start, so what "
            "it says about the response cannot be placed against it"
        )

    return parse_iso(str(began_at))


def _ended_at(reported: Mapping[str, Any]) -> datetime:
    """When the provider says the incident ended.

    An incident being written up has ended, so one of these two is there. If
    neither is, the provider answered something this cannot measure a span
    against, and saying so is better than dating the incident from now.
    """
    ended_at = reported.get(_RESOLVED_AT) or reported.get(_LAST_STATUS_CHANGE_AT)

    if not ended_at:
        raise OnCallUnavailable(
            "the on-call provider reported an incident with no end, so how "
            "long anyone was on it cannot be read"
        )

    return parse_iso(str(ended_at))
