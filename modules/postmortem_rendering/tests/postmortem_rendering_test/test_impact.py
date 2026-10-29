"""How bad it was: one card per figure, the figure first, and what the alert
found where the damage is not a rate.

Each case is one postmortem and what a card, the finding or the note says.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from argus_core.models import (
    AlarmClaim,
    Alert,
    CitedEvidence,
    Detection,
    ErrorRateLevels,
    Impact,
    ImpactExtent,
    LogsInTheGap,
    RuleSeriesBeforeTheAlert,
    RuleSeriesHarm,
    WorseWhen,
)
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from postmortem_rendering.impact import Card, the_impact
from postmortem_rendering.lines import Line, Role

from postmortem_rendering_test.framework.builders import a_postmortem, an_alert

SOME_MINUTE = datetime(2026, 10, 21, 19, 12, tzinfo=UTC)


@pytest.mark.unit
def test_a_measured_incident_shows_its_four_figures_each_beside_what_it_is() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=29), extent=ImpactExtent.MEASURED,
                              peak_error_rate=0.339, requests_failed=4210),
                customer_loss_estimate=Decimal("1736.68485900091116011163646"),
                estimate_currency="usd")
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards
        ) \
        .then(
            the_answer_was((Card(value="29m 0s", label="onset until back to normal"),
                            Card(value="33.9%", label="peak error rate"),
                            Card(value="4,210", label="requests failed"),
                            Card(value="1,736.68 USD", label="customer loss (estimated)",
                                 loss_is="measured"))))


@pytest.mark.unit
def test_nothing_measured_says_so_on_every_card() -> None:
    # Absence is said, never shown as a zero: a reader must not have to guess
    # whether nothing was lost or nothing was known. The rate and the count as
    # what the metrics did not measure: the service's own logs may well have.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(impact=None, customer_loss_estimate=None)
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards
        ) \
        .then(
            _the_values_are("not measured", "not measured by the metrics",
                            "not counted by the metrics", "not estimated"))


@pytest.mark.unit
def test_an_incident_that_never_ended_is_at_least_as_long_and_lost_at_least_as_much() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=40), extent=ImpactExtent.AT_LEAST,
                              peak_error_rate=None),
                customer_loss_estimate=Decimal("500"),
                estimate_currency="usd")
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards
        ) \
        .then(
            _the_values_are("at least 40m 0s", "not measured by the metrics",
                            "not counted by the metrics", "at least 500.00 USD"))


@pytest.mark.unit
@pytest.mark.parametrize(("extent", "expected"), [
    (ImpactExtent.MEASURED, Card(value="40m 0s", label="onset until back to normal")),
    (ImpactExtent.REPORTED, Card(value="40m 0s", label="onset until reported resolved")),
    (ImpactExtent.AT_LEAST, Card(value="at least 40m 0s",
                                 label="since onset, still not back to normal")),
    (ImpactExtent.METRICS_MISSING, Card(value="at least 40m 0s",
                                        label="since onset, metrics missing")),
    (ImpactExtent.DISPROVEN, Card(value="none", label="the alarm was disproven"))],
    ids=["measured", "reported", "at-least", "metrics-missing", "disproven"])
def test_the_duration_says_where_it_ends(extent: ImpactExtent, expected: Card) -> None:
    # Labelled "until back to normal", a duration that never got back names an
    # end the incident never had - and a blind spell still going when the
    # incident closed is no more over than a failure still going. An end a
    # person reported is theirs: back to normal is the metrics showing it.
    # And of a disproven alarm there was no stretch to end.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=40), extent=extent,
                              peak_error_rate=None))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards[0]
        ) \
        .then(
            the_answer_was(expected))


@pytest.mark.unit
def test_a_disproven_alarm_shows_there_was_none_and_the_minutes_its_claim_was_judged_on() -> None:
    # No failure rate, count or loss: of an incident that never happened they
    # read as figures nobody measured. In their place, what the rule's series
    # read over the minutes the alarm claimed its condition held in, beside its
    # line - the grounds of the disproof, which a reader otherwise takes on
    # trust - said as the series' card of harm says a level.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(0), extent=ImpactExtent.DISPROVEN,
                              peak_error_rate=None,
                              before_the_alert=RuleSeriesBeforeTheAlert(
                                  lowest=0.0, highest=0.015, first_minute=SOME_MINUTE,
                                  last_minute=SOME_MINUTE + timedelta(minutes=6), line=0.1,
                                  unit="percentunit", is_the_error_rate=True)))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards
        ) \
        .then(
            the_answer_was((Card(value="none", label="the alarm was disproven"),
                            Card(value="0.0% to 1.5%",
                                 label="what the alert watches, 19:12 to 19:18",
                                 note="the rule's line is 10%"))))


@pytest.mark.unit
def test_a_disproven_alarm_whose_rules_series_went_unread_says_only_that_there_was_none(
) -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(0), extent=ImpactExtent.DISPROVEN,
                              peak_error_rate=None))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards
        ) \
        .then(
            the_answer_was((Card(value="none", label="the alarm was disproven"),)))


@pytest.mark.unit
def test_a_loss_counted_to_a_persons_report_is_no_lower_bound() -> None:
    # Their report is the end (spec §16), and the takings were counted to it.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=40), extent=ImpactExtent.REPORTED,
                              peak_error_rate=None),
                customer_loss_estimate=Decimal("500"),
                estimate_currency="usd")
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards[3]
        ) \
        .then(
            the_answer_was(Card(value="500.00 USD", label="customer loss (estimated)",
                                loss_is="measured")))


@pytest.mark.unit
def test_a_lower_bound_on_the_loss_is_said_to_be_one() -> None:
    # For a destination that marks it: the page tags the card with which it is.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=40), extent=ImpactExtent.METRICS_MISSING,
                              peak_error_rate=None),
                customer_loss_estimate=Decimal("500"),
                estimate_currency="usd")
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards[3].loss_is
        ) \
        .then(
            the_answer_was("a lower bound"))


@pytest.mark.unit
def test_no_loss_is_said_as_none_rather_than_as_an_amount() -> None:
    # "0.00" is true and reads as a figure nobody filled in.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=9), extent=ImpactExtent.MEASURED,
                              peak_error_rate=0.1),
                customer_loss_estimate=Decimal("0"),
                estimate_currency="usd")
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards[3].value
        ) \
        .then(
            the_answer_was("none"))


@pytest.mark.unit
def test_no_loss_yet_from_an_incident_still_going_is_none_so_far() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=9), extent=ImpactExtent.AT_LEAST,
                              peak_error_rate=0.1),
                customer_loss_estimate=Decimal("0"),
                estimate_currency="usd")
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards[3].value
        ) \
        .then(
            the_answer_was("none so far"))


@pytest.mark.unit
def test_what_the_alert_found_is_said_beside_the_cards() -> None:
    # Where the damage is not a rate - totals written wrong rather than
    # requests failed - this is the one measurement there is.
    Scenario() \
        .given(
            some_alert := Alert(alert_name="dont care", service="dont care",
                                summary="212 order totals disagree with their items",
                                claim=AlarmClaim.ITS_OWN_FINDING)
        ) \
        .when(
            lambda: the_impact(a_postmortem(), some_alert).finding
        ) \
        .then(
            the_answer_was("What the alert found: 212 order totals disagree with their items"))


@pytest.mark.unit
def test_what_the_alert_found_is_under_the_label_it_is_cited_by() -> None:
    # Said here alone, so a citation of what the alert said leads here.
    some_finding = "212 order totals disagree with their items"

    Scenario() \
        .given(
            some_postmortem := a_postmortem(detection=Detection(
                alerted_at=datetime(2026, 10, 11, 14, 5, tzinfo=UTC), rule="dont care",
                onset_at=None, gap=None,
                said=CitedEvidence(label="AL1", text=some_finding)))
        ) \
        .when(
            lambda: the_impact(some_postmortem,
                               Alert(alert_name="dont care", service="dont care",
                                     summary=some_finding,
                                     claim=AlarmClaim.ITS_OWN_FINDING)).finding_label
        ) \
        .then(
            the_answer_was("AL1"))


@pytest.mark.unit
def test_an_alert_that_found_nothing_in_words_adds_no_finding() -> None:
    Scenario() \
        .given(
            some_alert := Alert(alert_name="dont care", service="dont care", summary=None)
        ) \
        .when(
            lambda: the_impact(a_postmortem(), some_alert).finding
        ) \
        .then(
            the_answer_was(None))


@pytest.mark.unit
def test_a_rules_condition_is_no_finding_and_is_left_to_what_the_alert_said() -> None:
    # A rule watching a series says what it pages on, not what it found: under
    # "found" it reads as a measurement of this incident. What it found is the
    # series' own card, and its words are the row of what the alert said.
    Scenario() \
        .given(
            some_alert := Alert(alert_name="dont care", service="dont care",
                                summary="confidently below 80% for 5m",
                                claim=AlarmClaim.A_SERIES_CONDITION)
        ) \
        .when(
            lambda: the_impact(a_postmortem(), some_alert).finding
        ) \
        .then(
            the_answer_was(None))


@pytest.mark.unit
def test_an_incident_whose_metrics_stopped_says_what_its_duration_measures() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=40), extent=ImpactExtent.METRICS_MISSING,
                              peak_error_rate=None))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).metrics_missing
        ) \
        .then(
            the_answer_was("The metrics stop at the onset, so the duration is how long they had "
                           "been missing by the close - not a stretch the service is known to "
                           "have spent broken."))


@pytest.mark.unit
def test_the_logs_reaching_into_the_stretch_the_metrics_missed_are_named_with_how_far() -> None:
    # Impact said what the metrics did not measure and never that the shop's
    # own logs measured it through the gap - the strongest evidence of how it
    # was doing there, given in the cause and nowhere in Impact. How far, said
    # once, and where the reading of them ended: where the lines stop is as
    # often where the reading did.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(impact=_metrics_missing(LogsInTheGap(
                read=True, labels=["G46bc", "Gbac1"], reach_until=SOME_MINUTE,
                read_until=SOME_MINUTE + timedelta(seconds=55), read_until_the_alert=True)))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).logs_in_the_gap
        ) \
        .then(all_of(
            _the_note_reads("The service's own logs reach into the stretch the metrics missed "
                            "until Oct 21, 2026, 19:12 UTC: G46bc, Gbac1. They were read up to "
                            "Oct 21, 2026, 19:12:55 UTC, when the alert was raised."),
            _the_note_cites("G46bc", "Gbac1")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("serving_as_before", "said"), [
    (True, "As far as they show, the service went on serving as it had before the metrics "
           "stopped."),
    (False, "They do not show the service serving as it had before the metrics stopped.")
], ids=["serving-as-before", "not-as-before"])
def test_whether_the_logs_show_the_service_serving_as_before_follows_how_far_they_reach(
        serving_as_before: bool, said: str) -> None:
    # Said by the document rather than by the model: told to bound the claim, a
    # write-up bounded it in one sentence and said it unbounded in the next.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(impact=_metrics_missing(LogsInTheGap(
                read=True, labels=["G46bc"], reach_until=SOME_MINUTE,
                read_until=SOME_MINUTE + timedelta(seconds=55), read_until_the_alert=True,
                serving_as_before=serving_as_before)))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).logs_in_the_gap
        ) \
        .then(
            _the_note_reads("The service's own logs reach into the stretch the metrics missed "
                            "until Oct 21, 2026, 19:12 UTC: G46bc. They were read up to "
                            f"Oct 21, 2026, 19:12:55 UTC, when the alert was raised. {said}")
        )


@pytest.mark.unit
def test_logs_reaching_as_far_as_they_were_read_say_the_instant_once() -> None:
    # Said twice - "until 08:28 UTC: G46bc. They were read up to 08:28 UTC." -
    # one instant reads as two facts, as it did in the summary.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(impact=_metrics_missing(LogsInTheGap(
                read=True, labels=["G46bc"], reach_until=SOME_MINUTE, read_until=SOME_MINUTE,
                read_until_the_alert=True)))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).logs_in_the_gap
        ) \
        .then(
            _the_note_reads("The service's own logs reach into the stretch the metrics missed "
                            "until Oct 21, 2026, 19:12 UTC: G46bc. They were read up to then, "
                            "when the alert was raised.")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("logs", "said"), [
    (LogsInTheGap(read=True, labels=[], reach_until=None, read_until=SOME_MINUTE,
                  read_until_the_alert=False),
     "No log line read reaches into the stretch the metrics missed. The logs were read up to "
     "Oct 21, 2026, 19:12 UTC."),
    (LogsInTheGap(read=False, labels=[], reach_until=None, read_until=None,
                  read_until_the_alert=False),
     "No logs were read.")
], ids=["none-reaching-in", "none-read"])
def test_logs_that_show_nothing_of_the_stretch_the_metrics_missed_say_so(logs: LogsInTheGap,
                                                                         said: str) -> None:
    # Said rather than left out: a note silent on the logs reads the same as
    # one whose logs nobody looked at.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(impact=_metrics_missing(logs))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).logs_in_the_gap
        ) \
        .then(
            _the_note_reads(said)
        )


@pytest.mark.unit
def test_an_incident_whose_metrics_never_stopped_says_nothing_of_logs_in_a_gap() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=9), extent=ImpactExtent.MEASURED,
                              peak_error_rate=None))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).logs_in_the_gap
        ) \
        .then(
            the_answer_was(None))


@pytest.mark.unit
def test_a_measured_incident_carries_no_note_on_its_duration() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=9), extent=ImpactExtent.MEASURED,
                              peak_error_rate=None))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).metrics_missing
        ) \
        .then(
            the_answer_was(None))


@pytest.mark.unit
def test_an_error_rate_that_rose_is_shown_at_its_peak_and_in_requests_failed() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=29), extent=ImpactExtent.MEASURED,
                              peak_error_rate=0.339, requests_failed=4210,
                              error_rates=ErrorRateLevels(before=0.01, while_broken=0.3,
                                                          rose=True)),
                customer_loss_estimate=None)
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards
        ) \
        .then(
            _the_values_are("29m 0s", "33.9%", "4,210", "not estimated"))


@pytest.mark.unit
def test_an_error_rate_that_did_not_rise_is_one_card_saying_so() -> None:
    # Failed requests that did not rise are no harm, and a count of them under
    # Impact reads as one - 72 requests failing at the rate they always do.
    # Left off instead, the rate reads as one nobody measured. Said as the
    # series' card says its levels, the one before and the one while broken.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=29), extent=ImpactExtent.MEASURED,
                              peak_error_rate=0.02, requests_failed=72,
                              error_rates=ErrorRateLevels(before=0.0104, while_broken=0.0093,
                                                          rose=False)),
                customer_loss_estimate=None)
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards
        ) \
        .then(
            the_answer_was((Card(value="29m 0s", label="onset until back to normal"),
                            Card(value="1.0% to 0.9%",
                                 label="error rate, before onset and while broken on average",
                                 note="no rise"),
                            Card(value="not estimated", label="customer loss (estimated)"))))


@pytest.mark.unit
@pytest.mark.parametrize(("worse_when", "before", "while_broken", "value"), [
    ("below", 0.8994, 0.45943, "0.899 to 0.459"),
    ("above", 0.45943, 0.8994, "0.459 to 0.899")
], ids=["worse-falling", "worse-rising"])
def test_a_series_that_got_worse_is_a_card_from_its_level_before_to_its_level_while_broken(
        worse_when: WorseWhen, before: float, while_broken: float, value: str) -> None:
    # The series is what paged, and where every request succeeded it is the
    # only harm there is - and a level alone is no harm until it is set against
    # the one before, so the figure is the two, in the order that says which
    # way it went. Said as what the alert watches, since only the rule knows
    # what it measures; in plain numbers, since only the rule knows the unit;
    # and written as the prose writes a level, so the card and the sentence
    # beside it are one figure. On average, as the error rate is, with the
    # worst minute in the note - one minute alone overstates the stretch.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=29), extent=ImpactExtent.MEASURED,
                              peak_error_rate=None,
                              rule_series_harm=RuleSeriesHarm(before=before,
                                                              while_broken=while_broken,
                                                              at_its_worst=0.39071,
                                                              worse_when=worse_when)))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert("CategorisationConfidenceLow")).cards[3]
        ) \
        .then(
            the_answer_was(Card(value=value,
                                label="what the alert watches, before onset and while broken "
                                      "on average",
                                note="worst minute 0.391")))


@pytest.mark.unit
def test_a_series_card_names_the_line_its_rule_pages_past() -> None:
    # In the series' own unit: the alert's words may say "80%" of a series
    # written as 0.459, and the line beside it lets a reader bridge the two
    # without the page guessing a unit.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=29), extent=ImpactExtent.MEASURED,
                              peak_error_rate=None,
                              rule_series_harm=RuleSeriesHarm(before=0.8994, while_broken=0.45943,
                                                              at_its_worst=0.39071,
                                                              worse_when="below", line=0.8)))
        ) \
        .when(
            lambda: the_impact(some_postmortem,
                               an_alert("CategorisationConfidenceLow")).cards[3].note
        ) \
        .then(
            the_answer_was("worst minute 0.391; the rule's line is 0.8"))


@pytest.mark.unit
def test_a_series_that_is_the_error_rate_leaves_its_worst_minute_to_the_peak_card() -> None:
    # Its worst minute is the peak error rate, on the card beside it; said again
    # in the note it is the one figure twice.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=8), extent=ImpactExtent.MEASURED,
                              peak_error_rate=0.38,
                              rule_series_harm=RuleSeriesHarm(before=0.00992, while_broken=0.276,
                                                              at_its_worst=0.38,
                                                              worse_when="above", line=0.1,
                                                              unit="percentunit",
                                                              is_the_error_rate=True)))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert("HighErrorRate")).cards[3].note
        ) \
        .then(
            the_answer_was("the rule's line is 10%"))


@pytest.mark.unit
def test_a_series_that_is_the_error_rate_is_said_on_its_card_as_the_error_rate_is() -> None:
    # The card read 1.02% where the summary beside it read the same rate as
    # 1.0%: one figure written two ways. Said as the error rate is said, the
    # card and the summary agree.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=8), extent=ImpactExtent.MEASURED,
                              peak_error_rate=0.38,
                              rule_series_harm=RuleSeriesHarm(before=0.00992, while_broken=0.276,
                                                              at_its_worst=0.38,
                                                              worse_when="above", line=0.1,
                                                              unit="percentunit",
                                                              is_the_error_rate=True)))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert("HighErrorRate")).cards[3].value
        ) \
        .then(
            the_answer_was("1.0% to 27.6%"))


@pytest.mark.unit
@pytest.mark.parametrize(("harm", "value", "note"), [
    (RuleSeriesHarm(before=120.0, while_broken=640.0, at_its_worst=910.0,
                    worse_when="above", line=600.0, unit="ms"),
     "120 ms to 640 ms", "worst minute 910 ms; the rule's line is 600 ms"),
    (RuleSeriesHarm(before=0.8994, while_broken=0.45943, at_its_worst=0.39071,
                    worse_when="below", line=0.8, unit="percentunit"),
     "89.9% to 45.9%", "worst minute 39.1%; the rule's line is 80%")
], ids=["milliseconds", "a-share-of-one"])
def test_a_series_card_says_its_levels_in_their_unit(harm: RuleSeriesHarm, value: str,
                                                     note: str) -> None:
    # Beside an alert saying "below 80%", a card reading 0.899 to 0.459 is a
    # second scale - in its unit, the card and the alert read as one.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=29), extent=ImpactExtent.MEASURED,
                              peak_error_rate=None, rule_series_harm=harm))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert("CategorisationConfidenceLow")).cards[3]
        ) \
        .then(
            the_answer_was(Card(value=value,
                                label="what the alert watches, before onset and while broken "
                                      "on average",
                                note=note)))


def _the_values_are(*expected: str) -> Assertion[tuple[Card, ...]]:
    def assertion(cards: tuple[Card, ...]) -> bool:
        values = tuple(card.value for card in cards)

        if values != expected:
            raise AssertionError(f"Expected the cards to read {expected}, got {values}.")

        return True

    return assertion


def _metrics_missing(logs: LogsInTheGap) -> Impact:
    """An incident whose metrics stopped at the onset, with these logs read."""
    return Impact(duration=timedelta(minutes=40), extent=ImpactExtent.METRICS_MISSING,
                  peak_error_rate=None, logs_in_the_gap=logs)


def _the_note_reads(expected: str) -> Assertion[Line | None]:
    def assertion(note: Line | None) -> bool:
        said = note.said if note is not None else None

        if said != expected:
            raise AssertionError(f"Expected the note on the logs to read [{expected}], "
                                 f"got [{said}].")

        return True

    return assertion


def _the_note_cites(*labels: str) -> Assertion[Line | None]:
    def assertion(note: Line | None) -> bool:
        cited = [run.address for run in note.runs
                 if run.role is Role.CITATION] if note is not None else []

        if cited != list(labels):
            raise AssertionError(f"Expected the note to cite {list(labels)}, and it cited "
                                 f"{cited}.")

        return True

    return assertion
