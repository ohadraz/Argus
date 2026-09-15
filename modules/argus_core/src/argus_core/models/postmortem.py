"""What a postmortem says, and what it says once it has been written down.

Here rather than in `agent_postmortem` because three modules name this shape:
the agent that produces it, the repository that persists it, and the walk that
carries it between them. A type two modules both have to name is a contract
between them, and a contract kept inside one of the parties is one the other
imports an agent to read.

Three quantities in three units (spec §21.3), and none of them convertible into
the others: what the incident cost the business, what it cost the people who
responded, and what it cost Argus. Only the first is an estimate.

Almost every figure is optional, because a figure whose source could not be read
is absent rather than zero - and `assumptions` is where the document says so. A
reader must never have to guess whether nothing was lost or nothing was known.
The lists are the exception: an empty one says the question was answered and the
answer was none, which is a different thing again.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from argus_core.ids import UuidStr
from argus_core.models.pull_request import OpenedPullRequest


class PostmortemDocument(BaseModel):
    """The finished postmortem, as the agent hands it over.

    Not yet the `postmortem` row - that is `Postmortem` below, which is this and
    three more fields. What the agent produces has no id and no date because it
    has not been written down yet, and an agent that filled either in would be
    an agent deciding something the database decides.

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
    # Where the permanent fix can be read, for the incidents that produced one.
    # A field rather than a sentence the model was asked to include: the walk
    # opened the pull request and recorded the address, so a document that
    # depended on the prose mentioning it would lose the one thing a reader
    # goes on to do - and would lose it silently, on the runs where the summary
    # read perfectly well without it.
    #
    # `None` for the ordinary ending, where a flag went back and there was
    # nothing in the code to change. An empty address would read as a proposal
    # whose link went missing.
    pull_request: OpenedPullRequest | None = None
    checklist_complete: bool


class Postmortem(PostmortemDocument):
    """The same document, once it is a row: identified, and dated.

    Inheritance rather than a second field list. The row *is* the document - the
    agent's own docstring says the two are distinct, and the distinction is
    exactly these three fields - so a mapping between them would be fifteen
    lines of transcription whose only failure mode is silence.
    """

    id: UuidStr
    incident_id: UuidStr
    created_at: datetime
