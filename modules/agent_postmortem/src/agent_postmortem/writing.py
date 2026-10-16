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
account is worth more than none, and the review is how the page says which it
is.
"""

from __future__ import annotations

import logging
from typing import Protocol

from argus_core.llm import LLMClient
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ChainStep,
    CitedEvidence,
    ContributingFactor,
    PostmortemDocument,
    PostmortemLead,
    ReviewCriterion,
    labelled,
)

from agent_postmortem.assumptions import assumptions_of
from agent_postmortem.conversation import answer_worth_writing
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.log_groups import grouped
from agent_postmortem.measuring import Measurements, measure
from agent_postmortem.prompting import (
    SubmittedPostmortem,
    the_changes_labelled,
    the_code_reading_labelled,
    the_deployment_changes_labelled,
    the_evidence_labelled,
)
from agent_postmortem.reviewing import review_of
from agent_postmortem.sections import (
    action_item_number,
    detection_of,
    hypotheses_of,
    impact_of,
    record_action_items_of,
    resolution_of,
    timeline_of,
    trigger_of,
)
from agent_postmortem.sources import EngagementAnswer, Sources

logger = logging.getLogger(__name__)


class Measure(Protocol):
    """Reading every source once and counting what they said."""

    def __call__(self, evidence: IncidentEvidence, sources: Sources) -> Measurements: ...


class Ask(Protocol):
    """Getting an answer out of the model that is worth writing down."""

    def __call__(self,
                 llm: LLMClient,
                 evidence: IncidentEvidence,
                 measured: Measurements
                 ) -> tuple[SubmittedPostmortem, list[str]]: ...


class Disclose(Protocol):
    """Turning what was measured into what the document admits to assuming."""

    def __call__(self,
                 answer: SubmittedPostmortem,
                 measured: Measurements,
                 working_hours_a_year: float) -> list[str]: ...


class Review(Protocol):
    """Judging the document as written against the review criteria."""

    def __call__(self,
                 document: PostmortemDocument,
                 faults: list[str]) -> list[ReviewCriterion]: ...


def write_postmortem(evidence: IncidentEvidence,
                     sources: Sources,
                     llm: LLMClient,
                     *,
                     measure: Measure = measure,
                     ask: Ask = answer_worth_writing,
                     disclose: Disclose = assumptions_of,
                     review: Review = review_of) -> PostmortemDocument:
    """The whole document: measure, ask once, write down both, then review it.

    The four collaborators are parameters so that a test of this arrangement
    can mock them and assert what each was given - which is the only thing that
    can go wrong here, and the one thing a test reading finished figures off
    the page cannot see. The sections code writes from the record are not: each
    is a value computed from the evidence, and placing it is all this does.
    """
    measured = measure(evidence, sources)
    answer, faults = ask(llm, evidence, measured)
    shown = the_evidence_labelled(evidence)

    if faults:
        logger.warning("postmortem written incomplete", extra={"faults": faults})

    # Minutes only where somebody measured them. Nobody paged and nobody able
    # to say both leave the figures blank, and the assumptions say which.
    engaged = measured.engaged if isinstance(measured.engaged, EngagementAnswer) else None

    document = PostmortemDocument(
        # Absent rather than empty where the model never answered: a blank on a
        # page reads as a root cause somebody wrote and left empty, and this
        # document is one nobody can ask a follow-up question of.
        root_cause=answer.root_cause,
        executive_summary=answer.executive_summary,
        symptom=answer.symptom,
        customer_loss_estimate=measured.loss,
        estimate_currency=measured.currency,
        # Not multiplied by the count: the source answers person-minutes, so
        # each responder's own engagement is already in the figure, and
        # scaling it again would charge every minute to everybody.
        engineer_minutes=engaged.minutes if engaged else None,
        responders=engaged.responders if engaged else None,
        responder_titles=engaged.titles if engaged else [],
        responder_cost_estimate=measured.cost.midpoint if measured.cost else None,
        responder_cost_minimum=measured.cost.minimum if measured.cost else None,
        responder_cost_maximum=measured.cost.maximum if measured.cost else None,
        responder_cost_currency=measured.cost.currency if measured.cost else None,
        tokens_spent=evidence.tokens_spent,
        # Carried across, never asked for: the walk recorded where the fix can
        # be read, and a document that waited for the model to mention it would
        # lose the address on any run whose prose read well without one.
        pull_request=evidence.pull_request,
        recommended_action=evidence.recommended_action,
        # The record's facts carried across, and the model's sentence beside
        # each. A lead the model said nothing of is reported with nothing said,
        # never dropped: the person who wrote it is owed the line either way.
        leads=[
            PostmortemLead(label=label,
                           person_id=lead.person_id,
                           person_name=lead.person_name,
                           text=lead.text,
                           written_at=lead.written_at,
                           weighing=lead.weighing,
                           effect=answer.lead_effects.get(label))
            for label, lead in labelled(evidence.leads)
        ],
        assumptions=disclose(answer, measured, sources.working_hours_a_year),
        # Written by code from the record, never asked of the model.
        impact=impact_of(measured),
        detection=detection_of(evidence),
        trigger=trigger_of(evidence),
        resolution=resolution_of(evidence),
        hypotheses=hypotheses_of(evidence),
        # Ending at the measured recovery, where the duration beside it ends.
        timeline=timeline_of(evidence, measured.back_to_normal_at,
                             back_before_the_action=measured.back_before_the_action),
        # The model's sections. Each empty where unanswered - a section of many
        # has no list to be absent from - and the review says what that costs.
        causal_chain=_the_chain_as_cited(answer, shown),
        contributing_factors=[ContributingFactor(text=factor.factor,
                                                 addressed_by=factor.addressed_by)
                              for factor in answer.contributing_factors or []],
        action_items=_the_record_s_items_then_the_model_s(evidence, answer),
        lessons=answer.lessons,
        # Under the labels the model was shown them by, so the prose that cites
        # one has a row to lead to.
        changes_read=the_changes_labelled(evidence),
        log_messages_read=grouped(evidence.log_lines),
        deployment_changes_read=the_deployment_changes_labelled(evidence),
        code_read=the_code_reading_labelled(evidence)
    )

    # Reviewed last, because what it reviews is the document as written.
    return document.model_copy(update={"review": review(document, faults)})


def _the_chain_as_cited(answer: SubmittedPostmortem,
                        shown: list[CitedEvidence]) -> list[ChainStep]:
    """Each step with the text of what it cites, since a label means nothing
    outside the prompt it was given in.

    A label never shown is left out rather than kept bare: the check has named
    it already and the review holds it against the analysis, and kept it would
    be a citation a reader can follow nowhere.
    """
    by_label = {cited.label: cited for cited in shown}

    return [ChainStep(text=step.step,
                      cites=[by_label[label] for label in step.cites if label in by_label])
            for step in answer.causal_chain or []]


def _the_record_s_items_then_the_model_s(evidence: IncidentEvidence,
                                        answer: SubmittedPostmortem) -> list[ActionItem]:
    """The record's items as numbered before the model was asked, and its
    proposals numbered on from them in the order it gave them.

    Open and nobody's: Argus edits no item after the document is written, so
    whoever takes one on does so somewhere else.
    """
    on_record = record_action_items_of(evidence)

    return [
        *on_record,
        *(ActionItem(number=action_item_number(len(on_record) + position),
                     text=proposed.item,
                     type=proposed.type,
                     owner=None,
                     tracking=None,
                     status=ActionItemStatus.OPEN)
          for position, proposed in enumerate(answer.action_items or [], start=1))
    ]
