"""Where Prometheus answers, and nothing else."""

from __future__ import annotations

from core import AdapterSettings


class PrometheusSettings(AdapterSettings):
    """Where Prometheus answers, and nothing else.

    A base URL rather than a host, so that the path after it is always
    Prometheus's own: a real Prometheus at its root, or a stand-in mounted under
    a prefix, are the same adapter aimed differently. The default is the Target
    Environment's stand-in, mounted under the shop's prefix.

    A module of its own beside the adapter, as each source's settings are, so
    that the port names no vendor and a composition root naming what the source
    needs does not import the client that talks to it.
    """

    prometheus_base_url: str = "http://localhost:8080/prometheus"
