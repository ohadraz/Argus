"""What a chat platform holds before anybody asks it anything.

The seed both adapters in the ports' suite are built from: the double reads it
directly, and the suite stages it on the Slack stand-in through its control
seam. Every value is frozen and every collection a tuple, so a seed is the same
seed whoever holds it and however many platforms are built from it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Person:
    """Somebody the platform can name: its id for them, and what it calls them
    - `None` for a person it holds who set no name."""

    id: str
    name: str | None


@dataclass(frozen=True)
class Refusal:
    """One refusal queued for the next write, a post or a rewrite: the
    platform's word for it, and whether the same write tried again could end
    differently."""

    why: str
    worth_another_go: bool


@dataclass(frozen=True)
class ChatState:
    """Everything the platform holds.

    `name` is the platform's name as people know it. `people` is everyone it
    can name; anyone else it cannot. `refusals` answer the next writes, one
    each, in order - and every write after them lands.
    """

    name: str
    people: tuple[Person, ...] = ()
    refusals: tuple[Refusal, ...] = ()
