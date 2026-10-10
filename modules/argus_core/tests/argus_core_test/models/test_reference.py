"""The names a chat platform gives a place in a conversation about an incident.

A thread, a person's message in it, and the offer Argus posts there are each
one of the incident's references, so that a message arriving later finds its
incident through the same lookup a paging tool's word does. Each is a channel
and a message within it, written into one value - and that value is written by
the relay, read by the web endpoint, and held unique per channel by the schema.
Three readers of one spelling is why it is spelled in one place, and why that
place promises to read back exactly what it was given.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from argus_core.models import (
    CHAT_MESSAGE,
    CHAT_OFFER,
    CHAT_THREAD,
    Reference,
    a_chat_message,
    a_chat_offer,
    a_chat_thread,
    the_place_of,
)
from argus_testkit import Assertion, Scenario, all_of

SOME_PLATFORM = "some-chat"
SOME_CHANNEL = "C-some-channel"
SOME_MESSAGE = "1700000000.000100"

type PlaceInAChat = Callable[[str, str, str], Reference]


@pytest.mark.unit
@pytest.mark.parametrize("built_by", [a_chat_thread, a_chat_message, a_chat_offer],
                         ids=["thread", "message", "offer"])
def test_a_place_in_a_chat_reads_back_as_the_channel_and_message_it_was_built_from(
        built_by: PlaceInAChat) -> None:
    # A reply in a thread is answered in that thread, which is only possible if
    # the channel and the message come back out exactly as they went in - a
    # message id rounded or split in the wrong place addresses nothing.
    Scenario() \
        .given(a_place := built_by(SOME_PLATFORM, SOME_CHANNEL, SOME_MESSAGE)) \
        .when(lambda: the_place_of(a_place.value)) \
        .then(_it_is_the_place((SOME_CHANNEL, SOME_MESSAGE)))


@pytest.mark.unit
@pytest.mark.parametrize(("built_by", "kind"), [
    (a_chat_thread, CHAT_THREAD),
    (a_chat_message, CHAT_MESSAGE),
    (a_chat_offer, CHAT_OFFER)
], ids=["thread", "message", "offer"])
def test_a_place_in_a_chat_is_the_platforms_and_of_its_own_kind(built_by: PlaceInAChat,
                                                                 kind: str) -> None:
    # A thread and a message in it can be the same channel and the same id -
    # the opening message of a thread is the thread - so only the kind tells
    # them apart, and only the source tells one platform's from another's.
    Scenario() \
        .when(lambda: built_by(SOME_PLATFORM, SOME_CHANNEL, SOME_MESSAGE)) \
        .then(all_of(_its_kind_is(kind), _its_source_is(SOME_PLATFORM)))


@pytest.mark.unit
def test_a_thread_its_opening_message_and_an_offer_on_it_are_three_references() -> None:
    # The opening message of a thread is the thread - the same channel and the
    # same id - so were two of these alike, a lookup for one would find another.
    Scenario() \
        .when(lambda: [built_by(SOME_PLATFORM, SOME_CHANNEL, SOME_MESSAGE)
                       for built_by in (a_chat_thread, a_chat_message, a_chat_offer)]) \
        .then(_no_two_are_alike())


def _it_is_the_place(expected: tuple[str, str]) -> Assertion[tuple[str, str]]:
    def assertion(place: tuple[str, str]) -> bool:
        if place != expected:
            raise AssertionError(
                f"Expected the place to read back as {expected}, got {place}."
            )

        return True

    return assertion


def _its_kind_is(expected: str) -> Assertion[Reference]:
    def assertion(reference: Reference) -> bool:
        if reference.kind != expected:
            raise AssertionError(
                f"Expected a reference of kind [{expected}], got [{reference.kind}]."
            )

        return True

    return assertion


def _its_source_is(expected: str) -> Assertion[Reference]:
    def assertion(reference: Reference) -> bool:
        if reference.source != expected:
            raise AssertionError(
                f"Expected a reference from [{expected}], got [{reference.source}]."
            )

        return True

    return assertion


def _no_two_are_alike() -> Assertion[list[Reference]]:
    def assertion(references: list[Reference]) -> bool:
        alike = [(one, other) for at, one in enumerate(references)
                 for other in references[at + 1:] if one == other]

        if alike:
            raise AssertionError(f"Expected no two references alike, got {alike}.")

        return True

    return assertion
