"""What a stored row is brought up to before it is read, and what a row that
cannot be read is said to be.

Every row holding a model's dump says which shape it was written in - a number
beside the dump, not inside it, so the dump keeps the keys anything reading it
by key reads. A reader brings an older row up to the shape its models have now,
one step at a time, before it validates anything (`up_to_date`).

A row in a shape the reader does not know was written by a newer Argus. It is
not guessed at - read as the shape the reader knows, it would be read with
whatever the newer one moved sitting in the wrong field - and it is said to be
newer (`NewerShape`), because what a reader does with it differs from what it
does with a row it cannot bring up: a row a newer release wrote is waited for,
since the release that knows it will read it, and one nobody can read is passed
over, since waiting would stop everything behind it for good (`Unreadable`).

The shapes a kind has been through are a value handed to `up_to_date`, not a
registry anybody writes into: the shipped ones by default (`SHIPPED`), and a
test's own where a test needs steps no release has shipped.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Self

# One step: what one write stored, in one shape, in, and the same in the next
# shape, out - one JSON value for most kinds, and for the postmortem and the
# synopsis every column of the document by name, as psycopg reads it (Decimals
# and datetimes included), since a step may move a field from one column to
# another. Stored values rather than a model, because the model is what the
# row is being brought up to.
type Upcaster = Callable[[Any], Any]

# The shape every kind starts at, and the one a row written before shapes were
# recorded is read as.
FIRST_SHAPE: Final = 1


class NewerShape(Exception):
    """A row written in a shape the reader does not know - by a newer Argus."""


@dataclass(frozen=True)
class Shapes:
    """Every step each stored kind has taken from its first shape, in order.

    A kind is at its first shape and one shape on for each step it has taken,
    so the shape a kind is at now cannot disagree with the steps that reach it.
    A kind with no steps is at its first shape - every kind is, until a shape
    changes.
    """

    upcasters: Mapping[str, Sequence[Upcaster]] = field(default_factory=dict)

    def current(self, kind: str) -> int:
        """The shape `kind` is written in now."""
        return FIRST_SHAPE + len(self.upcasters.get(kind, ()))


# The kinds of stored dump, by the name `Shapes` knows each one under.
# The alert an incident was opened for.
ALERT: Final = "alert"
# What an earlier incident tried, as long-term memory keeps it.
REMEMBERED_INCIDENT: Final = "remembered-incident"
# The evidence a candidate cause was formed on.
EVIDENCE: Final = "evidence"
# A change an action made or planned, as a put-back reads it - a plan and a
# change made are the one shape.
UNDO_DESCRIPTOR: Final = "undo-descriptor"
# The postmortem, every one of its columns together.
POSTMORTEM: Final = "postmortem"
# The executive synopsis, every one of its columns together.
EXECUTIVE_SYNOPSIS: Final = "executive-synopsis"
# The fix Code-Fix claimed before writing any of it.
FIX_CLAIM: Final = "fix-claim"

# The shapes this release reads and writes.
SHIPPED: Final = Shapes()


def up_to_date(kind: str, shape: int, raw: Any, shapes: Shapes = SHIPPED) -> Any:
    """`raw`, a row of `kind` written in `shape`, brought up to the shape
    `kind` is at now, through every step after `shape` in order.

    Raises `NewerShape` where `shape` is newer than `shapes` knows, and
    `ValueError` where it is no shape at all.
    """
    current = shapes.current(kind)

    if shape < FIRST_SHAPE:
        raise ValueError(f"shape {shape} of [{kind}] is no shape: the first is {FIRST_SHAPE}")

    if shape > current:
        raise NewerShape(f"shape {shape} of [{kind}], and this reader knows up to {current}")

    for upcast in shapes.upcasters.get(kind, ())[shape - FIRST_SHAPE:]:
        raw = upcast(raw)

    return raw


@dataclass(frozen=True)
class Unreadable:
    """A row a reader could not read, in place of what it would have read.

    `why` is what stopped it, in the failure's own words; `newer` is whether it
    was written in a shape the reader does not know - waited for, where a row
    nobody can read is passed over. Where the row is, each reader says in its
    own terms.
    """

    why: str
    newer: bool

    @classmethod
    def of(cls, failure: Exception) -> Self:
        """A row unreadable for `failure`."""
        return cls(why=str(failure), newer=isinstance(failure, NewerShape))
