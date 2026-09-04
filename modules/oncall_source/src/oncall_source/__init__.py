"""Who responded to an incident, and for how long.

The adapter behind `agent_postmortem`'s `Engagement` port. It answers one
question - what human attention one incident took - as minutes, a count of
people, and the titles they held.

The provider is reached through its own SDK rather than a hand-built request,
aimed by configuration at whichever host is to answer: the arrangement the
Anthropic and Stripe adapters have with their stand-ins, and for the same
reason - an adapter exercised only against a fake written by the same hand
proves the fake.
"""

from oncall_source.engagement import (
    Acknowledgement,
    Engagement,
    OnCallUnavailable,
    ReportedIncident,
    ReportedIncidents,
    engagement_with,
)

__all__ = [
    "Acknowledgement",
    "Engagement",
    "OnCallUnavailable",
    "ReportedIncident",
    "ReportedIncidents",
    "engagement_with",
]
