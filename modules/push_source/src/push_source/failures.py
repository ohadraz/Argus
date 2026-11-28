"""How a sender's adapter refuses a delivery it cannot vouch for, or cannot read."""

from __future__ import annotations


class PushUnverified(Exception):
    """The delivery did not come from the code host, or did not arrive intact.

    Raised rather than answered quietly, because the two things the endpoint
    can do are record a commit and refuse - and a refusal that looked like an
    accepted push would leave whoever configured the webhook believing the
    index is being told about their work.
    """


class PushUnreadable(Exception):
    """The delivery came from the code host, intact, and is no push it sends.

    Apart from `PushUnverified`, because the two say different things to
    whoever looks: that is the sender's identity, this is its input. Raised
    rather than read as "no news", because a push the endpoint cannot read is
    news it needs - and the sender, told, is how whoever configured it finds
    out.
    """
