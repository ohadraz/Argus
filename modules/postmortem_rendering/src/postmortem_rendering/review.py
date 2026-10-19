"""Whether it is finished: Google's review checks, a tick for what is met and a
cross for what is not yet - including the two only people can meet, which stay
crossed until a person does, and are said to be theirs rather than failed.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import PostmortemDocument
from pydantic import BaseModel, ConfigDict

_TICK: Final = "✓"
_CROSS: Final = "✗"

# What a check left to people means, as its row says it.
_FOR_A_PERSON: Final = "for a person"


class ReviewRow(BaseModel):
    """One check: what it asks, whether it is met (`yes`, `no`, or `left` for a
    person), its mark, what the mark means, and - for a check left for a
    person that is more than the check itself - what that person would do.

    The meaning and the reason are apart because they are set apart: the
    meaning is a word that fits beside the check, the reason a sentence that
    has to wrap under it."""

    model_config = ConfigDict(frozen=True)

    criterion: str
    met: str
    mark: str
    meaning: str
    because: str | None


class ReviewSection(BaseModel):
    """The checks, and the sentence said in their place where there are none."""

    model_config = ConfigDict(frozen=True)

    rows: tuple[ReviewRow, ...]
    absent: str | None


def the_review(postmortem: PostmortemDocument) -> ReviewSection:
    """Every check in the agent's order - a check left for a person saying what
    they would do, where that is more than the check itself."""
    rows = tuple(ReviewRow(criterion=check.criterion,
                           met="left" if check.met is None else ("yes" if check.met else "no"),
                           mark=_TICK if check.met else _CROSS,
                           meaning=(_FOR_A_PERSON if check.met is None
                                    else ("met" if check.met else "not met")),
                           because=check.because)
                 for check in postmortem.review)

    return ReviewSection(rows=rows, absent=None if rows else "Not reviewed.")
