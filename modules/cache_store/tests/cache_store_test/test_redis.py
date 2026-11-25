"""The cache store, as a Redis answers for it.

What the adapter decides is the order things are asked in and what each failure
is called. A store that is not there must be told apart from one that went once
the discard was on its way, because the first left the entries where they were
and the second may not have - and the client is let go whichever happened, since
nothing here holds a connection between actions.

The client itself is stood in for: that a real Redis answers to it is only true
or false against a real one, and the end-to-end stack is where one exists.
"""

from __future__ import annotations

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
    the_answer_was,
)
from cache_store import StoreNotReached
from cache_store.redis import RedisSettings, RedisStore, StoreClient, a_redis_at

SOME_CACHE_URL = "redis://cache.invalid:6379"
# Spelled as the store spells them. A placeholder would hide the one mistake
# these tests exist to catch - a seam that reordered or dropped an address.
SOME_KEYS = ("io-shop:summary:shopper-7", "io-shop:summary:shopper-2")


@pytest.mark.unit
def test_a_store_that_does_not_answer_before_the_discard_is_not_reached() -> None:
    # Asked before the discard, so a store that is not there is told apart
    # from one that went once the discard was on its way.
    client = _a_store_client()
    client.ping.side_effect = ConnectionError("connection refused")

    Scenario() \
        .given(store := _a_redis_reached_through(client)) \
        .when(attempting(lambda: store.discard(SOME_KEYS))) \
        .then(all_of(
            an_error_was_raised(StoreNotReached),
            _nothing_was_unlinked(client),
            _it_was_closed(client)
        ))


@pytest.mark.unit
def test_a_store_whose_client_cannot_be_built_is_not_reached() -> None:
    # An address the client cannot be built from was never dialled, so nothing
    # was asked of the store.
    Scenario() \
        .given(store := RedisStore(_some_settings(),
                                   connect=_a_client_that_cannot_be_built)) \
        .when(attempting(lambda: store.discard(SOME_KEYS))) \
        .then(an_error_was_raised(StoreNotReached))


@pytest.mark.unit
def test_a_store_lost_once_the_discard_was_asked_for_is_raised_as_it_came() -> None:
    # Not "not reached": the entries may have gone, and the caller must not
    # be told nothing changed.
    client = _a_store_client()
    client.unlink.side_effect = ConnectionError("connection reset by peer")

    Scenario() \
        .given(store := _a_redis_reached_through(client)) \
        .when(attempting(lambda: store.discard(SOME_KEYS))) \
        .then(all_of(
            an_error_was_raised(ConnectionError),
            _it_was_not_said_to_be_unreached(),
            _it_was_closed(client)
        ))


@pytest.mark.unit
def test_a_store_that_answered_says_how_many_went_and_is_let_go() -> None:
    client = _a_store_client()
    client.unlink.return_value = len(SOME_KEYS) - 1

    Scenario() \
        .given(store := _a_redis_reached_through(client)) \
        .when(lambda: store.discard(SOME_KEYS)) \
        .then(all_of(
            the_answer_was(len(SOME_KEYS) - 1),
            _it_was_closed(client)
        ))


@pytest.mark.unit
def test_every_key_is_unlinked_in_one_call_and_in_the_order_it_was_given() -> None:
    # The order is the evidence's, and a call per key would be a partial
    # discard whenever any of them failed.
    client = _a_store_client()
    client.unlink.return_value = len(SOME_KEYS)

    Scenario() \
        .given(store := _a_redis_reached_through(client)) \
        .when(lambda: store.discard(SOME_KEYS)) \
        .then(_it_unlinked_once(client, SOME_KEYS))


@pytest.mark.unit
def test_the_store_is_dialled_at_the_address_the_deployment_configured() -> None:
    # The address a refusal names is the endpoint, so the endpoint has to be
    # the address that was actually dialled - or a reader comparing the two is
    # comparing the wrong thing.
    client = _a_store_client()
    connect = create_autospec(a_redis_at, return_value=client)

    Scenario() \
        .given(store := RedisStore(_some_settings(SOME_CACHE_URL), connect=connect)) \
        .when(lambda: store.discard(SOME_KEYS)) \
        .then(all_of(
            _it_was_dialled_at(connect, SOME_CACHE_URL),
            _its_endpoint_is(store, SOME_CACHE_URL)
        ))


