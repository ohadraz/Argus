"""Whoever tells Argus a repository moved, as Argus hears it (spec §7.9, §11.5).

A port and the one adapter behind it. The port is named for the role - a sender
of pushes - and the adapter for the code host that sends them, in
`push_source.github`. Nothing above the port sees a header, a signature scheme
or a field of the host's payload.

The adapter is not exported here. It is built where the web application is
wired, and everything else is handed it typed as the port.
"""

from __future__ import annotations

from push_source.failures import PushUnreadable, PushUnverified
from push_source.port import Pushed, PushSource

__all__ = [
    "PushSource",
    "PushUnreadable",
    "PushUnverified",
    "Pushed"
]
