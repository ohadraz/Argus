"""What the investigation considered: every candidate it ranked, how confident
it was, and what became of each - from the record, ruled-out ones included,
since what was ruled out is half of what a reader is owed.

A candidate names a revision as the model wrote it - whole, mostly, or by as
much of it as the model liked - and the trigger and the timeline beside it say
it short. So it is said short here too, and leads to its commit: one document
naming one revision two ways reads as naming two.
"""

from __future__ import annotations

from typing import Final

from argus_core import said_short
from argus_core.models import PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Run
from postmortem_rendering.supporting import the_revision_addresses, the_short_forms

_HEADINGS: Final = ("", "Hypothesis", "Confidence", "Result")


class HypothesisRow(BaseModel):
    """One candidate: its label, what it said, how confident the ranking was -
    to two places, or `-` where it gave none - and what became of it. `also`
    are the labels of the candidates it stands for besides, which it goes by
    too."""

    model_config = ConfigDict(frozen=True)

    label: str
    summary: Line
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
    shorts = the_short_forms(postmortem.changes_read)
    addresses = the_revision_addresses(postmortem.changes_read)
    rows = tuple(HypothesisRow(label=hypothesis.label,
                               summary=Line(runs=Run(text=said_short(hypothesis.summary, shorts))
                                            .with_links(addresses)),
                               confidence=(f"{hypothesis.confidence:.2f}"
                                           if hypothesis.confidence is not None else "-"),
                               result=hypothesis.result,
                               also=tuple(hypothesis.also))
                 for hypothesis in postmortem.hypotheses)

    return HypothesesSection(headings=_HEADINGS,
                             rows=rows,
                             absent=None if rows else "No hypotheses were ranked.")
