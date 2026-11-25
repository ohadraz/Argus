"""Discarding the cache entries an incident's evidence named (spec §7.3, §12.1).

The write tier's sixth action, and the first that does not go through a control
plane. No control plane offers this one: a platform's built-in resource actions
reach a workload's lifecycle and its size - restart, scale, pause, resume - and
none of them reaches what a cache holds. So this action speaks to the store
itself, through the cache store's port (`cache_store`), whose adapter speaks the
protocol that store publishes.

Everything above the port sees a list of keys going in and a count coming back.
The keys are addresses and arrive from the evidence that named them; this module
composes none and knows nothing about how the service that wrote them spells one.
A key template here would be Argus holding one service's internals, and nothing
downstream could tell a derived key from a real one.

The count is the point of the module. Every other action in this tier answers with
a platform's acknowledgement and then has to go and look at something - a process's
start time, a deployment rolled back - because "the request was accepted" says nothing
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

from cache_store import CacheStore, StoreNotReached
from core.models import CACHE, CacheEntriesDiscarded
from mcp_transport import (
    ToolRefused,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
    an_unreachable_platform,
    with_what_it_left,
)

logger = logging.getLogger(__name__)


class NothingLeftToDiscard(ToolRefused):
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

    Refused as an exhausted action, which is what lets the walk tell this from a
    store it could not reach. Both leave the shop unchanged and they mean
    opposite things - here the tool worked and the store answered correctly.
    """


class EntriesNotDiscarded(ToolRefused):
    """The store could not be reached, or went once the discard was on its way.

    Raised rather than reported as a count of zero, because the two mean opposite
    things to whoever picks the incident up. A store that answered and held none
    of the named keys is a divergence something else has already cleared, and the
    shop is correct; a store that never answered is a mitigation that did not
    happen, and anything downstream treating it as done would read the unchanged
    shop as evidence against a diagnosis that was right.
    """


def discard_cache_entries(keys: Sequence[str], store: CacheStore) -> CacheEntriesDiscarded:
    """Discards the entries `keys` names from `store`, and answers with how many
    went.

    One call carrying all of them rather than one call each. The store takes them
    together, and a loop would be a partial discard whenever anything failed part
    way through - leaving a count that is honest about what went and no way to say
    which entries are still wrong.

    Raises `EntriesNotDiscarded` where the store did not answer, refused as an
    unreachable store so a caller narrows itself rather than offering the same
    action again: a store that is not there has taken every action through it
    away at once. Refused so only where it was not there before the discard: one
    that went after it may have discarded the entries, and a store said to be
    unreachable says nothing changed.
    The message names the endpoint that was dialled, which is the whole diagnosis
    of this particular failure - a reader setting it against the address the
    deployment configured is doing the one comparison that explains it.

    Raises the same thing, and never dials, where no keys were named. The tool
    above takes a bare list, and a schema is a request rather than a guarantee -
    so a caller that named nothing arrives here, and the store would refuse a
    removal of nothing. That refusal would be reported as a store that errored,
    which is this module's word for a cache that could not be reached, and a walk
    would narrow itself away from every action on a store that is perfectly well.
    Not refused as unreachable, because nothing about the estate is unavailable:
    it is a caller that has not said what to act on. And said to have left
    nothing, because nothing was asked of the store.
    """
    if not keys:
        logger.warning("no cache entries named")
        raise EntriesNotDiscarded(a_refusal_saying_what_it_left(
            f"no cache entries were named to discard at [{store.endpoint}], "
            f"so nothing was asked of it"
        ))

    try:
        discarded = store.discard(tuple(keys))
    except StoreNotReached as error:
        raise EntriesNotDiscarded(
            an_unreachable_platform(
                CACHE,
                f"could not discard {len(keys)} cache entries at "
                f"[{store.endpoint}]: {error}"
            )
        ) from error
    except Exception as error:
        # The discard was on its way, and the entries may have gone with it.
        # Unaccounted rather than unreachable, because a store said to be
        # unreachable says nothing was changed - and the walk would narrow away
        # from one that may well have answered.
        raise EntriesNotDiscarded(with_what_it_left(
            f"could not discard {len(keys)} cache entries at "
            f"[{store.endpoint}]: {error}",
            None
        )) from error

    if not discarded:
        raise NothingLeftToDiscard(
            an_exhausted_action(
                f"none of the {len(keys)} entries named at "
                f"[{store.endpoint}] are in the store, so there is nothing "
                f"here for a discard to remove"
            )
        )

    logger.info("cache entries discarded", extra={"named": len(keys), "discarded": discarded})

    return CacheEntriesDiscarded(discarded=discarded)
