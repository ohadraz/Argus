"""Which incidents there are to show: the history, and the one somebody
opening Argus is looking for.

A role of its own rather than part of `IncidentReads`, because these choose
among incidents rather than reading one: which incidents the history lists and
which one counts as current are questions about the rows, and answered anywhere
but here they would be a page deciding what counts as an incident.

On a connection its caller holds, as the pages that ask it read.
"""

from __future__ import annotations

from typing import Protocol

import psycopg
from core.models import Incident

from incident_record.repository import incidents


class IncidentsOnShow(Protocol):
    """The incidents a page shows."""

    def recent(self) -> list[Incident]:
        """Every incident, in the order the history lists them."""
        ...

    def current(self) -> Incident | None:
        """The newest incident still running, else the newest there is - or
        `None` where there has never been one."""
        ...


class _OnAConnection:
    """The incidents on show, read on a connection somebody else holds."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def recent(self) -> list[Incident]:
        return incidents.get_recent(self._conn)

    def current(self) -> Incident | None:
        return incidents.get_current(self._conn)


def incidents_on_show_on(conn: psycopg.Connection) -> IncidentsOnShow:
    """The incidents on show, read on `conn`, which the caller holds."""
    return _OnAConnection(conn)
