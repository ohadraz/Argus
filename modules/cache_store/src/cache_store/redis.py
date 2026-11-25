"""The cache store, as a Redis answers for it - and the only module in Argus that
knows its commands, its client or its address.

Spoken to directly, over the protocol the store publishes, because no control
plane offers this write: a platform's built-in resource actions reach a
workload's lifecycle and its size, and none of them reaches what a cache holds.
That is also what a responder doing it by hand would do.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Final, Protocol

from core import AdapterSettings

from cache_store.port import StoreNotReached

# How long to wait for a store that may not be there. Short on purpose: losing a
# cache is a slowdown by design, and a connect attempt that hangs for seconds
# turns it into a timeout - which is the shop's own reason for a short one, and
# the same reason here, since an action that cannot reach the store should say so
# while the walk still has time to try something else.
CONNECT_TIMEOUT_SECONDS: Final = 0.25


class RedisSettings(AdapterSettings):
    """Where the cache is, and nothing else.

    No credential, for the reason the service register has none: what is in
    here is a figure the account page would have worked out for itself, and a
    store holding a cheaper copy of public arithmetic is not a secret.
    """

    # Where the Target Service's rendered-summary cache answers. The first
    # address Argus holds that is a datastore rather than a control plane: every
    # other write goes through a platform that acts on Argus's behalf, and this
    # one is spoken to directly, in the store's own protocol.
    #
    # The shop holds a different address for the same cache, and that is correct
    # rather than drift. The shop reads its own deployment configuration and
    # dials the cluster service name there; Argus runs beside the environment
    # rather than inside it and reaches the published port, exactly as the shop's
    # own monitoring posts to `host.docker.internal` to reach a host Argus runs
    # on. Two addresses for one cache, because the two parties are in different
    # places.
    cache_url: str = "redis://localhost:6379"


class StoreClient(Protocol):
    """The three things `RedisStore` asks of a store's client - a `Protocol` so
    a test can stand one in with `create_autospec`."""

    def ping(self) -> Any: ...

    def unlink(self, *names: str) -> Any: ...

    def close(self) -> None: ...


def a_redis_at(cache_url: str) -> StoreClient:
    """A client for the Redis at `cache_url`, and the only code in Argus that
    imports a store's client.

    `decode_responses` is not asked for, because nothing here reads a value - the
    command answers with an integer and the keys go out as the text they arrived
    as. Nothing is read back either, so there is no reply to decode.

    Not unit-tested, and deliberately: what there would be to assert is that the
    client was built with these arguments, which is this function's body written
    twice. That a real store answers to it is only true or false against a real
    store, and the end-to-end stack is where one exists.
    """
    from redis import Redis

    return Redis.from_url(cache_url, socket_connect_timeout=CONNECT_TIMEOUT_SECONDS)


class RedisStore:
    """A Redis, behind the port.

    Holds where the store is and how a client is made for it, and no
    connection: one is made per call, for the reason the port gives. Built
    where the write server is wired, and handed on typed as `CacheStore`.
    `connect` is where a test puts the store.
    """

    def __init__(self,
                 settings: RedisSettings,
                 connect: Callable[[str], StoreClient] = a_redis_at) -> None:
        self._cache_url = settings.cache_url
        self._connect = connect

    @property
    def endpoint(self) -> str:
        """The address the store is dialled at, as the deployment configured it."""
        return self._cache_url

    def discard(self, keys: Sequence[str], /) -> int:
        """Removes `keys` from the Redis at `endpoint`, answering how many went."""
        # An address the client cannot be built from was never dialled, so nothing
        # was asked of the store.
        try:
            client = self._connect(self._cache_url)
        except Exception as error:
            raise StoreNotReached(f"{error}") from error

        try:
            # Asked before the discard, so a store that is not there is told apart
            # from one that went once the discard was on its way - after which the
            # entries may well be gone.
            try:
                client.ping()
            except Exception as error:
                raise StoreNotReached(f"{error}") from error

            # Redis's own way of removing keys without blocking on the memory,
            # and the one place in Argus that asks for it; everything above
            # this module says "discard".
            #
            # `UNLINK` rather than `DEL` because the two differ in who waits.
            # `DEL` frees each key's memory on the connection's own thread, so
            # one call naming many keys blocks the store - and the shop reading
            # that store is the service this is trying to put right. `UNLINK`
            # detaches the keys and reclaims the memory elsewhere, so the call
            # costs the shop nothing it would notice.
            return int(client.unlink(*keys))
        finally:
            client.close()
