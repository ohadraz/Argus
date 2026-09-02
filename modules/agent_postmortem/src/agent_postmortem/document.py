"""What a postmortem says, before anyone stores it.

Three quantities in three units (spec §21.3), and none of them convertible
into the others: what the incident cost the business, what it cost the people
who responded, and what it cost Argus. Only the first is an estimate.

Every one of them is optional, because a figure whose source could not be read
is absent rather than zero - and `assumptions` is where the document says so.
A reader must never have to guess whether nothing was lost or nothing was
known.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

# How the estimate's one judgment announces itself in the assumptions. A
# constant rather than a phrase written at each end, because the document and
# anything reading it have to agree on the wording, and two spellings of it
# would leave a disclosed assumption looking undisclosed.
IMPACT_WEIGHT_ASSUMPTION_LABEL = "impact weight"

# Said when a figure is missing because nobody could answer, so that the gap
# reads as an unanswered question rather than as a measurement of nothing.
REVENUE_UNAVAILABLE_ASSUMPTION = "no loss estimate: the revenue source could not be read"
ENGAGEMENT_UNAVAILABLE_ASSUMPTION = (
    "no engineer minutes: no source could say when a person engaged"
)


class PostmortemDocument(BaseModel):
    """The finished postmortem, as the agent hands it over.

    Not the `postmortem` row: the row is what the Orchestrator writes, and
    keeping the two apart is what stops this module holding a connection.

    `checklist_complete` is the agent's own verdict on its output (spec §7.6) -
    false is a legitimate outcome, not a failure, because an incident that is
    over is not improved by an agent that refuses to stop.
    """

    root_cause: str | None
    executive_summary: str | None
    customer_loss_estimate_usd: Decimal | None
    engineer_minutes: int | None
    responders: int | None
    tokens_spent: int | None
    assumptions: list[str]
    checklist_complete: bool
