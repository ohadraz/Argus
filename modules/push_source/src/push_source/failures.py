"""How a sender's adapter refuses a delivery it cannot vouch for."""

from __future__ import annotations


class PushUnverified(Exception):
    """The delivery did not come from the code host, or did not arrive intact.

    Raised rather than answered quietly, because the two things the endpoint
    can do are record a commit and refuse - and a refusal that looked like an
    accepted push would leave whoever configured the webhook believing the
    index is being told about their work.
    """
