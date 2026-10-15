"""Arrangement, and nothing else.

Four collaborators do the work - one measures the incident, one asks the model
for prose, one turns both into the sentences the document discloses, and one
reviews the result - and this module puts what they return onto a page. So all
four are mocked here, and what is asserted is that each was given what it needs
and that what it answered reached the document unaltered.

The sections code writes from the record are not mocked: each is a value
computed from the evidence, and what is asserted is that it lands in its own
column. What each section says is `test_sections`'s subject.

None of the figures are recomputed here. `test_measuring` says what the numbers
are, `test_assumptions` says what the disclosures are, `test_conversation` says
what a usable answer is, `test_reviewing` says what the review makes of a
document, and `component/test_postmortem` runs them for real against a
document. Asserting an exchange rate in this file would be testing `measuring`
through two layers of indirection, and it would still pass if `writing` put the
figure in the wrong column.

The one judgement `writing` makes is what an unusable answer means: faults do
not stop a document being written, they go to the review with it, so the page
says on its face that it is partial.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_postmortem import write_postmortem
from agent_postmortem.assumptions import assumptions_of
from agent_postmortem.conversation import answer_worth_writing
from agent_postmortem.log_groups import grouped
from agent_postmortem.measuring import Measurements, measure
from agent_postmortem.prompting import (
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedStep,
    the_changes_labelled,
)
from agent_postmortem.responder_cost import ResponderCost
from agent_postmortem.reviewing import review_of
from agent_postmortem.sections import (
    detection_of,
    hypotheses_of,
    impact_of,
    record_action_items_of,
    resolution_of,
    timeline_of,
    trigger_of,
)
from agent_postmortem.sources import EngagedResponder
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ChainStep,
    ChangeEvent,
    ChangeKind,
    CitedEvidence,
    ContributingFactor,
    Lessons,
    OpenedPullRequest,
    PostmortemDocument,
    PostmortemLead,
    ReviewCriterion,
    Standing,
    Verdict,
    Weighing,
)
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged

from agent_postmortem_test.framework.assertions import (
    _it_says_what_is_still_owed,
    estimates_a_loss_of,
    proposes_the_fix_at,
    reports_a_cost_ranging_from,
    reports_a_responder_cost_of,
    reports_engineer_minutes,
    reports_executive_summary,
    reports_no_engineer_minutes,
    reports_no_responder_cost,
    reports_no_root_cause,
    reports_responders,
    reports_root_cause,
    reports_the_cost_in,
    reports_the_titles,
    reports_tokens_spent,
    states_the_estimate_is_in,
)
from agent_postmortem_test.framework.builders import (
    RECOVERED_AT,
    SOME_CURRENCY,
    a_candidate,
    a_lead,
    a_measured_incident,
    a_submitted_answer,
    a_timeline_entry,
    an_action,
    an_answer,
    an_engagement_of,
    an_evidence_bundle,
    some_sources,
)

SOME_TITLE = "Senior Kuki"
SOME_OTHER_TITLE = "Site Reliability Engineer"
SOME_FLAG = "monthly-spend-feature"

DONT_CARE_WORKING_YEAR = 2080.0


@pytest.mark.unit
def test_the_prose_the_model_wrote_is_what_the_document_says() -> None:
    # The two fields Argus does not compute, and the only two the model is
    # asked for. They cross unaltered or the document is not the answer that
    # was checked.
    some_root_cause = "the checkout fallback was disabled by a flag toggle at 12:04"
    some_summary = "Checkout failed for half an hour after a flag change; reverted."

    Scenario() \
        .given(
            a_model_that_answered := _asking_that_answers(
                a_submitted_answer(root_cause=some_root_cause,
                                   executive_summary=some_summary))
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=a_model_that_answered,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                reports_root_cause(some_root_cause),
                reports_executive_summary(some_summary)
            )
        )


@pytest.mark.unit
def test_the_symptom_the_model_named_is_the_document_s() -> None:
    # What a reader sees first and remembers the incident by. Prose, so the
    # model's words, crossing unaltered for the reason the root cause does.
    some_symptom = "Account pages failed"

    Scenario() \
        .given(
            a_model_that_answered := _asking_that_answers(
                SubmittedPostmortem.model_validate(an_answer(symptom=some_symptom)))
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=a_model_that_answered,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _reports_symptom(some_symptom)
        )


@pytest.mark.unit
def test_a_field_the_answer_never_carried_is_absent_rather_than_empty() -> None:
    # An answer nothing could be read out of - a model that wrote prose, or
    # called the wrong tool. The document is still written, and the field it
    # could not fill has to be absent: an empty string on a page reads as a
    # root cause somebody wrote and left blank. A section that is many things
    # is the exception, and is empty: there is no list to be absent from.
    Scenario() \
        .given(
            an_answer_carrying_nothing := _asking_that_answers(SubmittedPostmortem())
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=an_answer_carrying_nothing,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                reports_no_root_cause(),
                _publishes("the lessons", lambda document: document.lessons, None),
                _publishes("the causal chain", lambda document: document.causal_chain, []),
                _publishes("the contributing factors",
                           lambda document: document.contributing_factors, [])
            )
        )


@pytest.mark.unit
def test_the_figures_measured_are_the_figures_published() -> None:
    # Every column the document carries about money and people, taken from one
    # measured incident. What makes this worth asserting is not the arithmetic -
    # it is that each figure lands in its own column, and a document that put
    # the minimum where the midpoint goes would be wrong in a way no reader
    # could see.
    some_loss = Decimal("1234.56")
    some_minutes = 25
    some_responders = 2
    some_cost = ResponderCost(midpoint=Decimal("30"),
                              minimum=Decimal("15"),
                              maximum=Decimal("60"),
                              currency=SOME_CURRENCY)

    Scenario() \
        .given(
            a_fully_measured_incident := a_measured_incident(
                loss=some_loss,
                engaged=an_engagement_of([
                    EngagedResponder(minutes=15, job_title=SOME_TITLE),
                    EngagedResponder(minutes=10, job_title=SOME_OTHER_TITLE)
                ]),
                cost=some_cost)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle(),
                some_sources(),
                _dont_care_llm(),
                measure=_measuring_that_returns(a_fully_measured_incident),
                ask=_asking_that_answers(a_submitted_answer()),
                disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                estimates_a_loss_of(some_loss),
                states_the_estimate_is_in(SOME_CURRENCY),
                reports_engineer_minutes(some_minutes),
                reports_responders(some_responders),
                reports_the_titles(SOME_TITLE, SOME_OTHER_TITLE),
                reports_a_responder_cost_of(some_cost.midpoint),
                reports_a_cost_ranging_from(some_cost.minimum, some_cost.maximum),
                reports_the_cost_in(SOME_CURRENCY)
            )
        )


@pytest.mark.unit
def test_an_incident_nobody_could_measure_reports_no_response() -> None:
    # The absence has to survive the arrangement. A document defaulting the
    # minutes to zero because nobody answered would report an incident that
    # took nobody's night, out of a source Argus failed to reach.
    Scenario() \
        .given(
            an_incident_nobody_could_say_who_worked_on := a_measured_incident(
                engaged=None, cost=None)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle(),
                some_sources(),
                _dont_care_llm(),
                measure=_measuring_that_returns(
                    an_incident_nobody_could_say_who_worked_on),
                ask=_asking_that_answers(a_submitted_answer()),
                disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                reports_no_engineer_minutes(),
                reports_no_responder_cost()
            )
        )


@pytest.mark.unit
def test_the_disclosures_produced_are_the_disclosures_listed() -> None:
    # In the order they were produced, and nothing added on the way past. The
    # order is the disclosure module's, and a document that sorted them or
    # deduplicated them would be editing what the page admits to.
    some_disclosures = ["the first thing assumed", "the second thing assumed"]

    Scenario() \
        .given(
            a_disclosure_of_two_things := _disclosing_that_returns(some_disclosures)
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=a_disclosure_of_two_things)
        ) \
        .then(
            _lists_exactly(some_disclosures)
        )


@pytest.mark.unit
def test_the_review_is_of_the_document_as_written_with_the_faults_still_in_it() -> None:
    # The one judgement this module makes. The faults do not stop a document
    # being written - the incident is over and a partial account is worth more
    # than none - so they go to the review beside the document they are about,
    # and the page says on its face what it is.
    some_faults = ["the field [root_cause] was missing"]
    some_review = [ReviewCriterion(criterion="some criterion", met=False)]
    reviewing = _reviewing_that_returns(some_review)

    Scenario() \
        .given(
            an_answer_still_wrong := _asking_that_answers(a_submitted_answer(),
                                                          faults=some_faults)
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=an_answer_still_wrong,
                                     disclose=_disclosing_that_returns([]),
                                     review=reviewing)
        ) \
        .then(
            all_of(
                _publishes("the review", lambda document: document.review, some_review),
                _reviewed_as_written(reviewing, some_faults)
            )
        )


@pytest.mark.unit
def test_the_sections_the_record_holds_are_the_sections_published() -> None:
    # Each written by code from the record, and never asked of the model.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("a flag change", subject=SOME_FLAG,
                                        tested=True, result=Verdict.CONFIRMED)],
                actions=[an_action(f"revert_feature_flag on {SOME_FLAG}",
                                   verdict=Verdict.CONFIRMED)])
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                _publishes("the detection",
                           lambda document: document.detection, detection_of(evidence)),
                _publishes("the trigger",
                           lambda document: document.trigger, trigger_of(evidence)),
                _publishes("the resolution",
                           lambda document: document.resolution, resolution_of(evidence)),
                _publishes("the hypotheses",
                           lambda document: document.hypotheses, hypotheses_of(evidence))
            )
        )


@pytest.mark.unit
def test_the_impact_is_the_incident_as_measured() -> None:
    Scenario() \
        .given(
            measured := a_measured_incident()
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(measured),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _publishes("the impact", lambda document: document.impact, impact_of(measured))
        )


@pytest.mark.unit
def test_the_timeline_ends_where_the_measured_recovery_does() -> None:
    # Not where the record put it. The document's duration ends at the
    # measured recovery, and a timeline ending somewhere else would contradict
    # the figure printed beside it.
    some_measured_recovery = RECOVERED_AT
    some_recorded_recovery = RECOVERED_AT + timedelta(minutes=7)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(recorded_recovery_at=some_recorded_recovery)
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident(
                                             recovered_at=some_measured_recovery)),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _publishes("the timeline",
                       lambda document: document.timeline,
                       timeline_of(evidence, some_measured_recovery))
        )


@pytest.mark.unit
def test_the_model_s_proposals_are_numbered_after_the_record_s_own_items() -> None:
    # The record's items were numbered before the model was asked, so its
    # factors could name them; its own proposals follow on, in the order it
    # gave them. Open and nobody's: Argus edits no item after the document is
    # written, so whoever takes one on does so somewhere else.
    evidence = an_evidence_bundle(pull_request=OpenedPullRequest(
        number=7, url="https://example.invalid/pull/7", branch="argus/fix-abc"))

    Scenario() \
        .given(
            a_model_proposing_two := _asking_that_answers(
                a_submitted_answer().model_copy(update={"action_items": [
                    SubmittedItem(item="test an empty month", type=ActionItemType.PREVENT),
                    SubmittedItem(item="alert on account pages", type=ActionItemType.DETECT)
                ]}))
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=a_model_proposing_two,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _publishes("the action items", lambda document: document.action_items, [
                *record_action_items_of(evidence),
                ActionItem(number="AI-2", text="test an empty month",
                           type=ActionItemType.PREVENT, owner=None, tracking=None,
                           status=ActionItemStatus.OPEN),
                ActionItem(number="AI-3", text="alert on account pages",
                           type=ActionItemType.DETECT, owner=None, tracking=None,
                           status=ActionItemStatus.OPEN)
            ])
        )


@pytest.mark.unit
def test_each_step_carries_the_text_of_the_evidence_it_cites() -> None:
    # The label means nothing outside the prompt it was given in, and the
    # stored document is read without one.
    the_log_line = "ZeroDivisionError in monthly_average"
    its_label = grouped([the_log_line])[0].label

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[the_log_line])
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(
                                         a_submitted_answer().model_copy(update={
                                             "causal_chain": [SubmittedStep(
                                                 step="the monthly average divided by zero",
                                                 cites=[its_label])]
                                         })),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _publishes("the causal chain", lambda document: document.causal_chain, [
                ChainStep(text="the monthly average divided by zero",
                          cites=[CitedEvidence(label=its_label, text=the_log_line)])
            ])
        )


@pytest.mark.unit
def test_a_citation_of_evidence_never_shown_is_not_published() -> None:
    # The check has named it already, and the review holds it against the
    # analysis. Kept, it would be a citation a reader can follow nowhere.
    the_log_line = "ZeroDivisionError in monthly_average"
    its_label = grouped([the_log_line])[0].label

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[the_log_line])
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(
                                         a_submitted_answer().model_copy(update={
                                             "causal_chain": [SubmittedStep(
                                                 step="the monthly average divided by zero",
                                                 cites=[its_label, "T99"])]
                                         }),
                                         faults=["the step cites [T99], which was never shown"]),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _publishes("the causal chain", lambda document: document.causal_chain, [
                ChainStep(text="the monthly average divided by zero",
                          cites=[CitedEvidence(label=its_label, text=the_log_line)])
            ])
        )


@pytest.mark.unit
def test_the_factors_and_lessons_the_model_wrote_are_the_ones_published() -> None:
    some_lessons = Lessons(went_well=["the alert fired within minutes"],
                           went_wrong=["no test exercised an empty month"],
                           got_lucky=["the fault was behind a flag"])

    Scenario() \
        .given(
            a_model_that_answered := _asking_that_answers(
                a_submitted_answer().model_copy(update={
                    "contributing_factors": [SubmittedFactor(
                        factor="the canary started at full traffic",
                        addressed_by=["AI-1"])],
                    "lessons": some_lessons
                }))
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=a_model_that_answered,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                _publishes("the contributing factors",
                           lambda document: document.contributing_factors,
                           [ContributingFactor(text="the canary started at full traffic",
                                               addressed_by=["AI-1"])]),
                _publishes("the lessons", lambda document: document.lessons, some_lessons)
            )
        )


@pytest.mark.unit
def test_the_evidence_read_is_every_piece_the_model_was_shown() -> None:
    # Two lines of narration, three of logs, one candidate, one action.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[a_timeline_entry("dont care"), a_timeline_entry("dont care")],
                log_lines=["one message", "another message", "a third message"],
                candidates=[a_candidate("dont care")],
                actions=[an_action("dont care")])
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _publishes("the evidence read", lambda document: document.evidence_read, 7)
        )


@pytest.mark.unit
def test_the_changes_and_log_messages_shown_are_published_under_their_labels() -> None:
    # The prose cites them by the labels the model was shown them under, and
    # no other section is a row for either - so the document carries them, or
    # a reader told "the deploy P2" has nowhere to find out what P2 was. The
    # labels are asserted on their own as well, so a list that came back empty
    # from both sides cannot pass for one that was carried.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                changes=[_a_change("some-revision"), _a_change("some-other-revision")],
                log_lines=["one message", "another message"])
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                _publishes("the changes read",
                           lambda document: document.changes_read,
                           the_changes_labelled(evidence)),
                _publishes("the changes' labels",
                           lambda document: [cited.label for cited in document.changes_read],
                           ["P1", "P2"]),
                _publishes("the log messages read",
                           lambda document: document.log_messages_read,
                           grouped(evidence.log_lines)),
                _publishes("the log messages' count",
                           lambda document: len(document.log_messages_read),
                           2)
            )
        )


@pytest.mark.unit
def test_the_tokens_the_incident_spent_come_from_its_evidence() -> None:
    # Not from this call. What the walk spent was counted while it was
    # happening, and the postmortem's own tokens are not part of what the
    # incident cost to handle.
    some_tokens_spent = 48_120

    Scenario() \
        .given(
            evidence := an_evidence_bundle(tokens_spent=some_tokens_spent)
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            reports_tokens_spent(some_tokens_spent)
        )


@pytest.mark.unit
def test_the_fix_that_was_proposed_is_carried_onto_the_document() -> None:
    # Carried, not written. The walk already opened the pull request and
    # recorded where; a document that relied on the model mentioning it in its
    # prose would lose the address on every run where the prose read fine
    # without one - which is what happened.
    where_it_can_be_read = "https://example.invalid/pull/7"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                pull_request=OpenedPullRequest(
                    number=7, url=where_it_can_be_read, branch="argus/fix-abc"
                )
            )
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            proposes_the_fix_at(where_it_can_be_read)
        )


@pytest.mark.unit
def test_each_lead_is_reported_with_what_the_model_said_it_changed() -> None:
    # The record's facts carried across, and the model's one sentence beside
    # them: who wrote, what they wrote, and what the investigation made of it
    # are not the model's to restate, and whether it changed what was done is
    # the one part only prose can carry. A lead the model said nothing about
    # is reported with nothing said, never dropped - the person who wrote it
    # is owed the line either way.
    a_supported_lead = a_lead(
        "the kuki flag was flipped at noon",
        Weighing(standing=Standing.SUPPORTED, reason="the flag history agrees"),
        ts="1760000100.000200"
    )
    an_unweighed_lead = a_lead("it is the database again", ts="1760000200.000300")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(leads=[a_supported_lead, an_unweighed_lead])
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer(
                                         lead_effects={"L1": "it named the flag reverted"}
                                     )),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _reports_the_leads([
                PostmortemLead(label="L1",
                               person_id=a_supported_lead.person_id,
                               person_name=None,
                               text=a_supported_lead.text,
                               written_at=a_supported_lead.written_at,
                               weighing=a_supported_lead.weighing,
                               effect="it named the flag reverted"),
                PostmortemLead(label="L2",
                               person_id=an_unweighed_lead.person_id,
                               person_name=None,
                               text=an_unweighed_lead.text,
                               written_at=an_unweighed_lead.written_at,
                               weighing=None,
                               effect=None)
            ])
        )


@pytest.mark.unit
def test_each_lead_carries_the_label_the_model_was_shown_it_by() -> None:
    # The prose cites a lead by it, so the page needs it for the citation to
    # lead anywhere - and it is written here, where the prompt numbered the
    # leads, so nothing downstream numbers them a second time and comes to
    # disagree about which lead a label names.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(leads=[
                a_lead("the kuki flag was flipped at noon", ts="1760000100.000200"),
                a_lead("it is the database again", ts="1760000200.000300")
            ])
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _publishes("the leads' labels",
                       lambda document: [lead.label for lead in document.leads],
                       ["L1", "L2"])
        )


@pytest.mark.unit
def test_each_lead_is_reported_under_its_writers_name_or_none_where_there_is_none() -> None:
    # The document names the person it owes the line to, as the chat platform
    # named them - and says it had no name where the platform could not, so
    # the page can stand the id in rather than a name nobody gave.
    some_name = "Some Person"
    a_named_lead = a_lead("the kuki flag was flipped at noon",
                          ts="1760000100.000200").model_copy(update={"person_name": some_name})
    an_unnamed_lead = a_lead("it is the database again", ts="1760000200.000300")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(leads=[a_named_lead, an_unnamed_lead])
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _names_the_writers([some_name, None])
        )


@pytest.mark.unit
def test_the_action_nobody_took_is_carried_onto_the_document() -> None:
    # Carried, not written, for the reason the pull request is: the gate worked
    # this out and declined it, and a document that relied on the model
    # mentioning it would lose the one thing a reader goes on to do - silently,
    # on every run where the summary read perfectly well without it.
    #
    # This one is worse to lose than the address. A postmortem that omits a
    # link still describes an incident somebody can act on; one that omits this
    # describes an incident that is over, and it is not over - the flag is
    # still on and the shop is still writing wrong totals.
    what_somebody_should_do = "put the monthly-spend-feature flag back"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                recommended_action=what_somebody_should_do
            )
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _it_says_what_is_still_owed(what_somebody_should_do)
        )


@pytest.mark.unit
def test_an_incident_argus_acted_on_itself_owes_nobody_an_action() -> None:
    # The ordinary ending. Argus took the action and watched it work, so there
    # is nothing here for a person to do, and a document saying otherwise would
    # send somebody to repeat a change already made.
    Scenario() \
        .given(evidence := an_evidence_bundle()) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _it_says_what_is_still_owed(None)
        )


@pytest.mark.unit
def test_an_incident_that_proposed_no_fix_offers_nowhere_to_read_one() -> None:
    # The ordinary ending: the flag went back and there was nothing in the code
    # to change. An empty link on the page would read as a proposal whose
    # address went missing.
    Scenario() \
        .given(evidence := an_evidence_bundle()) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            proposes_the_fix_at(None)
        )


@pytest.mark.unit
def test_the_model_is_asked_about_the_incident_that_was_measured() -> None:
    # The whole reason the measuring happens first. A model handed figures from
    # anything but this incident writes fluent prose about a different one, and
    # the document reads perfectly either way.
    measured = a_measured_incident()
    asking = _asking_that_answers(a_submitted_answer())

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(measured),
                                     ask=asking,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _was_asked_about(asking, evidence.incident_id, measured)
        )


@pytest.mark.unit
def test_the_disclosures_are_written_from_what_was_measured_and_configured() -> None:
    # The disclosure module reads no source of its own, so everything it needs
    # has to arrive here: the incident as measured, and the working year the
    # bands were divided by. Handed a different working year from the one the
    # cost was computed under, it would publish a divisor that does not explain
    # the figure beside it.
    measured = a_measured_incident()
    disclosing = _disclosing_that_returns([])
    some_working_year = 1_900.0

    Scenario() \
        .given(
            sources := some_sources(working_hours_a_year=some_working_year)
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     sources,
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(measured),
                                     ask=_asking_that_answers(a_submitted_answer()),
                                     disclose=disclosing)
        ) \
        .then(
            _disclosed_from(disclosing, measured, some_working_year)
        )


@pytest.mark.unit
def test_a_document_written_incomplete_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The page says so on its face; this is the line saying so to whoever is
    # watching the model rather than reading the document.
    some_faults = ["the field [root_cause] was missing"]

    Scenario() \
        .given(
            an_answer_still_wrong := _asking_that_answers(a_submitted_answer(),
                                                          faults=some_faults)
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=an_answer_still_wrong,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            one_record_was_logged(caplog, "agent_postmortem.writing", logging.WARNING,
                                  "postmortem written incomplete",
                                  values={"faults": some_faults})
        )


def _a_change(reference: str) -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.DEPLOY,
                       occurred_at="2026-09-02T11:59:00Z",
                       reference=reference,
                       summary="dont care")


def _measuring_that_returns(measured: Measurements) -> MagicMock:
    measuring = create_autospec(measure)
    measuring.return_value = measured

    return cast(MagicMock, measuring)


def _reports_symptom(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.symptom != expected:
            raise AssertionError(
                f"Expected the symptom [{expected}], got [{document.symptom}].")

        return True

    return assertion


def _asking_that_answers(answer: SubmittedPostmortem,
                         faults: list[str] | None = None) -> MagicMock:
    asking = create_autospec(answer_worth_writing)
    asking.return_value = (answer, faults if faults is not None else [])

    return cast(MagicMock, asking)


def _disclosing_that_returns(assumptions: list[str]) -> MagicMock:
    disclosing = create_autospec(assumptions_of)
    disclosing.return_value = assumptions

    return cast(MagicMock, disclosing)


def _reviewing_that_returns(review: list[ReviewCriterion]) -> MagicMock:
    reviewing = create_autospec(review_of)
    reviewing.return_value = review

    return cast(MagicMock, reviewing)


def _dont_care_llm() -> MagicMock:
    """A model nothing here ever reaches.

    Every test in this file mocks the asking, so the client is carried and not
    called - which is itself worth a double rather than a `None`, since a
    module that reached past its collaborator to the model would then fail
    here rather than in production.
    """
    return cast(MagicMock, create_autospec(_dont_care_llm))


def _publishes(what: str,
               read: Callable[[PostmortemDocument], object],
               expected: object) -> Assertion[PostmortemDocument]:
    """One section of the document, read off it by `read`, is `expected`."""
    def assertion(document: PostmortemDocument) -> bool:
        published = read(document)

        if published != expected:
            raise AssertionError(
                f"Expected the document to publish {what} as {expected}, got {published}.")

        return True

    return assertion


def _reports_the_leads(expected: list[PostmortemLead]) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.leads != expected:
            raise AssertionError(
                f"Expected the document to report the leads {expected}, got "
                f"{document.leads}.")

        return True

    return assertion


def _names_the_writers(expected: list[str | None]) -> Assertion[PostmortemDocument]:
    """Each lead's writer by the name the document reports them under, in the
    order written."""
    def assertion(document: PostmortemDocument) -> bool:
        named = [lead.person_name for lead in document.leads]

        if named != expected:
            raise AssertionError(
                f"Expected the leads' writers named {expected}, got {named}."
            )

        return True

    return assertion


def _lists_exactly(expected: list[str]) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.assumptions != expected:
            raise AssertionError(
                f"Expected the document to list {expected}, got {document.assumptions}")

        return True

    return assertion


def _reviewed_as_written(reviewing: MagicMock,
                         faults: list[str]) -> Assertion[PostmortemDocument]:
    """The review was of this document - every section but the review itself -
    and of the faults the answer still carried."""
    def assertion(document: PostmortemDocument) -> bool:
        reviewed, reviewed_with = reviewing.call_args.args
        as_written = document.model_copy(update={"review": []})

        if reviewed != as_written:
            raise AssertionError(
                f"Expected the review to be of the document as written, got "
                f"[{reviewed}].")

        if reviewed_with != faults:
            raise AssertionError(
                f"Expected the review to be given the faults {faults}, got "
                f"{reviewed_with}.")

        return True

    return assertion


def _was_asked_about(asking: MagicMock,
                     incident_id: str,
                     measured: Measurements) -> Assertion[PostmortemDocument]:
    """The model was put this incident, with these figures beside it."""
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        _, evidence, put_to_it = asking.call_args.args

        if evidence.incident_id != incident_id:
            raise AssertionError(
                f"Expected the model to be asked about incident [{incident_id}], "
                f"got [{evidence.incident_id}].")

        if put_to_it is not measured:
            raise AssertionError(
                f"Expected the model to be given the incident as measured, got "
                f"[{put_to_it}].")

        return True

    return assertion


def _disclosed_from(disclosing: MagicMock,
                    measured: Measurements,
                    working_hours_a_year: float) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        _, disclosed_from, under = disclosing.call_args.args

        if disclosed_from is not measured:
            raise AssertionError(
                f"Expected the disclosures to be written from the incident as "
                f"measured, got [{disclosed_from}].")

        if under != working_hours_a_year:
            raise AssertionError(
                f"Expected the disclosures to be written under a working year of "
                f"[{working_hours_a_year}], got [{under}].")

        return True

    return assertion
