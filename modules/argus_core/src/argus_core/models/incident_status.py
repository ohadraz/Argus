from __future__ import annotations

from enum import StrEnum


class IncidentStatus(StrEnum):
    INVESTIGATING = "investigating"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"
    FIXING = "fixing"
    ESCALATED = "escalated"
