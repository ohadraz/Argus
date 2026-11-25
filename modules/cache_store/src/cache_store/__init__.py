"""The store a service keeps its derived copies in, as the write tier reaches it
(spec §7.3, §12.1).

A port and the one adapter behind it. The port is named for the role - wherever
a service caches what it worked out - and the adapter for the vendor that
answers today, in `cache_store.redis`. Nothing above the port sees a command, a
client or a connection.

The adapter is not exported here. It is built where the write server is wired,
and everything else is handed it typed as the port - so the only modules allowed
to name it are the ones that have to.
"""

from __future__ import annotations

from cache_store.port import CacheStore, StoreNotReached

__all__ = [
    "CacheStore",
    "StoreNotReached"
]
