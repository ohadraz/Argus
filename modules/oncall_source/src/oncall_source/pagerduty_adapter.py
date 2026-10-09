"""The one place PagerDuty is known by name.

The provider is read through its own SDK rather than a hand-built request, so
what a suite exercises is what a real account would: the library's request
building, its authentication header, its error vocabulary. Aiming it is one
setting - the seam sits *below* the SDK, exactly as it does for the Anthropic
and Stripe clients - which is what makes `pagerduty_double` a stand-in rather
than a second implementation.

Nothing above this module imports `pagerduty`, and nothing above it sees a
PagerDuty error: a provider that cannot be read leaves here as
`OnCallUnavailable`, which is the vocabulary the rest of Argus answers in.

One thing the SDK will not do is speak plain HTTP - it refuses any base URL
that is not `https://`. That is right for a real account and is why the double
answers TLS, with a certificate it mints at startup; whether that certificate
is checked is a setting, true everywhere but against the double.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, Final

from argus_core import parse_iso
from argus_core.models import ReportChannel
from pagerduty import Error as PagerDutyError
from pagerduty import RestApiV2Client

from oncall_source.engagement import (
    Acknowledgement,
    OnCallSettings,
    OnCallUnavailable,
    ReportedIncident,
)
from oncall_source.pagerduty_webhooks import read_delivery
from oncall_source.platform import Delivery

logger = logging.getLogger(__name__)

# How a client is built. Injected rather than constructed outright so that a
# test can assert the case that matters most here - that a deployment holding
# no credential builds nothing at all - without a network, and without
# monkeypatching a name this module imported.
type ClientOf = Callable[..., RestApiV2Client]

# The resources this reads. Paths rather than URLs: the client joins them to
# whichever base address it was built with, which is the whole point of aiming
# that address at the double. Two of them, because a title is held on the person
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

# What a person's resolution needs. The keys an incident carries are its alerts'
# - one per alert, several once incidents were merged into it, since their
# alerts move with them. The incident list is asked by key, which PagerDuty
# matches against those same alert keys, resolved incidents included.
ALERTS_OF_AN_INCIDENT: Final = "/incidents/{incident_id}/alerts"
ALERT_KEY: Final = "alert_key"
INCIDENT_LIST: Final = "/incidents"
INCIDENT_KEY: Final = "incident_key"

# Where what a person wrote when they resolved the incident is kept: among the
# incident's notes, as one more note, marked only by the prefix PagerDuty writes
# into it. See `resolution_note` for why that prefix is relied on.
NOTES_ON_AN_INCIDENT: Final = "/incidents/{incident_id}/notes"
CONTENT: Final = "content"
RESOLUTION_NOTE_PREFIX: Final = "Resolution Note: "


class PagerDuty:
    """The on-call platform, when it is PagerDuty.

    Holds what each question needs and asks it through the functions below,
    which are where PagerDuty's API is known. Built only for a deployment that
    holds a key - see `pagerduty_from`.

    The webhook secret is given separately from the reading credential because
    only the process receiving deliveries holds it: the worker reads PagerDuty
    and never hears from it.
    """

    def __init__(self,
                 settings: OnCallSettings,
                 webhook_secret: str,
                 client_of: ClientOf = RestApiV2Client) -> None:
        self._settings = settings
        self._webhook_secret = webhook_secret
        self._client_of = client_of

    @property
    def channel(self) -> ReportChannel:
        return ReportChannel.PAGERDUTY

    def read_delivery(self, body: bytes, headers: Mapping[str, str]) -> Delivery:
        return read_delivery(body, headers, self._webhook_secret)

    def keys_of(self, platform_incident: str) -> list[str]:
        return keys_of(platform_incident, self._settings, self._client_of)

    def incident_for(self, keys: Iterable[str]) -> str | None:
        return incident_for(keys, self._settings, self._client_of)

    def resolution_note(self, platform_incident: str) -> str | None:
        return resolution_note(platform_incident, self._settings, self._client_of)

    def reported_incident(self, platform_incident: str) -> ReportedIncident:
        return reported_incident(platform_incident, self._settings, self._client_of)


def pagerduty_from(settings: OnCallSettings,
                   webhook_secret: str,
                   client_of: ClientOf = RestApiV2Client) -> PagerDuty | None:
    """PagerDuty as the on-call platform, or `None` where the deployment has none.

    PagerDuty is optional - Grafana alone is enough to run Argus - and a
    deployment holding no key has no on-call platform at all. `None` is how that
    reaches every caller, and nothing is built on the way to saying it.
    """
    if not settings.pagerduty_api_key:
        return None

    return PagerDuty(settings, webhook_secret, client_of)


def keys_of(incident_id: str,
            settings: OnCallSettings,
            client_of: ClientOf = RestApiV2Client) -> list[str]:
    """The keys the incident's senders stamped on it: each alert's key.

    Raises `OnCallUnavailable` when the alerts cannot be read, which is a
    different answer from an incident carrying none.
    """
    alerts = _read(_the_client(settings, client_of),
                   ALERTS_OF_AN_INCIDENT.format(incident_id=incident_id))

    return [str(alert[ALERT_KEY]) for alert in alerts if alert.get(ALERT_KEY)]


def incident_for(keys: Iterable[str],
                 settings: OnCallSettings,
                 client_of: ClientOf = RestApiV2Client) -> str | None:
    """The incident carrying any of these keys, or `None` where none does.

    One request per key, in order, until one finds an incident: Argus holds one
    or two keys for an incident, and the list endpoint takes one at a time.
    """
    client = _the_client(settings, client_of)

    for key in keys:
        found = _read(client, INCIDENT_LIST, params={INCIDENT_KEY: key})

        if found:
            return str(found[0][_ID])

    return None


def resolution_note(incident_id: str,
                    settings: OnCallSettings,
                    client_of: ClientOf = RestApiV2Client) -> str | None:
    """What the person wrote when they resolved the incident, or `None`.

    PagerDuty has no field linking a resolution to its note. The resolve log
    entry carries no note; the note is a separate note on the incident, like
    any written while it was going on; and the webhook carries neither. What
    marks it is the prefix PagerDuty writes into it, and that is what this
    relies on - as PagerDuty's own community manager recommends (May 2025),
    calling the missing field a logged bug with no timeline (Feb 2026):
    https://community.pagerduty.com/ask-a-product-question-2/i-am-interested-in-a-report-or-list-of-all-of-my-incident-resolution-notes-624
    https://community.pagerduty.com/ask-a-product-question-2/unable-to-retrieve-resolution-note-for-an-automated-incident-workflow-step-842

    Not "the latest note", the workaround that second thread accepted: resolved
    without a note, it would present something written mid-incident as what the
    person said when they ended it. The prefix is undocumented wording, and if
    PagerDuty changes it this finds no note - never a wrong one.

    The prefix is PagerDuty's, not the person's, so it is not part of what they
    said.
    """
    notes = _read(_the_client(settings, client_of),
                  NOTES_ON_AN_INCIDENT.format(incident_id=incident_id))

    for note in notes:
        content = str(note.get(CONTENT) or "")

        if content.startswith(RESOLUTION_NOTE_PREFIX):
            return content.removeprefix(RESOLUTION_NOTE_PREFIX).strip() or None

    return None


def _the_client(settings: OnCallSettings, client_of: ClientOf) -> RestApiV2Client:
    """A client aimed where the settings say, holding their credential."""
    return client_of(
        settings.pagerduty_api_key,
        verify=settings.pagerduty_verify_tls,
        **({"base_url": settings.pagerduty_base_url}
           if settings.pagerduty_base_url
           else {})
    )


def _read(client: RestApiV2Client, path: str, **request: Any) -> Any:
    """One resource, or `OnCallUnavailable` in Argus's words."""
    try:
        return client.rget(path, **request)
    except PagerDutyError as error:
        raise OnCallUnavailable(f"the on-call provider could not be read: {error}") from error


def reported_incident(incident_id: str,
                      settings: OnCallSettings,
                      client_of: ClientOf = RestApiV2Client) -> ReportedIncident:
    """One incident as the on-call provider holds it.

    Raises `OnCallUnavailable` for anything the provider fails to answer, and
    for a deployment holding no credential at all. The distinction the caller
    needs is between "nobody acknowledged it" and "nobody could say", and an
    exception is the only way a reading can say the second.
    """

    if not settings.pagerduty_api_key:
        raise OnCallUnavailable(
            "no on-call credential is configured, so who responded cannot be "
            "read"
        )

    client = _the_client(settings, client_of)
    reported = _read(client, _AN_INCIDENT.format(incident_id=incident_id))

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
        logger.warning("job title unreadable", exc_info=True,
                       extra={"responder_id": responder_id})
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
