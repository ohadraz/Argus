"""A push, written and signed as GitHub sends it.

The one writer of GitHub's push delivery in this suite: the wire suite builds
its deliveries here, and the port's suite writes what was sent through it for
the GitHub adapter, beside the double over its own writing of the same thing.
Every word of GitHub's it speaks that the adapter reads is imported from the
adapter, so the two cannot spell one differently.

How a push is written: its ref, the commit it moved to, and its repository
under its full name, as JSON - the body itself, or the payload of a form -
signed under GitHub's scheme over exactly the bytes sent. A delivery naming no
commit is GitHub's ping.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Final
from urllib.parse import urlencode

from push_source import Pushed
from push_source.github import (
    AFTER_FIELD,
    CONTENT_TYPE_HEADER,
    FORM_CONTENT_TYPE,
    FULL_NAME_FIELD,
    PAYLOAD_FIELD,
    REF_FIELD,
    REPOSITORY_FIELD,
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
)

# The words of GitHub's ping the adapter never reads: what it says, and which
# webhook sent it. Declared here, once, for every suite that writes one.
ZEN: Final = "zen"
HOOK_ID: Final = "hook_id"


def a_signature_over(body: bytes, secret: str) -> str:
    """GitHub's signature over `body`: an HMAC-SHA256 under the secret, in hex,
    after its prefix."""
    return SIGNATURE_PREFIX + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def as_github_signs(body: bytes, secret: str) -> dict[str, str]:
    """The header GitHub signs `body` in, under `secret`."""
    return {SIGNATURE_HEADER: a_signature_over(body, secret)}


def as_github_sends(sent: Pushed | None,
                    *,
                    signed_with: str,
                    as_a_form: bool = False) -> tuple[bytes, dict[str, str]]:
    """`sent` as GitHub delivers it - a push, or a ping for a delivery naming no
    commit - and the headers signing exactly those bytes.

    `as_a_form` sends it as a webhook set to GitHub's form content type does:
    the JSON as the form field `payload`, encoded as a form is, under a header
    saying so. The JSON is written with `json`'s own separators, which carry
    spaces, so the encoded form carries `+`.

    Signed here rather than by the caller, because the signature is over these
    bytes: a writer that handed back a document for the caller to serialize
    would sign a different document than it hands over.
    """
    payload = json.dumps(
        {ZEN: "Keep it logically awesome.", HOOK_ID: 1}
        if sent is None
        else {REF_FIELD: sent.ref,
              AFTER_FIELD: sent.after,
              REPOSITORY_FIELD: {FULL_NAME_FIELD: sent.repository}}
    )

    if not as_a_form:
        body = payload.encode()

        return body, as_github_signs(body, signed_with)

    body = urlencode({PAYLOAD_FIELD: payload}).encode()

    return body, {CONTENT_TYPE_HEADER: FORM_CONTENT_TYPE, **as_github_signs(body, signed_with)}
