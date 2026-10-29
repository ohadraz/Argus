"""What is wrong with an answer, asked of the answer itself.

The conversation beside this one asks the same questions through two model
turns, which is the right way to test the retry and the wrong way to test the
rule: a fault there is visible only as a second ask, so a rule that fired for
the wrong reason and a rule that fired for the right one read identically.
Here the answer goes in and the faults come out.

The faults are not alike. A required field the model left out is a fact about
the answer - and so is a lead it said nothing about, a step of the cause that
cites nothing, and a contributing factor nothing answers. A number written in
digits is a fact about the answer too, and deliberately so: the document's
figures are measured, and a figure the prose states is written in by code from
the name the model gives it (`figures`). Prose writing one itself is either
repeating it - rounded, or worked out again - or inventing it, and the two
cannot be told apart from the sentence. Said in words it is the same figure -
spelled out in a run of them, or in one that measures something ("twenty
minutes", "tripled", "a third"). Said with no number in it at all ("most
requests", "several minutes"), a magnitude carries what the prose needs and
claims no precision nobody measured.

That makes the verdict on a figure depend on the answer alone, never on the run
it is read in. A rule comparing the prose's numbers with this run's
measurements refuses a recorded answer whenever the run measures differently -
which every run does. A name is held to the figures the incident gave, as a
citation is held to the evidence: both are names, and every run gives the same
ones. The one verdict that is the run's is a working's: a difference that
comes out below nothing, or a division by nothing, is read from the figures
this run gave - which a replay gives exactly as its recording was given them.

Every case here asserts what was named, not only how many faults came back.
The wording is the product: a model told "invalid answer" rewrites the part it
liked least, which is rarely the part that was wrong.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, Unpack

import pytest
from agent_postmortem.checking import Given, faults_in, faults_in_the_turn
from agent_postmortem.estimate import ErrorRates
from agent_postmortem.figures import Figure, figures_of
from agent_postmortem.prompting import (
    ACTION_ITEMS_FIELD,
    ANSWERS_FIELD,
    CAUSAL_CHAIN_FIELD,
    CAUSE_IN_PLAIN_WORDS_FIELD,
    CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD,
    CONTRIBUTING_FACTORS_FIELD,
    HAD_IT_BEEN_OTHERWISE_FIELD,
    LESSONS_FIELD,
    LOGS_SHOW_SERVING_AS_BEFORE_FIELD,
    ROOT_CAUSE_FIELD,
    STILL_AT_RISK_FIELD,
    SUBMIT_TOOL_NAME,
    SYMPTOM_FIELD,
    SYMPTOM_WORDS_AT_MOST,
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedRuledOut,
    SubmittedStep,
)
from argus_core.models import ActionItemType, CodeUse, Lessons, ToolCall, Turn
from argus_testkit import Assertion, Scenario, all_of

from agent_postmortem_test.framework.builders import (
    a_lead,
    a_measured_incident,
    an_evidence_bundle,
)

SOME_CAUSE_WITHOUT_A_NUMBER = "checkout failed for several minutes, for most requests"

DONT_CARE_PROSE = "dont care"

# What the model was handed: two labelled pieces of evidence and one action
# item already on the record.
SOME_GIVEN = Given(labels=frozenset({"E1", "E2"}), items_on_record=1)

# What a model shown Code-Fix's reading and one file as it ran was given.
SOME_GIVEN_WITH_A_FILE_AS_IT_RAN = SOME_GIVEN.model_copy(update={
    "labels": SOME_GIVEN.labels | {"F1", "S1"},
    "as_it_ran": {"S1": "deploy/scrape.yaml at 53f02e9"}})

# What a model whose logs reach into a stretch the metrics did not watch was
# given: it is asked whether they show the service serving as before.
SOME_GIVEN_ASKING_HOW_IT_SERVED = SOME_GIVEN.model_copy(
    update={"serving_as_before_asked": True})

# What a model shown Code-Fix's reading and a deployment's diff was given.
SOME_GIVEN_WITH_A_READING = SOME_GIVEN.model_copy(update={
    "labels": SOME_GIVEN.labels | {"F1", "D1"}})

# The figures an incident that recovered gives, which a working is worked out
# from: it began at noon and recovered ten minutes later.
SOME_FIGURES = figures_of(an_evidence_bundle(), a_measured_incident())

# A figure a log group states whose written form is a range, beside an instant.
SOME_RANGE_FIGURES = {**SOME_FIGURES,
                      "Gbac1.1": Figure(given="21:41–22:01", written="21:41–22:01")}

# The paging rule's series before the incident, written in with its unit.
SOME_LEVEL_WITH_ITS_UNIT = {"series_before": Figure(given="215.13 ms", written="215 ms")}

DONT_CARE_FIGURE = Figure(given=DONT_CARE_PROSE, written=DONT_CARE_PROSE)


@pytest.mark.unit
def test_a_required_field_the_model_left_out_is_named() -> None:
    # Named rather than counted. The fault is handed back to the model as the
    # whole of its second chance, and a model told only that its answer was
    # wrong has nothing to correct.
    Scenario() \
        .given(
            an_answer_with_no_root_cause := _an_answer(root_cause=None)
        ) \
        .when(
            lambda: faults_in(an_answer_with_no_root_cause, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(ROOT_CAUSE_FIELD),
                _found(1)
            )
        )


@pytest.mark.unit
def test_every_required_field_missing_is_named_and_not_just_the_first() -> None:
    # A check that stopped at the first would spend the one retry on half the
    # problem, and the second answer would come back missing the other fields
    # with no chances left.
    Scenario() \
        .given(
            an_answer_carrying_nothing := SubmittedPostmortem()
        ) \
        .when(
            lambda: faults_in(an_answer_carrying_nothing, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(ROOT_CAUSE_FIELD),
                _named(CAUSE_IN_PLAIN_WORDS_FIELD),
                _named(STILL_AT_RISK_FIELD),
                _named(CAUSAL_CHAIN_FIELD),
                _named(CONTRIBUTING_FACTORS_FIELD),
                _named(ACTION_ITEMS_FIELD),
                _named(LESSONS_FIELD),
                _named(SYMPTOM_FIELD),
                _found(8)
            )
        )


@pytest.mark.unit
def test_an_answer_carrying_what_was_required_has_nothing_wrong_with_it() -> None:
    # The accepting case, which is the one that decides whether the document
    # says it is complete.
    Scenario() \
        .given(
            a_complete_answer := _an_answer()
        ) \
        .when(
            lambda: faults_in(a_complete_answer, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_field_the_tool_never_required_is_not_missed() -> None:
    # The model is asked for its assumptions and allowed to have none. A check
    # reading every field rather than the required ones would make an honest
    # empty answer into a fault, and spend the retry asking for it again.
    Scenario() \
        .given(
            an_answer_assuming_nothing := _an_answer(assumptions=[])
        ) \
        .when(
            lambda: faults_in(an_answer_assuming_nothing, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_how_the_logs_show_the_service_left_out_where_it_was_asked_is_named() -> None:
    # Asked only where a log line reaches into the stretch the metrics did not
    # watch, and required there: the document's sentence on that stretch is
    # written from it, and nothing else in the answer may say it.
    Scenario() \
        .given(
            an_answer_not_saying := _an_answer()
        ) \
        .when(
            lambda: faults_in(an_answer_not_saying, given=SOME_GIVEN_ASKING_HOW_IT_SERVED)
        ) \
        .then(
            all_of(
                _named(LOGS_SHOW_SERVING_AS_BEFORE_FIELD),
                _found(1)
            )
        )


@pytest.mark.unit
def test_how_the_logs_show_the_service_said_where_it_was_asked_is_accepted() -> None:
    Scenario() \
        .given(
            an_answer_saying := _an_answer(logs_show_serving_as_before=False)
        ) \
        .when(
            lambda: faults_in(an_answer_saying, given=SOME_GIVEN_ASKING_HOW_IT_SERVED)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_cause_said_to_rest_on_more_than_a_reading_nothing_read_bears_out_is_named() -> None:
    # A step resting on a reading, beside nothing that shows the code - only the
    # error it caused. Said to rest on more, the box would be ticked beside a
    # mechanism nothing that was read shows.
    Scenario() \
        .given(
            an_answer_saying_more := _an_answer(
                causal_chain=[SubmittedStep(step=DONT_CARE_PROSE, cites=["F1", "E1"])],
                cause_rests_on_an_unrun_reading=False)
        ) \
        .when(
            lambda: faults_in(an_answer_saying_more, given=SOME_GIVEN_WITH_A_READING)
        ) \
        .then(all_of(
            _named(CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD),
            _found(1)
        ))


@pytest.mark.unit
def test_a_cause_resting_on_a_reading_and_what_was_read_may_rest_on_more() -> None:
    # A diff or a file as it ran shows the code the reading describes - the
    # model's to weigh, and not a contradiction.
    Scenario() \
        .given(
            an_answer_saying_more := _an_answer(
                causal_chain=[SubmittedStep(step=DONT_CARE_PROSE, cites=["F1", "D1"])],
                cause_rests_on_an_unrun_reading=False)
        ) \
        .when(
            lambda: faults_in(an_answer_saying_more, given=SOME_GIVEN_WITH_A_READING)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_cause_said_to_rest_on_a_reading_the_chain_never_cites_is_named() -> None:
    # The document's sentence names the readings the chain cites, so with none
    # it would name nothing - and the box would be left for a reading nobody
    # can open.
    Scenario() \
        .given(
            an_answer_naming_no_reading := _an_answer(cause_rests_on_an_unrun_reading=True)
        ) \
        .when(
            lambda: faults_in(an_answer_naming_no_reading, given=SOME_GIVEN_WITH_A_READING)
        ) \
        .then(all_of(
            _named(CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD),
            _found(1)
        ))


@pytest.mark.unit
def test_an_answer_from_before_the_question_is_not_asked_it() -> None:
    # Recorded before the question existed, so asked for it again it would
    # need a turn its recording does not hold - and its own root cause already
    # says whether the cause is unverified.
    Scenario() \
        .given(
            an_answer_from_before_the_question := _an_answer(
                causal_chain=[SubmittedStep(step=DONT_CARE_PROSE, cites=["F1"])])
        ) \
        .when(
            lambda: faults_in(an_answer_from_before_the_question,
                              given=SOME_GIVEN_WITH_A_READING)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_number_in_digits_is_named() -> None:
    # "The alert took 7 minutes" in a lesson is a precise-looking figure the
    # reader has no way to tell from a measured one.
    Scenario() \
        .given(
            an_answer_stating_a_duration := _an_answer(lessons=Lessons(
                went_wrong=["the alert took 7 minutes to fire"]))
        ) \
        .when(
            lambda: faults_in(an_answer_stating_a_duration, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[7]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_figure_argus_measured_is_still_not_said_in_digits() -> None:
    # The document states its measured figures itself. Prose repeating one
    # adds nothing the reader lacks, and is refused like an invented one
    # because the two cannot be told apart without asking which run measured
    # it - which is what made the old rule refuse every recorded answer.
    Scenario() \
        .given(
            an_answer_restating_the_peak := _an_answer(
                cause_in_plain_words="errors peaked at 33.8% of requests")
        ) \
        .when(
            lambda: faults_in(an_answer_restating_the_peak, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[33.8%]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_money_in_digits_is_named() -> None:
    # The figure nothing downstream can check: a fluent sentence naming an
    # amount in a document whose own amount is stated beside it.
    Scenario() \
        .given(
            an_answer_costing_the_outage := _an_answer(
                cause_in_plain_words="the outage cost $1,200,000")
        ) \
        .when(
            lambda: faults_in(an_answer_costing_the_outage, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[$1,200,000]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_time_in_digits_is_named() -> None:
    # A time of day is the number most likely to be repeated wrongly: it is
    # the one a replayed answer carries from the run it was recorded in.
    Scenario() \
        .given(
            an_answer_naming_a_time := _an_answer(
                root_cause="the flag was switched on at 21:45")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_a_time, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[21:45]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("written", [
    "21:35–21:39",
    "21:35—21:39",
    "21:35Z",
    "23h16",
    "21:35Z–21:39Z",
    "2026-10-12T21:35:00Z–2026-10-12T21:39:00Z",
    "2026-10-12T21:35:00Z/2026-10-12T21:40:00Z",
    "5m"
])
def test_a_time_written_the_way_a_log_or_a_clock_writes_it_is_named(written: str) -> None:
    # The forms a model copies from what it was shown: a span of log minutes
    # joined by a dash, a minute in UTC, a clock's own spelling. Each is the
    # recorded run's time carried into a write-up about another run.
    Scenario() \
        .given(
            an_answer_naming_a_time := _an_answer(
                root_cause=f"the errors ran {written} before the flag went back")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_a_time, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(f"[{written}]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("written", [
    "5/s",
    "120/min"
])
def test_a_rate_in_digits_is_named(written: str) -> None:
    # A number and what it is counted per are one figure. Split at the slash,
    # the unit alone is no figure, and the rate went unnamed.
    Scenario() \
        .given(
            an_answer_naming_a_rate := _an_answer(
                root_cause=f"the errors ran at {written} before the flag went back")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_a_rate, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(f"[{written}]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_every_number_in_digits_is_named_and_not_just_the_first() -> None:
    # Corrected once or not at all. Naming one of two buys a second answer
    # that fixes half a sentence.
    Scenario() \
        .given(
            an_answer_naming_two := _an_answer(
                cause_in_plain_words="from 21:45 for 7 minutes")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_two, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[21:45]"),
                _named("[7]"),
                _found(2)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("spelled_out", [
    "one thousand two hundred ninety-seven and thirty-one hundredths",
    "one thousand two hundred",
    "one hundred and five",
    "twenty-four"
])
def test_a_figure_spelled_out_in_words_is_named(spelled_out: str) -> None:
    # Refused its digits, a model wrote "short by one thousand two hundred
    # ninety-seven and thirty-one hundredths": the same figure restated, and
    # one no reader can read. A figure the incident gives is named instead,
    # and code writes it in.
    Scenario() \
        .given(
            an_answer_spelling_a_figure_out := _an_answer(
                cause_in_plain_words=f"the widest total was short by {spelled_out}")
        ) \
        .when(
            lambda: faults_in(an_answer_spelling_a_figure_out, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(f"[{spelled_out}]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("said", [
    "twenty minutes",
    "seven days",
    "one minute",
    "half an hour",
    "ten percent",
    "three times",
    "tripled",
    "halved",
    "twice",
    "a third",
    "two thirds",
    "a minute",
    "an hour",
    "a day",
    "a minute and a half"
])
def test_a_figure_said_in_one_word_is_named(said: str) -> None:
    # "About twenty minutes" for an incident six minutes long was accepted
    # while "about 20 minutes" was refused: the rule judged the spelling, not
    # the claim. One word measuring something is a figure as much as a run of
    # them, and a figure the incident gave, or a working of two, says it truly.
    # "A" is one of those words before a unit: "about a minute" was written for
    # ninety-one seconds.
    Scenario() \
        .given(
            an_answer_saying_a_figure_in_a_word := _an_answer(
                cause_in_plain_words=f"after the deploy it was {said}")
        ) \
        .when(
            lambda: faults_in(an_answer_saying_a_figure_in_a_word, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(f"[{said}]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_figure_spelled_out_with_what_it_measures_is_named_once() -> None:
    # One figure, one fault: refused as spelled out, it is not refused again
    # for the unit after it.
    Scenario() \
        .given(
            an_answer_spelling_out_a_span := _an_answer(
                cause_in_plain_words="it ran for twenty-four hours")
        ) \
        .when(
            lambda: faults_in(an_answer_spelling_out_a_span, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[twenty-four]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("said", [
    "about a hundred shoppers",
    "several minutes",
    "most requests",
    "a few days",
    "one-minute buckets",
    "the one that failed",
    "a second candidate",
    "no purchases in a month"
])
def test_a_size_with_no_figure_in_it_is_accepted(said: str) -> None:
    # A count of things, a size said without a number, and a number that
    # describes rather than measures ("one-minute buckets") claim no precision
    # anybody measured - and the rule has to leave the model something to say.
    Scenario() \
        .given(
            an_answer_sizing_without_a_figure := _an_answer(
                cause_in_plain_words=f"after the deploy it was {said}")
        ) \
        .when(
            lambda: faults_in(an_answer_sizing_without_a_figure, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_figure_named_as_the_incident_gives_it_is_accepted() -> None:
    # The one way the prose states a figure: by its name, written in by code.
    Scenario() \
        .given(
            an_answer_naming_its_figures := _an_answer(
                cause_in_plain_words="short by {A3} for {duration}")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_its_figures,
                              given=_given_figures("A3", "duration"))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_figure_named_that_the_incident_never_gave_is_named() -> None:
    # A name for nothing would be written in as a blank where a figure goes -
    # a number nobody measured, said as nothing at all.
    Scenario() \
        .given(
            an_answer_naming_a_ghost_figure := _an_answer(cause_in_plain_words="short by {A9}")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_a_ghost_figure,
                              given=_given_figures("A3"))
        ) \
        .then(
            all_of(
                _named("[{A9}]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("before", ["between", "from", "Between"])
def test_a_range_figure_after_a_word_that_opens_a_range_is_named(before: str) -> None:
    # A range is written in whole, so "between {G}" reads "between 21:41–22:01".
    # The figure says its own range.
    Scenario() \
        .given(
            an_answer_opening_a_range_twice := _an_answer(
                cause_in_plain_words=f"errors held {before} {{Gbac1.1}}")
        ) \
        .when(
            lambda: faults_in(an_answer_opening_a_range_twice,
                              given=_given_figures("Gbac1.1", figures=SOME_RANGE_FIGURES))
        ) \
        .then(
            all_of(
                _named("[{Gbac1.1}]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("before", ["at", "by", "since", "until", "before", "after", "At"])
def test_a_range_figure_after_a_word_that_places_a_moment_is_named(before: str) -> None:
    # "This error first appears at {G}" read "first appears at 14:46–14:53": a
    # span where the sentence wanted its first minute.
    Scenario() \
        .given(
            an_answer_placing_a_range := _an_answer(
                cause_in_plain_words=f"errors held {before} {{Gbac1.1}}")
        ) \
        .when(
            lambda: faults_in(an_answer_placing_a_range,
                              given=_given_figures("Gbac1.1", figures=SOME_RANGE_FIGURES))
        ) \
        .then(
            all_of(
                _named("[{Gbac1.1}]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("prose", "name"), [
    ("errors held over {Gbac1.1}", "Gbac1.1"),
    ("errors held from {began}", "began")
], ids=["another-word-before-a-range", "a-word-opening-a-range-before-an-instant"])
def test_a_range_said_with_a_word_that_does_not_open_one_or_an_instant_after_one_is_accepted(
        prose: str, name: str) -> None:
    Scenario() \
        .given(
            an_answer := _an_answer(cause_in_plain_words=prose)
        ) \
        .when(
            lambda: faults_in(an_answer, given=_given_figures(name, figures=SOME_RANGE_FIGURES))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_working_the_figures_answer_is_accepted() -> None:
    # The way the prose states a figure the incident never measured as one: by
    # naming what to work out, which code works out from what was measured.
    Scenario() \
        .given(
            an_answer_working_out_a_span := _an_answer(
                cause_in_plain_words="it was broken for {back_to_normal - began}")
        ) \
        .when(
            lambda: faults_in(an_answer_working_out_a_span,
                              given=_given_figures("back_to_normal", "began"))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_working_between_two_instants_the_evidence_states_is_accepted() -> None:
    # What a real model asked for, and was refused: the span between two
    # lines of the narration. An instant is one wherever it was shown.
    some_narration = {
        "T18.1": Figure(given="2026-09-02T12:00:00Z", written="dont care"),
        "T21.1": Figure(given="2026-09-02T12:07:30Z", written="dont care")
    }

    Scenario() \
        .given(
            an_answer_working_from_the_narration := _an_answer(
                cause_in_plain_words="mitigation began {T21.1 - T18.1} in")
        ) \
        .when(
            lambda: faults_in(an_answer_working_from_the_narration,
                              given=_given_figures("T18.1", "T21.1", figures=some_narration))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_working_that_makes_no_sense_is_named() -> None:
    # Two instants have a span between them and no sum. Left in, it would reach
    # the page in braces - so it is sent back to the model instead.
    Scenario() \
        .given(
            an_answer_adding_two_instants := _an_answer(
                cause_in_plain_words="it ended at {began + argus_stopped}")
        ) \
        .when(
            lambda: faults_in(an_answer_adding_two_instants,
                              given=_given_figures("began", "argus_stopped"))
        ) \
        .then(
            all_of(
                _named("[{began + argus_stopped}]"),
                _named("works out to nothing"),
                _named("an instant minus an instant"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_working_of_figures_nobody_knows_the_kind_of_is_named() -> None:
    # What the alert's sender's numbers measure is the sender's to know, so
    # the page does no arithmetic on them.
    some_findings = {
        "A1": Figure(given="240", written="240"),
        "A2": Figure(given="120", written="120")
    }

    Scenario() \
        .given(
            an_answer_working_the_alerts_figures := _an_answer(
                cause_in_plain_words="the totals fell by {A1 - A2}")
        ) \
        .when(
            lambda: faults_in(an_answer_working_the_alerts_figures,
                              given=_given_figures("A1", "A2", figures=some_findings))
        ) \
        .then(
            all_of(
                _named("[{A1 - A2}]"),
                _named("cannot be worked with"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_working_from_a_figure_the_incident_never_gave_is_named() -> None:
    # An incident that never recovered has no recovery to work from, and the
    # working would reach the page in braces.
    Scenario() \
        .given(
            an_answer_working_from_a_ghost := _an_answer(
                cause_in_plain_words="it was broken for {back_to_normal - began}")
        ) \
        .when(
            lambda: faults_in(an_answer_working_from_a_ghost,
                              given=_given_figures("began"))
        ) \
        .then(
            all_of(
                _named("[{back_to_normal}]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_working_that_comes_out_below_nothing_is_named() -> None:
    # Broken for less than no time is the two figures the wrong way round. The
    # prose says which way a thing went, and the working says by how much.
    Scenario() \
        .given(
            an_answer_working_backwards := _an_answer(
                cause_in_plain_words="it was broken for {began - back_to_normal}")
        ) \
        .when(
            lambda: faults_in(an_answer_working_backwards,
                              given=_given_figures("back_to_normal", "began"))
        ) \
        .then(
            all_of(
                _named("[{began - back_to_normal}]"),
                _named("comes out below nothing"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_working_from_a_level_that_is_no_number_is_named() -> None:
    # Prometheus answers +Inf for a ratio over nothing but its numerator, and
    # the series averaged over such a minute is no number to work from.
    some_levels = {
        "series_while_broken": Figure(given="+Inf ms", written="+Inf ms"),
        "series_before": Figure(given="215.13 ms", written="215 ms")
    }

    Scenario() \
        .given(
            an_answer_working_from_no_number := _an_answer(
                cause_in_plain_words="it rose by {series_while_broken - series_before}")
        ) \
        .when(
            lambda: faults_in(an_answer_working_from_no_number,
                              given=_given_figures("series_while_broken", "series_before",
                                                   figures=some_levels))
        ) \
        .then(
            all_of(
                _named("[{series_while_broken - series_before}]"),
                _named("{series_while_broken} is no number"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_unit_misreading_a_figure_s_scale_is_named() -> None:
    # Written in, "{series_before} seconds" on a figure of 215 ms reads "215 ms
    # seconds", and only the model knows which it meant.
    Scenario() \
        .given(
            an_answer_misreading_the_scale := _an_answer(
                cause_in_plain_words="the slowest took {series_before} seconds")
        ) \
        .when(
            lambda: faults_in(an_answer_misreading_the_scale,
                              given=_given_figures("series_before",
                                                   figures=SOME_LEVEL_WITH_ITS_UNIT))
        ) \
        .then(
            all_of(
                _named("[{series_before} seconds]"),
                _named("ms"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_figure_s_own_unit_said_again_is_accepted() -> None:
    # A fair reading of a figure shown with its unit outside its name, and the
    # document writes the unit once - sending it back would cost a write-up.
    Scenario() \
        .given(
            an_answer_saying_the_unit_again := _an_answer(
                cause_in_plain_words="the slowest took {series_before} ms")
        ) \
        .when(
            lambda: faults_in(an_answer_saying_the_unit_again,
                              given=_given_figures("series_before",
                                                   figures=SOME_LEVEL_WITH_ITS_UNIT))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_working_that_divides_by_nothing_is_named() -> None:
    # A shop that failed nothing before has no "how many times" to compare
    # the incident with.
    some_figures_failing_nothing_before = figures_of(
        an_evidence_bundle(),
        a_measured_incident(
            error_rates=ErrorRates(baseline=0.0, while_broken=0.338, at_its_worst=0.5,
                                   usual_ceiling=0.02, usual_worst=0.04)))

    Scenario() \
        .given(
            an_answer_dividing_by_nothing := _an_answer(
                cause_in_plain_words="errors were {errors_at_worst / errors_before} as common")
        ) \
        .when(
            lambda: faults_in(an_answer_dividing_by_nothing,
                              given=_given_figures(
                                  "errors_at_worst", "errors_before",
                                  figures=some_figures_failing_nothing_before))
        ) \
        .then(
            all_of(
                _named("[{errors_at_worst / errors_before}]"),
                _named("nothing divides by it"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_label_or_an_item_named_in_the_prose_is_not_a_number() -> None:
    # "E2", "L1" and "AI-1" are names, and a check reading their digits as
    # figures would refuse the citations it asked for.
    Scenario() \
        .given(
            an_answer_naming_labels_and_an_item := _an_answer(
                root_cause="as E2 shows and L1 said, which AI-1 addresses")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_labels_and_an_item, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_revision_the_incident_read_is_a_name_not_a_number() -> None:
    # A revision is the name a deploy goes by, and the one a reader searches
    # for. Refused as a figure, it was swapped for a label nobody outside the
    # prompt can read: the root cause blamed "the later of the two recent
    # deploys (P2)" rather than the revision that shipped. Short or whole, a
    # revision the incident read is written as given.
    some_revision_read = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"

    Scenario() \
        .given(
            an_answer_naming_it_short := _an_answer(
                root_cause=f"the deploy of revision {some_revision_read[:8]} stopped "
                           f"keeping the monthly total")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_it_short,
                              given=SOME_GIVEN.model_copy(
                                  update={"revisions": frozenset({some_revision_read})}))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_revision_the_incident_never_read_is_named() -> None:
    # Checked rather than trusted. One a character off is corrected before
    # this is asked (`revisions`); one that starts like none the incident read
    # is a name nothing can be looked up by, and the model is told so.
    some_revision_read = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
    some_revision_nobody_read = "9999abcd"

    Scenario() \
        .given(
            an_answer_naming_a_stranger := _an_answer(
                root_cause=f"the deploy of revision {some_revision_nobody_read} broke it")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_a_stranger,
                              given=SOME_GIVEN.model_copy(
                                  update={"revisions": frozenset({some_revision_read})}))
        ) \
        .then(
            all_of(
                _named(f"[{some_revision_nobody_read}]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_figure_as_long_as_a_revision_is_still_named() -> None:
    # Only hex with a letter in it reads as a name. A figure of the same length
    # is still a figure.
    Scenario() \
        .given(
            an_answer_with_a_long_figure := _an_answer(
                cause_in_plain_words="the shop took 12345678 cents")
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_long_figure, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[12345678]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_revision_the_incident_read_whose_start_is_all_digits_is_a_name() -> None:
    # One revision in about thirty starts with seven digits. Told apart by its
    # letters alone, its short form read as a number and was refused - the very
    # name the rule above stopped refusing. A start that only one revision the
    # incident read begins with is that revision, letters or none.
    some_revision_read = "3398001c4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b"

    Scenario() \
        .given(
            an_answer_naming_it_short := _an_answer(
                root_cause=f"the deploy of revision {some_revision_read[:7]} broke checkout")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_it_short,
                              given=SOME_GIVEN.model_copy(
                                  update={"revisions": frozenset({some_revision_read})}))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_digits_shorter_than_a_revision_s_short_form_are_a_figure_whatever_they_start() -> None:
    # A revision is named by seven characters at least. One digit starts one
    # revision in sixteen, and a rule taking any start for a name would let
    # every small number through.
    some_revision_read = "3398001c4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b"

    Scenario() \
        .given(
            an_answer_with_a_small_figure := _an_answer(
                cause_in_plain_words="checkout failed for 3 hours")
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_small_figure,
                              given=SOME_GIVEN.model_copy(
                                  update={"revisions": frozenset({some_revision_read})}))
        ) \
        .then(
            all_of(
                _named("[3]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_date_or_an_instant_in_digits_is_named() -> None:
    # A date is a figure the document states itself, and the one a replayed
    # answer carries from the run it was recorded in.
    Scenario() \
        .given(
            an_answer_dating_the_deploy := _an_answer(
                root_cause="the deploy on 2026-10-05 landed at 2026-10-05T11:57:00Z")
        ) \
        .when(
            lambda: faults_in(an_answer_dating_the_deploy, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[2026-10-05]"),
                _named("[2026-10-05T11:57:00Z]"),
                _found(2)
            )
        )


@pytest.mark.unit
def test_a_duration_with_its_unit_attached_is_named() -> None:
    # "7min" is "7 minutes" with the space taken out, and a figure either way.
    Scenario() \
        .given(
            an_answer_timing_the_alert := _an_answer(
                lessons=Lessons(went_wrong=["the alert took 7min to fire"]))
        ) \
        .when(
            lambda: faults_in(an_answer_timing_the_alert, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[7min]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_name_mixing_letters_and_digits_is_not_a_number() -> None:
    # A pod, a node, a card: names that carry digits and are no figure, and
    # refusing them refuses the evidence's own words. The hash inside a pod's
    # name is part of the name, not a revision to check.
    Scenario() \
        .given(
            an_answer_naming_a_pod := _an_answer(
                root_cause="the pod io-shop-7d9c4f8b6-x2k9p on gpu-v100-0 ran a Tesla-V100")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_a_pod, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_line_of_source_is_a_place_not_a_number() -> None:
    # "spend_summary.py line 47" says where the fault is, not how much of
    # anything. Refused, it can only be spelled out - which is refused too.
    Scenario() \
        .given(
            an_answer_citing_a_line := _an_answer(
                root_cause="a division in spend_summary.py at line 47, and lines 50-52 after it")
        ) \
        .when(
            lambda: faults_in(an_answer_citing_a_line, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_name_joined_by_a_slash_or_a_dash_is_still_a_name() -> None:
    # A word is a figure only where every part of it is one. A protocol and a
    # pair of action items carry a slash or a dash between figures' marks and
    # are names all the same.
    Scenario() \
        .given(
            an_answer_naming_things := _an_answer(
                root_cause="the client spoke HTTP/2, and AI-3/AI-4 answer it")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_things, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_cause_the_model_never_wrote_is_missing_rather_than_numbered() -> None:
    # An absent cause has no numbers in it, and the fault it earns is the one
    # about the field.
    Scenario() \
        .given(
            an_answer_with_no_cause := _an_answer(cause_in_plain_words=None)
        ) \
        .when(
            lambda: faults_in(an_answer_with_no_cause, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(CAUSE_IN_PLAIN_WORDS_FIELD),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_lead_the_answer_says_nothing_about_is_named() -> None:
    # Refused as a missing field is, because it is one: what a person told the
    # incident and whether it changed anything is a question the document owes
    # them, and an answer that skipped one lead would leave it unanswered on
    # the page. Named by its label, which is what the model calls it.
    some_leads = [a_lead("the kuki flag was flipped at noon", ts="1760000100.000200"),
                  a_lead("it is the database again", ts="1760000200.000300")]

    Scenario() \
        .given(
            an_answer_about_the_first_lead_alone := _an_answer(
                lead_effects={"L1": DONT_CARE_PROSE})
        ) \
        .when(
            lambda: faults_in(an_answer_about_the_first_lead_alone, some_leads,
                              given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[L2]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_an_answer_saying_what_every_lead_changed_has_nothing_wrong_with_it() -> None:
    some_leads = [a_lead("the kuki flag was flipped at noon", ts="1760000100.000200"),
                  a_lead("it is the database again", ts="1760000200.000300")]

    Scenario() \
        .given(
            an_answer_about_every_lead := _an_answer(
                lead_effects={"L1": DONT_CARE_PROSE, "L2": DONT_CARE_PROSE})
        ) \
        .when(
            lambda: faults_in(an_answer_about_every_lead, some_leads, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_step_of_the_cause_citing_nothing_is_named() -> None:
    # A step resting on nothing is an assertion, and a chain of them is a
    # story. Named by its place in the chain, which is how the model wrote it.
    Scenario() \
        .given(
            an_answer_with_an_uncited_step := _an_answer(causal_chain=[
                SubmittedStep(step="account pages failed", cites=["E1"]),
                SubmittedStep(step="the divisor was zero", cites=[])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_with_an_uncited_step, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("the divisor was zero"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_step_citing_a_label_never_given_is_named() -> None:
    # A citation of nothing that exists is worse than none: it looks checked.
    Scenario() \
        .given(
            an_answer_citing_a_ghost := _an_answer(causal_chain=[
                SubmittedStep(step="the divisor was zero", cites=["E1", "E40"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_citing_a_ghost, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[E40]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_step_citing_code_fix_s_reading_and_no_file_as_it_ran_is_named() -> None:
    # Six of six write-ups called the scrape config "Code-Fix's reading,
    # nothing ran" while the file as it ran sat beneath that reading. Which file
    # a step's claim is about cannot be told, so any S row will do - and the
    # message names them all.
    Scenario() \
        .given(
            an_answer_resting_on_the_reading := _an_answer(causal_chain=[
                SubmittedStep(step="the scrape still selects the old name", cites=["E1", "F1"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_resting_on_the_reading,
                              given=SOME_GIVEN_WITH_A_FILE_AS_IT_RAN)
        ) \
        .then(
            all_of(
                _named("[F1]"),
                _named("[S1] deploy/scrape.yaml at 53f02e9"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_step_citing_code_fix_s_reading_beside_a_file_as_it_ran_is_accepted() -> None:
    Scenario() \
        .given(
            an_answer_citing_what_ran := _an_answer(causal_chain=[
                SubmittedStep(step="the scrape still selects the old name",
                              cites=["E1", "F1", "S1"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_citing_what_ran, given=SOME_GIVEN_WITH_A_FILE_AS_IT_RAN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_step_citing_code_fix_s_reading_with_no_file_as_it_ran_given_is_accepted() -> None:
    # The reading is then all there is, and saying so is the honest answer.
    Scenario() \
        .given(
            an_answer_resting_on_the_reading := _an_answer(causal_chain=[
                SubmittedStep(step="the scrape still selects the old name", cites=["E1", "F1"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_resting_on_the_reading,
                              given=SOME_GIVEN.model_copy(update={
                                  "labels": SOME_GIVEN.labels | {"F1"}}))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_step_citing_a_candidate_cause_is_named() -> None:
    # A candidate is the Investigator's guess, written before anything was
    # tried. A step resting on one rests on a hypothesis rather than on what
    # was observed, so it is named even beside evidence that is real.
    Scenario() \
        .given(
            an_answer_citing_a_guess := _an_answer(causal_chain=[
                SubmittedStep(step="the divisor was zero", cites=["E1", "C1"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_citing_a_guess,
                              given=Given(labels=frozenset({"E1", "C1"}),
                                          hypotheses=frozenset({"C1"})))
        ) \
        .then(
            all_of(
                _named("[C1]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_what_a_step_ruled_out_citing_a_label_never_given_is_named() -> None:
    # Held to what a step is held to: a ruling citing nothing that exists only
    # looks checked.
    Scenario() \
        .given(
            an_answer_ruling_out_on_a_ghost := _an_answer(causal_chain=[
                SubmittedStep(step="the divisor was zero", cites=["E1"],
                              ruled_out=[SubmittedRuledOut(what="the earlier deploy",
                                                           cites=["E40"])])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_ruling_out_on_a_ghost, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[E40]"),
                _named("ruled out"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_what_a_step_ruled_out_citing_nothing_is_named() -> None:
    # Asked to cite what ruled it out, and held to it as a step is: a ruling
    # resting on nothing is an assertion.
    Scenario() \
        .given(
            an_answer_ruling_out_on_nothing := _an_answer(causal_chain=[
                SubmittedStep(step="the divisor was zero", cites=["E1"],
                              ruled_out=[SubmittedRuledOut(what="the earlier deploy",
                                                           cites=[])])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_ruling_out_on_nothing, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[the earlier deploy]"),
                _named("cite what ruled it out"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_what_a_step_ruled_out_citing_a_candidate_is_named_as_that_entry() -> None:
    # Told to "leave the step out", a model could drop a step of the chain
    # rather than the entry that cited the guess.
    Scenario() \
        .given(
            an_answer_ruling_out_on_a_guess := _an_answer(causal_chain=[
                SubmittedStep(step="the divisor was zero", cites=["E1"],
                              ruled_out=[SubmittedRuledOut(what="the earlier deploy",
                                                           cites=["C1"])])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_ruling_out_on_a_guess,
                              given=Given(labels=frozenset({"E1", "C1"}),
                                          hypotheses=frozenset({"C1"})))
        ) \
        .then(
            all_of(
                _named("[C1]"),
                _named("leave that entry out"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_contributing_factor_nothing_answers_is_named() -> None:
    # A factor with no action item is a condition the document noticed and
    # left standing - the thing an analysis without actions is.
    Scenario() \
        .given(
            an_answer_with_an_unanswered_factor := _an_answer(contributing_factors=[
                SubmittedFactor(label="CF-1", factor="the canary started large",
                                had_it_been_otherwise=DONT_CARE_PROSE, addressed_by=[])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_with_an_unanswered_factor, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("the canary started large"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_factor_not_saying_what_it_would_have_changed_is_named() -> None:
    # A factor that only says the root cause again cannot say what it would
    # have changed with the root cause still true - and one left unsaid is the
    # question skipped.
    Scenario() \
        .given(
            an_answer_with_an_unweighed_factor := _an_answer(contributing_factors=[
                SubmittedFactor(label="CF-1", factor="the canary started large",
                                addressed_by=["AI-1"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_with_an_unweighed_factor, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("the canary started large"),
                _named(HAD_IT_BEEN_OTHERWISE_FIELD),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
def test_a_factor_answering_what_it_would_have_changed_with_nothing_is_named(
        blank: str) -> None:
    # A strict tool guarantees the field arrives, as a string - not that it
    # says anything. Blank is the question skipped as surely as absent is.
    Scenario() \
        .given(
            an_answer_with_a_blank_otherwise := _an_answer(contributing_factors=[
                SubmittedFactor(label="CF-1", factor="the canary started large",
                                had_it_been_otherwise=blank, addressed_by=["AI-1"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_blank_otherwise, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("the canary started large"),
                _named(HAD_IT_BEEN_OTHERWISE_FIELD),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_factor_naming_an_item_that_does_not_exist_is_named() -> None:
    Scenario() \
        .given(
            an_answer_naming_a_ghost_item := _an_answer(contributing_factors=[
                SubmittedFactor(label="CF-1", factor="no test covered an empty month",
                                had_it_been_otherwise=DONT_CARE_PROSE,
                                addressed_by=["AI-9"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_naming_a_ghost_item, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[AI-9]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_factor_may_be_answered_by_an_item_on_the_record_and_by_one_the_answer_proposes(
) -> None:
    # The record's item by its number, in the factor; the answer's own by the
    # factor's label, in the item - each link written after what it names.
    Scenario() \
        .given(
            an_answer_naming_both := _an_answer(
                contributing_factors=[
                    SubmittedFactor(label="CF-1", factor="no test covered an empty month",
                                    had_it_been_otherwise=DONT_CARE_PROSE,
                                    addressed_by=["AI-1"])
                ],
                action_items=[SubmittedItem(item="add a test for an empty month",
                                            type=ActionItemType.PREVENT, answers=["CF-1"])])
        ) \
        .when(
            lambda: faults_in(an_answer_naming_both, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_factor_answered_only_by_an_item_the_answer_proposes_is_accepted() -> None:
    # None of the record's items answers it, so its own list is empty - an
    # answer, not a fault.
    Scenario() \
        .given(
            an_answer_answering_by_a_proposal := _an_answer(
                contributing_factors=[
                    SubmittedFactor(label="CF-1", factor="no test covered an empty month",
                                    had_it_been_otherwise=DONT_CARE_PROSE, addressed_by=[])
                ],
                action_items=[SubmittedItem(item="add a test for an empty month",
                                            type=ActionItemType.PREVENT, answers=["CF-1"])])
        ) \
        .when(
            lambda: faults_in(an_answer_answering_by_a_proposal, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_factor_naming_an_item_the_answer_proposes_is_named() -> None:
    # One item on the record, so AI-2 is the answer's own first proposal -
    # a number it had to work out, which is how a write-up came to cite each
    # of its items one off. The proposal names the factor instead.
    Scenario() \
        .given(
            an_answer_numbering_its_own_item := _an_answer(
                contributing_factors=[
                    SubmittedFactor(label="CF-1", factor="no test covered an empty month",
                                    had_it_been_otherwise=DONT_CARE_PROSE,
                                    addressed_by=["AI-2"])
                ],
                action_items=[SubmittedItem(item="add a test for an empty month",
                                            type=ActionItemType.PREVENT, answers=["CF-1"])])
        ) \
        .when(
            lambda: faults_in(an_answer_numbering_its_own_item, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[AI-2]"),
                _named(ANSWERS_FIELD),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("second_label", ["CF-3", None], ids=["skipped", "missing"])
def test_a_factor_labelled_out_of_order_is_named(second_label: str | None) -> None:
    # The labels run CF-1, CF-2 and so on, as the factors are given: a label
    # that is not where its place says is one an item could name wrongly.
    Scenario() \
        .given(
            an_answer_mislabelling_a_factor := _an_answer(contributing_factors=[
                SubmittedFactor(label="CF-1", factor="the canary started large",
                                had_it_been_otherwise=DONT_CARE_PROSE, addressed_by=["AI-1"]),
                SubmittedFactor(label=second_label, factor="no test covered an empty month",
                                had_it_been_otherwise=DONT_CARE_PROSE, addressed_by=["AI-1"])
            ])
        ) \
        .when(
            lambda: faults_in(an_answer_mislabelling_a_factor, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("no test covered an empty month"),
                _named("CF-2"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_an_item_answering_a_label_no_factor_has_is_named() -> None:
    Scenario() \
        .given(
            an_answer_answering_a_ghost := _an_answer(
                contributing_factors=[
                    SubmittedFactor(label="CF-1", factor="no test covered an empty month",
                                    had_it_been_otherwise=DONT_CARE_PROSE,
                                    addressed_by=["AI-1"])
                ],
                action_items=[SubmittedItem(item="add a test for an empty month",
                                            type=ActionItemType.PREVENT, answers=["CF-9"])])
        ) \
        .when(
            lambda: faults_in(an_answer_answering_a_ghost, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[CF-9]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_factor_s_label_written_in_the_prose_is_named() -> None:
    # The reader never sees a factor's label: written into a sentence, it is a
    # name that leads nowhere.
    Scenario() \
        .given(
            an_answer_citing_a_factor_in_prose := _an_answer(
                root_cause="The canary started large, as CF-2 says.")
        ) \
        .when(
            lambda: faults_in(an_answer_citing_a_factor_in_prose, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named("[CF-2]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_symptom_of_more_than_one_sentence_is_named() -> None:
    # The symptom is the document's title. Asked for in a few words, a write-up
    # gave two sentences, and the title ran to fifteen words.
    some_symptom_in_two_sentences = ("No shopper-facing failure was seen. "
                                     "The shop's metrics stopped being collected.")

    Scenario() \
        .given(
            an_answer_with_a_symptom_in_two := _an_answer(
                symptom=some_symptom_in_two_sentences)
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_symptom_in_two, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(some_symptom_in_two_sentences),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_symptom_over_the_words_it_was_told_is_named() -> None:
    # Asked for a few words, a title ran to twenty - the longest of every
    # write-up recorded. Counted as a reader counts words, on the spaces, so
    # a hyphenated name is one.
    some_symptom_one_word_too_long = " ".join(["shop-totals"] * (SYMPTOM_WORDS_AT_MOST + 1))

    Scenario() \
        .given(
            an_answer_with_a_long_symptom := _an_answer(symptom=some_symptom_one_word_too_long)
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_long_symptom, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(f"runs to {SYMPTOM_WORDS_AT_MOST + 1} words"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_symptom_of_the_words_it_was_told_is_not_sent_back() -> None:
    some_symptom_at_the_limit = " ".join(["shop-totals"] * SYMPTOM_WORDS_AT_MOST)

    Scenario() \
        .given(
            an_answer_with_a_symptom_at_the_limit := _an_answer(
                symptom=some_symptom_at_the_limit)
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_symptom_at_the_limit, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
@pytest.mark.parametrize("field", [CAUSE_IN_PLAIN_WORDS_FIELD, STILL_AT_RISK_FIELD])
def test_a_summary_sentence_of_more_than_one_is_named(field: str) -> None:
    # Each is one sentence of the summary code writes around it; two, and the
    # model is writing the summary again, beside the record's own account.
    some_two_sentences = "The rename reached one file. The other still names the old port."

    Scenario() \
        .given(
            an_answer_in_two_sentences := _an_answer().model_copy(
                update={field: some_two_sentences})
        ) \
        .when(
            lambda: faults_in(an_answer_in_two_sentences, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(field),
                _named(some_two_sentences),
                _found(1)
            )
        )


@pytest.mark.unit
def test_nothing_still_at_risk_is_an_answer() -> None:
    # Empty, not missing: an incident whose fault is gone leaves nothing at risk.
    Scenario() \
        .given(
            an_answer_with_nothing_at_risk := _an_answer(still_at_risk="")
        ) \
        .when(
            lambda: faults_in(an_answer_with_nothing_at_risk, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_symptom_of_one_sentence_is_accepted() -> None:
    # Ended with a full stop or not: a sentence's own stop is not a second one.
    Scenario() \
        .given(
            an_answer_with_a_symptom_in_one := _an_answer(
                symptom="Far more purchases than usual were held for review.")
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_symptom_in_one, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
@pytest.mark.parametrize("missing_check", [
    "Nothing checks that the two names agree.",
    "Nothing seen checks that the two names agree.",
    "The record shows no check that an old reader survives new entries."
], ids=["nothing-checks", "nothing-seen-checks", "no-check"])
def test_a_root_cause_saying_a_check_is_missing_is_named(missing_check: str) -> None:
    # A missing check is a contributing factor. Told so in the root cause's
    # own description, three write-ups said one there anyway, in the words of
    # the reading of the code they cited. Where the missing check is itself
    # the mechanism - a read path that does not check what it loaded - moving
    # it out would empty the root cause, so the fault says what to say instead.
    Scenario() \
        .given(
            an_answer_blaming_a_missing_check := _an_answer(root_cause=missing_check)
        ) \
        .when(
            lambda: faults_in(an_answer_blaming_a_missing_check, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(missing_check),
                _named(CONTRIBUTING_FACTORS_FIELD),
                _named("say what the code does rather than what it lacks"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_missing_check_is_named_by_its_sentence_and_the_rest_is_kept() -> None:
    # Handed the whole root cause back, a model moved the missing check out by
    # deleting the sentence it was in - and with it that the two files name
    # the port separately, which was the mechanism. Quoting the one sentence
    # says which words are to move, and that the rest of it stays.
    the_mechanism = "The scrape config still names the old port, so it finds no target."
    the_missing_check = ("The two files name the port separately and no check was seen "
                         "that they agree.")

    Scenario() \
        .given(
            an_answer_blaming_a_missing_check_in_its_second_sentence := _an_answer(
                root_cause=f"{the_mechanism} {the_missing_check}")
        ) \
        .when(
            lambda: faults_in(an_answer_blaming_a_missing_check_in_its_second_sentence,
                              given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(f"[{the_missing_check}]"),
                _named("keep the rest of the sentence"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_root_cause_naming_the_change_that_set_it_off_is_named() -> None:
    # The document states the trigger in a section of its own. A root cause
    # naming the deploy's revision says it again: what it owes is why that
    # change broke the service.
    the_trigger = "53f02e9a1b2c3d4e5f60718293a4b5c6d7e8f901"

    Scenario() \
        .given(
            an_answer_naming_the_trigger := _an_answer(
                root_cause=f"Revision {the_trigger[:7]} renamed the port, so nothing scraped it.")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_the_trigger,
                              given=SOME_GIVEN.model_copy(update={
                                  "revisions": frozenset({the_trigger}),
                                  "trigger_revision": the_trigger}))
        ) \
        .then(
            all_of(
                _named(the_trigger[:7]),
                _named("say why that change broke the service"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_root_cause_naming_another_revision_is_accepted() -> None:
    # An earlier revision the mechanism turns on is not the trigger said again.
    the_trigger = "53f02e9a1b2c3d4e5f60718293a4b5c6d7e8f901"
    some_other_revision = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"

    Scenario() \
        .given(
            an_answer_naming_another_revision := _an_answer(
                root_cause=f"The reader {some_other_revision[:7]} left in place cannot parse it.")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_another_revision,
                              given=SOME_GIVEN.model_copy(update={
                                  "revisions": frozenset({the_trigger, some_other_revision}),
                                  "trigger_revision": the_trigger}))
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
@pytest.mark.parametrize("role", [
    "as the month's figure",
    "rather than adding the purchases up",
    "instead of adding the purchases up",
    "and trust it",
    "and rely on it",
    "and treat it as the month's",
    "as the month's figure as the record shows"
], ids=["as-the", "rather-than", "instead-of", "trust", "rely-on", "treat", "as-then-shows"])
def test_a_sentence_saying_one_role_of_lines_whose_rows_differ_is_named(role: str) -> None:
    # Write-ups said the statement, the summary and the reconciliation all read
    # the stored month "as the month's figure", though the reconciliation's own
    # row sets it against the purchases added up again.
    lumped = f"The monthly statement, the spend summary and the reconciliation read it {role}."

    Scenario() \
        .given(
            an_answer_lumping_them := _an_answer(root_cause=lumped)
        ) \
        .when(
            lambda: faults_in(an_answer_lumping_them, given=_given_lines_of_two_kinds())
        ) \
        .then(
            all_of(
                _named(ROOT_CAUSE_FIELD),
                _named(f"[{lumped}]"),
                _named("[U3]"),
                _named("say of each only what its own row says"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("field", [CAUSE_IN_PLAIN_WORDS_FIELD, STILL_AT_RISK_FIELD,
                                   CAUSAL_CHAIN_FIELD, CONTRIBUTING_FACTORS_FIELD,
                                   HAD_IT_BEEN_OTHERWISE_FIELD])
def test_a_role_said_of_lines_whose_rows_differ_is_named_in_every_field_of_prose(
        field: str) -> None:
    lumped = "The statement, the summary and the reconciliation read it as the month's figure."
    answers = {
        CAUSE_IN_PLAIN_WORDS_FIELD: _an_answer(cause_in_plain_words=lumped),
        STILL_AT_RISK_FIELD: _an_answer(still_at_risk=lumped),
        CAUSAL_CHAIN_FIELD: _an_answer(causal_chain=[SubmittedStep(step=lumped, cites=["E1"])]),
        CONTRIBUTING_FACTORS_FIELD: _an_answer(contributing_factors=[
            SubmittedFactor(label="CF-1", factor=lumped, had_it_been_otherwise=DONT_CARE_PROSE,
                            addressed_by=["AI-1"])]),
        HAD_IT_BEEN_OTHERWISE_FIELD: _an_answer(contributing_factors=[
            SubmittedFactor(label="CF-1", factor=DONT_CARE_PROSE, had_it_been_otherwise=lumped,
                            addressed_by=["AI-1"])])
    }

    Scenario() \
        .when(
            lambda: faults_in(answers[field], given=_given_lines_of_two_kinds())
        ) \
        .then(
            all_of(
                _named(field),
                _named(f"[{lumped}]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("lumped", [
    "src/shop/monthly_statement.py and src/shop/spend_reconciliation.py read it as the month's.",
    "Spend_summary and spend_reconciliation read it as the month's.",
    "render_statement and reconcile read it as the month's."
], ids=["by-path", "by-stem", "by-function"])
def test_a_line_is_named_by_its_file_or_the_function_it_sits_in(lumped: str) -> None:
    Scenario() \
        .given(
            an_answer_lumping_them := _an_answer(root_cause=lumped)
        ) \
        .when(
            lambda: faults_in(an_answer_lumping_them, given=_given_lines_of_two_kinds())
        ) \
        .then(
            all_of(
                _named("[U3]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_sentence_naming_lines_whose_rows_differ_without_saying_a_role_is_accepted() -> None:
    # "Still read" is true of every one of them: the reconciliation reads the
    # stored figure too, to set it against the purchases.
    Scenario() \
        .given(
            an_answer_naming_them := _an_answer(
                root_cause="The monthly statement, the spend summary and the reconciliation "
                           "all still read the stored field.")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_them, given=_given_lines_of_two_kinds())
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_role_said_of_lines_whose_rows_agree_is_accepted() -> None:
    # The statement and the summary do both take the stored figure's value.
    Scenario() \
        .given(
            an_answer_naming_two_readers := _an_answer(
                root_cause="The monthly statement and the spend summary read it as the "
                           "month's figure.")
        ) \
        .when(
            lambda: faults_in(an_answer_naming_two_readers, given=_given_lines_of_two_kinds())
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_role_said_where_no_lines_outside_the_patch_were_shown_is_accepted() -> None:
    Scenario() \
        .given(
            an_answer_lumping_them := _an_answer(
                root_cause="The monthly statement, the spend summary and the reconciliation "
                           "read it as the month's figure.")
        ) \
        .when(
            lambda: faults_in(an_answer_lumping_them, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
@pytest.mark.parametrize("contrast", [
    "and the reconciliation still compares it with the purchases",
    "and the reconciliation sets it against the purchases",
    "while the reconciliation compared it with the purchases"
], ids=["its-own-verb", "against", "its-own-verb-in-the-past"])
def test_a_sentence_saying_what_the_line_set_against_a_call_does_is_accepted(
        contrast: str) -> None:
    # A true contrast: each line is said as its row says it, and the role is
    # said of the field. The refusal asks for exactly this sentence.
    Scenario() \
        .given(
            an_answer_telling_them_apart := _an_answer(
                root_cause=f"The monthly statement and the spend summary still read it, "
                           f"{contrast}, so the field was still relied on.")
        ) \
        .when(
            lambda: faults_in(an_answer_telling_them_apart, given=_given_lines_of_two_kinds())
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
@pytest.mark.parametrize("sentence", [
    "As a result, the monthly statement, the spend summary and the reconciliation read it.",
    "The monthly statement, the spend summary and the reconciliation read it, as its "
    "docstring says.",
    "Readers such as the monthly statement and the reconciliation read it.",
    "The monthly statement as well as the reconciliation read it."
], ids=["as-a-result", "as-it-says", "such-as", "as-well-as"])
def test_an_as_that_says_no_role_is_accepted(sentence: str) -> None:
    Scenario() \
        .given(
            an_answer := _an_answer(root_cause=sentence)
        ) \
        .when(
            lambda: faults_in(an_answer, given=_given_lines_of_two_kinds())
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
@pytest.mark.parametrize("lumped", [
    "Monthly statements, spend summaries and the reconciliation read it as the month's figure.",
    "U1, U2 and U3 read it as the month's figure.",
    "The monthly statement, the month comparison, the spend summary and the reconciliation "
    "read it as the month's figure."
], ids=["plurals", "labels", "beside-a-noun-of-its-verb"])
def test_a_line_is_named_in_the_plural_or_by_its_label(lumped: str) -> None:
    Scenario() \
        .given(
            an_answer_lumping_them := _an_answer(root_cause=lumped)
        ) \
        .when(
            lambda: faults_in(an_answer_lumping_them, given=_given_lines_of_two_kinds())
        ) \
        .then(
            all_of(
                _named("[U3]"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_sentence_saying_the_checking_line_adds_the_purchases_up_is_accepted() -> None:
    # Adding the purchases up is what the reconciliation does: said beside a
    # reader, it tells the two apart rather than lumping them.
    Scenario() \
        .given(
            an_answer := _an_answer(
                root_cause="Each purchase raised the sum the reconciliation adds up while the "
                           "stored total the monthly statement shows stayed where it was.")
        ) \
        .when(
            lambda: faults_in(an_answer, given=_given_lines_of_two_kinds())
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_derivation_said_before_the_lines_are_named_is_accepted() -> None:
    # The change meant the month to be derived; that the readers still read
    # the stored field is true of every one of them.
    Scenario() \
        .given(
            an_answer := _an_answer(
                root_cause="The month was to be derived from the purchases, but the monthly "
                           "statement, the spend summary and the reconciliation still read it.")
        ) \
        .when(
            lambda: faults_in(an_answer, given=_given_lines_of_two_kinds())
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
@pytest.mark.parametrize("lumped", [
    "Until the statement, the summary and the reconciliation derive the month themselves, the "
    "field must stay.",
    "The change would have been held until the statement, spend-summary and reconciliation "
    "code derived the month total themselves.",
    "The reconciliation and the statement both add the purchases up."
], ids=["derive", "derived-with-a-hyphened-stem", "add-up"])
def test_a_list_of_both_kinds_said_to_work_the_figure_out_is_named(lumped: str) -> None:
    # The reconciliation adds the purchases up already: that a list holding it
    # should derive the month says of it what its row does not.
    Scenario() \
        .given(
            an_answer_lumping_them := _an_answer(root_cause=lumped)
        ) \
        .when(
            lambda: faults_in(an_answer_lumping_them, given=_given_lines_of_two_kinds())
        ) \
        .then(
            all_of(
                _named("[U3]"),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("sentence", [
    "Each purchase raised the sum the reconciliation adds up while the stored total the "
    "monthly statement shows stayed where it was.",
    "The monthly statement and the spend summary should derive the month themselves, while "
    "the reconciliation already does.",
    "The statement reads it and the reconciliation adds the purchases up.",
    "The reconciliation, unlike the statement and the summary, adds the purchases up.",
    "The premise was that the month would be derived from purchase history, but the stored "
    "field is still read by the monthly statement, spend summary and reconciliation code.",
    "The monthly statement, the spend summary and the reconciliation still read the stored "
    "field, and the totals no longer add up to the purchases.",
    "The reconciliation adds the purchases up again and compares the sum with the stored "
    "field, which the statement and the summary read."
], ids=["adds-up-beside-a-reader", "a-list-of-readers", "each-its-own-verb", "unlike",
        "derived-before-the-list", "add-up-to", "its-own-verb-too"])
def test_a_derivation_said_of_no_list_of_both_kinds_is_accepted(sentence: str) -> None:
    Scenario() \
        .given(
            an_answer := _an_answer(root_cause=sentence)
        ) \
        .when(
            lambda: faults_in(an_answer, given=_given_lines_of_two_kinds())
        ) \
        .then(
            _found_nothing_wrong()
        )


def _given_lines_of_two_kinds() -> Given:
    """`SOME_GIVEN`, with lines outside Code-Fix's patch of both kinds: two
    taking the stored figure's value, and one setting it against what a
    function of its own file returns."""
    return SOME_GIVEN.model_copy(update={"uses": {
        "U1": CodeUse(name="month", path="src/shop/monthly_statement.py", line=12,
                      function="render_statement", does="reads it: total = account.month"),
        "U2": CodeUse(name="month", path="src/shop/spend_summary.py", line=8,
                      function="average", does="divides with it: account.month // count"),
        "U3": CodeUse(name="month", path="src/shop/spend_reconciliation.py", line=20,
                      function="reconcile",
                      does="compares it with bought(account), where bought(account) returns "
                           "sum(account.purchases)",
                      set_against_a_call=True)
    }})


@pytest.mark.unit
def test_a_step_of_the_cause_saying_a_check_is_missing_is_named() -> None:
    # The chain's last step said "nothing seen checks that the two names
    # agree", though the chain is told the safeguard is a factor and no step.
    missing_check = "The rename shipped alone, and nothing seen checks that the names agree."

    Scenario() \
        .given(
            an_answer_with_a_step_blaming_a_missing_check := _an_answer(
                causal_chain=[SubmittedStep(step=DONT_CARE_PROSE, cites=["E1"]),
                              SubmittedStep(step=missing_check, cites=["E2"])])
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_step_blaming_a_missing_check, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(missing_check),
                _named(CONTRIBUTING_FACTORS_FIELD),
                _found(1)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("limit_of_the_evidence", [
    "No test or reproduction was run, so the chain stops here.",
    "The record does not show why the change was made, or why no test caught it.",
    "The scrape config is Code-Fix's reading, which nothing verified."
], ids=["no-test-was-run", "why-no-test-caught-it", "nothing-verified"])
def test_a_step_of_the_cause_saying_what_the_evidence_does_not_reach_is_accepted(
        limit_of_the_evidence: str) -> None:
    # Where the evidence stops is no safeguard missing. The first two are steps
    # of recorded write-ups, and the third is the hedge an F-only step is asked
    # for: a check the rule refused in any of them would send back an answer
    # that said what it was told to.
    Scenario() \
        .given(
            an_answer_with_a_step_at_the_evidence_s_limit := _an_answer(
                causal_chain=[SubmittedStep(step=DONT_CARE_PROSE, cites=["E1"]),
                              SubmittedStep(step=limit_of_the_evidence, cites=["E2"])])
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_step_at_the_evidence_s_limit, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_factor_saying_a_check_is_missing_is_accepted() -> None:
    # Where the missing check belongs.
    Scenario() \
        .given(
            an_answer_with_a_factor_naming_a_missing_check := _an_answer(
                contributing_factors=[SubmittedFactor(
                    label="CF-1",
                    factor="Nothing checks that the two names agree.",
                    had_it_been_otherwise=DONT_CARE_PROSE,
                    addressed_by=["AI-1"])])
        ) \
        .when(
            lambda: faults_in(an_answer_with_a_factor_naming_a_missing_check, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


@pytest.mark.unit
def test_a_turn_submitting_twice_is_named() -> None:
    # Two calls do not say which is the answer. In the turn that showed it the
    # real one came first and a placeholder second, but a model revising its
    # answer puts the real one second - so keeping either is a guess.
    Scenario() \
        .given(
            a_turn_submitting_twice := _a_turn_calling(SUBMIT_TOOL_NAME, SUBMIT_TOOL_NAME)
        ) \
        .when(
            lambda: faults_in_the_turn(a_turn_submitting_twice)
        ) \
        .then(
            all_of(
                _found(1),
                _named(f"{SUBMIT_TOOL_NAME} 2 times")
            )
        )


@pytest.mark.unit
def test_a_turn_submitting_once_has_nothing_wrong_with_it() -> None:
    Scenario() \
        .given(
            a_turn_submitting_once := _a_turn_calling(SUBMIT_TOOL_NAME)
        ) \
        .when(
            lambda: faults_in_the_turn(a_turn_submitting_once)
        ) \
        .then(
            _found_nothing_wrong()
        )


def _a_turn_calling(*tools: str) -> Turn:
    """A turn calling each of these tools once, in order, with no arguments."""
    return Turn(text="",
                tool_calls=[ToolCall(id=f"call_{position}", name=tool, arguments={})
                            for position, tool in enumerate(tools, start=1)],
                input_tokens=0,
                output_tokens=0)


class _WhatAnAnswerHolds(TypedDict, total=False):
    """Every field of a submitted answer, each typed as the model types it.

    Typed rather than `Any`, so mypy checks every name and value a case passes
    against this list, and this list against the model's own constructor: a
    field renamed in the model fails the typecheck here rather than being
    dropped while the case goes on asserting against the default.
    """

    root_cause: str | None
    cause_in_plain_words: str | None
    still_at_risk: str | None
    symptom: str | None
    assumptions: list[str]
    lead_effects: dict[str, str]
    causal_chain: list[SubmittedStep] | None
    contributing_factors: list[SubmittedFactor] | None
    action_items: list[SubmittedItem] | None
    lessons: Lessons | None
    reaches_a_cause: bool
    logs_show_serving_as_before: bool | None
    cause_rests_on_an_unrun_reading: bool | None


def _an_answer(**overrides: Unpack[_WhatAnAnswerHolds]) -> SubmittedPostmortem:
    """An answer that passes every check against `SOME_GIVEN`, but for what a
    test overrides: a chain of one step citing the first label, no factors, no
    proposals, and three empty lessons."""
    complete: _WhatAnAnswerHolds = {
        "root_cause": DONT_CARE_PROSE,
        "cause_in_plain_words": SOME_CAUSE_WITHOUT_A_NUMBER,
        "still_at_risk": "",
        "symptom": DONT_CARE_PROSE,
        "causal_chain": [SubmittedStep(step=DONT_CARE_PROSE, cites=["E1"])],
        "contributing_factors": [],
        "action_items": [],
        "lessons": Lessons()
    }

    return SubmittedPostmortem(**(complete | overrides))


def _given_figures(*names: str, figures: Mapping[str, Figure] = SOME_FIGURES) -> Given:
    """`SOME_GIVEN`, giving the figures named - each as `figures` has it, or
    one nobody cares about where it has none."""
    return SOME_GIVEN.model_copy(
        update={"figures": {name: figures.get(name, DONT_CARE_FIGURE) for name in names}})


def _named(expected: str) -> Assertion[list[str]]:
    """That some fault says the thing the model has to act on.

    Containment rather than equality: the sentence around it is written for a
    model and is free to be reworded, while the field or the figure inside it
    is the part a second attempt is about.
    """
    def assertion(faults: list[str]) -> bool:
        if not any(expected in fault for fault in faults):
            raise AssertionError(
                f"Expected a fault naming [{expected}], got {faults}.")

        return True

    return assertion


def _found(expected: int) -> Assertion[list[str]]:
    def assertion(faults: list[str]) -> bool:
        if len(faults) != expected:
            raise AssertionError(
                f"Expected [{expected}] fault(s), got [{len(faults)}]: {faults}.")

        return True

    return assertion


def _found_nothing_wrong() -> Assertion[list[str]]:
    def assertion(faults: list[str]) -> bool:
        if faults:
            raise AssertionError(
                f"Expected nothing wrong with the answer, got {faults}.")

        return True

    return assertion
