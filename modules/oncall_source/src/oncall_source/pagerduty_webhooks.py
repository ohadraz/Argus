"""What PagerDuty delivers to Argus, parsed only once PagerDuty is proven to have
sent it.

PagerDuty's V3 webhooks: a JSON body whose `event` names what happened, signed
with an HMAC-SHA256 of the raw body under the subscription's secret. Nothing
here reaches PagerDuty's API, so this is pure and takes the secret as given;
the adapter that does reach it composes this.

Which "resolved" counts is decided here, because only this module can tell a
person from an integration - and the order of that decision matters. Each rule
below says why it answers as it does.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, Final

from oncall_source.platform import (
    Delivery,
    Irrelevant,
    Merged,
    OnCallDeliveryUnverified,
    Reopened,
    ResolvedByAPerson,
    ResolvedWithoutAPerson,
)

# Where PagerDuty puts its signature, and how it versions each one. During a
# secret rotation it carries several, comma-separated.
SIGNATURE_HEADER: Final = "X-PagerDuty-Signature"
SIGNATURE_VERSION: Final = "v1="
_SIGNATURES_ARE_SEPARATED_BY: Final = ","

# The envelope: everything is under `event`, which names what happened, who did
# it, and the incident it happened to.
EVENT: Final = "event"
EVENT_TYPE: Final = "event_type"
AGENT: Final = "agent"
DATA: Final = "data"

# A reference to anything - an agent, an incident - and the one field read off
# an incident delivery's data beside its id.
ID: Final = "id"
TYPE: Final = "type"
SUMMARY: Final = "summary"
INCIDENT: Final = "incident"
RESOLVE_REASON: Final = "resolve_reason"

# The events read. Every other one is irrelevant.
RESOLVED_EVENT: Final = "incident.resolved"
REOPENED_EVENT: Final = "incident.reopened"

# The agent a person is. Anything else that acts on an incident - the monitor's
# integration, a service - is not one.
USER_AGENT: Final = "user_reference"

# Why an incident resolved when it was merged into another.
MERGE_RESOLVE_REASON: Final = "merge_resolve_reason"


def parse_delivery(body: bytes, headers: Mapping[str, str], secret: str) -> Delivery:
    """What one webhook delivery says, in Argus's words.

    Raises `OnCallDeliveryUnverified` unless the body is signed with `secret`,
    before any of it is parsed.
    """
    _verify(body, headers, secret)

    event = json.loads(body)[EVENT]
    event_type = str(event[EVENT_TYPE])
    data = event[DATA]
    incident = str(data[ID])

    if event_type == REOPENED_EVENT:
        return Reopened(platform_incident=incident)

    if event_type != RESOLVED_EVENT:
        return Irrelevant(event=event_type)

    return _a_resolution(incident, event.get(AGENT), data.get(RESOLVE_REASON))


def _a_resolution(incident: str,
                  agent: Mapping[str, Any] | None,
                  resolve_reason: Mapping[str, Any] | None) -> Delivery:
    """Who or what resolved the incident, which decides whether it counts.

    Checked in this order, and the order is the rule:

    1. A merge first. PagerDuty resolves a merged incident and credits it to
       the person who merged it, so asked "was it a person?" first, a merge
       would end an incident that only moved. Its alerts went to the target,
       where a later resolution finds them.
    2. A person: someone with the world in hand said it is over, and is owed
       the account.
    3. Anything else - the monitor's integration clearing its alert, which is a
       metrics signal Argus reads for itself, or nothing named at all, which is
       PagerDuty's own sign of automation or a timeout. Nobody decided.
    """
    if resolve_reason and resolve_reason.get(TYPE) == MERGE_RESOLVE_REASON:
        return Merged(platform_incident=incident,
                      into=str(resolve_reason[INCIDENT][ID]))

    if agent and agent.get(TYPE) == USER_AGENT:
        return ResolvedByAPerson(platform_incident=incident, by=str(agent[SUMMARY]))

    return ResolvedWithoutAPerson(
        platform_incident=incident,
        resolved_by=str(agent[SUMMARY]) if agent and agent.get(SUMMARY) else None
    )


def _verify(body: bytes, headers: Mapping[str, str], secret: str) -> None:
    """Refuses a body no signature of `secret` covers.

    An empty secret refuses everything: it is a deployment that never set one,
    and anybody can sign under it. Each signature is compared in constant time,
    so how long a refusal takes says nothing about how close a guess was.
    """
    if not secret:
        raise OnCallDeliveryUnverified(
            "no webhook secret is configured, so no delivery can be trusted"
        )

    expected = SIGNATURE_VERSION + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    stated = _the_header(headers, SIGNATURE_HEADER)
    signatures = stated.split(_SIGNATURES_ARE_SEPARATED_BY) if stated else []

    if not any(hmac.compare_digest(expected, signature.strip()) for signature in signatures):
        raise OnCallDeliveryUnverified("the delivery's signature does not match its body")


def _the_header(headers: Mapping[str, str], name: str) -> str | None:
    """One header, however the server that received it cased the name.

    HTTP header names are case-insensitive, and a web framework's mapping may
    hand them over lower-cased.
    """
    wanted = name.lower()

    return next((value for key, value in headers.items() if key.lower() == wanted), None)
