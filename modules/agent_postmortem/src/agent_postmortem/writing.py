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
    ActionItemType,
    ChainStep,
    CitedEvidence,
    ContributingFactor,
    PostmortemDocument,
    PostmortemLead,
    ReviewCriterion,
    RuledOut,
    labelled,
)

from agent_postmortem.assumptions import assumptions_of
from agent_postmortem.conversation import answer_worth_writing
from agent_postmortem.detection_lesson import the_detection_lesson
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.figures import the_day_it_began, the_latency_told
from agent_postmortem.log_groups import grouped
from agent_postmortem.measuring import Measurements, measure
from agent_postmortem.prompting import (
    CONFIRM_IT_REACHED_THE_SERVICE,
    KEPT_UNTIL_THE_FAULT_IS_FIXED,
    SubmittedPostmortem,
    the_cause_measured_labelled,
    the_changes_labelled,
    the_code_reading_labelled,
    the_deployment_changes_labelled,
    the_evidence_labelled,
    the_files_as_they_ran_labelled,
    the_uses_outside_labelled,
)
from agent_postmortem.response_cost_basis import response_cost_basis
from agent_postmortem.reviewing import review_of
from agent_postmortem.sections import (
    action_item_number,
    detection_of,
    hypotheses_of,
    impact_of,
    logs_in_the_gap_of,
    record_action_items_of,
    resolution_of,
    timeline_of,
    trigger_of,
    why_no_trigger,
)
from agent_postmortem.sources import EngagementAnswer, NotPaged, Sources
from agent_postmortem.summary import the_executive_summary

logger = logging.getLogger(__name__)


class Measure(Protocol):
    """Reading every source once and counting what they said."""

    def __call__(self, evidence: IncidentEvidence, sources: Sources) -> Measurements: ...


class Ask(Protocol):
    """Getting an answer out of the model that is worth writing down."""

    def __call__(self,
                 llm: LLMClient,
                 evidence: IncidentEvidence,
                 measured: Measurements,
                 judge: LLMClient | None = None
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
                 faults: list[str],
                 *,
                 reaches_a_cause: bool,
                 rests_on_an_unrun_reading: bool | None = None) -> list[ReviewCriterion]: ...


