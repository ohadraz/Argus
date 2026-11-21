"""Whoever sends Argus alerts, as Argus hears them (spec §7.9, §12).

A port and the one adapter behind it today. The port is named for the role -
a sender of alerts - and the adapter for the vendor that sends them, in
`alert_source.grafana`. Nothing above the port sees a payload's shape.

The adapter is not exported here. It is built where the web application is
wired, and everything else is handed it typed as the port.
"""

from __future__ import annotations

from alert_source.failures import AlertUnreadable
from alert_source.port import AlertSource, OnlyResolved

__all__ = [
    "AlertSource",
    "AlertUnreadable",
    "OnlyResolved"
]
