"""Why it happened: the root cause, the chain of whys under it with what each
rests on, and the factors that let it.

The claims are the model's prose and said as prose; what each step rests on is
said in the record's words, without the labels the prompt gave the evidence -
they named it for the model, and mean nothing to a reader.
"""

from __future__ import annotations

from argus_core.models import PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run


class ChainLink(BaseModel):
    """One step of the chain beside its place in it - the symptom first, then
    each why asked of the one before - and what it rests on."""

    model_config = ConfigDict(frozen=True)

    place: str
    claim: Line
    evidence: tuple[str, ...]


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


def the_cause(postmortem: PostmortemDocument) -> CauseSection:
    """The section as the model wrote it, in its order."""
    chain = tuple(ChainLink(place="symptom" if place == 1 else f"why {place}",
                            claim=_prose(step.text),
                            evidence=tuple(cited.text for cited in step.cites))
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


def _prose(text: str) -> Line:
    """The model's words as a line of their own."""
    return Line(runs=(Run(text=text, role=Role.PROSE),))
