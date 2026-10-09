"""Reading what PagerDuty tells Argus about an incident, and refusing what it
did not sign.

Two jobs, both of them the adapter's alone. The first is trust: a delivery is
read only once its signature says PagerDuty sent it, because what it can say -
"a person resolved this" - ends an incident. The second is translation into
Argus's words, and the rule this suite exists for: only a person's resolution
counts, and a merge is not one, though PagerDuty credits it to whoever merged.

The payloads are PagerDuty's V3 shape as a real account sent them (the spike of
2026-10-09), trimmed to the fields read.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, an_error_was_raised, attempting
from oncall_source.pagerduty_webhooks import (
    AGENT,
    DATA,
    EVENT,
    EVENT_TYPE,
    ID,
    INCIDENT,
    MERGE_RESOLVE_REASON,
    REOPENED_EVENT,
    RESOLVE_REASON,
    RESOLVED_EVENT,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION,
    SUMMARY,
    TYPE,
    USER_AGENT,
    read_delivery,
)
from oncall_source.platform import (
    Delivery,
    DeliveryUnverified,
    Irrelevant,
    Merged,
    Reopened,
    ResolvedByAPerson,
    ResolvedWithoutAPerson,
)

SOME_SECRET = "some-signing-secret"
SOME_INCIDENT = "Q2FJZEW25HFSAW"

# What PagerDuty names the integration a monitor resolves through. A value from
# the vendor rather than of Argus's, and read back only as a description.
AN_INTEGRATION_AGENT = "inbound_integration_reference"


@pytest.mark.unit
def test_a_delivery_signed_with_the_secret_is_read() -> None:
    some_delivery = _a_resolution(agent=_a_person("some person"))

    Scenario() \
        .given(some_delivery) \
        .when(lambda: read_delivery(some_delivery, _signed(some_delivery), SOME_SECRET)) \
        .then(_it_reads_as(ResolvedByAPerson(platform_incident=SOME_INCIDENT,
                                             by="some person")))


@pytest.mark.unit
def test_a_delivery_signed_with_another_secret_is_refused() -> None:
    # What a forged "a person resolved this" looks like. Read, it would end an
    # incident nobody ended.
    some_delivery = _a_resolution(agent=_a_person("some person"))

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: read_delivery(
            some_delivery, _signed(some_delivery, secret="some-other-secret"), SOME_SECRET
        ))) \
        .then(an_error_was_raised(DeliveryUnverified))


@pytest.mark.unit
def test_a_delivery_with_no_signature_is_refused() -> None:
    some_delivery = _a_resolution(agent=_a_person("some person"))

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: read_delivery(some_delivery, {}, SOME_SECRET))) \
        .then(an_error_was_raised(DeliveryUnverified))


@pytest.mark.unit
def test_with_no_secret_configured_every_delivery_is_refused() -> None:
    # An empty secret is a deployment that never set one, not a key anybody
    # holds - and anybody can compute a signature under it.
    no_secret = ""
    some_delivery = _a_resolution(agent=_a_person("some person"))

    Scenario() \
        .given(some_delivery) \
        .when(attempting(lambda: read_delivery(
            some_delivery, _signed(some_delivery, secret=no_secret), no_secret
        ))) \
        .then(an_error_was_raised(DeliveryUnverified))


@pytest.mark.unit
def test_a_delivery_signed_during_a_secret_rotation_is_read() -> None:
    # While a secret is being rotated PagerDuty signs with both, comma-separated,
    # and either one being Argus's is enough.
    some_delivery = _a_resolution(agent=_a_person("some person"))
    signed_with_both = {SIGNATURE_HEADER: ",".join([
        _signature(some_delivery, "the-retiring-secret"),
        _signature(some_delivery, SOME_SECRET)
    ])}

    Scenario() \
        .given(some_delivery) \
        .when(lambda: read_delivery(some_delivery, signed_with_both, SOME_SECRET)) \
        .then(_it_reads_as(ResolvedByAPerson(platform_incident=SOME_INCIDENT,
                                             by="some person")))


@pytest.mark.unit
def test_a_resolution_by_the_monitors_integration_is_not_a_persons() -> None:
    # The monitor cleared its alert, which is a metrics signal - and Argus reads
    # recovery from the metrics itself. Nobody decided the incident was over.
    some_integration = "Events API V2"
    some_delivery = _a_resolution(agent={TYPE: AN_INTEGRATION_AGENT,
                                         SUMMARY: some_integration})

    Scenario() \
        .given(some_delivery) \
        .when(lambda: read_delivery(some_delivery, _signed(some_delivery), SOME_SECRET)) \
        .then(_it_reads_as(ResolvedWithoutAPerson(platform_incident=SOME_INCIDENT,
                                                  resolved_by=some_integration)))


@pytest.mark.unit
def test_a_resolution_naming_nobody_is_not_a_persons() -> None:
    # PagerDuty's own reading of a missing agent: automation, or a timeout.
    # Either way, nobody decided anything.
    some_delivery = _a_resolution(agent=None)

    Scenario() \
        .given(some_delivery) \
        .when(lambda: read_delivery(some_delivery, _signed(some_delivery), SOME_SECRET)) \
        .then(_it_reads_as(ResolvedWithoutAPerson(platform_incident=SOME_INCIDENT,
                                                  resolved_by=None)))


@pytest.mark.unit
def test_a_merge_is_not_a_resolution_though_a_person_made_it() -> None:
    # The trap the merge spike found. PagerDuty resolves the merged incident and
    # credits the person who merged it - so read as a resolution, a merge would
    # end an incident that only moved. Its alerts went with it to the target.
    some_target = "Q0N5RRK7RT1Q46"
    some_delivery = _a_resolution(
        agent=_a_person("some person"),
        resolve_reason={TYPE: MERGE_RESOLVE_REASON, INCIDENT: {ID: some_target}}
    )

    Scenario() \
        .given(some_delivery) \
        .when(lambda: read_delivery(some_delivery, _signed(some_delivery), SOME_SECRET)) \
        .then(_it_reads_as(Merged(platform_incident=SOME_INCIDENT, into=some_target)))


@pytest.mark.unit
def test_a_reopened_incident_is_read_as_reopened() -> None:
    some_delivery = _a_delivery(REOPENED_EVENT, agent=_a_person("some person"))

    Scenario() \
        .given(some_delivery) \
        .when(lambda: read_delivery(some_delivery, _signed(some_delivery), SOME_SECRET)) \
        .then(_it_reads_as(Reopened(platform_incident=SOME_INCIDENT)))


@pytest.mark.unit
def test_any_other_event_is_irrelevant() -> None:
    # A note added mid-incident among them: answering those would be the
    # two-way conversation Argus does not hold.
    some_other_event = "incident.annotated"
    some_delivery = _a_delivery(some_other_event, agent=_a_person("some person"))

    Scenario() \
        .given(some_delivery) \
        .when(lambda: read_delivery(some_delivery, _signed(some_delivery), SOME_SECRET)) \
        .then(_it_reads_as(Irrelevant(event=some_other_event)))


def _a_person(name: str) -> dict[str, Any]:
    return {TYPE: USER_AGENT, SUMMARY: name}


def _a_resolution(agent: dict[str, Any] | None,
                  resolve_reason: dict[str, Any] | None = None) -> bytes:
    return _a_delivery(RESOLVED_EVENT, agent, resolve_reason)


def _a_delivery(event_type: str,
                agent: dict[str, Any] | None,
                resolve_reason: dict[str, Any] | None = None) -> bytes:
    """One webhook body, as the bytes PagerDuty signs."""
    return json.dumps({
        EVENT: {
            EVENT_TYPE: event_type,
            AGENT: agent,
            DATA: {ID: SOME_INCIDENT, RESOLVE_REASON: resolve_reason}
        }
    }).encode()


def _signature(body: bytes, secret: str) -> str:
    """PagerDuty's signature: an HMAC-SHA256 of the raw body, in hex, versioned."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    return f"{SIGNATURE_VERSION}{digest}"


def _signed(body: bytes, secret: str = SOME_SECRET) -> dict[str, str]:
    return {SIGNATURE_HEADER: _signature(body, secret)}


def _it_reads_as(expected: Delivery) -> Assertion[Delivery]:
    def assertion(read: Delivery) -> bool:
        if read != expected:
            raise AssertionError(f"Expected the delivery to read as {expected!r}, got {read!r}.")

        return True

    return assertion
