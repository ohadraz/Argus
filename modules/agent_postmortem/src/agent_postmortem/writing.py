"""The document assembled: three answers arranged onto one page.

Nothing here decides anything. The incident is measured, the model is asked for
the parts prose can carry, and the disclosures are composed from both - each by
a module of its own - and what this does is put the results in their columns.

The order is the only thing that matters and it is not an accident. Everything
is measured before the model is asked, and the figures are handed into the ask,
so the prose describes the same incident the numbers do and nothing the model
says can move them.

The one judgement it makes is what an unusable answer means: faults do not stop
a document being written. The incident is over by the time this runs, a partial
account is worth more than none, and `checklist_complete` is how the page says
which it is.
"""

from __future__ import annotations

from typing import Any, Protocol

from argus_core.llm.client import LLMClient

from agent_postmortem.assumptions import assumptions_of
from agent_postmortem.conversation import answer_worth_writing
from agent_postmortem.document import PostmortemDocument
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.measuring import Measurements, measure
from agent_postmortem.prompting import EXECUTIVE_SUMMARY_FIELD, ROOT_CAUSE_FIELD
from agent_postmortem.sources import Sources


class Measure(Protocol):
    """Reading every source once and counting what they said."""

    def __call__(self, evidence: IncidentEvidence, sources: Sources) -> Measurements: ...


class Ask(Protocol):
    """Getting an answer out of the model that is worth writing down."""

    def __call__(self,
                 llm: LLMClient,
                 evidence: IncidentEvidence,
                 measured: Measurements) -> tuple[dict[str, Any], list[str]]: ...


class Disclose(Protocol):
    """Turning what was measured into what the document admits to assuming."""

    def __call__(self,
                 answer: dict[str, Any],
                 measured: Measurements,
                 working_hours_a_year: float) -> list[str]: ...


def write_postmortem(evidence: IncidentEvidence,
                     sources: Sources,
                     llm: LLMClient,
                     *,
                     measure: Measure = measure,
                     ask: Ask = answer_worth_writing,
                     disclose: Disclose = assumptions_of) -> PostmortemDocument:
    """The whole document: measure, ask once, then write down both.

    The three collaborators are parameters so that a test of this arrangement
    can mock them and assert what each was given - which is the only thing that
    can go wrong here, and the one thing a test reading finished figures off
    the page cannot see.
    """
    measured = measure(evidence, sources)
    answer, faults = ask(llm, evidence, measured)

    return PostmortemDocument(
        root_cause=_text(answer, ROOT_CAUSE_FIELD),
        executive_summary=_text(answer, EXECUTIVE_SUMMARY_FIELD),
        customer_loss_estimate=measured.loss,
        estimate_currency=measured.currency,
        # Not multiplied by the count: the source answers person-minutes, so
        # each responder's own engagement is already in the figure, and
        # scaling it again would charge every minute to everybody.
        engineer_minutes=measured.engaged.minutes if measured.engaged else None,
        responders=measured.engaged.responders if measured.engaged else None,
        responder_titles=measured.engaged.titles if measured.engaged else [],
        responder_cost_estimate=measured.cost.midpoint if measured.cost else None,
        responder_cost_minimum=measured.cost.minimum if measured.cost else None,
        responder_cost_maximum=measured.cost.maximum if measured.cost else None,
        responder_cost_currency=measured.cost.currency if measured.cost else None,
        tokens_spent=evidence.tokens_spent,
        assumptions=disclose(answer, measured, sources.working_hours_a_year),
        checklist_complete=not faults
    )


def _text(answer: dict[str, Any], field: str) -> str | None:
    """The field as the document publishes it, or nothing at all.

    Absent rather than empty where the model never answered: a blank on a page
    reads as a root cause somebody wrote and left empty, and this document is
    one nobody can ask a follow-up question of.
    """
    value = answer.get(field)

    return str(value) if value is not None else None
