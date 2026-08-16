from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Alert(BaseModel):
    """Argus's own normalized alert shape (spec §7.9, §25).

    Built by a vendor-specific adapter (e.g. argus_web's Grafana parser) at
    the system boundary - nothing past that boundary ever sees a vendor's
    raw payload shape.
    """

    service: str
    alert_name: str
    severity: str | None = None
    summary: str | None = None
    started_at: datetime | None = None