def write_postmortem(evidence: IncidentEvidence,
                     sources: Sources,
                     llm: LLMClient,
                     *,
                     judge: LLMClient | None = None,
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

    `judge` is the grounding judge the answer is read by (`grounding`), where
    there is one.
    """
    measured = measure(evidence, sources)
    answer, faults = ask(llm, evidence, measured, judge=judge)
    shown = the_evidence_labelled(evidence, measured)

    if faults:
        logger.warning("postmortem written incomplete", extra={"faults": faults})

    # Minutes only where somebody measured them, or where nobody was paged and
    # so nobody spent any. Nobody able to say leaves the figures blank, and the
    # assumptions say which of the three it was.
    engaged = measured.engaged if isinstance(measured.engaged, EngagementAnswer) else None
    not_paged = isinstance(measured.engaged, NotPaged)

    document = PostmortemDocument(
        # Absent rather than empty where the model never answered: a blank on a
        # page reads as a root cause somebody wrote and left empty, and this
        # document is one nobody can ask a follow-up question of.
        root_cause=answer.root_cause_as_written(),
        cause_in_plain_words=answer.cause_in_plain_words,
        # Written by code from the record, around the two sentences only the
        # model can give: the cause in plain words, and what is still at risk.
        executive_summary=the_executive_summary(evidence, measured,
                                                answer.cause_in_plain_words,
                                                answer.still_at_risk),
        symptom=answer.symptom,
        customer_loss_estimate=measured.loss,
        estimate_currency=measured.currency,
        # Not multiplied by the count: the source answers person-minutes, so
        # each responder's own engagement is already in the figure, and
        # scaling it again would charge every minute to everybody.
        engineer_minutes=engaged.minutes if engaged else (0 if not_paged else None),
        responders=engaged.responders if engaged else (0 if not_paged else None),
        # Kept apart from the count, which is nobody both ways.
        paged=True if engaged else (False if not_paged else None),
        responder_titles=engaged.titles if engaged else [],
        responder_cost_estimate=measured.cost.midpoint if measured.cost else None,
        responder_cost_minimum=measured.cost.minimum if measured.cost else None,
        responder_cost_maximum=measured.cost.maximum if measured.cost else None,
        responder_cost_currency=measured.cost.currency if measured.cost else None,
        # Left to whoever holds the replay log, which reads it once this is
        # written: the count is of every call, this document's own among them.
        tokens_spent=None,
        # Carried across, never asked for: the walk recorded where the fix can
        # be read, and a document that waited for the model to mention it would
        # lose the address on any run whose prose read well without one.
        pull_request=evidence.pull_request,
        recommended_action=evidence.recommended_action,
        # The close, where the incident ended disproven: the ending is
        # terminal, so it is the disproof's moment.
        disproven_at=evidence.ended_at if evidence.disproven else None,
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
        # Beside the cost it explains, never among the assumptions: the
        # document says nothing of pay.
        response_cost_basis=response_cost_basis(measured, sources.working_hours_a_year),
        # Written by code from the record - and, of how the service did where
        # the metrics stopped, from the model's yes or no, never its prose.
        impact=impact_of(measured,
                         logs_in_the_gap=logs_in_the_gap_of(
                             evidence, measured, answer.logs_show_serving_as_before),
                         latency_told=the_latency_told(evidence, measured),
                         disproven=evidence.disproven),
        detection=detection_of(evidence, measured.rule_waits,
                               rule_wait_unread=measured.rule_wait_unread,
                               held_before_the_onset=measured.rule_held_before_the_onset),
        trigger=trigger_of(evidence),
        no_trigger=why_no_trigger(evidence),
        resolution=resolution_of(evidence),
        hypotheses=hypotheses_of(evidence),
        # Ending at the measured recovery, where the duration beside it ends.
        timeline=timeline_of(evidence, measured.back_to_normal_at,
                             back_before_the_action=measured.back_before_the_action,
                             metrics_stopped_at_onset=measured.metrics_stopped_at is not None,
                             ended_by_a_report=measured.reported_by is not None,
                             metrics_resumed=measured.metrics_resumed_at is not None),
        # The model's sections. Each empty where unanswered - a section of many
        # has no list to be absent from - and the review says what that costs.
        causal_chain=_the_chain_as_cited(answer, shown),
        contributing_factors=_the_factors_with_what_answers_them(evidence, measured, answer),
        action_items=_the_record_s_items_then_the_model_s(evidence, measured, answer),
        lessons=answer.lessons,
        # Written by code, never asked of the model: every part is measured,
        # and three write-ups asked to weigh it weighed nothing.
        detection_lesson=the_detection_lesson(evidence, measured),
        # Under the labels the model was shown them by, so the prose that cites
        # one has a row to lead to.
        changes_read=the_changes_labelled(evidence),
        log_messages_read=grouped(evidence.log_lines, measured.metrics_stopped_at,
                                  the_day_it_began(evidence, measured),
                                  acted_at=evidence.first_acted_at,
                                  metrics_resumed_at=measured.metrics_resumed_at),
        deployment_changes_read=the_deployment_changes_labelled(evidence),
        code_read=the_code_reading_labelled(evidence),
        as_it_ran_read=the_files_as_they_ran_labelled(evidence),
        uses_outside_read=the_uses_outside_labelled(evidence),
        cause_measured=the_cause_measured_labelled(evidence, measured),
        fix_branch_read=evidence.fix_branch_read,
        deploys_reading=evidence.deploys_reading,
        flags_reading=evidence.flags_reading,
        logs_reading=evidence.logs_reading
    )

    # Reviewed last, because what it reviews is the document as written.
    return document.model_copy(update={
        "review": review(document, faults, reaches_a_cause=answer.reaches_a_cause,
                         rests_on_an_unrun_reading=answer.cause_rests_on_an_unrun_reading)
    })


def _the_chain_as_cited(answer: SubmittedPostmortem,
                        shown: list[CitedEvidence]) -> list[ChainStep]:
    """Each step with the text of what it cites, since a label means nothing
    outside the prompt it was given in.

    A label never shown is left out rather than kept bare: the check has named
    it already and the review holds it against the analysis, and kept it would
    be a citation a reader can follow nowhere.
    """
    by_label = {cited.label: cited for cited in shown}

    def as_cited(labels: list[str]) -> list[CitedEvidence]:
        return [by_label[label] for label in labels if label in by_label]

    return [ChainStep(text=step.step,
                      cites=as_cited(step.cites),
                      ruled_out=[RuledOut(text=ruled.what, cites=as_cited(ruled.cites),
                                          said_by_the_record=ruled.by_the_record)
                                 for ruled in step.ruled_out])
            for step in answer.causal_chain or []]


def _the_factors_with_what_answers_them(evidence: IncidentEvidence,
                                        measured: Measurements,
                                        answer: SubmittedPostmortem) -> list[ContributingFactor]:
    """Each factor with the items that answer it, by number: the record's own
    it named, then each proposal naming it by its label, in the order given.

    Linked the way the answer could write them - each link to something
    already written - and published the way a reader looks them up. The label
    stays in the answer: the reader is never shown it.
    """
    on_record = len(record_action_items_of(evidence, measured.back_to_normal_at))
    proposals = answer.action_items or []

    return [ContributingFactor(
                text=factor.factor,
                addressed_by=[*factor.addressed_by,
                              *(action_item_number(on_record + position)
                                for position, proposed in enumerate(proposals, start=1)
                                if factor.label is not None
                                and factor.label in proposed.answers)])
            for factor in answer.contributing_factors or []]


def _the_record_s_items_then_the_model_s(evidence: IncidentEvidence,
                                        measured: Measurements,
                                        answer: SubmittedPostmortem) -> list[ActionItem]:
    """The record's items as numbered before the model was asked, its
    proposals numbered on from them in the order it gave them, and last the
    items it was asked for that stop the harm and find out why the change put
    back did not help, where it was asked.

    Last, so the numbers its factors gave its proposals stay theirs. Both
    mitigations, since the harm is still going on: the first stops it - and is
    kept until the fault is fixed, which the document says after the model's
    words, ending them as a sentence where they did not end as one - and the
    second finds out why the change put back did not. After them the document's
    own, a process item: that the Mitigation Agent confirm a change reached the
    service before judging it.

    Open and nobody's: Argus edits no item after the document is written, so
    whoever takes one on does so somewhere else.
    """
    on_record = record_action_items_of(evidence, measured.back_to_normal_at)
    proposed_items = [(proposed.item, proposed.type) for proposed in answer.action_items or []]
    if answer.stops_the_harm is not None:
        said = answer.stops_the_harm.rstrip()
        ended = said if said.endswith((".", "!", "?")) else f"{said}."
        proposed_items.append((f"{ended} {KEPT_UNTIL_THE_FAULT_IS_FIXED}",
                               ActionItemType.MITIGATE))
    if answer.why_it_did_not_help is not None:
        proposed_items.append((answer.why_it_did_not_help.rstrip(), ActionItemType.MITIGATE))
        proposed_items.append((CONFIRM_IT_REACHED_THE_SERVICE, ActionItemType.PROCESS))

    return [
        *on_record,
        *(ActionItem(number=action_item_number(len(on_record) + position),
                     text=text,
                     type=kind,
                     owner=None,
                     tracking=None,
                     status=ActionItemStatus.OPEN)
          for position, (text, kind) in enumerate(proposed_items, start=1))
    ]
