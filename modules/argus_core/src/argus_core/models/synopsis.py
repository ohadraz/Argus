"""What the executive synopsis says, and what it says once it is written down.

Here rather than in `agent_postmortem` because three modules name this shape:
the step that writes it, the repository that keeps it, and the Communicator
that posts it. A type two modules both name is a contract between them.

Apart from `PostmortemDocument`, never a field of it: the synopsis is written
by a step after the postmortem's and changes nothing of it, and it carries pay,
which the postmortem never shows.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from argus_core.ids import UuidStr


class TitleCost(BaseModel):
    """One title's share of the response: how many held it, their minutes,
    and what those minutes cost at the bottom, middle and top of its band.

    `title` is `None` for responders the source recorded no title for - a row
    of their own, so the rows still add up to everyone who responded. The
    three amounts are `None` together, for a title no band prices: the people
    and minutes are still known, and an unpriced row is not a free one.
    """

    title: str | None
    responders: int
    minutes: int
    midpoint: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None


class ExecutiveSynopsisDocument(BaseModel):
    """The synopsis as the step hands it over, before it has an id or a date.

    `overview` is `None` where the model's was given up, and `withheld_because`
    then says why: the one synopsis that is not sent. `cost_by_title` is empty
    where `breakdown_unmatched` - the breakdown, read again, disagreed with the
    postmortem's totals, which the synopsis then shows alone.
    `response_shared` is the postmortem's own line saying the on-call page also
    covered other incidents, where it did - said beside the cost in the
    postmortem's words.
    """

    overview: str | None
    withheld_because: str | None = None
    cost_by_title: list[TitleCost] = []
    breakdown_unmatched: bool = False
    response_shared: str | None = None


class ExecutiveSynopsis(ExecutiveSynopsisDocument):
    """The same synopsis, once it is a row: identified, and dated."""

    id: UuidStr
    incident_id: UuidStr
    created_at: datetime
