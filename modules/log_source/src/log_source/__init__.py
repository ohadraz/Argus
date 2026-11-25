"""A service's logs, as the read tier reads them (spec §12.1, §16).

A port and the one adapter behind it. The port is named for the role - wherever
the lines a service wrote are read from - and the adapter for whose wire it
reads today, in `log_source.target_service`. Nothing above the port sees a route
or an address.

The adapter is not exported here. It is built where the read server is wired,
and everything else is handed it typed as the port - so the only modules allowed
to name it are the ones that have to.
"""

from __future__ import annotations

from log_source.port import LogSource

__all__ = [
    "LogSource"
]
