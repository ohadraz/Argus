"""The feature-flag provider, as Argus needs it (spec §12.1, §13).

A port and the one adapter behind it. The port is named for the role - what
Argus asks of whatever serves and records its flags - and the adapter for the
vendor that answers today, in `flag_provider.unleash`. Nothing above the port
sees a route, a token or an event name.

The adapter is not exported here. It is built where a server is wired, and
everything else is handed it typed as a port - so the only modules allowed to
name it are the ones that have to.
"""

from __future__ import annotations

from flag_provider.failures import FlagProviderError, FlagProviderUnavailable, FlagWriteFailed
from flag_provider.port import FlagProviderReads, FlagProviderWrites

__all__ = [
    "FlagProviderError",
    "FlagProviderReads",
    "FlagProviderUnavailable",
    "FlagProviderWrites",
    "FlagWriteFailed"
]
