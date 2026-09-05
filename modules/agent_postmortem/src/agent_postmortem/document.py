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
PAY_BANDS_UNAVAILABLE_ASSUMPTION = (
    "no responder cost: the pay band source could not be read"
)

# How the divisor behind the response cost announces itself. An annual band
# becomes a per-minute rate only by being divided by a working year, and that
# year is a convention somebody configured rather than anything measured - so a
# reader reproducing the figure needs it stated beside the figure.
WORKING_YEAR_ASSUMPTION_LABEL = "working year"

# How each band the figure rests on announces itself, one line per title. The
# published figure is a midpoint, which is a range collapsed to a point: naming
# the range is what stops the point being read as a measurement.
PAY_BAND_ASSUMPTION_LABEL = "pay band"

# How a title nothing could price announces itself. The cost is absent rather
# than short, and the absence is only honest while the document can say which
# title caused it.
UNPRICED_TITLE_ASSUMPTION_LABEL = "unpriced title"


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
    # What those minutes were worth, at the midpoint of each responder's band.
    # Absent - never zero, and never a partial sum - where any one of them
    # could not be priced, since a cost missing a responder is wrong in the
    # flattering direction rather than merely small.
    responder_cost_estimate: Decimal | None = None
    # The same minutes at the bottom and top of the same bands, published
    # beside the figure so a midpoint is not read as measured to the dollar.
    responder_cost_minimum: Decimal | None = None
    responder_cost_maximum: Decimal | None = None
    # What the bands were quoted in, carried for the same reason
    # `estimate_currency` is: a figure relabelled from settings would rewrite
    # documents already published.
    responder_cost_currency: str | None = None
    tokens_spent: int | None
    assumptions: list[str]
    checklist_complete: bool
