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

# How a conversion announces itself in the assumptions. A constant rather than
# a phrase written at each end, because the document and anything reading it
# have to agree on the wording, and two spellings would leave a disclosed
# assumption looking undisclosed. Money taken abroad
# reaches the estimate through a rate, and a figure converted at a rate nobody
# can see is a figure nobody can check.
EXCHANGE_RATE_ASSUMPTION_LABEL = "exchange rate"

# How money left out of the figure announces itself. A shop can be paid in a
# currency the rate source prices nothing for, and the estimate then covers
# some of what was taken rather than all of it - which is a real answer, but
# only while the document says which part is missing.
EXCLUDED_CURRENCY_ASSUMPTION_LABEL = "excluded currency"

# Said when a figure is missing because nobody could answer, so that the gap
# reads as an unanswered question rather than as a measurement of nothing.
REVENUE_UNAVAILABLE_ASSUMPTION = "no loss estimate: the revenue source could not be read"
ONSET_UNKNOWN_ASSUMPTION = (
    "no loss estimate: no minute departed from the baseline, so there is no "
    "measured incident to attribute a loss to"
)
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
    customer_loss_estimate: Decimal | None
    # What currency that figure is in, carried rather than looked up. The
    # reporting currency is configured, so a document that left a reader to
    # read it back from settings would relabel figures already published the
    # day somebody changed it. `None` where there is no figure to label.
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    # What those responders were, never who. Empty where the source could say
    # how many people responded and not what any of them was called - a
    # description missing, rather than a measurement.
    responder_titles: list[str] = []
    tokens_spent: int | None
    assumptions: list[str]
    checklist_complete: bool
