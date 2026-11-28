"""The alert source's port, as every sender of alerts answers it.

What the port promises, asked of each adapter over one thing sent, which each
is delivered written as its own sender writes it: the Grafana adapter over
Grafana's webhook (`framework.grafana_world`), and the double over Argus's own
alert (`alert_source_double`). A promise one keeps and the other does not fails
here, so the double cannot drift from the port, and the port names nothing only
Grafana's wire could answer.

The promises and nothing beyond them. Which alert of a group is read, a
resolved one beside a firing, a claim spelled as no member is, keys split on a
comma, a count that disagrees with its keys, the names Grafana pages with, and
a rule's link in either release's shape are the wire suite's
(`test_grafana.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from alert_source import AlertSource, AlertUnreadable, OnlyResolved
from alert_source.grafana import GrafanaAlerts
from alert_source_double import AlertsAsArgusWrites, Sent, a_delivery_of
from argus_testkit import Scenario, an_error_was_raised, attempting, the_answer_was
from core.models import NOTIFICATION_KEY, AlarmClaim, Alert, Reference

from alert_source_test.framework.grafana_world import as_grafana_sends

DONT_CARE_HEADERS: dict[str, str] = {}

AN_ALERT_SAYING_EVERYTHING = Alert(
    service="some-service",
    alert_name="SomeTotalsDisagree",
    severity="some-severity",
    summary="Some summary of what was found",
    started_at=datetime(2026, 11, 28, 9, 45, tzinfo=UTC),
    stated_onset=datetime(2026, 11, 21, 14, 10, tzinfo=UTC),
    claim=AlarmClaim.ITS_OWN_FINDING,
    stale_entry_keys=("some:key:1", "some:key:2"),
    stale_entries_found=2,
    rule="some-rule"
)

AN_ALERT_SAYING_LITTLE = Alert(service="some-service", alert_name="SomeAlert")

AN_ALERT_NAMING_A_REFERENCE = AN_ALERT_SAYING_LITTLE.model_copy(update={"references": (
    Reference(source="some-sender", kind=NOTIFICATION_KEY, value="some-key"),
)})


@dataclass(frozen=True)
class _Sender:
    """One row: a sender, and how what it is sent is written as it sends it."""

    source: AlertSource
    writes: Callable[[Sent], bytes]


EVERY_SENDER = pytest.mark.parametrize("sender", [
    pytest.param(_Sender(AlertsAsArgusWrites(), a_delivery_of), id="in-memory"),
    pytest.param(_Sender(GrafanaAlerts(), as_grafana_sends), id="grafana")
])


@pytest.mark.unit
@EVERY_SENDER
@pytest.mark.parametrize("sent", [
    pytest.param(AN_ALERT_SAYING_EVERYTHING, id="saying-everything"),
    pytest.param(AN_ALERT_SAYING_LITTLE, id="saying-little")
])
def test_an_alert_sent_is_the_alert_read(sender: _Sender, sent: Alert) -> None:
    # Saying little, what it leaves unsaid is read unsaid: absent where absent
    # means nothing, and the claim a silence means.
    Scenario() \
        .given(delivery := sender.writes(sent)) \
        .when(lambda: sender.source.parse_delivery(delivery, DONT_CARE_HEADERS)) \
        .then(the_answer_was(sent))


@pytest.mark.unit
@EVERY_SENDER
def test_a_delivery_of_resolutions_alone_is_only_resolved(sender: _Sender) -> None:
    Scenario() \
        .given(delivery := sender.writes(OnlyResolved())) \
        .when(lambda: sender.source.parse_delivery(delivery, DONT_CARE_HEADERS)) \
        .then(the_answer_was(OnlyResolved()))


@pytest.mark.unit
@EVERY_SENDER
@pytest.mark.parametrize("delivery", [
    pytest.param(b"\xff", id="not-text"),
    pytest.param(b"not json at all", id="not-json"),
    pytest.param(b"[]", id="a-list"),
    pytest.param(b'"some string"', id="a-string")
])
def test_a_delivery_not_in_the_sender_s_shape_is_unreadable(sender: _Sender,
                                                            delivery: bytes) -> None:
    # Unreadable, and never another error: the route that receives it refuses
    # the sender's input on this one failure alone.
    Scenario() \
        .when(attempting(lambda: sender.source.parse_delivery(delivery, DONT_CARE_HEADERS))) \
        .then(an_error_was_raised(AlertUnreadable))


@pytest.mark.unit
@pytest.mark.parametrize("asked", [
    pytest.param(lambda: a_delivery_of(AN_ALERT_NAMING_A_REFERENCE),
                 id="the-double-writing-references"),
    pytest.param(lambda: AlertsAsArgusWrites().parse_delivery(
                     AN_ALERT_NAMING_A_REFERENCE.model_dump_json().encode(), DONT_CARE_HEADERS
                 ),
                 id="the-double-reading-references"),
    pytest.param(lambda: as_grafana_sends(AN_ALERT_NAMING_A_REFERENCE),
                 id="grafana-writing-references"),
    pytest.param(lambda: as_grafana_sends(AN_ALERT_SAYING_LITTLE.model_copy(
                     update={"stale_entry_keys": ("some:key",)}
                 )),
                 id="grafana-writing-keys-without-their-count"),
    pytest.param(lambda: as_grafana_sends(AN_ALERT_SAYING_LITTLE.model_copy(
                     update={"stale_entries_found": 1}
                 )),
                 id="grafana-writing-a-count-without-its-keys")
])
def test_what_a_row_cannot_say_is_refused_as_the_suite_s_mistake(
    asked: Callable[[], object]
) -> None:
    # A `ValueError`, never an answer and never `AlertUnreadable`: a row that
    # wrote or read it would hold the port to something one sender cannot say.
    Scenario() \
        .when(attempting(asked)) \
        .then(an_error_was_raised(ValueError))
