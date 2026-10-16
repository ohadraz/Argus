"""What the investigation considered: every candidate it ranked, how confident
it was, and what became of each - from the record, ruled-out ones included,
since what was ruled out is half of what a reader is owed.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import PostmortemDocument
from pydantic import BaseModel, ConfigDict

_HEADINGS: Final = ("", "Hypothesis", "Confidence", "Result")


class HypothesisRow(BaseModel):
    """One candidate: its label, what it said, how confident the ranking was -
    to two places, or `-` where it gave none - and what became of it. `also`
    are the labels of the candidates it stands for besides, which it goes by
    too."""

    model_config = ConfigDict(frozen=True)

    label: str
    summary: str
    confidence: str
    result: str
    also: tuple[str, ...] = ()

    @property
    def labels(self) -> tuple[str, ...]:
        """Every label the row goes by, its own first."""
        return (self.label, *self.also)


class HypothesesSection(BaseModel):
    """The table, and the sentence said in its place where nothing was ranked -
    `None` where something was."""

    model_config = ConfigDict(frozen=True)

    headings: tuple[str, ...]
    rows: tuple[HypothesisRow, ...]
    absent: str | None


def the_hypotheses(postmortem: PostmortemDocument) -> HypothesesSection:
    """Every candidate ranked, in the order the investigation ranked them."""
    rows = tuple(HypothesisRow(label=hypothesis.label,
                               summary=hypothesis.summary,
                               confidence=(f"{hypothesis.confidence:.2f}"
                                           if hypothesis.confidence is not None else "-"),
                               result=hypothesis.result,
                               also=tuple(hypothesis.also))
                 for hypothesis in postmortem.hypotheses)

    return HypothesesSection(headings=_HEADINGS,
                             rows=rows,
                             absent=None if rows else "No hypotheses were ranked.")
