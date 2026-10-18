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
from datetime import timedelta

import pytest
from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels
from agent_postmortem.figures import (
    ACTED_FIGURE,
    ALERT_RAISED_FIGURE,
    BACK_TO_NORMAL_FIGURE,
    BEGAN_FIGURE,
    CLOSED_FIGURE,
    DURATION_FIGURE,
    ERRORS_AT_WORST_FIGURE,
    ERRORS_BEFORE_FIGURE,
    ERRORS_RISE_FIGURE,
    ERRORS_WHILE_BROKEN_FIGURE,
    HELD_FIGURE,
    RULE_WAITS_FIGURE,
    SERIES_AT_WORST_FIGURE,
    SERIES_BEFORE_FIGURE,
    SERIES_WHILE_BROKEN_FIGURE,
    UNOBSERVED_FROM_FIGURE,
    Figure,
    figures_of,
    named,
    names_in,
    the_alerts_figures,
    the_evidence_figures,
    the_evidence_named,
    the_finding_named,
    with_figures_written,
)
from agent_postmortem.prompting import (
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedStep,
)
from argus_core import to_iso
from argus_core.models import ActionItemType, CitedEvidence, Lessons, Verdict
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

# A log group as the model reads it: a setting, a count, a span and the minutes
# it covers.
SOME_EVIDENCE = CitedEvidence(
    label="Gbac1",
    text="pool exhausted at 20 connections - 29 occurrences in 32 minutes, 15:11–15:42")


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
    ("{began + duration}", "Sep 02, 2026, 12:10:00 UTC"),
    ("{closed - held}", "Sep 02, 2026, 12:00:00 UTC"),
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
                                  written="Oct 05, 2026, 16:10:00 UTC")
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
            lambda: the_alerts_figures(some_finding)
        ) \
        .then(
            the_answer_was({
                "A1": Figure(given="240", written="240"),
                "A2": Figure(given="240", written="240"),
                "A3": Figure(given="1,297.31", written="1,297.31"),
                "A4": Figure(given="2026-10-05T16:10:00Z", written="Oct 05, 2026, 16:10:00 UTC")
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
            lambda: the_evidence_figures([some_evidence])
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
def test_a_figure_named_after_a_piece_of_evidence_is_written_in() -> None:
    Scenario() \
        .given(
            an_answer_quoting_the_evidence := SubmittedPostmortem(
                root_cause="The pool ran out at {Gbac1.1} connections.")
        ) \
        .when(
            lambda: with_figures_written(an_answer_quoting_the_evidence,
                                         the_evidence_figures([SOME_EVIDENCE]))
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
    # working with no result is the check's to put back, never a guess.
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
                CitedEvidence(label="T2", text="2026-09-02T12:07:30Z Mitigation: dont care")]),
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
            lambda: the_alerts_figures(a_finding_naming_a_pod)
        ) \
        .then(
            the_answer_was({"A1": Figure(given="3", written="3")})
        )


@pytest.mark.unit
def test_the_figures_argus_measured_are_named_for_what_they_are() -> None:
    # Instants as a reader says one, spans in words - and to the second,
    # because what is written in is the measurement, not a rounding of it.
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
                ALERT_RAISED_FIGURE: Figure(given=to_iso(STARTED_AT),
                                            written="Sep 02, 2026, 12:10:00 UTC"),
                BEGAN_FIGURE: Figure(given=to_iso(ONSET), written="Sep 02, 2026, 12:00:00 UTC"),
                BACK_TO_NORMAL_FIGURE: Figure(given=to_iso(RECOVERED_AT),
                                         written="Sep 02, 2026, 12:10:00 UTC"),
                DURATION_FIGURE: Figure(given="10 minutes", written="10 minutes"),
                HELD_FIGURE: Figure(given="30 minutes", written="30 minutes"),
                CLOSED_FIGURE: Figure(given=to_iso(ENDED_AT), written="Sep 02, 2026, 12:30:00 UTC")
            })
        )


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
                BEGAN_FIGURE: Figure(given=to_iso(STARTED_AT), written="Sep 02, 2026, 12:10:00 UTC")
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
                ALERT_RAISED_FIGURE: Figure(given=to_iso(some_firing),
                                            written="Sep 02, 2026, 12:08:00 UTC")
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
                ACTED_FIGURE: Figure(given=to_iso(some_action_taken),
                                     written="Sep 02, 2026, 12:09:00 UTC")
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
def test_metrics_that_stopped_are_dated_from_where_they_stopped() -> None:
    some_minute_they_stopped = ONSET

    Scenario() \
        .given(
            evidence := an_evidence_bundle(),
            measured := a_measured_incident(back_to_normal_at=None,
                                            unobserved_from=some_minute_they_stopped)
        ) \
        .when(
            lambda: figures_of(evidence, measured)
        ) \
        .then(
            _the_figures_include({
                UNOBSERVED_FROM_FIGURE: Figure(given=to_iso(some_minute_they_stopped),
                                               written="Sep 02, 2026, 12:00:00 UTC")
            })
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
            _the_figures_include(the_alerts_figures(SOME_FINDING))
        )


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
        executive_summary=said,
        symptom=said,
        assumptions=[said],
        lead_effects={"L1": said},
        causal_chain=[SubmittedStep(step=said, cites=["T1"])],
        contributing_factors=[SubmittedFactor(factor=said, addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item=said, type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=[said], went_wrong=[said], got_lucky=[said])
    )
