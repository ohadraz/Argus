from __future__ import annotations

import random
import string

from argus_core.config import get_settings
from argus_core.models.alert import Alert
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus


def an_incident_state(
    alert: Alert, status: IncidentStatus, incident_id: str | None = None
) -> IncidentState:
    if incident_id is None:
        incident_id = a_random_id()

    return IncidentState(incident_id=incident_id, alert=alert, status=status)


def a_random_id() -> str:
    letters = "".join(random.choices(string.ascii_lowercase, k=4))
    digits = "".join(random.choices(string.digits, k=3))

    return f"{letters}-{digits}"


def a_high_enough_confidence() -> float:
    return get_settings().mitigate_threshold + 0.01


def a_below_threshold_confidence() -> float:
    return get_settings().mitigate_threshold - 0.01
