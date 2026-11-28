"""The push source's port, as every sender of pushes answers it.

What the port promises, asked of each adapter over one thing sent, which each
is delivered written and signed as its own sender does it: the GitHub adapter
over GitHub's push webhook (`framework.github_world`), and the double over
Argus's own push (`push_source_double`). A promise one keeps and the other does
not fails here, so the double cannot drift from the port, and the port names
nothing only GitHub's wire could answer.

The promises and nothing beyond them. GitHub's two content types, its ping, a
header name cased otherwise, and what is logged are the wire suite's
(`test_github.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from argus_testkit import Scenario, an_error_was_raised, attempting, the_answer_was
from push_source import Pushed, PushSource, PushUnreadable, PushUnverified
from push_source.github import GitHubPushes
from push_source_double import PushesAsArgusWrites, a_delivery_of, headers_signing

from push_source_test.framework.github_world import as_github_sends, as_github_signs

THE_SECRET = "the-secret"
SOME_OTHER_SECRET = "some-other-secret"
NO_SECRET = ""

SOME_PUSH = Pushed(repository="some-owner/some-repository",
                   ref="refs/heads/some-branch",
                   after="0123456789abcdef0123456789abcdef01234567")


@dataclass(frozen=True)
class _Sender:
    """One row: a sender verifying under the secret it is built with, how what
    it is sent is written and signed as it sends it, and how it signs any bytes
    at all."""

    built: Callable[[str], PushSource]
    sends: Callable[..., tuple[bytes, dict[str, str]]]
    signs: Callable[[bytes, str], dict[str, str]]


EVERY_SENDER = pytest.mark.parametrize("sender", [
    pytest.param(_Sender(PushesAsArgusWrites, a_delivery_of, headers_signing), id="in-memory"),
    pytest.param(_Sender(GitHubPushes, as_github_sends, as_github_signs), id="github")
])

NO_PUSH_AT_ALL = pytest.mark.parametrize("body", [
    pytest.param(b"\xff", id="not-text"),
    pytest.param(b"not json at all", id="not-json"),
    pytest.param(b"[]", id="a-list"),
    pytest.param(b'"some string"', id="a-string")
])


@pytest.mark.unit
@EVERY_SENDER
def test_a_push_sent_and_signed_is_the_push_read(sender: _Sender) -> None:
    Scenario() \
        .given(delivery := sender.sends(SOME_PUSH, signed_with=THE_SECRET)) \
        .when(lambda: sender.built(THE_SECRET).parse_delivery(*delivery)) \
        .then(the_answer_was(SOME_PUSH))


@pytest.mark.unit
@EVERY_SENDER
def test_a_signed_delivery_naming_no_commit_is_no_push(sender: _Sender) -> None:
    Scenario() \
        .given(delivery := sender.sends(None, signed_with=THE_SECRET)) \
        .when(lambda: sender.built(THE_SECRET).parse_delivery(*delivery)) \
        .then(the_answer_was(None))


@pytest.mark.unit
@EVERY_SENDER
def test_a_delivery_carrying_no_signature_is_unverified(sender: _Sender) -> None:
    Scenario() \
        .given(delivery := sender.sends(SOME_PUSH, signed_with=THE_SECRET)) \
        .when(attempting(lambda: sender.built(THE_SECRET).parse_delivery(delivery[0], {}))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
@EVERY_SENDER
def test_a_delivery_signed_with_another_secret_is_unverified(sender: _Sender) -> None:
    Scenario() \
        .given(delivery := sender.sends(SOME_PUSH, signed_with=SOME_OTHER_SECRET)) \
        .when(attempting(lambda: sender.built(THE_SECRET).parse_delivery(*delivery))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
@EVERY_SENDER
def test_a_delivery_altered_after_it_was_signed_is_unverified(sender: _Sender) -> None:
    # The signature is over the bytes that were sent, and a space is a
    # different document.
    Scenario() \
        .given(delivery := sender.sends(SOME_PUSH, signed_with=THE_SECRET)) \
        .when(attempting(lambda: sender.built(THE_SECRET).parse_delivery(
            delivery[0] + b" ", delivery[1]
        ))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
@EVERY_SENDER
def test_a_sender_holding_no_secret_refuses_even_a_delivery_signed_with_none(
    sender: _Sender
) -> None:
    # A signature under an empty key is one anybody can make, so a deployment
    # that set no secret trusts nothing rather than everything.
    Scenario() \
        .given(delivery := sender.sends(SOME_PUSH, signed_with=NO_SECRET)) \
        .when(attempting(lambda: sender.built(NO_SECRET).parse_delivery(*delivery))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
@EVERY_SENDER
@NO_PUSH_AT_ALL
def test_a_signed_delivery_that_is_no_push_is_unreadable(sender: _Sender, body: bytes) -> None:
    # The sender's own, and not something to read as "no news": a push it
    # cannot read is news it needs, so the sender is told.
    Scenario() \
        .given(headers := sender.signs(body, THE_SECRET)) \
        .when(attempting(lambda: sender.built(THE_SECRET).parse_delivery(body, headers))) \
        .then(an_error_was_raised(PushUnreadable))


@pytest.mark.unit
@EVERY_SENDER
@NO_PUSH_AT_ALL
def test_an_unsigned_delivery_is_unverified_before_it_is_read(sender: _Sender,
                                                              body: bytes) -> None:
    # Verified over the bytes before any of them is read: a body nobody signed
    # is refused for that, whatever it holds.
    Scenario() \
        .when(attempting(lambda: sender.built(THE_SECRET).parse_delivery(body, {}))) \
        .then(an_error_was_raised(PushUnverified))
