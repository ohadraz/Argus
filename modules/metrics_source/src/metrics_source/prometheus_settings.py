"""Where Prometheus answers, and nothing else."""

from __future__ import annotations

from core import SettingsSlice


class PrometheusSettings(SettingsSlice):
    """Where Prometheus answers, and nothing else.

    A base URL rather than a host, so that the path after it is always
    Prometheus's own: a real Prometheus at its root, or a stand-in mounted under
    a prefix, are the same adapter aimed differently.

    A module of its own beside the adapter, as each source's settings are, so
    that the port names no vendor and a composition root naming what the source
    needs does not import the client that talks to it.
    """

    prometheus_base_url: str
