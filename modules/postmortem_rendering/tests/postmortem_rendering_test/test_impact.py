"""How bad it was: one card per figure, the figure first, and what the alert
found where the damage is not a rate.

Each case is one postmortem and what a card, the finding or the note says.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from argus_core.models import (
    AlarmClaim,
    Alert,
    ErrorRateLevels,
    Impact,
    ImpactExtent,
    RuleSeriesHarm,
    WorseWhen,
)
from argus_testkit import Assertion, Scenario, the_answer_was
from postmortem_rendering.impact import Card, the_impact

from postmortem_rendering_test.framework.builders import a_postmortem, an_alert


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
            the_answer_was((Card(value="29m 0s", label="onset to recovery"),
                            Card(value="33.9%", label="peak error rate"),
                            Card(value="4,210", label="requests failed"),
                            Card(value="1,736.68 USD", label="customer loss (estimated)",
                                 loss_is="measured"))))


@pytest.mark.unit
def test_nothing_measured_says_so_on_every_card() -> None:
    # Absence is said, never shown as a zero: a reader must not have to guess
    # whether nothing was lost or nothing was known.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(impact=None, customer_loss_estimate=None)
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).cards
        ) \
        .then(
            _the_values_are("not measured", "not measured", "not counted", "not estimated"))


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
            _the_values_are("at least 40m 0s", "not measured", "not counted",
                            "at least 500.00 USD"))


@pytest.mark.unit
def test_a_lower_bound_on_the_loss_is_said_to_be_one() -> None:
    # For a destination that marks it: the page tags the card with which it is.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=40), extent=ImpactExtent.UNOBSERVED,
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
                impact=Impact(duration=timedelta(minutes=40), extent=ImpactExtent.UNOBSERVED,
                              peak_error_rate=None))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).unobserved
        ) \
        .then(
            the_answer_was("Unobserved after a point - the metrics stopped, so the duration "
                           "is how long nobody could see."))


@pytest.mark.unit
def test_a_measured_incident_carries_no_note_on_its_duration() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                impact=Impact(duration=timedelta(minutes=9), extent=ImpactExtent.MEASURED,
                              peak_error_rate=None))
        ) \
        .when(
            lambda: the_impact(some_postmortem, an_alert()).unobserved
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
            the_answer_was((Card(value="29m 0s", label="onset to recovery"),
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


def _the_values_are(*expected: str) -> Assertion[tuple[Card, ...]]:
    def assertion(cards: tuple[Card, ...]) -> bool:
        values = tuple(card.value for card in cards)

        if values != expected:
            raise AssertionError(f"Expected the cards to read {expected}, got {values}.")

        return True

    return assertion
