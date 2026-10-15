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
from typing import Any

import pytest
from agent_postmortem.checking import Given, faults_in
from agent_postmortem.estimate import ErrorRates
from agent_postmortem.figures import Figure, figures_of
from agent_postmortem.prompting import (
    ACTION_ITEMS_FIELD,
    CAUSAL_CHAIN_FIELD,
    CONTRIBUTING_FACTORS_FIELD,
    EXECUTIVE_SUMMARY_FIELD,
    LESSONS_FIELD,
    ROOT_CAUSE_FIELD,
    SYMPTOM_FIELD,
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedStep,
)
from argus_core.models import ActionItemType, Lessons
from argus_testkit import Assertion, Scenario, all_of

from agent_postmortem_test.framework.builders import (
    a_lead,
    a_measured_incident,
    an_evidence_bundle,
)

SOME_SUMMARY_WITHOUT_A_NUMBER = "checkout failed for several minutes, for most requests"

DONT_CARE_PROSE = "dont care"

# What the model was handed: two labelled pieces of evidence and one action
# item already on the record.
SOME_GIVEN = Given(labels=frozenset({"E1", "E2"}), items_on_record=1)

# The figures an incident that recovered gives, which a working is worked out
# from: it began at noon and recovered ten minutes later.
SOME_FIGURES = figures_of(an_evidence_bundle(), a_measured_incident())

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
                _named(EXECUTIVE_SUMMARY_FIELD),
                _named(CAUSAL_CHAIN_FIELD),
                _named(CONTRIBUTING_FACTORS_FIELD),
                _named(ACTION_ITEMS_FIELD),
                _named(LESSONS_FIELD),
                _named(SYMPTOM_FIELD),
                _found(7)
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
                executive_summary="errors peaked at 33.8% of requests")
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
                executive_summary="the outage cost $1,200,000")
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
                executive_summary="from 21:45 for 7 minutes")
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
                executive_summary=f"the widest total was short by {spelled_out}")
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
    "two thirds"
])
def test_a_figure_said_in_one_word_is_named(said: str) -> None:
    # "About twenty minutes" for an incident six minutes long was accepted
    # while "about 20 minutes" was refused: the rule judged the spelling, not
    # the claim. One word measuring something is a figure as much as a run of
    # them, and a figure the incident gave, or a working of two, says it truly.
    Scenario() \
        .given(
            an_answer_saying_a_figure_in_a_word := _an_answer(
                executive_summary=f"after the deploy it was {said}")
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
                executive_summary="it ran for twenty-four hours")
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
    "the one that failed"
])
def test_a_size_with_no_figure_in_it_is_accepted(said: str) -> None:
    # A count of things, a size said without a number, and a number that
    # describes rather than measures ("one-minute buckets") claim no precision
    # anybody measured - and the rule has to leave the model something to say.
    Scenario() \
        .given(
            an_answer_sizing_without_a_figure := _an_answer(
                executive_summary=f"after the deploy it was {said}")
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
                executive_summary="short by {A3} for {duration}")
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
            an_answer_naming_a_ghost_figure := _an_answer(executive_summary="short by {A9}")
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
def test_a_working_the_figures_answer_is_accepted() -> None:
    # The way the prose states a figure the incident never measured as one: by
    # naming what to work out, which code works out from what was measured.
    Scenario() \
        .given(
            an_answer_working_out_a_span := _an_answer(
                executive_summary="it was broken for {recovered - began}")
        ) \
        .when(
            lambda: faults_in(an_answer_working_out_a_span,
                              given=_given_figures("recovered", "began"))
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
                executive_summary="mitigation began {T21.1 - T18.1} in")
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
    # the page in braces - so it is put back to the model instead.
    Scenario() \
        .given(
            an_answer_adding_two_instants := _an_answer(
                executive_summary="it ended at {began + closed}")
        ) \
        .when(
            lambda: faults_in(an_answer_adding_two_instants,
                              given=_given_figures("began", "closed"))
        ) \
        .then(
            all_of(
                _named("[{began + closed}]"),
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
                executive_summary="the totals fell by {A1 - A2}")
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
                executive_summary="it was broken for {recovered - began}")
        ) \
        .when(
            lambda: faults_in(an_answer_working_from_a_ghost,
                              given=_given_figures("began"))
        ) \
        .then(
            all_of(
                _named("[{recovered}]"),
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
                executive_summary="it was broken for {began - recovered}")
        ) \
        .when(
            lambda: faults_in(an_answer_working_backwards,
                              given=_given_figures("recovered", "began"))
        ) \
        .then(
            all_of(
                _named("[{began - recovered}]"),
                _named("comes out below nothing"),
                _found(1)
            )
        )


