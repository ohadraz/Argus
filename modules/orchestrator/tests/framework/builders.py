from __future__ import annotations

import random
import string

from argus_core.config import get_settings
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
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


def a_determined_hypothesis(incident_id: str, confidence: float) -> Hypothesis:
    return Hypothesis(
        incident_id=incident_id,
        summary="kukibuki hypothesis",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=confidence,
        supporting_evidence=["some log line"],
    )


def an_undetermined_hypothesis(incident_id: str) -> Hypothesis:
    """A hypothesis that found no cause - and so carries no confidence.

    Two builders rather than one with nullable arguments, because the model
    refuses to hold a cause without a confidence or the reverse: the two valid
    shapes are genuinely different objects.
    """
    return Hypothesis(
        incident_id=incident_id,
        summary="no cause determined from the evidence retrieved",
        cause_type=None,
        confidence=None,
        supporting_evidence=["some log line"],
    )
