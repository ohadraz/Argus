"""Deliveries written as Argus's own model writes an alert, and read back.

Everything it says is what the port promises and its suite pins over both
adapters: an alert sent is the alert read, a delivery of resolutions alone is
`OnlyResolved`, and a delivery not in this sender's shape - bytes that are no
text or no JSON, JSON that is no alert - is `AlertUnreadable`, never another
error.

An alert naming references is refused, written or read, as a suite's mistake
rather than answered: references are a sender's own names for an incident (for
Grafana, its group key's hash and each firing), which no other sender's writer
can produce, so the port's suite cannot hold a double to carrying them - and a
suite that needs an incident to carry one files it into the record itself.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

from alert_source import AlertUnreadable, OnlyResolved
from core.models import Alert

# What a delivery saying only that rules stopped firing is written as: a word
# no alert carries, so neither can be read as the other.
ONLY_RESOLVED: Final = "only_resolved"

# What a sender is sent, in Argus's terms.
type Sent = Alert | OnlyResolved


def a_delivery_of(sent: Sent) -> bytes:
    """`sent`, as this sender writes it: the alert's own JSON, or the word for
    resolutions alone."""
    if isinstance(sent, OnlyResolved):
        return json.dumps({ONLY_RESOLVED: True}).encode()

    _refuse_references_in(sent)

    return sent.model_dump_json().encode()


class AlertsAsArgusWrites:
    """An `AlertSource` whose deliveries are Argus's own alerts. Holds nothing,
    and reads no header: nothing it is sent is signed."""

    def parse_delivery(self, body: bytes, headers: Mapping[str, str], /) -> Alert | OnlyResolved:
        """What one delivery says, or `AlertUnreadable` saying what was wrong
        as the error that found it."""
        # `ValueError` covers all three ways a delivery is no alert: bytes that
        # are not text or not JSON, and JSON the model refuses (pydantic's
        # `ValidationError` is one).
        try:
            sent = json.loads(body)

            if sent == {ONLY_RESOLVED: True}:
                return OnlyResolved()

            alert = Alert.model_validate(sent)
        except ValueError as unreadable:
            raise AlertUnreadable(repr(unreadable)) from unreadable

        _refuse_references_in(alert)

        return alert


def _refuse_references_in(alert: Alert) -> None:
    if alert.references:
        raise ValueError(f"the alert names references {alert.references}: they are a "
                         f"sender's own names, which this double does not carry")
