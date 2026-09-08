from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from argus_core.ids import UuidStr
from argus_core.models.undo_descriptor import UndoDescriptor


class TakenAction(BaseModel):
    id: UuidStr
    incident_id: UuidStr
    hypothesis_id: UuidStr | None
    type: str | None
    target: str | None
    reversible: bool
    tier: str | None
    undo_descriptor: UndoDescriptor | None
    outcome: str | None
    taken_at: datetime
    approved_by: str | None
