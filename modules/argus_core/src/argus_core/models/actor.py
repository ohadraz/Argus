from __future__ import annotations

from enum import StrEnum


class Actor(StrEnum):
    ORCHESTRATOR = "orchestrator"
    INVESTIGATOR = "investigator"
    MITIGATION = "mitigation"
