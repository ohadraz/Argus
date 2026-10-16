"""Why it happened: the root cause, the chain of whys under it with what each
rests on, and the factors that let it.

The claims are the model's prose and said as prose; what each step rests on is
said the way its own row in the document says it, under the label that leads
to the row - not in the words the model was briefed in, which are the
record's raw instants and whole revisions.
"""

from __future__ import annotations

from collections.abc import Mapping

from argus_core.models import CitedEvidence, PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run


class ChainLink(BaseModel):
    """One step of the chain beside its place in it - the symptom first, then
    each why asked of the one before - and what it rests on, each item a line
    of its own."""

    model_config = ConfigDict(frozen=True)

    place: str
    claim: Line
    evidence: tuple[Line, ...]


class Factor(BaseModel):
    """A contributing factor, and the action items that answer it - `None`
    where it names none."""

    model_config = ConfigDict(frozen=True)

    text: Line
    addressed_by: Line | None


class CauseSection(BaseModel):
    """The root cause, the chain and the factors, each list under its heading
    with the sentence said in its place where it is empty - `None` where it is
    not."""

    model_config = ConfigDict(frozen=True)

    chain_heading: str = "Causal chain"
    factors_heading: str = "Contributing factors"
    evidence_label: str = "Evidence:"
    root_cause: Line | None
    chain: tuple[ChainLink, ...]
    chain_absent: str | None
    factors: tuple[Factor, ...]
    factors_absent: str | None


def the_cause(postmortem: PostmortemDocument, rows: Mapping[str, Line]) -> CauseSection:
    """The section as the model wrote it, in its order - each item a step
    cites said as `rows` says its row does, by label."""
    chain = tuple(ChainLink(place="symptom" if place == 1 else f"why {place}",
                            claim=_prose(step.text),
                            evidence=tuple(_as_its_row_says_it(cited, rows)
                                           for cited in step.cites))
                  for place, step in enumerate(postmortem.causal_chain, start=1))

    factors = tuple(Factor(text=_prose(factor.text),
                           addressed_by=(_prose(f"({', '.join(factor.addressed_by)})")
                                         if factor.addressed_by else None))
                    for factor in postmortem.contributing_factors)

    return CauseSection(
        root_cause=_prose(postmortem.root_cause) if postmortem.root_cause else None,
        chain=chain,
        chain_absent=None if chain else "No causal chain was written.",
        factors=factors,
        factors_absent=None if factors else "No contributing factors were named.")


def _as_its_row_says_it(cited: CitedEvidence, rows: Mapping[str, Line]) -> Line:
    """A cited item under its label: the label a citation of its row, and the
    row's own words after it. A label with no row keeps the words the model
    was briefed in, and leads nowhere - nothing cited disappears."""
    row = rows.get(cited.label)
    if row is None:
        return Line(runs=(Run(text=cited.label), Run(text=" "), Run(text=cited.text)))

    return Line(runs=(Run(text=cited.label, role=Role.CITATION, address=cited.label),
                      Run(text=" "),
                      *row.runs))


def _prose(text: str) -> Line:
    """The model's words as a line of their own."""
    return Line(runs=(Run(text=text, role=Role.PROSE),))
