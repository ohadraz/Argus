from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from math import isclose

import pytest
from agent_postmortem.measuring import Measurements, measure
from agent_postmortem.sources import EngagedResponder, PayBand
from argus_testkit import Assertion, Kept, Scenario, all_of

from agent_postmortem_test.framework.builders import (
    ENDED_AT,
    ONSET,
    SOME_CURRENCY,
    SOME_OTHER_CURRENCY,
    SOME_UNPRICED_CURRENCY,
    STARTED_AT,
    a_band_source_pricing,
    a_band_source_that_cannot_answer,
    a_revenue_source_that_cannot_answer,
    an_engagement_source_reporting_each,
    an_engagement_source_that_cannot_answer,
    an_evidence_bundle,
    metrics_recording_the_window_into,
    metrics_showing_error_rates,
    metrics_that_answer_with_nothing,
    rates_published,
    rates_that_cannot_be_read,
    revenue_that_was,
    some_sources,
)

"""Everything about an incident that is a number, measured before anything is
asked of a model.

One function, because the figures are not independent: the loss is a
subtraction between two windows, both windows are dated from the same instant,
and the currency the answer is published in is a property of the table that
converted them. Measured separately they could disagree with each other, and a
document whose duration and whose loss describe different incidents is worse
than one carrying neither.

Two costs, and they are the same kind of thing: what the outage cost customers,
and what the response cost the business. Both are money, both come from ports,
and both are reported side by side on the page - so both are measured here.

Nothing here is a judgement and no figure rests on another's absence. Metrics
nobody could read cost the document a sentence of narrative; they do not touch
the money, because the money was measured by the party that took it.
"""

SOME_CALM_HOURLY_REVENUE = 1_200
SOME_REVENUE_DURING_THE_INCIDENT = Decimal("100.00")

SOME_TITLE = "Senior Kuki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"
SOME_ENGAGED_MINUTES = 30

# A 2000-hour year is 120,000 minutes, so a midpoint of 120,000 is worth one
# unit a minute and an arithmetic slip shows as a different figure rather than
# as a rounding argument.
SOME_WORKING_YEAR_IN_HOURS = 2000.0
SOME_WORKING_YEAR_IN_MINUTES = Decimal(120_000)

SOME_BAND = PayBand(
    minimum=Decimal(60_000),
    midpoint=Decimal(120_000),
    maximum=Decimal(240_000),
    currency=SOME_CURRENCY
)


@pytest.mark.unit
def test_the_incident_is_measured_from_its_onset_rather_than_from_the_alert() -> None:
    # The two differ by however long the alert rule took to trip. Counting
    # those minutes as calm trade would raise the baseline using the very
    # minutes the shop was already failing in, and shorten the incident the
    # loss is spread over - wrong twice, both times flatteringly.
    an_incident_dated_from_its_onset = _hours_between(ONSET, ENDED_AT)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(started_at=STARTED_AT,
                                           ended_at=ENDED_AT,
                                           onset_at=ONSET)
        ) \
        .when(
            lambda: measure(evidence, some_sources())
        ) \
        .then(
            _ran_for(an_incident_dated_from_its_onset)
        )


@pytest.mark.unit
def test_the_loss_is_what_the_calm_hour_predicted_less_what_came_in() -> None:
    # The whole estimate, and the only arithmetic in it: the rate the shop was
    # trading at before the onset, scaled to the length of the incident, less
    # what it actually took while it was broken. Both terms are money the
    # payment provider reported.
    expected_loss = (
        Decimal(SOME_CALM_HOURLY_REVENUE)
        * Decimal(str(_hours_between(ONSET, ENDED_AT)))
        - SOME_REVENUE_DURING_THE_INCIDENT
    )

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(revenue=revenue_that_was(
                    per_hour={SOME_CURRENCY: SOME_CALM_HOURLY_REVENUE},
                    until=ONSET,
                    and_then={SOME_CURRENCY: SOME_REVENUE_DURING_THE_INCIDENT})))
        ) \
        .then(
            all_of(
                _the_loss_was(expected_loss),
                _the_figure_is_in(SOME_CURRENCY)
            )
        )


