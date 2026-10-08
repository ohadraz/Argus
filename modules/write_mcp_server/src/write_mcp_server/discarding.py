"""Discarding the cache entries an incident's evidence named (spec §7.3, §12.1).

The write tier's sixth action, and the first that does not go through a control
plane. No control plane offers this one: a platform's built-in resource actions
reach a workload's lifecycle and its size - restart, scale, pause, resume - and
none of them reaches what a cache holds. So this module speaks to the store
itself, over the protocol that store publishes, which is also what a responder
doing it by hand would do.

Everything above the port sees a list of keys going in and a count coming back.
The keys are addresses and arrive from the evidence that named them; this module
composes none and knows nothing about how the service that wrote them spells one.
A key template here would be Argus holding one service's internals, and nothing
downstream could tell a derived key from a real one.

The count is the point of the module. Every other action in this tier answers with
a platform's acknowledgement and then has to go and look at something - a process's
start time, a revision put back - because "the request was accepted" says nothing
about whether it took effect. A store answering how many of the named keys existed
and are now gone has made a statement about the world, and it is the only thing in
a position to make it. So nothing is read back afterwards: asking the same store
whether the keys are still there is the same store answering the same question.

There is no undo descriptor and no field for one, and that is not the restart's
reason either. A restart changes no persistent state; this removes some, and
putting it back is neither possible nor wanted - the entries were a copy of
records this never touches, whatever reads one next works it out again from those
records, and writing the stale figures back would be recreating the incident.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Final, Protocol

from argus_core import SettingsSlice
from argus_core.mcp_transport import an_exhausted_action, an_unreachable_platform
from argus_core.models import CACHE, CacheEntriesDiscarded

logger = logging.getLogger(__name__)

# Redis's own name for removing keys without blocking on the memory, and the one
# place in Argus that holds it. The vendor's wire vocabulary, named here for the
# reason Argo CD's `restart` is named in `restarting`: the spelling belongs to the
# store, and everything above this module says "discard".
#
# `UNLINK` rather than `DEL` because the two differ in who waits. `DEL` frees each
# key's memory on the connection's own thread, so one call naming many keys blocks
# the store - and the shop reading that store is the service this is trying to put
# right. `UNLINK` detaches the keys and reclaims the memory elsewhere, so the call
# costs the shop nothing it would notice.
UNLINK_COMMAND: Final = "UNLINK"

# How long to wait for a store that may not be there. Short on purpose: losing a
# cache is a slowdown by design, and a connect attempt that hangs for seconds
# turns it into a timeout - which is the shop's own reason for a short one, and
# the same reason here, since an action that cannot reach the store should say so
# while the walk still has time to try something else.
CONNECT_TIMEOUT_SECONDS: Final = 0.25


class DiscardSettings(SettingsSlice):
    """Where the cache is, and nothing else.

    One field, and the slice is worth having for what it leaves out rather than
    for what it carries: this tool has no business holding the credential that
    reaches the deployment platform, and a slice naming it would be this tool
    able to restart or roll back something.

    The address is a fact about the estate, like the platform's URL beside it -
    and it is **not** the address the service itself dials. The shop reaches its
    cache inside the network it runs in, where Argus is a process outside that
    network reaching the same store by a published port. One cache, two addresses,
    which is the asymmetry the deploy history's own host already lives with.
    """

    cache_url: str


class DiscardEntries(Protocol):
    """How keys are actually removed from a store.

    A `Protocol` rather than a `Callable` alias, for the reason `ObserveStartTime`
    is one: a test stands it in with `create_autospec`, which needs something
    introspectable.

    It is handed the endpoint as well as the keys rather than being built around
    one, so that nothing here holds a connection open between actions - a walk
    takes at most a handful of these, minutes apart, and a pooled client would be
    a connection kept alive for an incident's duration to save a handshake.

    Answers how many of the named keys existed and were removed. Raises whatever
    the client raises where the store could not be reached at all.
    """

    def __call__(self, cache_url: str, keys: Sequence[str], /) -> int: ...


class NothingLeftToDiscard(Exception):
    """None of the entries named are in the store, so there is nothing to remove.

    Raised rather than answered with a count of zero, and this is the one judgement
    in the module that was wrong before it was right. A zero is a true statement
    about the store and a misleading one about the incident: nothing was changed,
    so a caller recording the discard as done would confirm a mitigation that never
    happened - and because this action is confirmed from its own answer rather than
    by watching the service, nothing downstream would catch it. The incident would
    close as mitigated over a shop whose figures are still wrong.

    So the honest account is the one a refusal gives, exactly as it is for a
    deployment already at its largest: the action Argus has for this cause is
    exhausted here, the walk moves on to another candidate, and no hypothesis is
    struck off on the strength of a change nobody made.

    Marked as an exhausted action on the way out, which is what lets the walk tell
    this from a store it could not reach. Both leave the shop unchanged and they
    mean opposite things - here the tool worked and the store answered correctly.
    """


class EntriesNotDiscarded(Exception):
    """The store could not be reached, so nothing was discarded.

    Raised rather than reported as a count of zero, because the two mean opposite
    things to whoever picks the incident up. A store that answered and held none
    of the named keys is a divergence something else has already cleared, and the
    shop is correct; a store that never answered is a mitigation that did not
    happen, and anything downstream treating it as done would read the unchanged
    shop as evidence against a diagnosis that was right.
    """


def with_redis(cache_url: str, keys: Sequence[str], /) -> int:
    """Removes `keys` from the Redis at `cache_url`, answering how many went.

    The real seam, and the only code in Argus that imports a store's client. A
    connection per call rather than a pool, for the reason the protocol above
    says: a walk takes a handful of these minutes apart.

    `decode_responses` is not asked for, because nothing here reads a value - the
    command answers with an integer and the keys go out as the text they arrived
    as. Nothing is read back either, so there is no reply to decode.

    Not unit-tested, and deliberately: what there would be to assert is that the
    client was asked for `UNLINK` with these keys, which is this function's body
    written twice. What it is actually claiming - that a real store answers that
    way - is only true or false against a real store, and the end-to-end stack is
    where one exists.
    """
    from redis import Redis

    client = Redis.from_url(cache_url, socket_connect_timeout=CONNECT_TIMEOUT_SECONDS)

    try:
        return int(client.unlink(*keys))
    finally:
        client.close()


def discard_cache_entries(
    keys: Sequence[str],
    settings: DiscardSettings,
    *,
    discard: DiscardEntries = with_redis
) -> CacheEntriesDiscarded:
    """Discards the entries `keys` names, and answers with how many went.

    One call carrying all of them rather than one call each. The store takes them
    together, and a loop would be a partial discard whenever anything failed part
    way through - leaving a count that is honest about what went and no way to say
    which entries are still wrong.

    Raises `EntriesNotDiscarded` where the store did not answer, marked so a
    caller narrows itself rather than offering the same action again: a store that
    is not there has taken every action through it away at once. The message names
    the endpoint that was dialled, which is the whole diagnosis of this particular
    failure - a reader setting it against the address the deployment configured is
    doing the one comparison that explains it.

    Raises the same thing, and never dials, where no keys were named. The tool
    above takes a bare list, and a schema is a request rather than a guarantee -
    so a caller that named nothing arrives here, and the store would refuse a
    removal of nothing. That refusal would be reported as a store that errored,
    which is this module's word for a cache that could not be reached, and a walk
    would narrow itself away from every action on a store that is perfectly well.
    Unmarked, because nothing about the estate is unavailable: it is a caller that
    has not said what to act on.
    """
    if not keys:
        logger.warning("no cache entries named")
        raise EntriesNotDiscarded(
            f"no cache entries were named to discard at [{settings.cache_url}], "
            f"so nothing was asked of it"
        )

    try:
        discarded = discard(settings.cache_url, tuple(keys))
    except Exception as error:
        raise EntriesNotDiscarded(
            an_unreachable_platform(
                CACHE,
                f"could not discard {len(keys)} cache entries at "
                f"[{settings.cache_url}]: {error}"
            )
        ) from error

    if not discarded:
        raise NothingLeftToDiscard(
            an_exhausted_action(
                f"none of the {len(keys)} entries named at "
                f"[{settings.cache_url}] are in the store, so there is nothing "
                f"here for a discard to remove"
            )
        )

    logger.info("cache entries discarded", extra={"named": len(keys), "discarded": discarded})

    return CacheEntriesDiscarded(discarded=discarded)
