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
    # When the incident began, according to whatever raised the alert - and
    # unset for almost every alert there is, which is the normal case rather
    # than a gap. A rule watching a series reports a minute Argus measures for
    # itself from the buckets it retrieved, and a measured minute is evidence
    # where a stated one is testimony.
    #
    # An alert states one only where it knows something the series cannot say. A
    # check that reconciles stored values against the records behind them finds
    # what went wrong long after the writing did, and dates it from the oldest
    # record it found wrong; nothing in any series marks that minute, because
    # nothing failed and nothing slowed. Distinct from `started_at` for exactly
    # that reason - that is when somebody noticed, and here the two differ by a
    # week.
    stated_onset: datetime | None = None