"""The figures a write-up may state, each by its name, and the write-up with
every one written in.

The model writes no figure. Every figure a postmortem states is one Argus
measured or one the alert reported, and a model left to restate one rounds it,
works it out again, or - refused its digits - spells it out in words nobody can
read: "one thousand two hundred ninety-seven and thirty-one hundredths". So each
figure the model is shown carries a name after it, the model writes the name
where the figure goes, and code writes the figure in, in digits, as the
incident gave it.

The figure written in is the run's own. A recorded answer names `{duration}`,
and the run replaying it writes in the duration it measured, so a page never
quotes a figure from the incident the recording was made against.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from agent_postmortem import EngagementAnswer, NotPaged
from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels
from agent_postmortem.figures import (
    ACTED_FIGURE,
    AFTER_THE_WAIT_FIGURE,
    ALERT_RAISED_FIGURE,
    ALERTED_AFTER_THE_ONSET_FIGURE,
    ARGUS_STOPPED_FIGURE,
    BACK_TO_NORMAL_FIGURE,
    BEGAN_FIGURE,
    CUSTOMER_LOSS_FIGURE,
    DURATION_FIGURE,
    ERRORS_AT_WORST_FIGURE,
    ERRORS_BEFORE_FIGURE,
    ERRORS_RISE_FIGURE,
    ERRORS_WHILE_BROKEN_FIGURE,
    FIRST_TOLD_FIGURE,
    HELD_FIGURE,
    LOG_READING_ENDED_FIGURE,
    LOGS_REACH_UNTIL_FIGURE,
    METRICS_STOPPED_AT_FIGURE,
    RULE_LOOKS_BACK_FIGURE,
    RULE_WAITS_FIGURE,
    SERIES_AT_WORST_FIGURE,
    SERIES_BEFORE_FIGURE,
    SERIES_WHILE_BROKEN_FIGURE,
    Figure,
    figures_of,
    named,
    names_in,
    the_alerts_figures,
    the_evidence_figures,
    the_evidence_named,
    the_finding_named,
    the_log_group_figures,
    the_narration_figures,
    units_against_their_figures,
    with_every_day_said,
    with_figures_written,
    with_figures_written_with_every_day,
)
from agent_postmortem.prompting import (
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedStep,
)
from argus_core import said_as_a_day, to_iso
from argus_core.models import (
    ActionItemType,
    CitedEvidence,
    FirstTold,
    Lessons,
    ReportChannel,
    Verdict,
)
from argus_testkit import Assertion, Scenario, all_of, the_answer_was

from agent_postmortem_test.framework.builders import (
    ENDED_AT,
    ONSET,
    RECOVERED_AT,
    STARTED_AT,
    a_measured_incident,
    an_action,
    an_evidence_bundle,
)

# What a shop's integrity check reports, in its own words: two counts, an
# amount, and an instant.
SOME_FINDING = ("240 of 240 shopper totals do not reconcile with the purchases behind "
                "them. The widest is short by 1,297.31, and the oldest affected purchase "
                "was recorded at 2026-10-05T16:10:00Z.")

SOME_AMOUNT = Figure(given="1,297.31", written="1,297.31")

# Figures written in with their units - a level, a share and two spans - and
# one a log group gives with none.
SOME_FIGURES_WITH_UNITS = {
    SERIES_BEFORE_FIGURE: Figure(given="215.13 ms", written="215 ms"),
    ERRORS_BEFORE_FIGURE: Figure(given="1.2%", written="1.2%"),
    HELD_FIGURE: Figure(given="30 minutes", written="30 minutes"),
    DURATION_FIGURE: Figure(given="10 minutes", written="10 minutes"),
    "G46bc.2": Figure(given="37", written="37")
}

# The day the finding's instant falls on, so the alert is read as one that
# began that day and its instant is said without it.
THE_FINDING_S_DAY = date(2026, 10, 5)

# The day an incident began, where nothing read is an instant it could leave
# unsaid.
DONT_CARE_DAY = date(2026, 9, 2)

# A log group as the model reads it: a setting, a count, a span and the minutes
# it covers.
SOME_EVIDENCE = CitedEvidence(
    label="Gbac1",
    text="pool exhausted at 20 connections - 29 occurrences in 32 minutes, 15:11–15:42")

SOME_DIFF = CitedEvidence(label="D1", text="modified deploy/values-production.yaml\n"
                                           "  @@ -12,7 +12,7 @@\n"
                                           "  -  timeout: 30\n"
                                           "  +  timeout: 5")

# A line of narration dating a time on another day than its own, as narration
# dates one: the day, then the time.
SOME_MOMENT_ON_ANOTHER_DAY = datetime(2026, 10, 20, 20, 31, tzinfo=UTC)
SOME_LINE_DATING_A_TIME = CitedEvidence(
    label="T8",
    text=f"Asked for production change events, the 1 day before "
         f"{said_as_a_day(SOME_MOMENT_ON_ANOTHER_DAY)} {SOME_MOMENT_ON_ANOTHER_DAY:%H:%M}")


@pytest.mark.unit
def test_a_figure_the_prose_names_is_written_in() -> None:
    Scenario() \
        .given(
            an_answer_naming_it := SubmittedPostmortem(root_cause="The widest was short by {A3}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_it, {"A3": SOME_AMOUNT})
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="The widest was short by 1,297.31."))
        )


@pytest.mark.unit
def test_every_sentence_the_answer_publishes_has_its_figures_written_in() -> None:
    # A figure is named wherever the model writes one, and a field left out
    # here is one that reaches the page saying {A3}.
    Scenario() \
        .given(
            an_answer_naming_it_everywhere := _an_answer_saying_everywhere("short by {A3}")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_it_everywhere, {"A3": SOME_AMOUNT})
        ) \
        .then(
            the_answer_was(_an_answer_saying_everywhere("short by 1,297.31"))
        )


@pytest.mark.unit
def test_a_name_no_figure_was_given_is_left_for_the_check() -> None:
    # Nothing here can know which figure it meant, and a guess written in as
    # the figure is a number nobody measured.
    Scenario() \
        .given(
            an_answer_naming_nothing_given := SubmittedPostmortem(root_cause="short by {A9}")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_nothing_given, {"A3": SOME_AMOUNT})
        ) \
        .then(
            the_answer_was(an_answer_naming_nothing_given)
        )


@pytest.mark.unit
def test_the_span_between_two_instants_is_written_in_as_one() -> None:
    # Worked out by code from the figures the model was shown, so the model
    # does no arithmetic and the page never disagrees with itself.
    Scenario() \
        .given(
            figures := figures_of(an_evidence_bundle(), a_measured_incident()),
            an_answer_naming_the_span := SubmittedPostmortem(
                root_cause="It was broken for {back_to_normal - began}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_the_span, figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="It was broken for 10 minutes."))
        )


@pytest.mark.unit
def test_the_difference_of_two_shares_is_written_in_percentage_points() -> None:
    # Points, because "rose by 32.7%" reads as a share of where it started.
    # And from the shares as shown, 1.2% and 33.9%: worked from what was
    # measured, 1.24% and 33.86%, it would say 32.6 beside two figures that
    # plainly differ by 32.7.
    Scenario() \
        .given(
            figures := figures_of(an_evidence_bundle(), a_measured_incident(
                error_rates=ErrorRates(baseline=0.0124, while_broken=0.3386, at_its_worst=0.5,
                                       usual_ceiling=0.02, usual_worst=0.04))),
            an_answer_naming_the_difference := SubmittedPostmortem(
                root_cause="Errors rose by {errors_while_broken - errors_before}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_the_difference, figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(
                root_cause="Errors rose by 32.7 percentage points."))
        )


@pytest.mark.unit
def test_the_ratio_of_two_shares_is_written_in_as_how_many_times() -> None:
    # To a tenth, from the shares as shown: 50.0% over 1.5%.
    Scenario() \
        .given(
            figures := figures_of(an_evidence_bundle(), a_measured_incident(
                error_rates=ErrorRates(baseline=0.015, while_broken=0.338, at_its_worst=0.5,
                                       usual_ceiling=0.02, usual_worst=0.04))),
            an_answer_naming_the_ratio := SubmittedPostmortem(
                root_cause="At worst errors were {errors_at_worst / errors_before} as common.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_the_ratio, figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(
                root_cause="At worst errors were 33.3 times as common."))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("working", "written"), [
    ("{began + duration}", "12:10 UTC"),
    ("{argus_stopped - held}", "12:00 UTC"),
    ("{held + duration}", "40 minutes"),
    ("{held - duration}", "20 minutes"),
    ("{held / duration}", "3.0 times"),
    ("{series_before - series_at_worst}", "0.8"),
    ("{series_before / series_at_worst}", "7.7 times")
])
def test_every_working_the_kinds_allow_is_written_in(working: str, written: str) -> None:
    # An instant moved by a span is an instant, two spans add to a span, and a
    # level less a level is a level in the rule's own unit. Two of a kind
    # divide into how many times.
    Scenario() \
        .given(
            figures := figures_of(an_evidence_bundle(), a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=0.92, while_broken=0.41,
                                             at_its_worst=0.12, worse_when="below"))),
            an_answer_naming_it := SubmittedPostmortem(root_cause=f"It was {working}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_it, figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause=f"It was {written}."))
        )


@pytest.mark.unit
def test_an_instant_worked_out_onto_another_day_than_the_one_it_began_says_its_day() -> None:
    # The page dates the incident once, in its head; an instant on that day is
    # said as a time, and one past midnight says which day it fell on.
    some_figures = {
        BEGAN_FIGURE: Figure(given="2026-09-02T23:50:00Z", written="dont care"),
        DURATION_FIGURE: Figure(given="20 minutes", written="dont care")
    }

    Scenario() \
        .given(
            an_answer_naming_it := SubmittedPostmortem(root_cause="It was {began + duration}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_it, some_figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="It was Sep 03, 00:10 UTC."))
        )


@pytest.mark.unit
def test_an_instant_worked_out_with_no_day_it_began_says_its_date_in_full() -> None:
    # Nothing to leave unsaid: with no instant the incident is dated from, a
    # time alone says no day at all.
    some_figures = {
        ARGUS_STOPPED_FIGURE: Figure(given="2026-09-02T12:30:00Z", written="dont care"),
        HELD_FIGURE: Figure(given="30 minutes", written="dont care")
    }

    Scenario() \
        .given(
            an_answer_naming_it := SubmittedPostmortem(
                root_cause="It was {argus_stopped - held}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_it, some_figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="It was Sep 02, 2026, 12:00 UTC."))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("unit", "before", "at_worst", "working", "written"), [
    ("ms", 900.0, 300.0, "{series_before - series_at_worst}", "600 ms"),
    ("percentunit", 0.899, 0.446, "{series_before - series_at_worst}", "45.3 percentage points"),
    ("ms", 900.0, 300.0, "{series_before / series_at_worst}", "3.0 times")
], ids=["a-difference-in-milliseconds", "a-difference-of-two-percentages", "a-ratio"])
def test_a_working_of_two_levels_is_written_in_their_unit(unit: str, before: float,
                                                          at_worst: float, working: str,
                                                          written: str) -> None:
    # A level less a level is a level in the same unit - and two percentages
    # differ by points, as two shares of traffic do. How many times is no unit.
    Scenario() \
        .given(
            figures := figures_of(an_evidence_bundle(), a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=before, while_broken=at_worst,
                                             at_its_worst=at_worst, worse_when="below"),
                rule_series_unit=unit)),
            an_answer_naming_it := SubmittedPostmortem(root_cause=f"It was {working}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_it, figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause=f"It was {written}."))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("said", "written"), [
    ("{series_before} ms", "215 ms"),
    ("{series_before} milliseconds", "215 ms"),
    ("{errors_before} percent", "1.2%"),
    ("{errors_before}%", "1.2%"),
    ("{held / duration} times", "3.0 times")
], ids=["the-same-spelling", "another-spelling", "a-share-in-a-word", "a-share-in-a-sign",
        "a-working"])
def test_a_unit_said_again_after_a_figure_written_with_it_is_written_once(said: str,
                                                                          written: str) -> None:
    # The model is shown a figure with its unit outside the name, "215.13 ms
    # {series_before}", so "{series_before} ms" is a fair reading of it. The
    # figure is written in with its unit already, and a bad-deployment write-up
    # reached the page as "1943 ms ms".
    Scenario() \
        .given(
            an_answer_saying_the_unit_again := SubmittedPostmortem(root_cause=f"It was {said}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_saying_the_unit_again,
                                         SOME_FIGURES_WITH_UNITS)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause=f"It was {written}."))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("name", "figure", "said", "written"), [
    (SERIES_BEFORE_FIGURE, Figure(given="1024 bytes", written="1024 bytes"),
     "{series_before} bytes", "1024 bytes"),
    (BEGAN_FIGURE, Figure(given="2026-09-02T12:00:00Z", written="12:00 UTC"),
     "{began} UTC", "12:00 UTC")
], ids=["a-unit-as-grafana-names-it", "an-instant-s-zone"])
def test_the_word_a_figure_is_written_ending_in_said_again_is_written_once(
        name: str, figure: Figure, said: str, written: str) -> None:
    # A rule's unit is whatever Grafana names it, and no list of spellings
    # holds them all: the word the figure ends in, said again, is said once.
    Scenario() \
        .given(
            an_answer_saying_it_again := SubmittedPostmortem(root_cause=f"It was {said}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_saying_it_again, {name: figure})
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause=f"It was {written}."))
        )


@pytest.mark.unit
def test_a_word_after_a_figure_written_with_no_unit_is_the_writers_own() -> None:
    # A count a log group gives carries no unit, so the word after its name is
    # the one thing saying what it counts.
    Scenario() \
        .given(
            an_answer_saying_what_it_counts := SubmittedPostmortem(
                root_cause="It ran for {G46bc.2} minutes.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_saying_what_it_counts,
                                         SOME_FIGURES_WITH_UNITS)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="It ran for 37 minutes."))
        )


@pytest.mark.unit
@pytest.mark.parametrize("working", [
    "{series_while_broken - series_before}",
    "{series_at_worst / series_before}"
], ids=["infinity", "not-a-number"])
def test_a_working_from_a_level_that_is_no_number_is_left_for_the_check(working: str) -> None:
    # Prometheus answers +Inf or NaN for a ratio over nothing, and a level
    # averaged over such a minute is one too. Nothing can be worked out from
    # it, and working it out raised where it should have been sent back.
    Scenario() \
        .given(
            figures := figures_of(an_evidence_bundle(), a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=200.0, while_broken=float("inf"),
                                             at_its_worst=float("nan"), worse_when="above"),
                rule_series_unit="ms")),
            an_answer_working_from_it := SubmittedPostmortem(root_cause=f"It was {working}.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_working_from_it, figures)
        ) \
        .then(
            the_answer_was(an_answer_working_from_it)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("said", "against"), [
    ("{series_before} seconds", "ms"),
    ("{held - duration} seconds", "minutes")
], ids=["a-figure", "a-working"])
def test_another_unit_of_what_a_figure_measures_is_found_against_it(said: str,
                                                                    against: str) -> None:
    # "215 ms seconds" misreads the figure's scale, and nothing can tell which
    # of the two the sentence meant - so it goes back to the model.
    Scenario() \
        .given(
            a_sentence_misreading_the_scale := f"The slowest took {said} at worst."
        ) \
        .when(
            lambda: units_against_their_figures(a_sentence_misreading_the_scale,
                                                SOME_FIGURES_WITH_UNITS)
        ) \
        .then(
            the_answer_was([(said, against)])
        )


@pytest.mark.unit
@pytest.mark.parametrize("said", [
    "{series_before} ms",
    "{G46bc.2} minutes",
    "{errors_before} times"
], ids=["the-same-unit", "a-figure-with-no-unit", "a-unit-of-another-measure"])
def test_a_unit_that_does_not_misread_its_figure_is_not_found(said: str) -> None:
    # The same unit is written once; a figure with none leaves the word after
    # it to the writer; a unit of something else is no reading of its scale.
    nothing_found: list[tuple[str, str]] = []

    Scenario() \
        .given(
            a_sentence := f"It was {said}."
        ) \
        .when(
            lambda: units_against_their_figures(a_sentence, SOME_FIGURES_WITH_UNITS)
        ) \
        .then(
            the_answer_was(nothing_found)
        )


@pytest.mark.unit
def test_the_names_a_sentence_uses_in_the_order_it_uses_them() -> None:
    Scenario() \
        .given(
            some_prose := "short by {A3} after {duration}, and by {A3} again"
        ) \
        .when(
            lambda: names_in(some_prose)
        ) \
        .then(
            the_answer_was(["A3", "duration", "A3"])
        )


@pytest.mark.unit
def test_a_figure_is_shown_to_the_model_with_its_name_after_it() -> None:
    Scenario() \
        .given(
            some_figure := Figure(given="2026-10-05T16:10:00Z",
                                  written="Oct 05, 2026, 16:10 UTC")
        ) \
        .when(
            lambda: named(BEGAN_FIGURE, some_figure)
        ) \
        .then(
            the_answer_was("2026-10-05T16:10:00Z {began}")
        )


@pytest.mark.unit
def test_the_alerts_figures_are_named_in_the_order_it_states_them() -> None:
    # An instant is written as a reader says one; every other figure is
    # written exactly as the sender wrote it.
    Scenario() \
        .given(
            some_finding := SOME_FINDING
        ) \
        .when(
            lambda: the_alerts_figures(some_finding, THE_FINDING_S_DAY)
        ) \
        .then(
            the_answer_was({
                "A1": Figure(given="240", written="240"),
                "A2": Figure(given="240", written="240"),
                "A3": Figure(given="1,297.31", written="1,297.31"),
                "A4": Figure(given="2026-10-05T16:10:00Z", written="16:10 UTC")
            })
        )


@pytest.mark.unit
def test_an_alert_s_instant_on_another_day_than_the_incident_began_says_its_day() -> None:
    # The year is the head's to say: a day of the incident's is never a year
    # away from the one in its Date row.
    Scenario() \
        .given(
            some_finding := SOME_FINDING
        ) \
        .when(
            lambda: the_alerts_figures(some_finding, THE_FINDING_S_DAY + timedelta(days=1))
        ) \
        .then(
            _the_figures_include({
                "A4": Figure(given="2026-10-05T16:10:00Z", written="Oct 05, 16:10 UTC")
            })
        )


@pytest.mark.unit
def test_an_instant_is_written_to_the_second_only_where_it_has_one() -> None:
    # A minute said "16:10:00" claims a precision nothing measured; a second an
    # alert reported is one it measured, and is kept.
    Scenario() \
        .given(
            some_finding := "The oldest affected purchase was recorded at 2026-10-05T16:10:53Z."
        ) \
        .when(
            lambda: the_alerts_figures(some_finding, THE_FINDING_S_DAY)
        ) \
        .then(
            the_answer_was({
                "A1": Figure(given="2026-10-05T16:10:53Z", written="16:10:53 UTC")
            })
        )


@pytest.mark.unit
def test_the_alert_is_shown_with_each_figure_named_after_it() -> None:
    # The name sits before whatever punctuation closed the figure, so the
    # sentence still reads as the sender wrote it.
    Scenario() \
        .given(
            some_finding := SOME_FINDING
        ) \
        .when(
            lambda: the_finding_named(some_finding)
        ) \
        .then(
            the_answer_was(
                "240 {A1} of 240 {A2} shopper totals do not reconcile with the purchases "
                "behind them. The widest is short by 1,297.31 {A3}, and the oldest affected "
                "purchase was recorded at 2026-10-05T16:10:00Z {A4}."
            )
        )


@pytest.mark.unit
def test_the_figures_in_a_piece_of_evidence_are_named_after_its_label() -> None:
    # Quoted as given, "20 connections" was refused as digits, so the model
    # could not say what its own evidence said. Named after the evidence they
    # are in, in the order it says them, like the alert's.
    Scenario() \
        .given(
            some_evidence := SOME_EVIDENCE
        ) \
        .when(
            lambda: the_evidence_figures([some_evidence], DONT_CARE_DAY)
        ) \
        .then(
            the_answer_was({
                "Gbac1.1": Figure(given="20", written="20"),
                "Gbac1.2": Figure(given="29", written="29"),
                "Gbac1.3": Figure(given="32", written="32"),
                "Gbac1.4": Figure(given="15:11–15:42", written="15:11–15:42")
            })
        )


@pytest.mark.unit
def test_a_piece_of_evidence_is_shown_with_each_figure_named_after_it() -> None:
    Scenario() \
        .given(
            some_evidence := SOME_EVIDENCE
        ) \
        .when(
            lambda: the_evidence_named(some_evidence)
        ) \
        .then(
            the_answer_was("pool exhausted at 20 {Gbac1.1} connections - 29 {Gbac1.2} "
                           "occurrences in 32 {Gbac1.3} minutes, 15:11–15:42 {Gbac1.4}")
        )


@pytest.mark.unit
def test_a_diffs_hunk_header_states_no_figure() -> None:
    # Where in a file a hunk sits is no figure of the incident's, and tagged it
    # is offered as one. A value the diff changed is - it can be the cause.
    Scenario() \
        .given(
            some_diff := SOME_DIFF
        ) \
        .when(
            lambda: the_evidence_figures([some_diff], DONT_CARE_DAY)
        ) \
        .then(
            the_answer_was({
                "D1.1": Figure(given="30", written="30"),
                "D1.2": Figure(given="5", written="5")
            })
        )


@pytest.mark.unit
def test_a_diff_is_shown_with_its_hunk_header_as_it_was_read() -> None:
    Scenario() \
        .given(
            some_diff := SOME_DIFF
        ) \
        .when(
            lambda: the_evidence_named(some_diff)
        ) \
        .then(
            the_answer_was("modified deploy/values-production.yaml\n"
                           "  @@ -12,7 +12,7 @@\n"
                           "  -  timeout: 30 {D1.1}\n"
                           "  +  timeout: 5 {D1.2}")
        )


@pytest.mark.unit
def test_a_day_said_beside_a_time_states_no_figure() -> None:
    # Read word by word, the day of the month was a figure of its own, offered
    # to the model as a number the incident gave. The time beside it is one -
    # here on the incident's own day, so written as a time of that day.
    Scenario() \
        .given(
            some_line := SOME_LINE_DATING_A_TIME
        ) \
        .when(
            lambda: the_narration_figures([some_line], SOME_MOMENT_ON_ANOTHER_DAY.date())
        ) \
        .then(
            the_answer_was({
                "T8.1": Figure(given="1", written="1"),
                "T8.2": Figure(given="20:31", written="20:31 UTC")
            })
        )


@pytest.mark.unit
def test_a_time_said_beside_another_day_than_the_incident_s_is_written_with_that_day() -> None:
    # Written as a bare time, "the replica restarts at 19:44:24" read as a
    # time of the onset's day, not of the day the line said. Shown to the
    # model as it was given: only how it is written in changes.
    Scenario() \
        .given(
            some_line := SOME_LINE_DATING_A_TIME
        ) \
        .when(
            lambda: the_narration_figures([some_line], ONSET.date())["T8.2"]
        ) \
        .then(
            the_answer_was(Figure(given="20:31", written="Oct 20, 20:31 UTC"))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("day", "written"), [
    (date(2028, 3, 1), "Feb 29, 10:00 UTC"),
    (date(2026, 3, 1), "10:00")
], ids=["a-leap-year-is-near", "no-leap-year-is-near"])
def test_a_time_said_beside_feb_29_is_read_in_the_leap_year_nearest_the_incident(
        day: date, written: str) -> None:
    # The day carries no year, so it is read in the year nearest the
    # incident's that has one. With none near, it is written as it was given.
    Scenario() \
        .given(
            some_line := CitedEvidence(label="T3", text="restarted Feb 29 10:00")
        ) \
        .when(
            lambda: the_narration_figures([some_line], day)["T3.1"]
        ) \
        .then(
            the_answer_was(Figure(given="10:00", written=written))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("text", "name", "written"), [
    ("2026-10-25T07:45:02Z Asked for the metrics, anchored on 07:44:29", "T4.2",
     "Oct 25, 07:44:29 UTC"),
    ("Asked for the metrics, anchored on 07:44:29", "T4.1", "07:44:29"),
    ("2026-10-25T07:45:02Z Logged 2026-10-24T23:59:00Z, anchored on 07:44:29", "T4.3",
     "Oct 25, 07:44:29 UTC")
], ids=["after-the-line-s-stamp", "with-no-stamp-before-it",
        "after-an-instant-it-quotes"])
def test_a_time_alone_is_on_the_day_of_the_stamp_its_line_opens_with(text: str, name: str,
                                                                      written: str) -> None:
    # A line of the narration says a time alone only on its own day, which its
    # stamp says. Written as a bare time, it read as a time of the onset's day.
    Scenario() \
        .given(
            some_line := CitedEvidence(label="T4", text=text)
        ) \
        .when(
            lambda: the_narration_figures([some_line], date(2026, 10, 18))[name]
        ) \
        .then(
            the_answer_was(Figure(given="07:44:29", written=written))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("text", "name"), [
    ("2026-10-25T07:45:02Z checkout retried, last at 07:44:29", "G1.2"),
    ("checkout retried Oct 25 07:44:29", "G1.1")
], ids=["after-an-instant-it-quotes", "beside-a-day-it-quotes"])
def test_a_time_in_words_argus_quotes_is_written_as_its_writer_gave_it(text: str,
                                                                       name: str) -> None:
    # A log line, a change's summary or a person's note is in its writer's
    # words, and Argus knows neither the day nor the zone of a time said in
    # one. Read on a day, it was written in as a time of UTC.
    Scenario() \
        .given(
            some_evidence := CitedEvidence(label="G1", text=text)
        ) \
        .when(
            lambda: the_evidence_figures([some_evidence], date(2026, 10, 18))[name]
        ) \
        .then(
            the_answer_was(Figure(given="07:44:29", written="07:44:29"))
        )


@pytest.mark.unit
def test_a_time_beside_a_day_in_the_alert_is_written_as_its_sender_gave_it() -> None:
    # The alert is in its sender's words, whose zone Argus does not know.
    Scenario() \
        .given(
            some_finding := "Totals stopped reconciling Oct 25 07:44:29."
        ) \
        .when(
            lambda: the_alerts_figures(some_finding, date(2026, 10, 18))
        ) \
        .then(
            the_answer_was({"A1": Figure(given="07:44:29", written="07:44:29")})
        )


@pytest.mark.unit
@pytest.mark.parametrize(("text", "quoted", "name", "written"), [
    ("Oct 12 00:05 ERROR retry scheduled for Oct 12 06:00", (13, 51), "G1.1",
     "Oct 12, 00:05 UTC"),
    ("Oct 12 00:05 ERROR retry scheduled for Oct 12 06:00", (13, 51), "G1.2", "06:00"),
    ("ERROR checkout - 2 occurrences in 3 minutes, Oct 12 00:05–00:07", (0, 14), "G1.3",
     "Oct 12, 00:05–00:07 UTC"),
    ("ERROR checkout - 2 occurrences in 3 minutes, 23:41–23:43", (0, 14), "G1.3",
     "23:41–23:43 UTC"),
    ("14:59 ERROR checkout", (6, 20), "G1.1", "14:59 UTC")
], ids=["argus-s-minute", "a-minute-the-message-says", "argus-s-span",
        "a-span-on-the-day-it-began", "a-minute-on-the-day-it-began"])
def test_a_log_group_s_own_minutes_are_read_on_their_day_and_its_message_as_given(
        text: str, quoted: tuple[int, int], name: str, written: str) -> None:
    # The minutes are Argus's, said from the lines' stamps in UTC; the message
    # is its writer's, whose day and zone Argus does not know. Written as a
    # bare time, a minute of the next day read as one of the onset's - and a
    # minute of the onset's day, said bare on its row, is a time of that day.
    Scenario() \
        .given(
            some_group := CitedEvidence(label="G1", text=text)
        ) \
        .when(
            lambda: the_log_group_figures([(some_group, quoted)], date(2026, 10, 11))[name]
        ) \
        .then(
            _written_in_as(written)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("value", "written"), [
    ("36.00%", "36%"),
    ("36.0%", "36%"),
    ("36.50%", "36.5%"),
    ("36.36%", "36.36%"),
    ("1.50ms", "1.5ms"),
    ("2300ms", "2300ms"),
    ("12.50", "12.50"),
    ("1.50M", "1.50M")
], ids=["zeros-only", "one-zero", "a-zero-after-a-digit", "no-zero", "a-unit-in-letters",
        "no-fraction", "no-unit", "a-magnitude"])
def test_a_measurement_a_log_group_says_is_written_without_the_zeros_ending_its_fraction(
        value: str, written: str) -> None:
    # The row says each value to as many places as the service logged it, and
    # the model reads it so. A reader handed "36.00%" reads a column of a
    # report. A number with no unit of measure, or with a magnitude, can be a
    # price, and money is read to two places: it is written as logged.
    message = "WARN io-shop: account page error rate at #% over the last minute"

    Scenario() \
        .given(
            some_group := CitedEvidence(
                label="G1",
                text=f"{message} - 2 occurrences in 2 minutes, 23:37–23:38; "
                     f"# was {value} to 40.25%")
        ) \
        .when(
            lambda: the_log_group_figures([(some_group, (0, len(message)))],
                                          date(2026, 10, 11))["G1.4"]
        ) \
        .then(
            the_answer_was(Figure(given=value, written=written))
        )


@pytest.mark.unit
def test_a_number_the_message_of_a_log_group_says_is_written_as_given() -> None:
    # The message is its writer's words, quoted.
    message = "WARN io-shop: account page error rate at 36.00% over the last minute"

    Scenario() \
        .given(
            some_group := CitedEvidence(label="G1",
                                        text=f"{message} - 1 occurrence in 1 minute, 23:37")
        ) \
        .when(
            lambda: the_log_group_figures([(some_group, (0, len(message)))],
                                          date(2026, 10, 11))["G1.1"]
        ) \
        .then(
            the_answer_was(Figure(given="36.00%", written="36.00%"))
        )


@pytest.mark.unit
def test_every_day_said_dates_each_time_the_page_writes_without_its_day() -> None:
    # Off the page no head dates the incident. Only a wire instant was dated,
    # so a time a line of the narration or a group of log lines gave stayed
    # bare; one written as given carries no zone, and stays as it is.
    Scenario() \
        .given(
            some_figures := {
                "T1.2": Figure(given="07:44:29", written="07:44:29 UTC"),
                "G1.3": Figure(given="21:35–21:39", written="21:35–21:39 UTC"),
                "A1": Figure(given="2026-10-11T16:10:00Z", written="16:10 UTC"),
                "G2.1": Figure(given="06:00", written="06:00"),
                "P1.1": Figure(given="2026-10-12T00:05:00Z", written="Oct 12, 00:05 UTC")
            }
        ) \
        .when(
            lambda: with_every_day_said(some_figures, date(2026, 10, 11))
        ) \
        .then(
            the_answer_was({
                "T1.2": Figure(given="07:44:29", written="Oct 11, 07:44:29 UTC"),
                "G1.3": Figure(given="21:35–21:39", written="Oct 11, 21:35–21:39 UTC"),
                "A1": Figure(given="2026-10-11T16:10:00Z", written="Oct 11, 16:10 UTC"),
                "G2.1": Figure(given="06:00", written="06:00"),
                "P1.1": Figure(given="2026-10-12T00:05:00Z", written="Oct 12, 00:05 UTC")
            })
        )


@pytest.mark.unit
def test_a_working_s_instant_is_dated_with_every_other_figure_off_the_page() -> None:
    # Worked out from the figures as the model was shown them, an instant
    # after the onset came out bare beside figures that said their day.
    some_figures = {
        BEGAN_FIGURE: Figure(given="2026-10-18T14:03:00Z", written="14:03 UTC"),
        HELD_FIGURE: Figure(given="2 hours", written="2 hours")
    }

    Scenario() \
        .given(
            an_answer_working_an_instant := SubmittedPostmortem(
                root_cause=f"It began at {{{BEGAN_FIGURE}}} and was held until "
                           f"{{{BEGAN_FIGURE} + {HELD_FIGURE}}}.")
        ) \
        .when(
            lambda: with_figures_written_with_every_day(an_answer_working_an_instant,
                                                        some_figures, date(2026, 10, 18))
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(
                root_cause="It began at Oct 18, 14:03 UTC and was held until Oct 18, 16:03 UTC."))
        )


@pytest.mark.unit
def test_a_line_dating_a_time_is_shown_with_its_day_as_it_was_said() -> None:
    Scenario() \
        .given(
            some_line := SOME_LINE_DATING_A_TIME
        ) \
        .when(
            lambda: the_evidence_named(some_line)
        ) \
        .then(
            the_answer_was("Asked for production change events, the 1 {T8.1} day before "
                           "Oct 20 20:31 {T8.2}")
        )


@pytest.mark.unit
def test_a_figure_named_after_a_piece_of_evidence_is_written_in() -> None:
    Scenario() \
        .given(
            an_answer_quoting_the_evidence := SubmittedPostmortem(
                root_cause="The pool ran out at {Gbac1.1} connections.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_quoting_the_evidence,
                                         the_evidence_figures([SOME_EVIDENCE], DONT_CARE_DAY))
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="The pool ran out at 20 connections."))
        )


@pytest.mark.unit
def test_a_span_said_in_days_and_hours_is_worked_with_in_full() -> None:
    # A span is shown in words, and worked with from them: a day or an hour
    # read as anything less would put the result out by as much.
    some_spans = {
        HELD_FIGURE: Figure(given="2 days 1 hour 30 minutes", written="dont care"),
        DURATION_FIGURE: Figure(given="1 hour 15 minutes 10 seconds", written="dont care")
    }

    Scenario() \
        .given(
            an_answer_naming_the_difference := SubmittedPostmortem(
                root_cause="It was held {held - duration} longer.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_naming_the_difference, some_spans)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(
                root_cause="It was held 2 days 14 minutes 50 seconds longer."))
        )


@pytest.mark.unit
def test_a_ratio_to_a_span_of_less_than_a_second_is_left_for_the_check() -> None:
    # Shown as "less than a second", it is nothing to divide by - and a
    # working with no result is the check's to send back, never a guess.
    some_spans = {
        HELD_FIGURE: Figure(given="30 minutes", written="dont care"),
        DURATION_FIGURE: Figure(given="less than a second", written="dont care")
    }

    Scenario() \
        .given(
            an_answer_dividing_by_it := SubmittedPostmortem(
                root_cause="It was held {held / duration} as long.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_dividing_by_it, some_spans)
        ) \
        .then(
            the_answer_was(an_answer_dividing_by_it)
        )


@pytest.mark.unit
def test_the_span_between_two_instants_the_evidence_states_is_written_in() -> None:
    # The model reached for the span between two lines of the narration and
    # was refused: an instant is one wherever it was shown.
    Scenario() \
        .given(
            figures := the_evidence_figures([
                CitedEvidence(label="T1", text="2026-09-02T12:00:00Z Investigator: dont care"),
                CitedEvidence(label="T2", text="2026-09-02T12:07:30Z Mitigation: dont care")],
                DONT_CARE_DAY),
            an_answer_working_from_the_narration := SubmittedPostmortem(
                root_cause="Mitigation began {T2.1 - T1.1} in.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_working_from_the_narration, figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(
                root_cause="Mitigation began 7 minutes 30 seconds in."))
        )


@pytest.mark.unit
def test_a_word_mixing_letters_and_digits_is_a_name_and_not_a_figure() -> None:
    # A pod, a revision, a label: what a reader searches for, written as given.
    Scenario() \
        .given(
            a_finding_naming_a_pod := "the pod io-shop-7d9c4f8b6-x2k9p restarted 3 times"
        ) \
        .when(
            lambda: the_alerts_figures(a_finding_naming_a_pod, DONT_CARE_DAY)
        ) \
        .then(
            the_answer_was({"A1": Figure(given="3", written="3")})
        )


@pytest.mark.unit
def test_the_figures_argus_measured_are_named_for_what_they_are() -> None:
    # Instants as a reader says one - a time, on the day the incident began -
    # spans in words, and to the second, because what is written in is the
    # measurement, not a rounding of it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident()
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            the_answer_was({
                ALERT_RAISED_FIGURE: Figure(given=to_iso(STARTED_AT), written="12:10 UTC"),
                BEGAN_FIGURE: Figure(given=to_iso(ONSET), written="12:00 UTC"),
                BACK_TO_NORMAL_FIGURE: Figure(given=to_iso(RECOVERED_AT), written="12:10 UTC"),
                DURATION_FIGURE: Figure(given="10 minutes", written="10 minutes"),
                HELD_FIGURE: Figure(given="30 minutes", written="30 minutes"),
                ARGUS_STOPPED_FIGURE: Figure(given=to_iso(ENDED_AT), written="12:30 UTC"),
                CUSTOMER_LOSS_FIGURE: Figure(given="500.00 USD", written="500.00 USD")
            })
        )


@pytest.mark.unit
def test_an_instant_argus_measured_on_another_day_than_the_incident_began_says_its_day() -> None:
    some_stop_past_midnight = ONSET + timedelta(hours=13)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(ended_at=some_stop_past_midnight),
            measured := a_measured_incident()
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                ARGUS_STOPPED_FIGURE: Figure(given=to_iso(some_stop_past_midnight),
                                             written="Sep 03, 01:00 UTC")
            })
        )


@pytest.mark.unit
def test_the_last_instant_is_named_for_argus_stopping_rather_than_the_incident_closing() -> None:
    # Named "closed", it sat beside the last instant of an escalated incident
    # too - one that had not closed, whose blind stretch was still running. The
    # name is what a recorded answer writes, so it is spelled out here rather
    # than read off the constant: renaming it is renaming what the model is
    # shown.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident()
        ) \
        .when(
            lambda: sorted(figures_of(evidence, measured))
        ) \
        .then(all_of(
            _includes("argus_stopped"),
            _leaves_out("closed")
        ))


@pytest.mark.unit
def test_an_incident_with_no_onset_is_dated_from_its_alert() -> None:
    # The figure is the one the incident is dated from either way, which is
    # why it is named for beginning rather than for the onset.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None),
            measured := a_measured_incident(onset_at=None)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                BEGAN_FIGURE: Figure(given=to_iso(STARTED_AT), written="12:10 UTC")
            })
        )


@pytest.mark.unit
def test_an_incident_with_no_onset_is_dated_from_its_sender_s_alert_not_its_opening() -> None:
    # The page's head dates such an incident by the alert as its sender dated
    # it. Dated here by the incident's opening instead, the two named different
    # days for an alert fired before midnight and delivered after it.
    some_alert_the_day_before = STARTED_AT - timedelta(hours=13)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, alerted_at=some_alert_the_day_before),
            measured := a_measured_incident(onset_at=None)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                BEGAN_FIGURE: Figure(given=to_iso(some_alert_the_day_before),
                                     written="23:10 UTC")
            })
        )


@pytest.mark.unit
def test_the_alert_is_raised_when_its_sender_says_it_fired() -> None:
    # Not when the incident opened: a sender holds an alert back before
    # delivering it.
    some_firing = STARTED_AT.replace(minute=8)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=some_firing),
            measured := a_measured_incident()
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                ALERT_RAISED_FIGURE: Figure(given=to_iso(some_firing), written="12:08 UTC")
            })
        )


@pytest.mark.unit
def test_a_recovery_nobody_saw_is_no_figure() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(back_to_normal_at=None)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(BACK_TO_NORMAL_FIGURE)
        )


@pytest.mark.unit
def test_how_long_the_paging_rule_waits_is_named_as_a_span() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(rule_waits=timedelta(minutes=5))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                RULE_WAITS_FIGURE: Figure(given="5 minutes", written="5 minutes")
            })
        )


@pytest.mark.unit
@pytest.mark.parametrize("rule_waits", [None, timedelta()], ids=["unread", "nothing"])
def test_a_wait_for_nothing_or_one_never_read_is_no_figure(rule_waits: timedelta | None) -> None:
    # A rule that fires at once is said in words, and a span of no time is no
    # figure to work with.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(rule_waits=rule_waits)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(RULE_WAITS_FIGURE)
        )


@pytest.mark.unit
def test_how_far_back_the_paging_rule_s_condition_looks_is_named_as_a_span() -> None:
    # How much of the time from the onset to the alert can be the condition's
    # own window filling. Told only that it may be some, a write-up was left to
    # find it in the alert's words and subtract it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(rule_waits=timedelta(0),
                                            rule_looks_back=timedelta(minutes=5))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                RULE_LOOKS_BACK_FIGURE: Figure(given="5 minutes", written="5 minutes")
            })
        )


@pytest.mark.unit
@pytest.mark.parametrize("rule_looks_back", [timedelta(0), None], ids=["no-range", "no-rule"])
def test_a_condition_looking_back_over_nothing_or_no_rule_at_all_is_no_figure(
        rule_looks_back: timedelta | None) -> None:
    # A check rather than a query over a range looks back over nothing, and a
    # span of no time is no figure to work with.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(rule_looks_back=rule_looks_back)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(RULE_LOOKS_BACK_FIGURE)
        )


@pytest.mark.unit
def test_how_long_the_alert_came_after_its_rule_s_wait_is_named_from_a_minute_up() -> None:
    # Told only that the wait is part of the gap, a write-up still called
    # detection slow, unable to see what was left of the gap after the wait:
    # the two figures it would have to work from take two operations.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=6, seconds=30)),
            measured := a_measured_incident(onset_at=ONSET, rule_waits=timedelta(minutes=5))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                AFTER_THE_WAIT_FIGURE: Figure(given="1 minute 30 seconds",
                                              written="1 minute 30 seconds")
            })
        )


@pytest.mark.unit
def test_a_rule_that_waits_for_nothing_still_names_how_long_after_the_onset_it_came() -> None:
    # A wait of nothing is still a wait the gap comes after. Told only that the
    # rule fires as soon as its condition holds, a write-up left 5m 53s from the
    # onset to the alert unweighed - and said nothing of detection at all.
    # Named for the onset rather than the wait: beside a sentence saying the
    # rule waits for nothing, a model citing {after_the_wait} cites a wait that
    # is not there.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=5, seconds=53)),
            measured := a_measured_incident(onset_at=ONSET, rule_waits=timedelta(0))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(all_of(
            _the_figures_include({
                ALERTED_AFTER_THE_ONSET_FIGURE: Figure(given="5 minutes 53 seconds",
                                                       written="5 minutes 53 seconds")
            }),
            _the_figures_leave_out(AFTER_THE_WAIT_FIGURE)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("alerted_after_the_onset", "onset_at"), [
    (timedelta(minutes=5, seconds=16), ONSET),
    (timedelta(minutes=4, seconds=51), ONSET),
    (timedelta(minutes=6, seconds=30), None)
], ids=["under-a-minute", "sooner-than-the-wait", "no-measured-onset"])
def test_what_came_after_the_wait_is_no_figure_below_a_minute_or_without_an_onset(
        alerted_after_the_onset: timedelta, onset_at: datetime | None) -> None:
    # A measured onset is a whole minute, so less than one after the wait is
    # inside what the onset can tell - a lag named in seconds nobody measured.
    # Sooner than the wait, the condition held before the onset, which is said
    # in words; and with no onset measured there is no gap to take it from.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + alerted_after_the_onset),
            measured := a_measured_incident(onset_at=onset_at, rule_waits=timedelta(minutes=5))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(AFTER_THE_WAIT_FIGURE)
        )


@pytest.mark.unit
def test_what_came_after_the_wait_is_worked_with_as_a_span() -> None:
    Scenario() \
        .given(
            figures := figures_of(
                an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=6, seconds=30)),
                a_measured_incident(onset_at=ONSET, rule_waits=timedelta(minutes=5))),
            an_answer_adding_the_two := SubmittedPostmortem(
                root_cause=f"It paged {{{RULE_WAITS_FIGURE} + {AFTER_THE_WAIT_FIGURE}}} in.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_adding_the_two, figures)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="It paged 6 minutes 30 seconds in."))
        )


@pytest.mark.unit
def test_a_service_back_before_the_action_credited_with_it_names_when_it_was_taken() -> None:
    # The write-up says the service was back before the action, and a time it
    # cannot name is one it cannot say.
    some_action_taken = STARTED_AT.replace(minute=9)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("dont care", verdict=Verdict.CONFIRMED, taken_at=some_action_taken)]),
            measured := a_measured_incident(back_before_the_action=True)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                ACTED_FIGURE: Figure(given=to_iso(some_action_taken), written="12:09 UTC")
            })
        )


@pytest.mark.unit
def test_a_service_back_after_the_action_credited_with_it_names_no_time_it_was_taken() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("dont care", verdict=Verdict.CONFIRMED)]),
            measured := a_measured_incident(back_before_the_action=False)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(ACTED_FIGURE)
        )


@pytest.mark.unit
def test_a_post_where_nobody_was_paged_is_named_when_the_platform_accepted_it() -> None:
    # The write-up is told Argus posted, by this name, where nobody was paged -
    # the incident a write-up said nobody was told about.
    some_post = FirstTold(channel=ReportChannel.SLACK, at=STARTED_AT + timedelta(seconds=2))

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"first_told": some_post}),
            measured := a_measured_incident().model_copy(update={"engaged": NotPaged()})
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                FIRST_TOLD_FIGURE: Figure(given=to_iso(some_post.at), written="12:10:02 UTC")
            })
        )


@pytest.mark.unit
@pytest.mark.parametrize("engaged", [EngagementAnswer(minutes=0, responders=0), None],
                         ids=["somebody-paged", "unread"])
def test_a_post_where_nobody_is_known_unpaged_is_not_named(
        engaged: EngagementAnswer | None) -> None:
    # Only where it is said, and it is said only beside nobody paged.
    dont_care_post = FirstTold(channel=ReportChannel.SLACK, at=STARTED_AT)

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"first_told": dont_care_post}),
            measured := a_measured_incident().model_copy(update={"engaged": engaged})
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(FIRST_TOLD_FIGURE)
        )


@pytest.mark.unit
def test_an_incident_argus_never_posted_about_names_no_post() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident().model_copy(update={"engaged": NotPaged()})
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(FIRST_TOLD_FIGURE)
        )


@pytest.mark.unit
def test_metrics_that_stopped_are_dated_from_where_they_stopped() -> None:
    some_minute_they_stopped = ONSET

    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(back_to_normal_at=None,
                                            metrics_stopped_at=some_minute_they_stopped)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                METRICS_STOPPED_AT_FIGURE: Figure(given=to_iso(some_minute_they_stopped),
                                               written="12:00 UTC")
            })
        )


@pytest.mark.unit
def test_how_far_the_logs_read_reach_into_a_metrics_gap_is_a_figure() -> None:
    # A figure rather than the logs' own spans, so a write-up saying nothing is
    # known after the onset contradicts an instant it was handed by name.
    some_minute_logged_inside = ONSET + timedelta(minutes=5)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[
                f"{to_iso(some_minute_logged_inside)} WARN io-shop: some warning"]),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                LOGS_REACH_UNTIL_FIGURE: Figure(given=to_iso(some_minute_logged_inside),
                                                written="12:05 UTC")
            })
        )


@pytest.mark.unit
def test_a_metrics_gap_no_log_line_reaches_into_names_no_reach() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[
                f"{to_iso(ONSET - timedelta(minutes=10))} WARN io-shop: some warning"]),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(LOGS_REACH_UNTIL_FIGURE)
        )


@pytest.mark.unit
def test_where_the_reading_of_the_logs_ended_is_a_figure_beside_a_metrics_gap() -> None:
    # Where the lines stop inside the gap is where the reading stopped as often
    # as where the service did. Told only how far the lines reach, a model
    # wrote that nothing was known of the shop after them - of minutes nobody
    # had read.
    some_end_of_the_reading = ONSET + timedelta(minutes=5, seconds=53)

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(
                update={"log_reading_ended": some_end_of_the_reading}),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                LOG_READING_ENDED_FIGURE: Figure(given=to_iso(some_end_of_the_reading),
                                                 written="12:05:53 UTC")
            })
        )


@pytest.mark.unit
@pytest.mark.parametrize(("log_reading_ended", "metrics_stopped_at"), [    (None, ONSET),
    (ONSET + timedelta(minutes=5), None)
], ids=["no-reading-recorded", "no-metrics-gap"])
def test_where_the_reading_of_the_logs_ended_is_no_figure_without_a_reading_and_a_gap(
        log_reading_ended: datetime | None, metrics_stopped_at: datetime | None) -> None:
    # Only beside a gap, where how far the lines reach is said: elsewhere the
    # metrics say how the service was doing, and the end of a read says nothing.
    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(
                update={"log_reading_ended": log_reading_ended}),
            measured := a_measured_incident(metrics_stopped_at=metrics_stopped_at)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(LOG_READING_ENDED_FIGURE)
        )


@pytest.mark.unit
def test_the_customer_loss_is_a_figure_to_the_cent_in_its_currency() -> None:
    # Argus's one direct measure of who the incident affected, and the page
    # says it; a write-up never told it said only that the shop "appears to
    # have kept serving". To the cent and half up, as the page says it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(loss=Decimal("1297.315"))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                CUSTOMER_LOSS_FIGURE: Figure(given="1,297.32 USD", written="1,297.32 USD")
            })
        )


@pytest.mark.unit
@pytest.mark.parametrize(("loss", "baseline_revenue"), [
    (Decimal(0), Decimal("1000")),
    (None, None)
], ids=["none-lost", "not-estimated"])
def test_a_customer_loss_of_nothing_or_none_estimated_is_no_figure(
        loss: Decimal | None, baseline_revenue: Decimal | None) -> None:
    # Each is said in words: "0.00 USD" reads as a figure nobody filled in,
    # and an estimate nobody made has no figure to name.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(loss=loss, baseline_revenue=baseline_revenue)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(CUSTOMER_LOSS_FIGURE)
        )


@pytest.mark.unit
def test_the_error_rates_are_named_at_every_level_worth_reporting() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                error_rates=ErrorRates(baseline=0.015, while_broken=0.338, at_its_worst=0.5,
                                       usual_ceiling=0.02, usual_worst=0.04))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                ERRORS_BEFORE_FIGURE: Figure(given="1.5%", written="1.5%"),
                ERRORS_WHILE_BROKEN_FIGURE: Figure(given="33.8%", written="33.8%"),
                ERRORS_AT_WORST_FIGURE: Figure(given="50.0%", written="50.0%"),
                ERRORS_RISE_FIGURE: Figure(given="32.3%", written="32.3%")
            })
        )


@pytest.mark.unit
@pytest.mark.parametrize(("while_broken", "usual_ceiling"), [
    pytest.param(0.017, 0.025, id="fell"),
    pytest.param(0.02, 0.025, id="flat"),
    pytest.param(0.022, 0.025, id="within-its-variation"),
    pytest.param(0.30, None, id="variation-unknown")
])
def test_a_rise_not_beyond_the_rate_s_own_variation_is_no_figure(
    while_broken: float, usual_ceiling: float | None
) -> None:
    # The model is told there was none, or none it can tell from noise, in
    # words - and a name for the difference would let it write a rise anyway.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                error_rates=ErrorRates(baseline=0.02, while_broken=while_broken,
                                       at_its_worst=0.03,
                                       usual_ceiling=usual_ceiling, usual_worst=None))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(ERRORS_RISE_FIGURE)
        )


@pytest.mark.unit
def test_error_rates_nobody_measured_are_no_figures() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(error_rates=None)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_leave_out(ERRORS_BEFORE_FIGURE, ERRORS_WHILE_BROKEN_FIGURE,
                                   ERRORS_AT_WORST_FIGURE, ERRORS_RISE_FIGURE)
        )


@pytest.mark.unit
def test_the_paging_rules_series_is_named_at_its_three_levels() -> None:
    # Plain numbers, in whatever unit the rule watches.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=0.92, while_broken=0.41,
                                             at_its_worst=0.12, worse_when="below"))
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                SERIES_BEFORE_FIGURE: Figure(given="0.92", written="0.92"),
                SERIES_WHILE_BROKEN_FIGURE: Figure(given="0.41", written="0.41"),
                SERIES_AT_WORST_FIGURE: Figure(given="0.12", written="0.12")
            })
        )


@pytest.mark.unit
@pytest.mark.parametrize(("level", "given", "written"), [
    (0.594083, "0.594083", "0.594"),
    (0.000123456, "0.000123456", "0.000123"),
    (0.92, "0.92", "0.92"),
    (1234.5, "1234.5", "1235"),
    (0.5943428571, "0.5943428571", "0.594")
], ids=["a-ratio", "a-small-one", "already-short", "a-whole-number-and-a-half",
        "a-mean-of-several-minutes"])
def test_a_level_is_written_as_a_person_says_it_and_given_as_measured(
        level: float, given: str, written: str) -> None:
    # Six places of a ratio read as a precision nobody measured it to: three
    # figures are what a reader compares two levels by - and never fewer than
    # a whole number has, since "1230" reads as an exact count. The model is
    # given the level as measured, and a working is worked from that.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=level, while_broken=0.41,
                                             at_its_worst=0.12, worse_when="below"))
        ) \
        .when(
            lambda: figures_of(evidence, measured)[SERIES_BEFORE_FIGURE]
        ) \
        .then(
            the_answer_was(Figure(given=given, written=written))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("unit", "level", "given", "written"), [
    ("ms", 600.0, "600 ms", "600 ms"),
    ("percentunit", 0.899, "89.9%", "89.9%"),
    ("percentunit", 0.4456789, "44.56789%", "44.6%")
], ids=["milliseconds", "a-share-of-one", "a-share-given-exactly-and-written-short"])
def test_the_paging_rules_series_is_given_and_written_in_its_unit(
        unit: str, level: float, given: str, written: str) -> None:
    # Beside an alert saying "below 80%", a series written 0.899 is a second
    # scale on one page. In its unit, and given exactly: a share of one moves
    # its point and keeps every digit it was measured to.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=level, while_broken=0.41,
                                             at_its_worst=0.12, worse_when="below"),
                rule_series_unit=unit)
        ) \
        .when(
            lambda: figures_of(evidence, measured)[SERIES_BEFORE_FIGURE]
        ) \
        .then(
            the_answer_was(Figure(given=given, written=written))
        )


@pytest.mark.unit
def test_a_series_that_is_the_error_rate_is_written_as_the_error_rate_is() -> None:
    # The summary said the error rate before the onset was 1.0%, and the cause
    # citing the rule's series - the same rate - said 1.02%. Written the error
    # rate's way, the two are one figure; given exactly, the model loses nothing.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=0.0102, while_broken=0.284,
                                             at_its_worst=0.355, worse_when="above"),
                rule_series_unit="percentunit",
                rule_series_is_the_error_rate=True)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                SERIES_BEFORE_FIGURE: Figure(given="1.02%", written="1.0%"),
                SERIES_WHILE_BROKEN_FIGURE: Figure(given="28.4%", written="28.4%"),
                SERIES_AT_WORST_FIGURE: Figure(given="35.5%", written="35.5%")
            })
        )


@pytest.mark.unit
def test_the_alerts_figures_are_among_the_incidents() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"alert_finding": SOME_FINDING}),
            measured := a_measured_incident()
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include(the_alerts_figures(SOME_FINDING, ONSET.date()))
        )


def _includes(name: str) -> Assertion[list[str]]:
    def assertion(names: list[str]) -> bool:
        if name not in names:
            raise AssertionError(f"Expected a figure named [{name}], got {names}.")

        return True

    return assertion


def _leaves_out(name: str) -> Assertion[list[str]]:
    def assertion(names: list[str]) -> bool:
        if name in names:
            raise AssertionError(f"Expected no figure named [{name}], got {names}.")

        return True

    return assertion


def _the_figures_include(expected: Mapping[str, Figure]) -> Assertion[Mapping[str, Figure]]:
    def assertion(figures: Mapping[str, Figure]) -> bool:
        return all_of(*(_the_figure_named(name, figure) for name, figure in expected.items()))(
            figures)

    return assertion


def _the_figure_named(name: str, expected: Figure) -> Assertion[Mapping[str, Figure]]:
    def assertion(figures: Mapping[str, Figure]) -> bool:
        if figures.get(name) != expected:
            raise AssertionError(
                f"Expected the figure named [{name}] to be {expected!r}, and it was "
                f"{figures.get(name)!r}."
            )

        return True

    return assertion


def _the_figures_leave_out(*names: str) -> Assertion[Mapping[str, Figure]]:
    def assertion(figures: Mapping[str, Figure]) -> bool:
        named_anyway = [name for name in names if name in figures]

        if named_anyway:
            raise AssertionError(
                f"Expected no figure named {list(names)}, and these were named: "
                f"{named_anyway}."
            )

        return True

    return assertion


def _an_answer_saying_everywhere(said: str) -> SubmittedPostmortem:
    """An answer saying one sentence in every field it would publish."""
    return SubmittedPostmortem(
        root_cause=said,
        cause_in_plain_words=said,
        still_at_risk=said,
        symptom=said,
        assumptions=[said],
        lead_effects={"L1": said},
        causal_chain=[SubmittedStep(step=said, cites=["T1"])],
        contributing_factors=[SubmittedFactor(factor=said, addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item=said, type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=[said], went_wrong=[said], got_lucky=[said])
    )


def _written_in_as(expected: str) -> Assertion[Figure]:
    def assertion(figure: Figure) -> bool:
        if figure.written != expected:
            raise AssertionError(f"Expected the figure written in as [{expected}], and it was "
                                 f"[{figure.written}].")

        return True

    return assertion
