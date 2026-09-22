"""Rows these repository suites need to exist before they can read anything."""

from __future__ import annotations

import psycopg
from argus_core.models import Alert
from argus_incidents.repository import incidents


def an_incident_created_for(conn: psycopg.Connection, alert: Alert) -> str:
    """One incident, written through the repository rather than by hand.

    Through the repository on purpose: every one of these suites reads rows
    that only exist because an incident does, and a fixture inserting them
    directly would be a second statement of the schema that stops agreeing
    with the first the day a column moves.
    """
    return incidents.create(conn, alert)