@pytest.mark.unit
def test_an_incident_with_no_onset_is_not_costed() -> None:
    # No onset means no minute departed from baseline (spec §9): there is no
    # measured incident to attribute a loss to. Dating one from the alert would
    # invent a window nobody measured, and the alert is late by however long
    # the rule took to trip - so the figure would be both fabricated and short.
    #
    # The duration is still measured, from the alert, because the model is told
    # how long the incident ran whether or not anybody can price it.
    an_incident_dated_from_the_alert = _hours_between(STARTED_AT, ENDED_AT)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None)
        ) \
        .when(
            lambda: measure(evidence, some_sources())
        ) \
        .then(
            all_of(
                _nothing_was_costed(),
                _ran_for(an_incident_dated_from_the_alert)
            )
        )


@pytest.mark.unit
def test_a_revenue_source_that_cannot_be_read_costs_nothing_rather_than_zero() -> None:
    # Zero here would become a postmortem telling an executive the outage cost
    # them nothing, on the strength of a service Argus failed to reach. Both
    # windows are needed, because a loss is the difference between them - one
    # alone is half a subtraction.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(revenue=a_revenue_source_that_cannot_answer()))
        ) \
        .then(
            all_of(
                _nothing_was_costed(),
                _read_no_baseline()
            )
        )


@pytest.mark.unit
def test_takings_abroad_are_converted_at_the_published_rate() -> None:
    # The shop sells abroad, so the baseline hour is partly money that is not
    # in the currency the estimate is reported in. The rates say how many units
    # of a currency one unit of the base buys, so money taken abroad is divided
    # by its rate rather than multiplied - the direction that turns eighty
    # euros into a hundred dollars rather than sixty-four.
    some_calm_hourly_revenue_abroad = 800
    some_revenue_abroad_during_the_incident = Decimal("200.00")
    some_rate = Decimal("0.80")
    expected_loss = (
        Decimal(some_calm_hourly_revenue_abroad) / some_rate
        * Decimal(str(_hours_between(ONSET, ENDED_AT)))
        - some_revenue_abroad_during_the_incident / some_rate
    )

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(
                    revenue=revenue_that_was(
                        per_hour={
                            SOME_OTHER_CURRENCY: some_calm_hourly_revenue_abroad
                        },
                        until=ONSET,
                        and_then={
                            SOME_OTHER_CURRENCY: some_revenue_abroad_during_the_incident
                        }),
                    rates=rates_published(on=ONSET.date(),
                                          per_unit={SOME_OTHER_CURRENCY: some_rate},
                                          base=SOME_CURRENCY)))
        ) \
        .then(
            all_of(
                _the_loss_was(expected_loss),
                _the_figure_is_in(SOME_CURRENCY)
            )
        )


@pytest.mark.unit
def test_a_currency_the_table_has_no_rate_for_is_left_out_and_named() -> None:
    # The rate provider publishes thirty-odd currencies and a shop may take one
    # it does not cover. Losing the whole figure over the part that cannot be
    # converted would throw away the part that can - and silently dropping it
    # would publish a figure that looks like all the money and is not. So the
    # figure covers what could be converted, and the currency that stopped it
    # is named for whoever writes the disclosure.
    some_calm_hourly_revenue = 1_000
    dont_care_hourly_revenue_that_cannot_be_priced = 400
    dont_care_revenue_that_cannot_be_priced = Decimal("50.00")
    expected_loss = (
        Decimal(some_calm_hourly_revenue)
        * Decimal(str(_hours_between(ONSET, ENDED_AT)))
        - SOME_REVENUE_DURING_THE_INCIDENT
    )

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(revenue=revenue_that_was(
                    per_hour={
                        SOME_CURRENCY: some_calm_hourly_revenue,
                        SOME_UNPRICED_CURRENCY:
                            dont_care_hourly_revenue_that_cannot_be_priced
                    },
                    until=ONSET,
                    and_then={
                        SOME_CURRENCY: SOME_REVENUE_DURING_THE_INCIDENT,
                        SOME_UNPRICED_CURRENCY: dont_care_revenue_that_cannot_be_priced
                    })))
        ) \
        .then(
            all_of(
                _the_loss_was(expected_loss),
                _left_out(SOME_UNPRICED_CURRENCY)
            )
        )


@pytest.mark.unit
def test_rates_that_cannot_be_read_leave_no_currency_to_publish_a_figure_in() -> None:
    # The table is what says which currency this document reports in, so
    # without one there is no figure to publish even where only one currency
    # was taken. Naming that currency would be a guess, and a guess about which
    # money this is would be a worse failure than an absent estimate.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence, some_sources(rates=rates_that_cannot_be_read()))
        ) \
        .then(
            all_of(
                _nothing_was_costed(),
                _the_figure_is_in(None)
            )
        )


