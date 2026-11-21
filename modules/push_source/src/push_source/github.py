"""GitHub as a sender of pushes: its push webhook, verified and read into a
`Pushed`, and the only module that knows its header, its signature scheme or a
field of its payload.

Order is the whole of the security here. GitHub signs the bytes it sent, not
anything parsed out of them, so the signature is checked before the body is
read at all: a payload decoded, validated and only then verified is a payload
that ran through a parser on an unauthenticated caller's say-so.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from typing import Any, Final

from push_source.failures import PushUnverified
from push_source.port import Pushed

logger = logging.getLogger(__name__)

# GitHub's wire vocabulary for a push, named for the fields that carry it.
# `AFTER_FIELD` is the load-bearing one: it is the commit the branch now
# points at, which is the whole of what the endpoint exists to record.
REF_FIELD: Final = "ref"
AFTER_FIELD: Final = "after"
REPOSITORY_FIELD: Final = "repository"
FULL_NAME_FIELD: Final = "full_name"

# The header the delivery is signed in, and how that signature is spelled.
SIGNATURE_HEADER: Final = "X-Hub-Signature-256"
SIGNATURE_PREFIX: Final = "sha256="


class GitHubPushes:
    """GitHub, as a sender of pushes.

    Holds the secret GitHub signs each delivery with and nothing else: no
    credential that reads or writes a repository, since nothing here fetches
    anything. Built where the web application is wired, and handed on typed as
    `PushSource`.
    """

    def __init__(self, webhook_secret: str) -> None:
        self._webhook_secret = webhook_secret

    def parse_delivery(self, body: bytes, headers: Mapping[str, str], /) -> Pushed | None:
        """The ref a verified delivery moved, and the commit it moved to.

        `None` for a verified delivery naming no commit: GitHub's ping, sent
        when the webhook is created, is one, and is news of nothing."""
        _verified(body, _the_header(headers, SIGNATURE_HEADER), self._webhook_secret)

        push = json.loads(body)
        after = push.get(AFTER_FIELD)

        if after is None:
            return None

        return Pushed(repository=_the_repository_of(push),
                      ref=str(push.get(REF_FIELD, "")),
                      after=str(after))


def _verified(body: bytes, signature: str | None, secret: str) -> None:
    """That these bytes were signed with the secret, or the refusal that they
    were not.

    An empty secret refuses everything: it is a deployment that never set one,
    and a digest under an empty key is one anybody can compute - so without
    this, the deployment that configured nothing would accept every delivery
    signed with nothing.

    `compare_digest` rather than `==`: a comparison that returns early on the
    first wrong byte tells an attacker how much of a guess was right, and a
    signature can be guessed a byte at a time by anybody who can time the
    answer.
    """
    if not secret:
        logger.warning("push refused: no webhook secret is configured")
        raise PushUnverified(
            "no webhook secret is configured, so no delivery can be trusted"
        )

    expected = SIGNATURE_PREFIX + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    if signature is None or not hmac.compare_digest(expected, signature):
        logger.warning("push signature rejected", extra={"signed": signature is not None})
        raise PushUnverified(
            "the delivery is not signed with this deployment's webhook secret"
        )


def _the_header(headers: Mapping[str, str], name: str) -> str | None:
    """One header, however the server that received it cased the name.

    HTTP header names are case-insensitive, and a web framework's mapping may
    hand them over lower-cased.
    """
    wanted = name.lower()

    return next((value for key, value in headers.items() if key.lower() == wanted), None)


def _the_repository_of(push: dict[str, Any]) -> str:
    """Which repository the delivery is about, as it names itself."""
    repository = push.get(REPOSITORY_FIELD) or {}

    return str(repository.get(FULL_NAME_FIELD, ""))
