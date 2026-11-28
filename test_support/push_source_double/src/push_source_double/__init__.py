"""A sender of pushes that writes Argus's own push: a double of the port, for suites.

A second adapter of `push_source`'s port, and never one a process runs: a push
read from memory would have Argus record a commit nobody pushed, so it lives
where nothing that ships can install it. It is held to the port by the port's
own suite, which runs it beside the vendor's adapter, each sent the same thing
written and signed in its own sender's way.

A parser holds nothing but the secret it verifies under, so there is no seed.
`a_delivery_of` writes what was sent - a `Pushed`, or `None` for a delivery
naming no commit - and signs it; `headers_signing` signs any bytes, for a
delivery that is no push; `PushesAsArgusWrites` verifies and reads it back.
"""

from __future__ import annotations

from push_source_double.argus_written import (
    PushesAsArgusWrites,
    a_delivery_of,
    headers_signing,
)

__all__ = [
    "PushesAsArgusWrites",
    "a_delivery_of",
    "headers_signing"
]
