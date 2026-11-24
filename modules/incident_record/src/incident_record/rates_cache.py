"""The exchange rates a source last published, kept so the next incident that
prices something in another currency need not ask for them again.

Not incident state: a cache of somebody else's figures, kept beside the
incident record because that is where Argus's tables are. On a connection its
caller holds, as the source that reads through it is handed one.
"""

from __future__ import annotations

from typing import Protocol

import psycopg
from core.models import PublishedRates

from incident_record.repository import exchange_rates


class RatesCache(Protocol):
    """The exchange rates kept from their source's last publication."""

    def latest_for(self, base: str, /) -> PublishedRates | None:
        """The newest rates kept for `base`, where any are."""
        ...

    def keep(self, rates: PublishedRates, /) -> None:
        """Keeps rates as their source published them."""
        ...


class _OnAConnection:
    """The cache, on a connection somebody else holds."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def latest_for(self, base: str, /) -> PublishedRates | None:
        return exchange_rates.get_latest_for(self._conn, base)

    def keep(self, rates: PublishedRates, /) -> None:
        exchange_rates.record(self._conn, rates)


def rates_cache_on(conn: psycopg.Connection) -> RatesCache:
    """The cache, on `conn`, which the caller holds."""
    return _OnAConnection(conn)
