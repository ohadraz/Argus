"""Whether a request that failed is known not to have been applied.

The line between what a write tier can say it left behind and what it cannot.
A request that never left the process, or one the server answered by saying it
did not handle it, changed nothing; one whose answer was lost, or that the server
faulted part way through, may have changed something nobody can see.

One rule for every write tier that asks over HTTP - the deployment platform's
adapter and the flag provider's write alike - because two lists of errors and
statuses are two lists to keep in step, and the day one learns a status the
other does not, one tier says it left nothing where the other would not.

A door of its own and a narrow one, for the reason `llm` and `mcp_transport`
are narrow: it names `httpx2`, which is an extra of the kernel's, and a module
naming a `UuidStr` should not install an HTTP client to do it. The two modules
that go through it declare `httpx2` themselves.
"""

from __future__ import annotations

from typing import Final

import httpx2

# The methods that change nothing however their answer went missing (RFC 9110,
# 9.2.1): a read that failed is a failure the estate is untouched by.
_SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})

# The server saying it could not handle the request at all (RFC 9110, 15.6.4),
# as against the rest of the 5xx: a fault while handling it, or a gateway that
# lost the answer from behind it, neither of which says the change was not made.
_NOT_HANDLED: Final = 503

# The failures that happen before a byte of the request is sent: no connection
# was had, or none was free to send it on.
_NEVER_SENT: Final = (httpx2.ConnectError, httpx2.ConnectTimeout, httpx2.PoolTimeout)

_CLIENT_ERROR: Final = range(400, 500)


def known_not_applied(method: str, failure: BaseException) -> bool:
    """Whether `failure`, raised by a `method` request, says it was not applied.

    True for a read, for a request that was never sent, and for an answer that
    says it was not handled - a 4xx, read and rejected, or a 503. False for
    everything else, a failure that is not the transport's included: a bug
    between the request and here says nothing about what the server did, and is
    not taken to say the change was not made.
    """
    if method.upper() in _SAFE_METHODS:
        return True

    if isinstance(failure, _NEVER_SENT):
        return True

    if isinstance(failure, httpx2.HTTPStatusError):
        status = failure.response.status_code

        return status in _CLIENT_ERROR or status == _NOT_HANDLED

    return False
