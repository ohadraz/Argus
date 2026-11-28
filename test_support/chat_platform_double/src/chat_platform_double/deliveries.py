"""Deliveries as this platform sends them: Argus's own `Delivery`, written as
JSON naming which it is, and signed over the moment it was sent and its bytes.

Signed with an HMAC-SHA256 under headers of its own: the double proves nothing
to anybody, but a signature is the one construction worth copying correctly,
and the moment is under it so that a delivery recorded and sent again later
gives itself away by its age.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Final

from chat_platform import Delivery

# Where this double's signature and the moment it covers travel: headers no
# platform sends, so a delivery signed for another platform is unsigned here.
SIGNATURE_HEADER: Final = "X-Chat-Double-Signature"
SENT_AT_HEADER: Final = "X-Chat-Double-Sent-At"

# Which of the four a delivery is, beside its own fields.
KIND: Final = "kind"


def headers_signing(body: bytes, secret: str, at: datetime) -> dict[str, str]:
    """The headers signing `body` under `secret`, as sent at `at`."""
    sent_at = str(int(at.timestamp()))

    return {SENT_AT_HEADER: sent_at, SIGNATURE_HEADER: _signature(body, secret, sent_at)}


def a_delivery_of(said: Delivery,
                  *,
                  signed_with: str,
                  at: datetime) -> tuple[bytes, dict[str, str]]:
    """`said` as this platform delivers it, and the headers signing exactly
    those bytes as sent at `at`."""
    body = json.dumps({KIND: type(said).__name__, **said.model_dump(mode="json")}).encode()

    return body, headers_signing(body, signed_with, at)


def _signature(body: bytes, secret: str, sent_at: str) -> str:
    return hmac.new(secret.encode(), f"{sent_at}:".encode() + body, hashlib.sha256).hexdigest()
