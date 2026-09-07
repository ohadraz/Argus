from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from argus_core.ids import UuidStr


class TakenAction(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    hypothesis_id: UuidStr | None
    type: str | None
    target: str | None
    reversible: bool
    tier: str | None
    undo_descriptor: dict[str, Any] | None
    outcome: str | None
    taken_at: datetime
    approved_by: str | None
