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
    person), its mark, and what the mark means."""

    model_config = ConfigDict(frozen=True)

    criterion: str
    met: str
    mark: str
    meaning: str


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
                           meaning=(_FOR_A_PERSON + (f" - {check.because}" if check.because
                                                     else "")
                                    if check.met is None
                                    else ("met" if check.met else "not met")))
                 for check in postmortem.review)

    return ReviewSection(rows=rows, absent=None if rows else "Not reviewed.")
