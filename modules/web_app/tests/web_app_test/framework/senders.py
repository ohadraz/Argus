"""The senders the suite's application hears from, standing in for a vendor's.

A delivery to the stand-in is the alert itself, as Argus's own model writes it,
or a word saying only resolutions were sent - so what a case varies is what a
route does with an alert. Which vendor's shape an alert arrives in, and how
each vendor's is read, is each adapter's own suite's to say.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

from alert_source import AlertUnreadable, OnlyResolved
from core.models import Alert
from pydantic import ValidationError

# What the stand-in is sent for a delivery saying only that rules stopped firing.
ONLY_RESOLVED: Final = "only_resolved"

# What the stand-in says of a delivery that is not an alert.
NOT_AN_ALERT: Final = "not an alert as Argus writes one"


class AlertsAsArgusWritesThem:
    """An `AlertSource` whose deliveries are Argus's own alerts."""

    def parse_delivery(self, body: bytes, headers: Mapping[str, str], /) -> Alert | OnlyResolved:
        sent = json.loads(body)

        if sent == {ONLY_RESOLVED: True}:
            return OnlyResolved()

        try:
            return Alert.model_validate(sent)
        except ValidationError as unreadable:
            raise AlertUnreadable(NOT_AN_ALERT) from unreadable