@pytest.mark.unit
def test_metrics_that_cannot_be_read_leave_the_rise_unknown_and_the_money_alone() -> None:
    # The rise in errors is told to the model and nothing else: what the
    # incident cost is a subtraction between two sums the payment provider
    # reported. So metrics nobody could read cost the document a sentence of
    # narrative and not its figure - which is the point of measuring the loss
    # rather than modelling it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence, some_sources(metrics=metrics_that_answer_with_nothing()))
        ) \
        .then(
            all_of(
                _the_rise_is_unknown(),
                _something_was_costed()
            )
        )


@pytest.mark.unit
def test_the_rise_is_measured_against_the_calm_minutes_before_the_incident() -> None:
    # Not the raw rate during it. A service that always fails two requests in a
    # hundred did not start doing so because of this incident, and charging
    # those to it overstates the story by the same amount every time.
    some_baseline_error_rate = 0.02
    some_error_rate_during_the_incident = 0.30

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(metrics=metrics_showing_error_rates(
                    baseline=some_baseline_error_rate,
                    during=some_error_rate_during_the_incident)))
        ) \
        .then(
            _the_rise_was(some_error_rate_during_the_incident - some_baseline_error_rate)
        )


@pytest.mark.unit
def test_the_metrics_window_spans_the_whole_incident() -> None:
    # The Investigator stops reading the moment it has a cause, so what it
    # stored ends somewhere in the middle: the recovery between the mitigation
    # landing and the incident ending was never fetched, and that recovery is
    # most of what the duration covers. Reusing that window here would describe
    # an incident that never got better.
    windows_asked_for: Kept[tuple[datetime, datetime]] = Kept()

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(
                    metrics=metrics_recording_the_window_into(windows_asked_for)))
        ) \
        .then(
            _asked_metrics_for_a_window_spanning(STARTED_AT, ENDED_AT, windows_asked_for)
        )


@pytest.mark.unit
def test_the_response_is_priced_at_the_bands_published_for_it() -> None:
    # The second cost, and the one nobody thinks to check: an incident's real
    # price is what it took out of the shop plus what it took out of the people.
    # The minutes come from one source and the bands from another, and pricing
    # is the only place they meet.
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)
    cost_at_midpoint = (SOME_BAND.midpoint * SOME_ENGAGED_MINUTES
                        / SOME_WORKING_YEAR_IN_MINUTES)

    Scenario() \
        .given(
            a_responder
        ) \
        .when(
            lambda: measure(
                an_evidence_bundle(),
                some_sources(
                    engagement=an_engagement_source_reporting_each([a_responder]),
                    bands=a_band_source_pricing({SOME_TITLE: SOME_BAND}),
                    working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS))
        ) \
        .then(
            all_of(
                _the_response_took(SOME_ENGAGED_MINUTES),
                _the_response_cost(cost_at_midpoint)
            )
        )


@pytest.mark.unit
def test_an_engagement_source_that_cannot_be_read_measures_no_response_at_all() -> None:
    # Nothing to report and nothing to price, which are one absence rather than
    # two: a response nobody could measure cannot be costed, and a cost of zero
    # would say the incident took nobody's night.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(engagement=an_engagement_source_that_cannot_answer()))
        ) \
        .then(
            all_of(
                _measured_no_response(),
                _priced_no_response()
            )
        )


@pytest.mark.unit
def test_bands_that_cannot_be_read_leave_the_response_measured_but_unpriced() -> None:
    # An HR system Argus could not reach is not evidence that the response was
    # free. The minutes were measured and the money was not, so only one of them
    # goes - the same distinction the revenue source already makes.
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            a_responder
        ) \
        .when(
            lambda: measure(
                an_evidence_bundle(),
                some_sources(
                    engagement=an_engagement_source_reporting_each([a_responder]),
                    bands=a_band_source_that_cannot_answer()))
        ) \
        .then(
            all_of(
                _the_response_took(SOME_ENGAGED_MINUTES),
                _priced_no_response()
            )
        )


