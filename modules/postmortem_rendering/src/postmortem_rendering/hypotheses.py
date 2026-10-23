"""What the investigation considered: every candidate it ranked, how confident
it was, and what became of each - from the record, ruled-out ones included,
since what was ruled out is half of what a reader is owed.

A candidate names a revision as the model wrote it - whole, mostly, or by as
much of it as the model liked - and the trigger and the timeline beside it say
it short. So it is said short here too, and leads to its commit: one document
naming one revision two ways reads as naming two.

An instant it names is said as a moment, for the same reason: the model writes
it in the wire format its tools speak, and the rest of the document does not.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final

from argus_core import parse_iso, said_short
from argus_core.models import HypothesisConsidered, PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import the_revision_addresses, the_short_forms

_HEADINGS: Final = ("", "Hypothesis", "Confidence", "Result")

# An instant as the tools speak one, to the minute or the second, its zone
# marker optional.
_AN_INSTANT: Final = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z?)")


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
        return tuple(said for linked in Run(text=said_short(summary, shorts)).with_links(addresses)
                     for said in _with_moments(linked))

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
                      result=hypothesis.result_of(member))
        for member in hypothesis.members)


def _with_moments(run: Run) -> tuple[Run, ...]:
    """The run cut at every instant in its words, each said as a moment and
    the words between them left as they were. A link is left whole, and so is
    a string shaped like an instant that names no day there is."""
    if run.role is not Role.PLAIN:
        return (run,)

    # `split` puts what the group matched at every odd place.
    return tuple(_a_moment(piece) if place % 2 else run.model_copy(update={"text": piece})
                 for place, piece in enumerate(_AN_INSTANT.split(run.text)) if piece)


def _a_moment(said: str) -> Run:
    """An instant as a moment, or its words as they came where it is none."""
    try:
        return Run.a_moment(parse_iso(said))
    except ValueError:
        return Run(text=said)


def _to_two_places(confidence: float | None) -> str:
    """A ranking's confidence to two places, or `-` where it gave none."""
    return f"{confidence:.2f}" if confidence is not None else "-"
