"""A sender of alerts that writes Argus's own alerts: a double of the port, for suites.

A second adapter of `alert_source`'s port, and never one a process runs: an
alert read from memory would have Argus open an incident no sender raised, so
it lives where nothing that ships can install it. It is held to the port by
the port's own suite, which runs it beside the vendor's adapter, each sent the
same thing written in its own sender's bytes.

A parser holds nothing, so there is no seed. What two senders differ in is how
a delivery is written: `a_delivery_of` writes what was sent - an `Alert`, or
`OnlyResolved` - as this sender sends it, and `AlertsAsArgusWrites` reads it
back.
"""

from __future__ import annotations

from alert_source_double.argus_written import AlertsAsArgusWrites, Sent, a_delivery_of

__all__ = [
    "AlertsAsArgusWrites",
    "Sent",
    "a_delivery_of"
]
