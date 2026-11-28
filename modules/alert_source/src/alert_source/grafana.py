"""Grafana as a sender of alerts: its unified-alerting webhook, read into
Argus's own `Alert`, and the only module that knows that webhook's shape."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import urlsplit

from core.models import ALERT_FIRING, NOTIFICATION_KEY, AlarmClaim, Alert, Reference

from alert_source.failures import AlertUnreadable
from alert_source.port import OnlyResolved

logger = logging.getLogger(__name__)

# Whose names for an incident this parser records.
GRAFANA_SOURCE: Final = "grafana"

# Grafana's words for its webhook, each named for the field that carries it.
# Public because whatever writes a notification as Grafana does - the suites'
# stand-ins - has to spell them as this module reads them, and a spelling
# restated in two places drifts the moment one is corrected.

# On the envelope: the alerts the notification carries, and the key of the
# alert group it is about.
ALERTS: Final = "alerts"
GROUP_KEY: Final = "groupKey"

# On each alert: whether it is firing, its labels and annotations, its identity,
# the moment this firing of it began, and the link to the rule that fired it.
STATUS: Final = "status"
LABELS: Final = "labels"
ANNOTATIONS: Final = "annotations"
FINGERPRINT: Final = "fingerprint"
STARTS_AT: Final = "startsAt"
GENERATOR_URL: Final = "generatorURL"

# What Grafana calls an alert whose rule has stopped firing.
RESOLVED: Final = "resolved"

# The labels an alert is read by. Grafana's labels are the alert's identity.
SERVICE_LABEL: Final = "service"
ALERT_NAME_LABEL: Final = "alertname"
SEVERITY_LABEL: Final = "severity"

# The annotations an alert is read by.
#
# Every one of them is a convention two parties keep rather than a field this
# parser happens to want: a rule in the estate writes it and this module reads
# it. The claim's *values* need no constants of their own - they are
# `AlarmClaim`'s members, declared once where the field they fill is declared.
SUMMARY_ANNOTATION: Final = "summary"
ONSET_ANNOTATION: Final = "onset"
CLAIM_ANNOTATION: Final = "claim"
STALE_ENTRY_KEYS_ANNOTATION: Final = "stale_entry_keys"
STALE_ENTRIES_FOUND_ANNOTATION: Final = "stale_entries_found"

# How a list of cache keys is written into a single annotation. Grafana carries
# annotations as text, so a check reporting many entries renders them as one
# string - and this is the character it renders between them.
KEYS_ARE_SEPARATED_BY: Final = ","

# Where in a link to a rule Grafana puts its uid: after this, past the source
# segment below where there is one.
THE_ALERTING_PATH: Final = "/alerting/"
# The source segment Grafana's releases put before a managed rule's uid.
GRAFANA_MANAGED: Final = "grafana"

# Between the two halves of a firing's name. A character neither a fingerprint
# (hex) nor a timestamp (RFC 3339) carries.
_FIRING_SEPARATOR: Final = "@"


class GrafanaAlerts:
    """Grafana, as a sender of alerts.

    Holds nothing: Grafana's webhook is not signed here, so a delivery is read
    for what it says and nothing proves who said it - the route it arrives on
    is the deployment's to keep private. Built where the web application is
    wired, and handed on typed as `AlertSource`.
    """

    def parse_delivery(self, body: bytes, headers: Mapping[str, str], /) -> Alert | OnlyResolved:
        """What one notification says: the first alert still firing in it, or
        that it carries only resolutions.

        Anything that is not a notification in Grafana's shape - not JSON, not
        an object, alerts that are not a list of objects, an alert missing a
        field the `Alert` needs - is `AlertUnreadable`, saying what was wrong as
        the error that found it."""
        try:
            payload = json.loads(body)

            if not isinstance(payload, dict):
                raise TypeError(f"a notification is a JSON object, not a {type(payload).__name__}")

            if reports_only_resolutions(payload):
                return OnlyResolved()

            return parse_grafana_alert(payload)
        # `AttributeError` too: alerts that are a string, or a list of strings,
        # meet `.get` on something that is no object.
        except (AttributeError, LookupError, TypeError, ValueError) as unreadable:
            raise AlertUnreadable(repr(unreadable)) from unreadable


def parse_grafana_alert(raw_payload: dict[str, Any]) -> Alert:
    """Deterministic parser for Grafana's unified-alerting webhook format -
    plain field mapping, no LLM call (spec §25 tracks generic, LLM-based
    ingestion as one more sender behind the same port)."""
    alerts = raw_payload[ALERTS]
    # The first alert still firing. A notification carries every alert of its
    # group, a resolved one can come first, and a resolution never starts an
    # incident.
    alert = next(
        (each for each in alerts if each.get(STATUS) != RESOLVED), alerts[0]
    )
    labels = alert[LABELS]
    annotations = alert.get(ANNOTATIONS, {})
    return Alert(
        service=labels[SERVICE_LABEL],
        alert_name=labels[ALERT_NAME_LABEL],
        severity=labels.get(SEVERITY_LABEL),
        summary=annotations.get(SUMMARY_ANNOTATION),
        started_at=alert.get(STARTS_AT),
        # An annotation rather than a label, because Grafana's labels are the
        # alert's identity and a timestamp in one would make every firing a
        # different alert. Absent from almost every payload, and left unset
        # rather than defaulted to `startsAt`: an onset invented here would be
        # a measured minute's rival carrying none of its evidence, and would
        # be the minute somebody noticed rather than the minute it began.
        stated_onset=annotations.get(ONSET_ANNOTATION),
        # What the rule looked at, which decides whether a window holding no
        # departure contradicts this alarm or says nothing about it.
        #
        # Read from the rule rather than worked out here, and the two things it
        # is not derived from are worth naming. Not whether an onset came with
        # it: a check can find a disagreement it cannot date, and such an alert
        # is indistinguishable from a threshold rule that stated nothing. Not
        # `alertname` either, which would be a table every rule in the estate
        # has to join and would read a rule named after its service by its
        # spelling.
        claim=_the_claim_in(annotations.get(CLAIM_ANNOTATION)),
        # Annotations, for the reason the onset is one, and carried as text
        # because an annotation is all Grafana has: a check templating its
        # finding into an alert writes a list, not a structure.
        #
        # Split on a comma, which is what such a template produces - and a key
        # holding one would split into two addresses that look exactly as real
        # as the rest. Nothing here can tell the difference, so nothing here
        # tries: the count travels beside the keys and the alert refuses itself
        # when the two disagree, which catches a bad split and a truncated list
        # with one rule.
        stale_entry_keys=_the_keys_listed_in(annotations.get(STALE_ENTRY_KEYS_ANNOTATION)),
        stale_entries_found=annotations.get(STALE_ENTRIES_FOUND_ANNOTATION),
        # The link to the rule, which is the only place the webhook names it:
        # Grafana's payload has no field for the rule that fired.
        rule=_the_rule_linked_from(alert.get(GENERATOR_URL)),
        references=(*_the_names_grafana_pages_with(raw_payload.get(GROUP_KEY)),
                    *_the_firings_in(alerts))
    )


def reports_only_resolutions(raw_payload: dict[str, Any]) -> bool:
    """Whether a webhook says only that rules stopped firing.

    Grafana sends one when a rule resolves. It is never the start of an
    incident, and whether a rule has stopped firing is read from the rule.

    One carrying no alerts at all answers the same way - nothing in it is
    firing - though Grafana never sends one, so it is said.
    """
    alerts = raw_payload.get(ALERTS, [])

    if not alerts:
        logger.warning("notification carried no alerts")

    return all(alert.get(STATUS) == RESOLVED for alert in alerts)


def _the_rule_linked_from(generator_url: str | None) -> str | None:
    """The rule uid in a link to a Grafana-managed rule, or `None`.

    The uid is the segment after `/alerting/`, past the `grafana/` that names
    the rule's source where the link carries one: Grafana's releases build
    `.../alerting/grafana/<uid>/view`, and its documentation shows
    `.../alerting/<uid>/edit`. Whatever follows the uid is not read. A link with
    no `/alerting/` in it names no rule this can read.
    """
    if not generator_url:
        return None

    _, found, rest = urlsplit(generator_url).path.partition(THE_ALERTING_PATH)
    segments = [segment for segment in rest.split("/") if segment]

    if segments[:1] == [GRAFANA_MANAGED]:
        segments = segments[1:]

    return segments[0] if found and segments else None


def _the_names_grafana_pages_with(group_key: str | None) -> tuple[Reference, ...]:
    """What Grafana will call this incident to a paging tool, or nothing.

    The SHA-256 of the group's key, in hex - Grafana's own `Key.Hash()`, which
    every integration it pages through is sent "as integrations may have
    maximum length requirements". Recorded as the hash rather than the key
    because the hash is what a paging tool hands back: observed against a real
    Grafana, whose PagerDuty incident carried exactly this as its alert key.

    Nothing without a group key: a sender shaped like Grafana without being it
    pages no tool with one.
    """
    if not group_key:
        return ()

    return (Reference(
        source=GRAFANA_SOURCE,
        kind=NOTIFICATION_KEY,
        value=hashlib.sha256(group_key.encode()).hexdigest()
    ),)


def _the_firings_in(alerts: list[dict[str, Any]]) -> tuple[Reference, ...]:
    """Every firing the notification carries, as the names a later
    notification about the same alerts will carry again.

    A firing is an alert's fingerprint - Grafana's identity for it, a hash of
    its labels - and the moment this firing of it started. The group key
    cannot tell one firing from the next, because every firing of the group
    pages under it; this pair can, and Grafana repeats it on every reminder
    while the alert is still firing, in whatever order it lists the group's
    alerts. Resolved alerts are named too: each is still a firing the incident
    knew.

    Spelled as Grafana sent both halves, never normalised, because it is
    matched against what Grafana sends next. An alert with no fingerprint
    names no firing: a start alone is shared by every alert that began in the
    same second.
    """
    return tuple(
        Reference(
            source=GRAFANA_SOURCE,
            kind=ALERT_FIRING,
            value=f"{alert[FINGERPRINT]}{_FIRING_SEPARATOR}{alert.get(STARTS_AT, '')}"
        )
        for alert in alerts
        if alert.get(FINGERPRINT)
    )


def _the_claim_in(stated: str | None) -> AlarmClaim:
    """The kind of claim one annotation names, or the one a silence means.

    An absent annotation and a value no member spells answer the same way, and
    that is one judgement rather than two conveniences. Argus is not the only
    thing writing rules against this estate, so a vocabulary it does not
    recognise is an ordinary rule from somewhere else - and the series reading is
    what such a rule almost certainly is.

    Answered rather than refused for the same reason the onset is defaulted and
    not demanded: an alert rejected at this boundary is an incident nobody is
    told about, which is a worse failure than one read conservatively.
    """
    if stated is None:
        return AlarmClaim.A_SERIES_CONDITION

    try:
        return AlarmClaim(stated)
    except ValueError:
        logger.warning("unknown claim annotation", extra={"claim": stated})
        return AlarmClaim.A_SERIES_CONDITION


def _the_keys_listed_in(listed: str | None) -> tuple[str, ...] | None:
    """The keys one annotation names, or `None` where it named none.

    `None` rather than an empty tuple for an absent annotation, exactly as the
    onset is left unset: almost no alert is about a cache, and an empty tuple
    would say a check compared one against its records and found everything in
    order - a claim no ordinary alert makes and one a reader would act on.

    An annotation that is present and empty answers `None` too, and that is the
    same judgement rather than a convenience. A template that rendered nothing
    produced no keys, and the alternative is a single empty-string key, which is
    an address.
    """
    if not listed:
        return None

    return tuple(listed.split(KEYS_ARE_SEPARATED_BY))
