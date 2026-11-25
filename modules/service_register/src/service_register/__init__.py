"""The organisation's register of what calls what, as the read tier reads it
(spec §12.1).

A port and the one adapter behind it. The port is named for the role - whatever
records what a service depends on and whose each of those is - and the adapter
for whose register it reads today, in `service_register.target_service`.
Nothing above the port sees a route, an address or a field of the register's
own.

The adapter is not exported here. It is built where the read server is wired,
and everything else is handed it typed as the port - so the only modules allowed
to name it are the ones that have to.
"""

from __future__ import annotations

from service_register.port import RegistryUnavailable, ServiceRegister

__all__ = [
    "RegistryUnavailable",
    "ServiceRegister"
]
