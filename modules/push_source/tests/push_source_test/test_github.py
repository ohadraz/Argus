"""GitHub's push webhook, verified and read into a `Pushed`.

What it must get right is the order. GitHub signs the delivery, and the
signature covers the bytes that arrived rather than anything parsed out of
them, so verification comes before the body is read at all: a payload that was
decoded, validated and only then checked is a payload that already ran through
a parser on an unauthenticated caller's say-so.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlencode

import pytest
from argus_testkit.assertions import an_error_was_raised, the_answer_was
from argus_testkit.logs import one_record_was_logged
from argus_testkit.scenario import Scenario, attempting
from push_source import Pushed, PushUnreadable, PushUnverified
from push_source.github import (
    AFTER_FIELD,
    CONTENT_TYPE_HEADER,
    FORM_CONTENT_TYPE,
    REF_FIELD,
    REPOSITORY_FIELD,
    GitHubPushes,
)

from push_source_test.framework.github_world import as_github_sends, as_github_signs

THE_REPOSITORY = "ohadraz/Argus-Demo-Target-App"
THE_REF = "refs/heads/main"
THE_COMMIT_PUSHED = "77296acf1d2b4e5a6c7d8e9f0a1b2c3d4e5f6a7b"
THE_PUSH = Pushed(repository=THE_REPOSITORY, ref=THE_REF, after=THE_COMMIT_PUSHED)

SOME_SECRET = "a-webhook-secret"


@pytest.mark.unit
def test_a_signed_push_is_read_as_the_ref_it_moved_and_the_commit_it_moved_to() -> None:
    body, headers = as_github_sends(THE_PUSH, signed_with=SOME_SECRET)

    Scenario() \
        .when(lambda: GitHubPushes(SOME_SECRET).parse_delivery(body, headers)) \
        .then(the_answer_was(THE_PUSH))


@pytest.mark.unit
def test_a_signature_under_a_header_name_cased_otherwise_is_read() -> None:
    # Header names are case-insensitive, and a web framework may hand them on
    # lower-cased.
    body, headers = as_github_sends(THE_PUSH, signed_with=SOME_SECRET)
    lower_cased = {name.lower(): value for name, value in headers.items()}

    Scenario() \
        .when(lambda: GitHubPushes(SOME_SECRET).parse_delivery(body, lower_cased)) \
        .then(the_answer_was(THE_PUSH))


@pytest.mark.unit
def test_an_unsigned_delivery_is_refused() -> None:
    # This endpoint is open to the internet, and what it reads is what the
    # index chases.
    body, _ = as_github_sends(THE_PUSH, signed_with=SOME_SECRET)

    Scenario() \
        .when(attempting(lambda: GitHubPushes(SOME_SECRET).parse_delivery(body, {}))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
def test_a_delivery_signed_with_the_wrong_secret_is_refused() -> None:
    body, headers = as_github_sends(THE_PUSH, signed_with="not-the-secret")

    Scenario() \
        .when(attempting(lambda: GitHubPushes(SOME_SECRET).parse_delivery(body, headers))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
def test_a_signature_over_different_bytes_than_arrived_is_refused() -> None:
    # The signature covers what was sent, byte for byte. A body re-serialized
    # on the way in - a key reordered, a space added - is a different document
    # and has a different digest, which is why nothing may parse it first and
    # verify the result.
    body, headers = as_github_sends(THE_PUSH, signed_with=SOME_SECRET)

    Scenario() \
        .when(attempting(lambda: GitHubPushes(SOME_SECRET).parse_delivery(body + b" ", headers))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
def test_an_unsigned_delivery_is_refused_before_its_body_is_read() -> None:
    # The order is the security property: a body that is not even JSON must
    # come back as a refused signature rather than as a parse error.
    not_even_json = b"not json at all"

    Scenario() \
        .when(attempting(lambda: GitHubPushes(SOME_SECRET).parse_delivery(not_even_json, {}))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
def test_a_deployment_that_set_no_secret_refuses_even_a_delivery_signed_with_none() -> None:
    # A digest under an empty key is one anybody can compute. Without this, the
    # deployment that configured nothing would accept every delivery signed with
    # nothing - the wrong way round for an endpoint open to the internet.
    no_secret = ""
    body, headers = as_github_sends(THE_PUSH, signed_with=no_secret)

    Scenario() \
        .when(attempting(lambda: GitHubPushes(no_secret).parse_delivery(body, headers))) \
        .then(an_error_was_raised(PushUnverified))


@pytest.mark.unit
def test_a_signed_delivery_naming_no_commit_is_no_push() -> None:
    # GitHub's ping, sent when the webhook is created: signed, and news of
    # nothing.
    a_ping, headers = as_github_sends(None, signed_with=SOME_SECRET)

    Scenario() \
        .when(lambda: GitHubPushes(SOME_SECRET).parse_delivery(a_ping, headers)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_a_delivery_signed_with_the_wrong_secret_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Two very different stories - a secret rotated on one side only, or
    # somebody who is not GitHub - and whether it was signed at all is the
    # first thing that tells them apart.
    body, headers = as_github_sends(THE_PUSH, signed_with="not-the-secret")

    Scenario() \
        .when(attempting(lambda: GitHubPushes(SOME_SECRET).parse_delivery(body, headers))) \
        .then(
            one_record_was_logged(caplog, "push_source.github", logging.WARNING,
                                  "push signature rejected",
                                  values={"signed": True})
        )


@pytest.mark.unit
def test_a_push_sent_as_a_form_is_read_from_its_payload_field() -> None:
    # The content type a webhook made through GitHub's API sends by default.
    # Encoded as a form is, so the spaces in the payload arrive as `+`: a
    # reader that unquoted the field rather than parsing the form would keep
    # them, and read no JSON.
    body, headers = as_github_sends(THE_PUSH, signed_with=SOME_SECRET, as_a_form=True)

    Scenario() \
        .when(lambda: GitHubPushes(SOME_SECRET).parse_delivery(body, headers)) \
        .then(the_answer_was(THE_PUSH))


@pytest.mark.unit
def test_a_signed_form_carrying_no_payload_is_unreadable() -> None:
    a_form_of_something_else = urlencode({"something_else": "dont-care"}).encode()

    Scenario() \
        .when(attempting(lambda: GitHubPushes(SOME_SECRET).parse_delivery(
            a_form_of_something_else,
            {CONTENT_TYPE_HEADER: FORM_CONTENT_TYPE,
             **as_github_signs(a_form_of_something_else, SOME_SECRET)}
        ))) \
        .then(an_error_was_raised(PushUnreadable))


@pytest.mark.unit
def test_a_signed_push_whose_repository_is_no_object_is_unreadable() -> None:
    # GitHub names a repository by an object holding its full name; one named
    # by anything else is a delivery whose repository nothing here can read.
    a_repository_named_bare = json.dumps({
        REF_FIELD: THE_REF,
        AFTER_FIELD: THE_COMMIT_PUSHED,
        REPOSITORY_FIELD: THE_REPOSITORY
    }).encode()

    Scenario() \
        .when(attempting(lambda: GitHubPushes(SOME_SECRET).parse_delivery(
            a_repository_named_bare, as_github_signs(a_repository_named_bare, SOME_SECRET)
        ))) \
        .then(an_error_was_raised(PushUnreadable))
