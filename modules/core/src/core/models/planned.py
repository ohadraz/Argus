"""A change worked out before it is made, what a flag reads as now, and what a
walk resumed after its worker died finds of a change.

Here rather than in the write tier because the plan travels: the write tier
works it out, the walk writes it onto the claim before anything in the estate
moves, and the write it is handed back to compares the estate with it. Three
parties naming one shape is a contract, and a contract lives in `core.models`.
The two answers a resumed walk is given - a claim's change found made, and a
performed change found still Argus's or not - are the write tier's to work out
and the walk's to act on, for the same reason.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class Made[D](BaseModel):
    """A claim's change found made: `descriptor`, what the write would have
    answered with, and `made_at`, when the estate says it was made.

    `made_at` is the provider's or the platform's own record of the moment -
    the earliest change of Argus's to a flag, the deployment a rollback added,
    the moment the mark on a patched object says it was written - and `None`
    where nothing says when: a rollback still pending, a mark whose moment is
    absent. Never another clock's moment standing in for it.
    """

    model_config = ConfigDict(frozen=True)

    descriptor: D
    made_at: datetime | None


class NotMade[D](BaseModel):
    """A claim's change found not made - the write is still to make - and
    `left_behind`, what of the claim's is out there all the same: the plan,
    where the suspension of the platform's own reconciliation made for the
    change still stands under the claim's mark, and `None` where nothing of the
    claim's is out there at all.

    Carried so that a walk which stops before it writes still has what puts the
    suspension back: an answer saying only that nothing landed would leave a
    suspension of Argus's standing that nothing records.

    Extra fields are refused, so a made answer on the wire is never read as
    this one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    left_behind: D | None = None


class ChangeFound(BaseModel):
    """Whether a change Argus made is still as Argus left it.

    `still_argus_s` is `True` where it is, and `found` is then `None`; `False`
    where somebody's change since overtook it, `found` saying what was found;
    `None` where nobody can say - a read that never came back, a call naming no
    claim to compare a mark with - `found` saying why. `None` is never `False`:
    a question nobody could answer is no evidence anybody acted.
    """

    model_config = ConfigDict(frozen=True)

    still_argus_s: bool | None
    found: str | None = None