@pytest.mark.unit
def test_the_settings_carry_the_endpoint_and_no_credential() -> None:
    # A cache the shop keeps needs an address and nothing else here has a use
    # for one - and settings that named the platform's token would be this
    # adapter able to reach the deployment platform, which it has no business
    # touching.
    Scenario() \
        .given(
            settings := _some_settings()
        ) \
        .when(lambda: set(settings.model_dump())) \
        .then(_it_carries_exactly({"cache_url"}))


@pytest.mark.unit
def test_the_store_is_configured_by_the_variable_it_always_was(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    # The name a deployment already sets, unchanged by the move out of the
    # kernel's `Settings` - a renamed variable is a deployment that silently
    # falls back to its default.
    some_cache_url = "redis://kuki.invalid:6380"

    Scenario() \
        .given(
            calling(lambda: monkeypatch.setenv("CACHE_URL", some_cache_url))
        ) \
        .when(lambda: RedisSettings()) \
        .then(the_answer_was(RedisSettings(cache_url=some_cache_url)))


@pytest.mark.unit
def test_an_unconfigured_store_is_the_demos() -> None:
    # The default the kernel's `Settings` declared before the setting moved,
    # spelled out because there is nothing left to derive it from. Read off
    # the declared default rather than off a `RedisSettings()`, which would
    # read the developer's own environment. The port the demo's cache is
    # published on, which is not the address the shop dials it at.
    the_demos_cache = "redis://localhost:6379"

    Scenario() \
        .when(lambda: RedisSettings.model_construct().model_dump()) \
        .then(the_answer_was({"cache_url": the_demos_cache}))


def _some_settings(cache_url: str = SOME_CACHE_URL) -> RedisSettings:
    return RedisSettings(cache_url=cache_url)


def _a_redis_reached_through(client: StoreClient) -> RedisStore:
    """A store whose every connection is `client`."""
    return RedisStore(_some_settings(), connect=lambda dont_care_url: client)


def _a_store_client() -> Any:
    """A store's client, answering every ping. `Any` because what a test needs
    back is both the client and the record of how it was called, and the
    protocol describes only the first."""
    return create_autospec(StoreClient, instance=True)


def _a_client_that_cannot_be_built(dont_care_url: str) -> StoreClient:
    """What Redis's client does with an address in a scheme it does not know."""
    raise ValueError("Redis URL must specify one of the following schemes")


def _nothing_was_unlinked(client: Any) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        if client.unlink.called:
            raise AssertionError(
                f"Expected nothing to be discarded from a store that did not answer, "
                f"and it was asked {client.unlink.call_args_list}."
            )

        return True

    return assertion


def _it_was_closed(client: Any) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        if client.close.call_count != 1:
            raise AssertionError(
                f"Expected the client closed once, and it was closed "
                f"{client.close.call_count} times."
            )

        return True

    return assertion


def _it_was_not_said_to_be_unreached() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if isinstance(raised, StoreNotReached):
            raise AssertionError(
                f"Expected the failure raised as it came, and it was called a store "
                f"not reached: [{raised}]."
            )

        return True

    return assertion


def _it_unlinked_once(client: Any, keys: tuple[str, ...]) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        asked = [each.args for each in client.unlink.call_args_list]

        if asked != [keys]:
            raise AssertionError(
                f"Expected one unlink naming {keys} in that order, and the client "
                f"was asked {asked}."
            )

        return True

    return assertion


def _it_was_dialled_at(connect: Any, expected: str) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        dialled = [each.args for each in connect.call_args_list]

        if dialled != [(expected,)]:
            raise AssertionError(
                f"Expected the store dialled once at [{expected}], and it was "
                f"dialled {dialled}."
            )

        return True

    return assertion


def _its_endpoint_is(store: RedisStore, expected: str) -> Assertion[object]:
    def assertion(dont_care: object) -> bool:
        if store.endpoint != expected:
            raise AssertionError(
                f"Expected the store's endpoint to be [{expected}], the address it "
                f"dials, and it says [{store.endpoint}]."
            )

        return True

    return assertion


def _it_carries_exactly(fields: set[str]) -> Assertion[set[str]]:
    def assertion(carried: set[str]) -> bool:
        if carried != fields:
            raise AssertionError(
                f"Expected the settings to carry exactly {sorted(fields)}, and they "
                f"carry {sorted(carried)}."
            )

        return True

    return assertion
