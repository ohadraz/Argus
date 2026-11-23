"""What the executive synopsis says, and what it says once it is written down.

Here rather than in `postmortem_writing` because three modules name this shape:
the step that writes it, the repository that keeps it, and the Communicator
that posts it. A type two modules both name is a contract between them.

Apart from `PostmortemDocument`, never a field of it: the synopsis is written
by a step after the postmortem's and changes nothing of it. And only the
synopsis carries pay - the postmortem stores the response's minutes by title
and never prices them, since its readers are the people it would price.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from core.ids import UuidStr
from core.models.postmortem import TitleMinutes


class SynopsisFigure(StrEnum):
    """The figures an overview may name, by the name it names each by: how long
    it lasted, how badly requests failed, what customers lost, and who
    responded, for how long and at what cost.

    A contract between the renderer that writes each figure as the page does
    and the synopsis that asks for them by name - the name is what the model is
    shown and writes, so it is spelled once."""

    DURATION = "duration"
    PEAK_ERROR_RATE = "peak_error_rate"
    CUSTOMER_LOSS = "customer_loss"
    RESPONDERS = "responders"
    ENGINEER_MINUTES = "engineer_minutes"
    RESPONDER_COST = "responder_cost"


class TitleCost(TitleMinutes):
    """One title's share of the response, and what its minutes cost at the
    bottom, middle and top of its band.

    The three amounts are `None` together, for a title no band prices: the
    people and minutes are still known, and an unpriced row is not a free one.
    """

    midpoint: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None


class PricedResponse(BaseModel):
    """What the response cost, by title and in all, and how that was arrived
    at.

    `cost_by_title` is one row per row of the postmortem's minutes by title, in
    its order - empty where nobody responded, or nobody could say who did. The
    totals are absent - never zero, and never a partial sum - wherever any row
    is unpriced, since a cost missing a responder is wrong in the flattering
    direction rather than merely small. The midpoint is the figure; the minimum
    and maximum are the same minutes at the bottom and top of the same bands,
    so a midpoint is not read as measured to the cent.

    `responder_cost_currency` is what the bands were quoted in, carried rather
    than looked up: a figure relabelled from settings would rewrite synopses
    already sent. `response_cost_basis` says how the cost was arrived at - the
    working year, the band each title was priced at, or what stopped it - for
    whoever is shown the cost.
    """

    cost_by_title: list[TitleCost] = []
    responder_cost_estimate: Decimal | None = None
    responder_cost_minimum: Decimal | None = None
    responder_cost_maximum: Decimal | None = None
    responder_cost_currency: str | None = None
    response_cost_basis: list[str] = []


class ExecutiveSynopsisDocument(PricedResponse):
    """The synopsis as the step hands it over, before it has an id or a date:
    the response priced, and what is said beside it.

    `overview` is `None` where the model's was given up, and `withheld_because`
    then says why: the one synopsis that is not sent. `response_shared` is the
    postmortem's own line saying the on-call page also covered other
    incidents, where it did - said beside the cost in the postmortem's words.
    """

    overview: str | None
    withheld_because: str | None = None
    response_shared: str | None = None


class ExecutiveSynopsis(ExecutiveSynopsisDocument):
    """The same synopsis, once it is a row: identified, and dated."""

    id: UuidStr
    incident_id: UuidStr
    created_at: datetime
