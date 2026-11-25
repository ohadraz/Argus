"""Discarding the cache entries an incident's evidence named.

The first write in this tier that reaches a datastore rather than a control
plane, and the only one whose own answer is evidence. Every other action here
comes back with a platform's acknowledgement - the request was accepted, and
whether it helped has to be watched for in the service's window. This one comes
back with how many entries are gone, which is the store stating a fact about
itself.

That makes the count the thing worth pinning. An attempt is confirmed from it, so
a count that counted the wrong thing would confirm a mitigation that did not
happen - and the two ways it can be wrong are both staged here: keys that were
already gone, and a store that never answered at all.

What is deliberately absent is a read-back. Asking the store whether the keys are
there after it has said they are gone is the same store answering the same
question, and the restart's own follow-up exists only because a platform performs
one asynchronously.

The store itself is the cache store's port, stood in for here; how its adapter
reaches a real one is `cache_store`'s own suite.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from cache_store import CacheStore, StoreNotReached
from core.models import CACHE, CacheEntriesDiscarded
from mcp_transport import ToolRefusalKind, ToolRefused
from write_mcp_server.discarding import (
    EntriesNotDiscarded,
    NothingLeftToDiscard,
    discard_cache_entries,
)

from write_mcp_server_test.framework.refusals import (
    it_is_refused_as_unreachable,
    what_it_left_is_known,
)

SOME_ENDPOINT = "redis://cache.invalid:6379"
# Spelled as the store spells them. A placeholder would hide the one mistake
# these tests exist to catch - a seam that reordered or dropped an address.
SOME_KEYS = ("io-shop:summary:shopper-7", "io-shop:summary:shopper-2")
DONT_CARE_KEYS = ("io-shop:summary:shopper-1",)


@pytest.mark.unit
def test_every_key_goes_in_one_call_and_in_the_order_it_was_given() -> None:
    # One call rather than one per key, because the store can take them all and a
    # loop would be a partial discard whenever anything failed half way - leaving
    # a count that is honest and a set of entries nobody can name.
    #
    # In order, because the order is the evidence's. Nothing downstream could
    # notice a seam that sorted them, and the keys would still look exactly as
    # plausible as the ones the check actually found.
    Scenario() \
        .given(
            store := _a_store_reporting(len(SOME_KEYS))
        ) \
        .when(
            lambda: discard_cache_entries(SOME_KEYS, store)
        ) \
        .then(
            _it_asked_once_for(SOME_KEYS, store)
        )


@pytest.mark.unit
def test_the_count_the_store_reported_is_what_comes_back() -> None:
    # The receipt, and the only confirmation this mode has. Anything derived here
    # instead - the number of keys asked for, say - would report a discard that
    # removed nothing as a discard that removed everything, and the attempt would
    # be confirmed on the strength of a number this tier made up.
    Scenario() \
        .given(
            store := _a_store_reporting(len(SOME_KEYS))
        ) \
        .when(
            lambda: discard_cache_entries(SOME_KEYS, store)
        ) \
        .then(
            _it_reported(len(SOME_KEYS))
        )


@pytest.mark.unit
def test_keys_that_were_already_gone_are_reported_as_not_removed() -> None:
    # Not an error, and not corrected upwards. Something else may have discarded
    # them - a later run of the check, a responder, an eviction - and all of those
    # end with the entry absent, which is what the incident needed. The count has
    # to say what actually went, because the figure is read out in the account of
    # the incident.
    Scenario() \
        .given(
            store := _a_store_reporting(len(SOME_KEYS) - 1)
        ) \
        .when(
            lambda: discard_cache_entries(SOME_KEYS, store)
        ) \
        .then(
            _it_reported(len(SOME_KEYS) - 1)
        )


@pytest.mark.unit
def test_a_store_that_held_none_of_them_refuses_rather_than_reporting_nothing() -> None:
    # This test asserted the opposite until the agent's own suite showed it was
    # wrong, and the error is worth keeping written down. A count of zero is a
    # true statement about the store and a misleading one about the incident:
    # nothing was changed, so a caller recording the discard as done confirms a
    # mitigation that never happened - and because this action is confirmed from
    # its own answer rather than by watching a series, nothing downstream can
    # contradict it. The incident closes as mitigated over a shop whose figures
    # are still wrong.
    #
    # So it is a refusal, refused as an exhausted action exactly as a deployment
    # already at its largest is: the tool worked, the store answered correctly,
    # and the action Argus has for this cause has nothing left to do here. The
    # walk moves on to its next candidate rather than striking a hypothesis off
    # on the strength of a change nobody made.
    #
    # Still distinct from a store that could not be reached, which is the pair
    # this and the test below are about: both leave the shop unchanged and they
    # mean opposite things.
    Scenario() \
        .given(
            store := _a_store_reporting(0)
        ) \
        .when(
            attempting(
                lambda: discard_cache_entries(SOME_KEYS, store)
            )
        ) \
        .then(all_of(
            an_error_was_raised(NothingLeftToDiscard),
            _it_named(SOME_ENDPOINT),
            _it_was_refused_as_exhausted()
        ))


@pytest.mark.unit
def test_a_cache_that_could_not_be_reached_raises_and_says_which_one() -> None:
    # The opposite finding to the one above, and they must not end the same way.
    # A store that answered and held nothing is a mitigation that had nothing
    # left to do; a store that never answered is a mitigation that did not
    # happen, and anything downstream treating it as done would read the
    # unchanged shop as evidence against the diagnosis.
    #
    # The endpoint is in the message because it is the whole diagnosis of this
    # failure: a reader setting the address Argus dialled against the address the
    # deployment configured is doing the one comparison that explains it.
    Scenario() \
        .given(
            store := _a_store_that_cannot_be_reached()
        ) \
        .when(
            attempting(
                lambda: discard_cache_entries(DONT_CARE_KEYS, store)
            )
        ) \
        .then(all_of(
            an_error_was_raised(EntriesNotDiscarded),
            _it_named(SOME_ENDPOINT),
            _it_was_refused_as_the_platform_unreachable(),
            what_it_left_is_known(True)
        ))


@pytest.mark.unit
def test_a_cache_lost_once_the_discard_was_asked_for_is_not_said_to_have_changed_nothing() -> None:
    # The entries may have gone: refused as a store that could not be reached,
    # the record would say nothing was changed and the walk would narrow away
    # from a store that may well have answered.
    Scenario() \
        .given(
            store := _a_store_lost_after_it_was_asked()
        ) \
        .when(
            attempting(
                lambda: discard_cache_entries(DONT_CARE_KEYS, store)
            )
        ) \
        .then(all_of(
            an_error_was_raised(EntriesNotDiscarded),
            _it_named(SOME_ENDPOINT),
            it_is_refused_as_unreachable(False),
            what_it_left_is_known(False)
        ))


@pytest.mark.unit
def test_a_discard_naming_no_keys_never_reaches_the_store() -> None:
    # The tool takes a bare list, so a model can call it with an empty one - and
    # a schema is a request rather than a guarantee, which makes this the
    # handler's job. The store itself refuses a removal that names nothing, so
    # the call would come back as a store that errored, which is this tier's
    # word for a cache that could not be reached. A caller would then narrow
    # itself away from every action on a store that is perfectly well.
    #
    # Refused before the connection rather than after, because there is nothing
    # to ask: no keys named is no work to do, and it is a caller that has not
    # said what to act on rather than an estate that failed.
    Scenario() \
        .given(
            store := _a_store_reporting(0)
        ) \
        .when(
            attempting(
                lambda: discard_cache_entries((), store)
            )
        ) \
        .then(all_of(
            an_error_was_raised(EntriesNotDiscarded),
            _it_never_asked(store),
            it_is_refused_as_unreachable(False),
            what_it_left_is_known(True)
        ))


@pytest.mark.unit
def test_a_discard_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production. Both counts, because the gap between what was
    # named and what went is the part a person reading it afterwards would ask
    # about.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            store := _a_store_reporting(len(SOME_KEYS) - 1)
        ) \
        .when(
            lambda: discard_cache_entries(SOME_KEYS, store)
        ) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.discarding", logging.INFO,
                                  "cache entries discarded",
                                  values={"named": len(SOME_KEYS),
                                          "discarded": len(SOME_KEYS) - 1})
        )


@pytest.mark.unit
def test_a_discard_naming_no_keys_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # A caller that has not said what to act on. Nothing failed, and nothing in
    # the estate is wrong - but a tool called with nothing is a caller worth
    # looking at.
    Scenario() \
        .given(
            store := _a_store_reporting(0)
        ) \
        .when(
            attempting(
                lambda: discard_cache_entries((), store)
            )
        ) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.discarding", logging.WARNING,
                                  "no cache entries named")
        )


def _a_store(endpoint: str = SOME_ENDPOINT) -> Any:
    """The cache store's port, dialled at `endpoint`.

    `create_autospec` rather than a hand-written stub, so a port whose signature
    changes takes this with it instead of silently accepting the old call. Typed
    `Any` for the reason the restart's own double is: what the test needs back is
    both the port and the record of how it was called, and the protocol describes
    only the first.
    """
    store = create_autospec(CacheStore, instance=True)
    store.endpoint = endpoint

    return store


def _a_store_reporting(discarded: int) -> Any:
    """A store that answers, having removed `discarded` of what it was asked."""
    store = _a_store()
    store.discard.return_value = discarded

    return store


def _a_store_that_cannot_be_reached() -> Any:
    """A store that did not answer before anything was asked of it - the port's
    own word for a connection that was never had."""
    store = _a_store()
    store.discard.side_effect = StoreNotReached("connection refused")

    return store


def _a_store_lost_after_it_was_asked() -> Any:
    """A store that went once the discard was on its way.

    An arbitrary exception rather than a Redis one: what reaches this port is
    whatever the client raised, and a module catching one specific class would
    let every other way a connection fails escape as an unhandled error.
    """
    store = _a_store()
    store.discard.side_effect = OSError("connection reset by peer")

    return store


def _it_asked_once_for(keys: Sequence[str], store: Any) -> Assertion[object]:
    """One call, naming those keys in that order.

    The store is passed in because what is being asserted is how it was called
    rather than what came back - the same shape the restart's assertions about
    the action asked for have.
    """
    def assertion(dont_care_result: object) -> bool:
        if store.discard.call_count != 1:
            raise AssertionError(
                f"Expected the store to be asked once, and it was asked "
                f"{store.discard.call_count} times - a discard split across calls "
                f"is a partial one whenever any of them fails."
            )

        asked_for = store.discard.call_args.args

        if asked_for != (tuple(keys),):
            raise AssertionError(
                f"Expected the store to be asked for {tuple(keys)}, and it was "
                f"asked {asked_for} - these are addresses, so a set that arrived "
                f"reordered or short is a different set of entries."
            )

        return True

    return assertion


def _it_reported(discarded: int) -> Assertion[CacheEntriesDiscarded]:
    def assertion(result: CacheEntriesDiscarded) -> bool:
        if result.discarded != discarded:
            raise AssertionError(
                f"Expected the discard to report [{discarded}] entries removed, "
                f"got [{result.discarded}] - which is the figure an attempt is "
                f"confirmed from and the one the incident's account reads out."
            )

        return True

    return assertion


def _it_named(endpoint: str) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if error is None or endpoint not in str(error):
            raise AssertionError(
                f"Expected the failure to name the endpoint [{endpoint}] that "
                f"was dialled, and it said [{error}] - leaving a reader knowing "
                f"the cache is unreachable and unable to work out why."
            )

        return True

    return assertion


def _it_never_asked(store: Any) -> Assertion[Exception | None]:
    """That the store was not dialled at all.

    The point of the refusal rather than a detail of it: a call that reached the
    store and was rejected there is reported as a store that failed, and a
    caller reads that as a platform it should stop offering actions for.
    """
    def assertion(dont_care_error: Exception | None) -> bool:
        if store.discard.call_count:
            raise AssertionError(
                f"Expected the store never to be asked, and it was asked "
                f"{store.discard.call_count} times with no keys named."
            )

        return True

    return assertion


def _it_was_refused_as_the_platform_unreachable() -> Assertion[Exception | None]:
    """The failure is of the unreachable-platform kind, naming the store, so a
    caller narrows itself rather than retrying.

    A store that did not answer takes every action through it away at once, and
    the kind is how that travels: without it the walk reads this as one action
    that failed and goes on offering the same action again.
    """
    def assertion(error: Exception | None) -> bool:
        refusal = error.refusal if isinstance(error, ToolRefused) else None
        kind = refusal.kind if refusal is not None else None
        platform = refusal.platform if refusal is not None else None

        if kind is not ToolRefusalKind.PLATFORM_UNREACHABLE or platform != CACHE:
            raise AssertionError(
                f"Expected the failure to be refused as the [{CACHE}] platform "
                f"being unreachable, and it was [{kind}] naming [{platform}]: "
                f"[{error}]."
            )

        return True

    return assertion


def _it_was_refused_as_exhausted() -> Assertion[Exception | None]:
    """The refusal is of the kind of an action with nothing left to do.

    The other half of the pair this file is about. An exhausted action and an
    unreachable platform both leave the shop unchanged, and a walk does opposite
    things with them: one moves to the next candidate, the other stops offering
    anything on that platform at all. The kind is how they are told apart, and
    a refusal of neither reads as an error nobody classified.
    """
    def assertion(error: Exception | None) -> bool:
        kind = error.refusal.kind if isinstance(error, ToolRefused) else None

        if kind is not ToolRefusalKind.EXHAUSTED:
            raise AssertionError(
                f"Expected the refusal to be of an exhausted action, and it was "
                f"[{kind}]: [{error}] - otherwise, a walk cannot tell a store with "
                f"nothing left to remove from one it could not reach."
            )

        return True

    return assertion
