"""Ports a suite's servers listen on, asked of the operating system.

A port written into a suite is one every copy of that suite shares: a second
checkout running it, or a run inside WSL, whose listeners `wslrelay.exe`
forwards to this machine's loopback. Two at once, and one dies on the bind
while the other's server answers its client. A port the operating system hands
out was free when it was handed out.

Domain-free like the rest of this package: a port is nobody's business.
"""

from __future__ import annotations

import socket

_LOOPBACK = "127.0.0.1"


def a_free_port() -> int:
    """A loopback port nothing was listening on a moment ago, for a server the
    suite starts in a process of its own.

    Found by binding port 0 and letting it go, so that the process it is handed
    to can bind it. Between the two it is anybody's, which is why a server
    started on one is waited for until it answers as itself rather than until
    anything answers. A server in the suite's own process needs none of this:
    it binds port 0 and reads back what it was given.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as asking:
        asking.bind((_LOOPBACK, 0))

        return int(asking.getsockname()[1])
