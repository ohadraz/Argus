"""A change worked out before it is made, and what a flag reads as now.

Here rather than in the write tier because the plan travels: the write tier
works it out, the walk writes it onto the claim before anything in the estate
moves, and the write it is handed back to compares the estate with it. Three
parties naming one shape is a contract, and a contract lives in `core.models`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Planned[D](BaseModel):
    """`descriptor` - the change a write is to make, in the shape that puts it
    back - and `since`, when the state it was worked out from was read.

    `since` is the platform's own clock, read before the state it dates, never
    the write tier's: what a resumed walk asks of it is whether anything the
    platform recorded landed after it, and a moment on another clock can fall
    the wrong side of a change it is compared with. Read first, a change made
    between the clock and the state is at worst taken for somebody else's.

    A plan changes nothing. It is the record the claim carries of what the write
    will compare the estate against, and the write never works it out again.
    """

    descriptor: D
    since: datetime


class FlagState(BaseModel):
    """Whether a flag is on, and when the provider said so - by its own clock."""

    enabled: bool
    read_at: datetime
