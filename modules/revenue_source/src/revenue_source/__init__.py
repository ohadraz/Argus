"""What the shop took, read from the payment provider.

The adapter behind `agent_postmortem`'s `Revenue` port. It answers one question
- what was taken between two instants - and answers it in the currencies the
provider was paid in.

The provider is reached through its own SDK rather than a hand-built request,
aimed by configuration at whichever host is to answer: the arrangement the
Anthropic adapter has with its double, and for the same reason - an adapter
exercised only against a fake written by the same hand proves the fake.
"""

from revenue_source.takings import (
    Charge,
    Charges,
    RevenueUnavailable,
    Takings,
    taken_between,
)

__all__ = [
    "Charge",
    "Charges",
    "RevenueUnavailable",
    "Takings",
    "taken_between",
]
