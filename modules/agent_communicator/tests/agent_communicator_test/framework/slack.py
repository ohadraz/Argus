"""Reading back what the Slack double actually holds.

Through the double's control seam rather than through anything of Argus's: what
these tests claim is that a message arrived, and asking the code under test
whether it sent one would be asking the wrong party.
"""

from __future__ import annotations

from typing import Any

import httpx


def messages_posted_to(base_url: str) -> list[dict[str, Any]]:
    """Every message the double accepted, oldest first."""
    answered: dict[str, Any] = httpx.get(f"{base_url}/double-control/posted").json()
    held: list[dict[str, Any]] = answered["posted"]

    return held
