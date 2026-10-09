from __future__ import annotations

import hashlib
import logging
from typing import Any, Final
from urllib.parse import urlsplit

from argus_core.models import NOTIFICATION_KEY, AlarmClaim, Alert, Reference

logger = logging.getLogger(__name__)

# Whose names for an incident this parser records.
GRAFANA_SOURCE: Final = "grafana"

# Where Grafana puts the key of the alert group a notification is about: on the
# envelope, not on any one alert.
_GROUP_KEY: Final = "groupKey"

# How a list of cache keys is written into a single annotation. Grafana carries
# annotations as text, so a check reporting many entries renders them as one
# string - and this is the character it renders between them.
_KEYS_ARE_SEPARATED_BY: Final = ","

# The annotation a rule says what it looked at in.
#
# Public and named, unlike the four annotations read below it, because this one
# is a convention two parties keep rather than a field this parser happens to
# want: a rule in the estate writes it and this module reads it, and a spelling
# restated in both places is a fact that drifts the moment one is corrected.
# Its *values* need no constants of their own - they are `AlarmClaim`'s members,
# declared once where the field they fill is declared.
CLAIM_ANNOTATION: Final = "claim"

# What Grafana calls an alert whose rule has stopped firing.
_RESOLVED: Final = "resolved"

# Where in a link to a rule Grafana puts its uid: after this, past the source
# segment below where there is one.
_THE_ALERTING_PATH: Final = "/alerting/"
# The source segment Grafana's releases put before a managed rule's uid.
_GRAFANA_MANAGED: Final = "grafana"


def parse_grafana_alert(raw_payload: dict[str, Any]) -> Alert:
    """Deterministic parser for Grafana's unified-alerting webhook format -
    plain field mapping, no LLM call (design.md Non-Goals; spec §7.9/§25
    tracks generic/LLM-based ingestion as separate future work)."""
    alerts = raw_payload["alerts"]
    # The first alert still firing. A notification carries every alert of its
    # group, a resolved one can come first, and a resolution never starts an
    # incident.
    alert = next(
        (each for each in alerts if each.get("status") != _RESOLVED), alerts[0]
    )
    labels = alert["labels"]
    annotations = alert.get("annotations", {})
    return Alert(
        service=labels["service"],
        alert_name=labels["alertname"],
        severity=labels.get("severity"),
        summary=annotations.get("summary"),
        started_at=alert.get("startsAt"),
        # An annotation rather than a label, because Grafana's labels are the
        # alert's identity and a timestamp in one would make every firing a
        # different alert. Absent from almost every payload, and left unset
        # rather than defaulted to `startsAt`: an onset invented here would be
        # a measured minute's rival carrying none of its evidence, and would
        # be the minute somebody noticed rather than the minute it began.
        stated_onset=annotations.get("onset"),
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
        stale_entry_keys=_the_keys_listed_in(annotations.get("stale_entry_keys")),
        stale_entries_found=annotations.get("stale_entries_found"),
        # The link to the rule, which is the only place the webhook names it:
        # Grafana's payload has no field for the rule that fired.
        rule=_the_rule_linked_from(alert.get("generatorURL")),
        references=_the_names_grafana_pages_with(raw_payload.get(_GROUP_KEY))
    )


def reports_only_resolutions(raw_payload: dict[str, Any]) -> bool:
    """Whether a webhook says only that rules stopped firing.

    Grafana sends one when a rule resolves. It is never the start of an
    incident, and whether a rule has stopped firing is read from the rule.

    One carrying no alerts at all answers the same way - nothing in it is
    firing - though Grafana never sends one, so it is said.
    """
    alerts = raw_payload.get("alerts", [])

    if not alerts:
        logger.warning("notification carried no alerts")

    return all(alert.get("status") == _RESOLVED for alert in alerts)


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

    _, found, rest = urlsplit(generator_url).path.partition(_THE_ALERTING_PATH)
    segments = [segment for segment in rest.split("/") if segment]

    if segments[:1] == [_GRAFANA_MANAGED]:
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

    return tuple(listed.split(_KEYS_ARE_SEPARATED_BY))
