"""What the investigation considered: every candidate it ranked, how confident
it was, and what became of each - from the record, ruled-out ones included,
since what was ruled out is half of what a reader is owed.

A candidate names a revision as the model wrote it - whole, mostly, or by as
much of it as the model liked - and the trigger and the timeline beside it say
it short. So it is said short here too, and leads to its commit: one document
naming one revision two ways reads as naming two.

An instant it names is said as a moment, for the same reason: the model writes
it in the wire format its tools speak, and the rest of the document does not.
Found as the page finds one (`the_instants_in`), so the two never disagree about
which of a candidate's words are instants.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Final

from argus_core import said_short
from argus_core.models import HypothesisConsidered, PostmortemDocument
from argus_narration import the_instants_in
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run
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


def the_hypotheses(postmortem: PostmortemDocument,
                   day: date | None = None) -> HypothesesSection:
    """Every candidate ranked, in the order the investigation ranked them.

    `day` is the one the document is dated by: a clock time a candidate names
    with the wire's zone marker is put on it, as the page puts one on the day
    of its line - and is left as it was written where the document names none.

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
                     for said in _with_moments(linked, day))

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


def _with_moments(run: Run, day: date | None) -> tuple[Run, ...]:
    """The run cut at every instant in its words, each said as a moment and
    the words between them left as they were. A link is left whole."""
    if run.role is not Role.PLAIN:
        return (run,)

    runs: list[Run] = []
    written = 0
    for instant in the_instants_in(run.text, day):
        runs += [run.model_copy(update={"text": run.text[written:instant.start]}),
                 Run.a_moment(instant.at)]
        written = instant.end
    runs.append(run.model_copy(update={"text": run.text[written:]}))

    return tuple(each for each in runs if each.text)


def _to_two_places(confidence: float | None) -> str:
    """A ranking's confidence to two places, or `-` where it gave none."""
    return f"{confidence:.2f}" if confidence is not None else "-"