@pytest.mark.unit
def test_a_title_no_band_covers_leaves_the_response_measured_but_unpriced() -> None:
    # A cost covering one of two people is not a smaller cost, it is a wrong
    # one - and wrong in the direction that flatters the response, which is the
    # one nobody questions. The minutes stay, because they were measured.
    a_priced_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES,
                                          job_title=SOME_TITLE)
    a_responder_no_band_covers = EngagedResponder(minutes=SOME_ENGAGED_MINUTES,
                                                  job_title=SOME_TITLE_NO_BAND_COVERS)

    Scenario() \
        .given(
            a_priced_responder,
            a_responder_no_band_covers
        ) \
        .when(
            lambda: measure(
                an_evidence_bundle(),
                some_sources(
                    engagement=an_engagement_source_reporting_each(
                        [a_priced_responder, a_responder_no_band_covers]),
                    bands=a_band_source_pricing({SOME_TITLE: SOME_BAND}),
                    working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS))
        ) \
        .then(
            all_of(
                _the_response_took(SOME_ENGAGED_MINUTES * 2),
                _priced_no_response()
            )
        )


def _hours_between(start: datetime, end: datetime) -> float:
    """The span, worked out here rather than asked of the code under test.

    A test computing its expectation the way the code does would agree with it
    however wrong both were.
    """
    return (end - start) / timedelta(hours=1)


def _ran_for(expected: float) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if not isclose(measured.duration_in_hours, expected):
            raise AssertionError(
                f"Expected an incident of [{expected}] hours, got "
                f"[{measured.duration_in_hours}].")

        return True

    return assertion


def _the_loss_was(expected: Decimal) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.loss != expected:
            raise AssertionError(
                f"Expected a loss of [{expected}], got [{measured.loss}].")

        return True

    return assertion


def _nothing_was_costed() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.loss is not None:
            raise AssertionError(
                f"Expected no loss where a term of it could not be read, got "
                f"[{measured.loss}].")

        return True

    return assertion


def _something_was_costed() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.loss is None:
            raise AssertionError(
                "Expected a loss: both windows were readable, and no figure rests "
                "on the metrics.")

        return True

    return assertion


def _read_no_baseline() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.baseline_revenue is not None:
            raise AssertionError(
                f"Expected no baseline where the source could not answer, got "
                f"[{measured.baseline_revenue}].")

        return True

    return assertion


def _the_figure_is_in(expected: str | None) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.currency != expected:
            raise AssertionError(
                f"Expected a figure in [{expected}], got [{measured.currency}].")

        return True

    return assertion


def _left_out(expected: str) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if expected not in measured.currencies_left_out:
            raise AssertionError(
                f"Expected [{expected}] to be named as left out of the figure, got "
                f"{measured.currencies_left_out}.")

        return True

    return assertion


def _the_rise_was(expected: float) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.error_rate_delta is None or not isclose(measured.error_rate_delta,
                                                            expected):
            raise AssertionError(
                f"Expected a rise of [{expected}], got [{measured.error_rate_delta}]")

        return True

    return assertion


def _the_rise_is_unknown() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.error_rate_delta is not None:
            raise AssertionError(
                f"Expected no rise where the metrics could not be read, got "
                f"[{measured.error_rate_delta}].")

        return True

    return assertion


def _the_response_took(expected: int) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.engaged is None:
            raise AssertionError(
                f"Expected a response of [{expected}] minutes, and none was measured.")

        if measured.engaged.minutes != expected:
            raise AssertionError(
                f"Expected a response of [{expected}] minutes, got "
                f"[{measured.engaged.minutes}].")

        return True

    return assertion


def _measured_no_response() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.engaged is not None:
            raise AssertionError(
                f"Expected no response where nobody could say, got "
                f"[{measured.engaged}].")

        return True

    return assertion


def _the_response_cost(expected: Decimal) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.cost is None:
            raise AssertionError(
                f"Expected the response to be priced at [{expected}], and it was "
                f"not priced at all.")

        if measured.cost.midpoint != expected:
            raise AssertionError(
                f"Expected a response cost of [{expected}], got "
                f"[{measured.cost.midpoint}].")

        return True

    return assertion


def _priced_no_response() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.cost is not None:
            raise AssertionError(
                f"Expected no response cost where it could not be priced in full, "
                f"got [{measured.cost.midpoint}].")

        return True

    return assertion


def _asked_metrics_for_a_window_spanning(
        started_at: datetime,
        ended_at: datetime,
        windows: Kept[tuple[datetime, datetime]]) -> Assertion[Measurements]:
    def assertion(dont_care_measured: Measurements) -> bool:
        window_start, window_end = windows.only()

        if window_start > started_at:
            raise AssertionError(
                f"Expected a window starting at or before the incident "
                f"[{started_at}], got [{window_start}].")

        if window_end < ended_at:
            raise AssertionError(
                f"Expected a window reaching the end of the incident "
                f"[{ended_at}], got [{window_end}].")

        return True

    return assertion
