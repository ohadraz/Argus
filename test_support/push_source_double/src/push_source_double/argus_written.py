"""Pushes written as Argus's own `Pushed` is, signed, and read back.

Everything it says is what the port promises and its suite pins over both
adapters: a push sent and signed is the push read, a signed delivery naming no
commit is `None`, a signed delivery that is no push is `PushUnreadable`, and a
delivery not signed with its secret as it arrived - unsigned, signed with
another secret, or altered after it was signed - is `PushUnverified`, refused
before a byte of it is read. Holding no secret, it refuses every delivery.

Signed with an HMAC-SHA256 under a header of its own: the double proves nothing
to anybody, but a signature is the one construction worth copying correctly.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Final

from push_source import Pushed, PushUnreadable, PushUnverified

# Where this double's signature travels: a header no host sends, so a delivery
# signed for another sender is unsigned here.
SIGNATURE_HEADER: Final = "X-Push-Double-Signature"


def headers_signing(body: bytes, secret: str) -> dict[str, str]:
    """The header signing `body` under `secret`, as this double signs."""
    return {SIGNATURE_HEADER: hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}


def a_delivery_of(sent: Pushed | None, *, signed_with: str) -> tuple[bytes, dict[str, str]]:
    """`sent` as this sender delivers it - the push's own fields, or an empty
    object for one naming no commit - and the header signing exactly those
    bytes."""
    body = json.dumps({} if sent is None else dataclasses.asdict(sent)).encode()

    return body, headers_signing(body, signed_with)


class PushesAsArgusWrites:
    """A `PushSource` whose deliveries are Argus's own pushes, signed with
    `secret`."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def parse_delivery(self, body: bytes, headers: Mapping[str, str], /) -> Pushed | None:
        """The push a verified delivery says, `None` where it names no commit,
        or `PushUnreadable` where it is no push of this sender's writing."""
        # An empty secret refuses everything: anybody can sign under it.
        if not self._secret:
            raise PushUnverified("no secret is held, so no delivery can be trusted")

        # Header names are case-insensitive, and a web framework may hand them
        # over lower-cased.
        signature = next((value for name, value in headers.items()
                          if name.lower() == SIGNATURE_HEADER.lower()), None)
        expected = headers_signing(body, self._secret)[SIGNATURE_HEADER]

        if signature is None or not hmac.compare_digest(signature, expected):
            raise PushUnverified("the delivery is not signed with this double's secret")

        # `ValueError` for bytes that are no text or no JSON, `TypeError` for
        # JSON that is no object of a push's own fields.
        try:
            sent = json.loads(body)

            return None if sent == {} else Pushed(**sent)
        except (ValueError, TypeError) as unreadable:
            raise PushUnreadable(repr(unreadable)) from unreadable
