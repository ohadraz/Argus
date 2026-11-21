"""The one shape the model's answer may take, read off its call and said back.

The answer arrives as a tool call, and each field of it costs only itself: one
that did not arrive in its declared shape is read as unanswered, never as a
refusal of the whole call, so a root cause the model did write still reaches the
document. And every sentence it would publish is read by one walk over its
fields - the one the checks read, and the one the figures are written in by - so
a field one of them left out would be prose the other's rule never sees.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from core.models import ActionItemType, Lessons
from postmortem_writing.answer import (
    ACTION_ITEMS_FIELD,
    ADDRESSED_BY_FIELD,
    ANSWERS_FIELD,
    ASSUMPTIONS_FIELD,
    CAUSAL_CHAIN_FIELD,
    CAUSE_IN_PLAIN_WORDS_FIELD,
    CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD,
    CITES_FIELD,
    CONTRIBUTING_FACTORS_FIELD,
    EFFECT_FIELD,
    FACTOR_FIELD,
    GOT_LUCKY_FIELD,
    HAD_IT_BEEN_OTHERWISE_FIELD,
    ITEM_FIELD,
    ITEM_TYPE_FIELD,
    LABEL_FIELD,
    LEAD_EFFECTS_FIELD,
    LEAD_FIELD,
    LESSONS_FIELD,
    LOGS_SHOW_SERVING_AS_BEFORE_FIELD,
    REACHES_A_CAUSE_FIELD,
    ROOT_CAUSE_FIELD,
    RULED_OUT_FIELD,
    STEP_FIELD,
    STILL_AT_RISK_FIELD,
    TIMED_BY_FIELD,
    WENT_WELL_FIELD,
    WENT_WRONG_FIELD,
    WHAT_FIELD,
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedRuledOut,
    SubmittedStep,
)

from postmortem_writing_test.framework.builders import an_answer, an_answer_without


@pytest.mark.unit
def test_every_sentence_the_answer_would_publish_is_read() -> None:
    # The check reads only what this yields. A field left out is prose whose
    # figures nothing refuses and whose names nothing writes in.
    some_answer = SubmittedPostmortem(
        root_cause="the root cause",
        cause_in_plain_words="the cause in plain words",
        still_at_risk="what is still at risk",
        symptom="the symptom",
        stops_the_harm="what stops the harm",
        why_it_did_not_help="why it did not help",
        assumptions=["an assumption"],
        lead_effects={"L1": "a lead's effect"},
        causal_chain=[SubmittedStep(step="a step", cites=["T1"],
                                    ruled_out=[SubmittedRuledOut(what="what it ruled out",
                                                                 cites=["T2"])])],
        contributing_factors=[SubmittedFactor(factor="a factor",
                                              had_it_been_otherwise="had it been otherwise",
                                              addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item="an item", type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=["went well"], went_wrong=["went wrong"],
                        got_lucky=["got lucky"]))

    Scenario() \
        .when(
            lambda: list(some_answer.sentences())
        ) \
        .then(
            the_answer_was(["the root cause", "the cause in plain words",
                            "what is still at risk", "the symptom", "what stops the harm",
                            "why it did not help", "an assumption", "a lead's effect",
                            "a step", "what it ruled out", "a factor",
                            "had it been otherwise", "an item", "went well", "went wrong",
                            "got lucky"])
        )


@pytest.mark.unit
def test_every_sentence_the_answer_would_publish_is_read_with_a_place_of_its_own() -> None:
    # A fault keyed by its check alone is one the model is never told of again
    # once it moves into another item: told of it in one item, a rewrite saying
    # it in another would count as already told. So every sentence comes with a
    # place of its own, which is what a fault found in it is keyed by.
    some_answer = SubmittedPostmortem(
        root_cause="the root cause",
        cause_in_plain_words="the cause in plain words",
        still_at_risk="what is still at risk",
        symptom="the symptom",
        stops_the_harm="what stops the harm",
        why_it_did_not_help="why it did not help",
        assumptions=["an assumption"],
        lead_effects={"L1": "a lead's effect"},
        causal_chain=[SubmittedStep(step="a step", cites=["T1"],
                                    ruled_out=[SubmittedRuledOut(what="what it ruled out",
                                                                 cites=["T2"])])],
        contributing_factors=[SubmittedFactor(factor="a factor",
                                              had_it_been_otherwise="had it been otherwise",
                                              addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item="an item", type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=["went well"], went_wrong=["went wrong"],
                        got_lucky=["got lucky"]))

    Scenario() \
        .when(
            lambda: list(some_answer.placed_sentences())
        ) \
        .then(all_of(
            _read_in_the_order_sentences_reads(some_answer),
            _each_in_a_place_of_its_own()
        ))


@pytest.mark.unit
def test_a_sentence_code_says_instead_is_not_read() -> None:
    # Code says it in the record's words, or drops it: none of the model's
    # words there reach a reader, and no rule is held to them.
    some_step = "a step"
    some_answer = SubmittedPostmortem(
        causal_chain=[SubmittedStep(step=some_step, cites=["T1"],
                                    ruled_out=[SubmittedRuledOut(what="what code says instead",
                                                                 cites=["T2"])])],
        lessons=Lessons(went_well=["what code says as its row"], went_wrong=[], got_lucky=[]),
        said_by_code=frozenset({f"{CAUSAL_CHAIN_FIELD} 1 {RULED_OUT_FIELD} 1",
                                f"{WENT_WELL_FIELD} 1"}))

    Scenario() \
        .when(
            lambda: list(some_answer.sentences())
        ) \
        .then(
            the_answer_was([some_step])
        )


@pytest.mark.unit
def test_what_a_step_ruled_out_is_rewritten_as_every_other_sentence_is() -> None:
    # Read by the same fields `sentences` reads: a figure named in what was
    # ruled out is written in like one named anywhere else.
    some_answer = SubmittedPostmortem(
        causal_chain=[SubmittedStep(step="a step", cites=["T1"],
                                    ruled_out=[SubmittedRuledOut(what="what it ruled out",
                                                                 cites=["T2"])])])

    Scenario() \
        .when(
            lambda: some_answer.with_each_sentence(str.upper).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(step="A STEP", cites=["T1"],
                                          ruled_out=[SubmittedRuledOut(
                                              what="WHAT IT RULED OUT", cites=["T2"])])])
        )


@pytest.mark.unit
def test_a_rule_out_the_record_says_stays_marked_so_when_rewritten() -> None:
    # Rewritten is how the figures are written in, after code has said the
    # rule-out from its rows; rebuilt from its words and citations alone, it
    # reached the document unmarked, and the page cited its rows twice over.
    some_step, some_step_cites = "a step", ["T1"]
    some_rule_out, some_rule_out_cites = "what the record rules out", ["T2"]

    Scenario() \
        .given(
            some_answer := SubmittedPostmortem(causal_chain=[SubmittedStep(
                step=some_step, cites=some_step_cites,
                ruled_out=[SubmittedRuledOut(what=some_rule_out, cites=some_rule_out_cites,
                                             by_the_record=True)])])
        ) \
        .when(
            lambda: some_answer.with_each_sentence(str.upper).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(
                step=some_step.upper(), cites=some_step_cites,
                ruled_out=[SubmittedRuledOut(what=some_rule_out.upper(),
                                             cites=some_rule_out_cites,
                                             by_the_record=True)])])
        )


@pytest.mark.unit
def test_what_a_factor_would_have_changed_is_rewritten_as_every_other_sentence_is() -> None:
    # Read by the same fields `sentences` reads: a figure named in what a
    # factor would have changed is written in like one named anywhere else.
    some_answer = SubmittedPostmortem(
        contributing_factors=[SubmittedFactor(label="CF-1", factor="a factor",
                                              had_it_been_otherwise="had it been otherwise",
                                              addressed_by=["AI-1"])])

    Scenario() \
        .when(
            lambda: some_answer.with_each_sentence(str.upper).contributing_factors
        ) \
        .then(
            the_answer_was([SubmittedFactor(label="CF-1", factor="A FACTOR",
                                            had_it_been_otherwise="HAD IT BEEN OTHERWISE",
                                            addressed_by=["AI-1"])])
        )


@pytest.mark.unit
def test_what_a_put_back_asks_for_is_rewritten_as_every_other_sentence_is() -> None:
    # Read by the same fields `sentences` reads: a figure named in what stops
    # the harm, or in why the change put back did not help, is written in like
    # one named anywhere else - and the item that stops it names one.
    some_answer = SubmittedPostmortem(stops_the_harm="what stops the harm",
                                      why_it_did_not_help="why it did not help")

    Scenario() \
        .when(
            lambda: some_answer.with_each_sentence(str.upper)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(stops_the_harm="WHAT STOPS THE HARM",
                                               why_it_did_not_help="WHY IT DID NOT HELP"))
        )


@pytest.mark.unit
def test_the_factors_an_item_answers_survive_the_rewrite() -> None:
    # Labels, not prose: rewriting the item's words leaves what it answers.
    some_answer = SubmittedPostmortem(
        action_items=[SubmittedItem(item="an item", type=ActionItemType.PREVENT,
                                    answers=["CF-1"])])

    Scenario() \
        .when(
            lambda: some_answer.with_each_sentence(str.upper).action_items
        ) \
        .then(
            the_answer_was([SubmittedItem(item="AN ITEM", type=ActionItemType.PREVENT,
                                          answers=["CF-1"])])
        )


@pytest.mark.unit
def test_what_went_well_is_read_with_the_row_each_item_happened_on() -> None:
    # In step, off the one list: an item naming no row is timed by nothing, as
    # is one naming it in blanks.
    Scenario() \
        .when(
            lambda: SubmittedPostmortem.model_validate({LESSONS_FIELD: {WENT_WELL_FIELD: [
                {ITEM_FIELD: "THE FIRST", TIMED_BY_FIELD: "T13"},
                {ITEM_FIELD: "THE SECOND"},
                {ITEM_FIELD: "THE THIRD", TIMED_BY_FIELD: "  "}]}})
        ) \
        .then(all_of(
            _what_went_well_reads(["THE FIRST", "THE SECOND", "THE THIRD"]),
            _timed_by(["T13", None, None])
        ))


@pytest.mark.unit
def test_what_went_well_sent_as_sentences_is_read_as_the_shape_before_rows() -> None:
    # The shape every answer recorded before the rows were asked for came in,
    # which a replay of one still sends - and which `checking` holds to none
    # of what it asks of the new one.
    Scenario() \
        .when(
            lambda: SubmittedPostmortem.model_validate({LESSONS_FIELD: {WENT_WELL_FIELD: [
                "THE FIRST", "THE SECOND"]}})
        ) \
        .then(all_of(
            _what_went_well_reads(["THE FIRST", "THE SECOND"]),
            _timed_by(None)
        ))


@pytest.mark.unit
def test_what_each_lead_changed_is_read_by_the_lead_it_names() -> None:
    Scenario() \
        .given(
            a_submission_saying_what_two_leads_changed := an_answer(
                lead_effects={"L1": "it named the flag reverted",
                              "L2": "it changed nothing"}
            )
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_saying_what_two_leads_changed)
        ) \
        .then(
            _says_of_the_leads({"L1": "it named the flag reverted",
                                "L2": "it changed nothing"})
        )


@pytest.mark.unit
def test_a_lead_effect_not_in_its_declared_shape_costs_only_itself() -> None:
    # As an assumption that is not a sentence costs that line: one unreadable
    # entry is one lead the check then names and asks about again, where
    # refusing the list would lose what was said of every other.
    Scenario() \
        .given(
            a_submission_with_one_readable_effect := {
                LEAD_EFFECTS_FIELD: [
                    {LEAD_FIELD: "L1", EFFECT_FIELD: "it named the flag reverted"},
                    {LEAD_FIELD: "L2"},
                    "not an entry"
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_with_one_readable_effect)
        ) \
        .then(
            _says_of_the_leads({"L1": "it named the flag reverted"})
        )


@pytest.mark.unit
def test_the_cause_is_read_as_steps_each_citing_its_evidence() -> None:
    Scenario() \
        .given(
            a_submission_with_a_chain := {
                CAUSAL_CHAIN_FIELD: [
                    {STEP_FIELD: "account pages returned 500", CITES_FIELD: ["E1", "E2"]},
                    {STEP_FIELD: "the divisor was zero", CITES_FIELD: ["E3"]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission_with_a_chain).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(step="account pages returned 500", cites=["E1", "E2"]),
                            SubmittedStep(step="the divisor was zero", cites=["E3"])])
        )


@pytest.mark.unit
def test_what_a_step_ruled_out_is_read_with_what_it_cites() -> None:
    Scenario() \
        .given(
            a_submission_ruling_something_out := {
                CAUSAL_CHAIN_FIELD: [
                    {STEP_FIELD: "the deploy renamed the port", CITES_FIELD: ["D1"],
                     RULED_OUT_FIELD: [{WHAT_FIELD: "the earlier deploy, healthy since",
                                        CITES_FIELD: ["T5"]}]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_ruling_something_out).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(
                step="the deploy renamed the port", cites=["D1"],
                ruled_out=[SubmittedRuledOut(what="the earlier deploy, healthy since",
                                             cites=["T5"])])])
        )


@pytest.mark.unit
def test_what_a_step_ruled_out_not_in_its_declared_shape_costs_only_itself() -> None:
    # As a step does: one with no words is dropped, one citing in the wrong
    # shape is kept citing nothing, and a list that is not one rules out
    # nothing - the step itself stands either way.
    Scenario() \
        .given(
            a_submission_ruling_out_badly := {
                CAUSAL_CHAIN_FIELD: [
                    {STEP_FIELD: "the deploy renamed the port", CITES_FIELD: ["D1"],
                     RULED_OUT_FIELD: [{WHAT_FIELD: "the earlier deploy", CITES_FIELD: "T5"},
                                       {CITES_FIELD: ["T5"]},
                                       "not a ruling"]},
                    {STEP_FIELD: "the scrape lost its target", CITES_FIELD: ["F1"],
                     RULED_OUT_FIELD: "not a list"}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission_ruling_out_badly).causal_chain
        ) \
        .then(
            the_answer_was([
                SubmittedStep(step="the deploy renamed the port", cites=["D1"],
                              ruled_out=[SubmittedRuledOut(what="the earlier deploy",
                                                           cites=[])]),
                SubmittedStep(step="the scrape lost its target", cites=["F1"])])
        )


@pytest.mark.unit
def test_a_chain_step_not_in_its_declared_shape_costs_only_itself() -> None:
    # A step with no words is no step; one citing in the wrong shape still
    # said something, and is read as citing nothing - which the check then
    # names, rather than the reading silently dropping a claim.
    Scenario() \
        .given(
            a_submission_with_one_readable_step := {
                CAUSAL_CHAIN_FIELD: [
                    {STEP_FIELD: "the divisor was zero", CITES_FIELD: "E3"},
                    {CITES_FIELD: ["E1"]},
                    "not a step"
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_with_one_readable_step).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(step="the divisor was zero", cites=[])])
        )


@pytest.mark.unit
def test_a_contributing_factor_is_read_with_its_label_and_the_record_s_items_that_answer_it(
) -> None:
    Scenario() \
        .given(
            a_submission_with_a_factor := {
                CONTRIBUTING_FACTORS_FIELD: [
                    {LABEL_FIELD: "CF-1",
                     FACTOR_FIELD: "the canary started at 40%",
                     HAD_IT_BEEN_OTHERWISE_FIELD: "a smaller canary would have failed fewer",
                     ADDRESSED_BY_FIELD: ["AI-2"]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_with_a_factor).contributing_factors
        ) \
        .then(
            the_answer_was([SubmittedFactor(
                label="CF-1",
                factor="the canary started at 40%",
                had_it_been_otherwise="a smaller canary would have failed fewer",
                addressed_by=["AI-2"])])
        )


@pytest.mark.unit
def test_a_proposed_item_of_a_kind_nobody_declared_costs_only_itself() -> None:
    # The four kinds are Google's, and a fifth is a proposal nobody can file.
    Scenario() \
        .given(
            a_submission_proposing_two := {
                ACTION_ITEMS_FIELD: [
                    {ITEM_FIELD: "add a test for an empty month",
                     ITEM_TYPE_FIELD: "prevent"},
                    {ITEM_FIELD: "be more careful", ITEM_TYPE_FIELD: "vibes"}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_proposing_two).action_items
        ) \
        .then(
            the_answer_was([SubmittedItem(item="add a test for an empty month",
                                          type=ActionItemType.PREVENT)])
        )


@pytest.mark.unit
def test_a_proposed_item_is_read_with_the_factors_it_answers() -> None:
    # The item names the factors, by the labels they were written under, rather
    # than a factor naming the item: told to cite items it had not yet written,
    # by numbers it had to work out, a write-up cited each one number off.
    Scenario() \
        .given(
            a_submission_proposing_one := {
                ACTION_ITEMS_FIELD: [
                    {ITEM_FIELD: "add a test for an empty month",
                     ITEM_TYPE_FIELD: "prevent",
                     ANSWERS_FIELD: ["CF-1", "CF-3"]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_proposing_one).action_items
        ) \
        .then(
            the_answer_was([SubmittedItem(item="add a test for an empty month",
                                          type=ActionItemType.PREVENT,
                                          answers=["CF-1", "CF-3"])])
        )


@pytest.mark.unit
def test_the_lessons_are_read_as_three_lists() -> None:
    Scenario() \
        .given(
            a_submission_with_lessons := {
                LESSONS_FIELD: {WENT_WELL_FIELD: ["the alert fired fast"],
                                WENT_WRONG_FIELD: ["no test covered an empty month"],
                                GOT_LUCKY_FIELD: []}
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission_with_lessons).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=["the alert fired fast"],
                                   went_wrong=["no test covered an empty month"],
                                   got_lucky=[]))
        )


@pytest.mark.unit
def test_a_field_that_did_not_arrive_as_prose_costs_only_itself() -> None:
    # The whole reason the answer is read leniently. A submission refused
    # outright over one badly typed field would throw away a root cause the
    # model wrote, and the document would then record as unanswered something
    # that was answered - a manufactured absence, in an agent whose entire
    # discipline is telling a real one from a missing measurement.
    some_root_cause = "the checkout fallback was disabled by a flag toggle"

    Scenario() \
        .given(
            a_submission_whose_cause_is_not_prose := {
                ROOT_CAUSE_FIELD: some_root_cause,
                CAUSE_IN_PLAIN_WORDS_FIELD: {"nested": "in the wrong shape"}
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_whose_cause_is_not_prose)
        ) \
        .then(
            all_of(
                _answered(ROOT_CAUSE_FIELD, some_root_cause),
                _left_unanswered(CAUSE_IN_PLAIN_WORDS_FIELD)
            )
        )


@pytest.mark.unit
def test_a_figure_where_prose_was_asked_for_is_still_an_answer() -> None:
    # Dropped, it would be a root cause the model supplied and the document
    # denies. Written out, it is an answer in the wrong register - which the
    # reader can see, argue with, and ask about.
    some_figure_the_model_sent = 1200

    Scenario() \
        .given(
            a_submission_answering_with_a_number := {
                ROOT_CAUSE_FIELD: some_figure_the_model_sent
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_answering_with_a_number)
        ) \
        .then(
            _answered(ROOT_CAUSE_FIELD, str(some_figure_the_model_sent))
        )


@pytest.mark.unit
def test_a_single_assumption_sent_on_its_own_is_the_list_containing_it() -> None:
    # A model with one thing to disclose sends it as a sentence rather than as
    # a list of one often enough to be worth reading. Refused, the disclosure
    # would go missing - and a disclosure is the one field whose absence the
    # document has no other way to admit to.
    some_assumption = "the log lines shown were the whole of the failing traffic"

    Scenario() \
        .given(
            a_submission_disclosing_one_thing := {
                ASSUMPTIONS_FIELD: some_assumption
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_disclosing_one_thing)
        ) \
        .then(
            _disclosed([some_assumption])
        )


@pytest.mark.unit
def test_an_assumption_that_is_not_a_sentence_costs_that_line_and_no_other() -> None:
    # One unreadable disclosure is one line lost. Refusing the list would lose
    # every other disclosure with it, and the root cause besides.
    some_assumption = "takings in NZD are not in the figure"

    Scenario() \
        .given(
            a_submission_disclosing_one_of_each := {
                ASSUMPTIONS_FIELD: [some_assumption, {"not": "a sentence"}]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_disclosing_one_of_each)
        ) \
        .then(
            _disclosed([some_assumption])
        )


@pytest.mark.unit
def test_a_submission_carrying_nothing_usable_is_empty_rather_than_refused() -> None:
    # The terminating case, and the one the rest of the agent is built on: an
    # answer nothing can be read out of is an empty answer, not an exception.
    # `checking` names every field that went unanswered, the model is asked once
    # more, and a second unusable answer is written down as an incomplete
    # document rather than thrown away entirely.
    Scenario() \
        .given(
            a_submission_of_something_else := {"nonsense": 1}
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_of_something_else)
        ) \
        .then(
            all_of(
                _left_unanswered(ROOT_CAUSE_FIELD),
                _left_unanswered(CAUSE_IN_PLAIN_WORDS_FIELD),
                _left_unanswered(STILL_AT_RISK_FIELD),
                _left_unanswered(CAUSAL_CHAIN_FIELD),
                _left_unanswered(CONTRIBUTING_FACTORS_FIELD),
                _left_unanswered(ACTION_ITEMS_FIELD),
                _left_unanswered(LESSONS_FIELD),
                _disclosed([])
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("answered", "read_as"), [
    (True, True),
    (False, False),
    ("yes", False),
    (1, False),
    (None, False)
], ids=["yes", "no", "a word", "a number", "null"])
def test_only_a_plain_yes_reads_as_a_chain_that_reaches_a_cause(answered: object,
                                                                read_as: bool) -> None:
    # The box it ticks is one a person signs off on, so anything short of a
    # plain yes reads as no - and costs that box alone, never the answer.
    Scenario() \
        .given(
            a_submission := {REACHES_A_CAUSE_FIELD: answered}
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission).reaches_a_cause
        ) \
        .then(
            the_answer_was(read_as)
        )


@pytest.mark.unit
def test_an_answer_that_never_said_whether_its_chain_reaches_a_cause_reads_as_no() -> None:
    # Every answer recorded before the question existed carries no such field.
    # Read as a chain that stopped at the change, it unticks one box; refused,
    # it would cost a document that was otherwise whole.
    Scenario() \
        .given(
            an_answer_from_before_the_question := an_answer_without(REACHES_A_CAUSE_FIELD)
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                an_answer_from_before_the_question).reaches_a_cause
        ) \
        .then(
            the_answer_was(False)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("answered", "read_as"), [
    (True, True),
    (False, False),
    ("yes", None),
    (1, None),
    (None, None)
], ids=["yes", "no", "a word", "a number", "null"])
def test_only_a_plain_yes_or_no_reads_as_how_the_logs_show_the_service(
        answered: object, read_as: bool | None) -> None:
    # Anything else is unanswered, and asked for again where it was asked -
    # never a guess the document then says, and never the whole answer refused.
    Scenario() \
        .given(
            a_submission := {LOGS_SHOW_SERVING_AS_BEFORE_FIELD: answered}
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission).logs_show_serving_as_before
        ) \
        .then(
            the_answer_was(read_as)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("answered", "read_as"), [
    (True, True),
    (False, False),
    ("yes", None),
    (1, None),
    (None, None)
], ids=["yes", "no", "a word", "a number", "null"])
def test_only_a_plain_yes_or_no_reads_as_whether_the_cause_rests_on_an_unrun_reading(
        answered: object, read_as: bool | None) -> None:
    # Anything else is unanswered - never a guess the document then says.
    Scenario() \
        .given(
            a_submission := {CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD: answered}
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission).cause_rests_on_an_unrun_reading
        ) \
        .then(
            the_answer_was(read_as)
        )


@pytest.mark.unit
def test_an_answer_from_before_the_question_leaves_whether_it_rests_on_a_reading_unanswered(
) -> None:
    # Every answer recorded before the question existed carries no such field,
    # and its root cause already says whether the cause is unverified.
    Scenario() \
        .given(
            an_answer_from_before_the_question := an_answer_without(
                CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD)
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                an_answer_from_before_the_question).cause_rests_on_an_unrun_reading
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_root_cause_resting_on_no_unrun_reading_is_written_as_the_model_says_it() -> None:
    some_root_cause = "The average divides by this month's purchases, which can be none."

    Scenario() \
        .given(
            an_answer_resting_on_nothing_unrun := SubmittedPostmortem.model_validate(an_answer(
                root_cause=some_root_cause, cause_rests_on_an_unrun_reading=False))
        ) \
        .when(
            lambda: an_answer_resting_on_nothing_unrun.root_cause_as_written()
        ) \
        .then(
            the_answer_was(some_root_cause)
        )


@pytest.mark.unit
def test_a_root_cause_resting_on_an_unrun_reading_is_written_naming_each_reading_cited() -> None:
    # Each reading once, in the order the chain first cites it, so a reader
    # can open them; a line cited beside one is no reading.
    some_root_cause = "The average divides by this month's purchases, which can be none."
    a_line = "T1"
    a_reading = "F1"
    another_reading = "F2"

    Scenario() \
        .given(
            an_answer_resting_on_readings := SubmittedPostmortem.model_validate(an_answer(
                root_cause=some_root_cause, cause_rests_on_an_unrun_reading=True,
                causal_chain=[{STEP_FIELD: "dont care", CITES_FIELD: [a_line, a_reading]},
                              {STEP_FIELD: "dont care",
                               CITES_FIELD: [another_reading, a_reading]}]))
        ) \
        .when(
            lambda: an_answer_resting_on_readings.root_cause_as_written()
        ) \
        .then(
            the_answer_was(f"{some_root_cause} It rests on {a_reading}, {another_reading}, a "
                           f"reading of the source nothing ran, so it is unverified.")
        )


@pytest.mark.unit
def test_a_root_cause_resting_on_an_unrun_reading_the_chain_never_cites_names_none() -> None:
    # Still unverified: the answer says the cause rests on one, whichever
    # step would have cited it.
    some_root_cause = "The average divides by this month's purchases, which can be none."
    a_line = "T1"

    Scenario() \
        .given(
            an_answer_citing_no_reading := SubmittedPostmortem.model_validate(an_answer(
                root_cause=some_root_cause, cause_rests_on_an_unrun_reading=True,
                causal_chain=[{STEP_FIELD: "dont care", CITES_FIELD: [a_line]}]))
        ) \
        .when(
            lambda: an_answer_citing_no_reading.root_cause_as_written()
        ) \
        .then(
            the_answer_was(f"{some_root_cause} It rests on a reading of the source nothing "
                           f"ran, so it is unverified.")
        )


def _answered(field: str, expected: str) -> Assertion[SubmittedPostmortem]:
    def assertion(submitted: SubmittedPostmortem) -> bool:
        if getattr(submitted, field) != expected:
            raise AssertionError(
                f"Expected [{field}] to be [{expected}], got "
                f"[{getattr(submitted, field)}].")

        return True

    return assertion


def _left_unanswered(field: str) -> Assertion[SubmittedPostmortem]:
    """That a field carries nothing, rather than carrying something empty.

    The distinction the document rests on: absent is a question nobody
    answered, and an empty string on a page is an answer somebody left blank.
    """
    def assertion(submitted: SubmittedPostmortem) -> bool:
        if getattr(submitted, field) is not None:
            raise AssertionError(
                f"Expected [{field}] to have gone unanswered, got "
                f"[{getattr(submitted, field)}].")

        return True

    return assertion


def _disclosed(expected: list[str]) -> Assertion[SubmittedPostmortem]:
    def assertion(submitted: SubmittedPostmortem) -> bool:
        if submitted.assumptions != expected:
            raise AssertionError(
                f"Expected the assumptions to be {expected}, got "
                f"{submitted.assumptions}.")

        return True

    return assertion


def _says_of_the_leads(expected: dict[str, str]) -> Assertion[SubmittedPostmortem]:
    def assertion(submitted: SubmittedPostmortem) -> bool:
        if submitted.lead_effects != expected:
            raise AssertionError(
                f"Expected what each lead changed to be read as {expected}, got "
                f"{submitted.lead_effects}.")

        return True

    return assertion


def _read_in_the_order_sentences_reads(
        answer: SubmittedPostmortem) -> Assertion[list[tuple[str, str]]]:
    """The same sentences `sentences` yields, in its order."""
    def assertion(placed: list[tuple[str, str]]) -> bool:
        read = [prose for _, prose in placed]

        if read != list(answer.sentences()):
            raise AssertionError(
                f"Expected the sentences {list(answer.sentences())}, each with its place, "
                f"got {read}.")

        return True

    return assertion


def _each_in_a_place_of_its_own() -> Assertion[list[tuple[str, str]]]:
    def assertion(placed: list[tuple[str, str]]) -> bool:
        places = [place for place, _ in placed]

        if len(set(places)) != len(places):
            raise AssertionError(f"Expected every sentence in a place of its own, got {places}.")

        return True

    return assertion


def _what_went_well_reads(expected: list[str]) -> Assertion[SubmittedPostmortem]:
    def assertion(answer: SubmittedPostmortem) -> bool:
        read = answer.lessons.went_well if answer.lessons is not None else None

        if read != expected:
            raise AssertionError(f"Expected what went well to read {expected}, it reads {read}.")

        return True

    return assertion


def _timed_by(expected: list[str | None] | None) -> Assertion[SubmittedPostmortem]:
    def assertion(answer: SubmittedPostmortem) -> bool:
        if answer.went_well_timed_by != expected:
            raise AssertionError(f"Expected what went well to be timed by {expected}, it is "
                                 f"timed by {answer.went_well_timed_by}.")

        return True

    return assertion