@pytest.mark.unit
def test_a_working_that_divides_by_nothing_is_named() -> None:
    # A shop that failed nothing before has no "how many times" to compare
    # the incident with.
    some_figures_failing_nothing_before = figures_of(
        an_evidence_bundle(),
        a_measured_incident(
            error_rates=ErrorRates(baseline=0.0, while_broken=0.338, at_its_worst=0.5)))

    Scenario() \
        .given(
            an_answer_dividing_by_nothing := _an_answer(
                executive_summary="errors were {errors_at_worst / errors_before} as common")
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
                executive_summary="the shop took 12345678 cents")
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
def test_a_summary_the_model_never_wrote_is_missing_rather_than_numbered() -> None:
    # An absent summary has no numbers in it, and the fault it earns is the one
    # about the field.
    Scenario() \
        .given(
            an_answer_with_no_summary := _an_answer(executive_summary=None)
        ) \
        .when(
            lambda: faults_in(an_answer_with_no_summary, given=SOME_GIVEN)
        ) \
        .then(
            all_of(
                _named(EXECUTIVE_SUMMARY_FIELD),
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
def test_a_contributing_factor_nothing_answers_is_named() -> None:
    # A factor with no action item is a condition the document noticed and
    # left standing - the thing an analysis without actions is.
    Scenario() \
        .given(
            an_answer_with_an_unanswered_factor := _an_answer(contributing_factors=[
                SubmittedFactor(factor="the canary started large", addressed_by=[])
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
def test_a_factor_naming_an_item_that_does_not_exist_is_named() -> None:
    Scenario() \
        .given(
            an_answer_naming_a_ghost_item := _an_answer(contributing_factors=[
                SubmittedFactor(factor="no test covered an empty month",
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
def test_a_factor_may_name_an_item_on_the_record_or_one_the_answer_proposes() -> None:
    # One item on the record, so the answer's first proposal is AI-2.
    Scenario() \
        .given(
            an_answer_naming_both := _an_answer(
                contributing_factors=[
                    SubmittedFactor(factor="no test covered an empty month",
                                    addressed_by=["AI-1", "AI-2"])
                ],
                action_items=[SubmittedItem(item="add a test for an empty month",
                                            type=ActionItemType.PREVENT)])
        ) \
        .when(
            lambda: faults_in(an_answer_naming_both, given=SOME_GIVEN)
        ) \
        .then(
            _found_nothing_wrong()
        )


def _an_answer(**overrides: Any) -> SubmittedPostmortem:
    """An answer that passes every check against `SOME_GIVEN`, but for what a
    test overrides: a chain of one step citing the first label, no factors, no
    proposals, and three empty lessons."""
    complete: dict[str, Any] = {
        "root_cause": DONT_CARE_PROSE,
        "executive_summary": SOME_SUMMARY_WITHOUT_A_NUMBER,
        "symptom": DONT_CARE_PROSE,
        "causal_chain": [SubmittedStep(step=DONT_CARE_PROSE, cites=["E1"])],
        "contributing_factors": [],
        "action_items": [],
        "lessons": Lessons()
    }

    return SubmittedPostmortem(**{**complete, **overrides})


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
