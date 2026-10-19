"""What the investigation considered: every candidate it ranked, how confident
it was, and what became of each - from the record, ruled-out ones included,
since what was ruled out is half of what a reader is owed.

A candidate names a revision as the model wrote it - whole, mostly, or by as
much of it as the model liked - and the trigger and the timeline beside it say
it short. So it is said short here too, and leads to its commit: one document
naming one revision two ways reads as naming two.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from argus_core import said_short
from argus_core.models import CandidateConsidered, HypothesisConsidered, PostmortemDocument
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
    """Every candidate ranked, in the order the investigation ranked them.

    Candidates the record merged are each a row of their own, in their own
    words and confidence, the result saying whose test reached it: on one row
    they read as one claim, and one candidate's figures shown as the row's own
    read as another's - a candidate never tried as confirmed, at a confidence
    it never had. A document written before the several were carried shows
    the row as it always did.
    """
    shorts = the_short_forms(postmortem.changes_read)
    addresses = the_revision_addresses(postmortem.changes_read)

    def said(summary: str) -> tuple[Run, ...]:
        return Run(text=said_short(summary, shorts)).with_links(addresses)

    rows = tuple(row
                 for hypothesis in postmortem.hypotheses
                 for row in (_the_rows_of_several(hypothesis, said) if hypothesis.members
                             else (HypothesisRow(label=hypothesis.label,
                                                 summary=Line(runs=said(hypothesis.summary)),
                                                 confidence=_to_two_places(hypothesis.confidence),
                                                 result=hypothesis.result,
                                                 also=tuple(hypothesis.also)),)))

    return HypothesesSection(headings=_HEADINGS,
                             rows=rows,
                             absent=None if rows else "No hypotheses were ranked.")


def _the_rows_of_several(hypothesis: HypothesisConsidered,
                         said: Callable[[str], tuple[Run, ...]]) -> tuple[HypothesisRow, ...]:
    """A row for each candidate the record merged, the one whose test decided
    them with the result as it stands and the rest saying it was that one's."""
    return tuple(
        HypothesisRow(label=member.label,
                      summary=Line(runs=said(member.summary)),
                      confidence=_to_two_places(member.confidence),
                      result=_its_result(member, hypothesis))
        for member in hypothesis.members)


def _its_result(member: CandidateConsidered, hypothesis: HypothesisConsidered) -> str:
    """What became of a merged candidate: the result, and whose test it was
    where that was another's."""
    if hypothesis.decided_by and hypothesis.decided_by != member.label:
        return f"{hypothesis.result}, as tested for {hypothesis.decided_by}"
    return hypothesis.result


def _to_two_places(confidence: float | None) -> str:
    """A ranking's confidence to two places, or `-` where it gave none."""
    return f"{confidence:.2f}" if confidence is not None else "-"
