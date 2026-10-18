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

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from math import isclose

import pytest
from agent_postmortem.estimate import RuleSeriesLevels, Unmeasured, calm_to_read_for
from agent_postmortem.measuring import Measurements, measure
from agent_postmortem.sources import EngagedResponder, EngagementAnswer, Metrics, PayBand, Revenue
from argus_core.models import MetricBucket, Verdict
from argus_testkit import Assertion, Kept, Scenario, all_of, the_answer_was

from agent_postmortem_test.framework.builders import (
    ENDED_AT,
    ONSET,
    RECORDED_RECOVERY_AT,
    RECOVERED_AT,
    SOME_CURRENCY,
    SOME_OTHER_CURRENCY,
    SOME_UNPRICED_CURRENCY,
    STARTED_AT,
    a_band_source_pricing,
    a_band_source_that_cannot_answer,
    a_bucket,
    a_revenue_source_that_cannot_answer,
    a_rule_waiting,
    an_action,
    an_engagement_source_reporting_each,
    an_engagement_source_that_cannot_answer,
    an_evidence_bundle,
    hours_between,
    metrics_recording_the_rule_into,
    metrics_recording_the_window_into,
    metrics_showing_error_rates,
    metrics_that_answer_with_nothing,
    metrics_that_recovered,
    metrics_that_stop_at_the_onset,
    metrics_whose_rule_series_went,
    rates_published,
    rates_that_cannot_be_read,
    revenue_that_was,
    some_sources,
)

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

A_WEEK = timedelta(weeks=1)


@pytest.mark.unit
def test_the_incident_is_measured_from_its_onset_rather_than_from_the_alert() -> None:
    # The two differ by however long the alert rule took to trip. Counting
    # those minutes as calm trade would raise the baseline using the very
    # minutes the shop was already failing in, and shorten the incident the
    # loss is spread over - wrong twice, both times flatteringly.
    an_incident_dated_from_its_onset = hours_between(ONSET, ENDED_AT)

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
        * Decimal(str(hours_between(ONSET, ENDED_AT)))
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
def test_a_shortfall_within_what_the_shop_varies_by_on_its_own_is_no_loss() -> None:
    # Like with like: the incident against as long a stretch just before its
    # onset, and that stretch against the one before it. Here the two calm
    # stretches differ by more than the incident fell short.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(revenue=_a_shop_taking(earlier=Decimal("1000.00"),
                                                    just_before=Decimal("1300.00"),
                                                    during=Decimal("1100.00"))))
        ) \
        .then(
            all_of(
                _the_loss_was(Decimal(0)),
                _the_shop_varies_by(Decimal("300.00"))
            )
        )


@pytest.mark.unit
def test_a_shortfall_beyond_what_the_shop_varies_by_is_the_loss() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(revenue=_a_shop_taking(earlier=Decimal("1000.00"),
                                                    just_before=Decimal("1100.00"),
                                                    during=Decimal("100.00"))))
        ) \
        .then(
            _the_loss_was(Decimal("1000.00"))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("lasting", "weeks_back"), [
    (timedelta(minutes=10), 1),
    (timedelta(days=8), 2)
])
def test_takings_are_compared_at_the_incident_s_own_hours_whole_weeks_earlier(
        lasting: timedelta, weeks_back: int) -> None:
    # The same hours on the same weekday, so a shop's day and week cancel out:
    # a morning incident against the night before it is a loss the morning rush
    # invented. Far enough back that the stretch never overlaps the incident.
    recovered = ONSET + lasting
    back = A_WEEK * weeks_back
    windows_asked_for: Kept[tuple[datetime, datetime]] = Kept()

    Scenario() \
        .given(
            evidence := an_evidence_bundle(ended_at=recovered + timedelta(minutes=5),
                                           recorded_recovery_at=recovered)
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(metrics=metrics_that_recovered(),
                             revenue=_revenue_recording_the_windows_into(windows_asked_for)))
        ) \
        .then(
            _asked_for_the_takings_over([(ONSET - 2 * back, recovered - 2 * back),
                                         (ONSET - back, recovered - back),
                                         (ONSET, recovered)],
                                        windows_asked_for)
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
    an_incident_dated_from_the_alert = hours_between(STARTED_AT, ENDED_AT)

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
        * Decimal(str(hours_between(ONSET, ENDED_AT)))
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
        * Decimal(str(hours_between(ONSET, ENDED_AT)))
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
def test_rates_that_cannot_be_read_still_leave_the_takings_that_needed_no_rate() -> None:
    # A table nobody could read is a table with no rates in it, and the currency
    # the document reports in is configured rather than derived from one. So the
    # figure covers the money that needed no conversion and names every currency
    # that did - the same answer the arithmetic already gives for a single
    # currency the table does not cover. Losing the whole estimate over the part
    # that cannot be converted throws away the part that can.
    some_calm_hourly_revenue = 1_000
    dont_care_hourly_revenue_abroad = 400
    dont_care_revenue_abroad = Decimal("50.00")
    expected_loss = (
        Decimal(some_calm_hourly_revenue)
        * Decimal(str(hours_between(ONSET, ENDED_AT)))
        - SOME_REVENUE_DURING_THE_INCIDENT
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
                            SOME_CURRENCY: some_calm_hourly_revenue,
                            SOME_OTHER_CURRENCY: dont_care_hourly_revenue_abroad
                        },
                        until=ONSET,
                        and_then={
                            SOME_CURRENCY: SOME_REVENUE_DURING_THE_INCIDENT,
                            SOME_OTHER_CURRENCY: dont_care_revenue_abroad
                        }),
                    rates=rates_that_cannot_be_read()))
        ) \
        .then(
            all_of(
                _the_loss_was(expected_loss),
                _the_figure_is_in(SOME_CURRENCY),
                _left_out(SOME_OTHER_CURRENCY)
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
def test_metrics_that_cannot_be_read_say_why_the_rise_is_unknown() -> None:
    # An unknown rise alone leaves the reader to guess: an empty read and a read
    # that held no calm minute are different gaps, and only one is an outage.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence, some_sources(metrics=metrics_that_answer_with_nothing())
            ).error_rates_unmeasured
        ) \
        .then(
            the_answer_was(Unmeasured.NOTHING_READ)
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
def test_every_figure_is_measured_to_the_minute_the_service_came_back() -> None:
    # The defect. Argus held this incident for thirty minutes and the service
    # was broken for ten of them: the mitigation landed, the metrics
    # recovered, and the verification wait, the code-fix attempt and the
    # write-up all ran afterwards. Measured to the close, the rise averages
    # twenty healthy minutes in with ten broken ones and reads as almost
    # nothing - or, on a quieter baseline, as less than nothing.
    #
    # Recovery is read off the series and nothing else. Not the moment the
    # action was applied, and not the verdict that confirmed it: those say
    # when Argus acted, and a service does not recover because somebody acted
    # on it.
    some_baseline_error_rate = 0.02
    some_error_rate_while_broken = 0.30
    ten_of_the_thirty_minutes = 10 / 60

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(metrics=metrics_that_recovered(
                    baseline=some_baseline_error_rate,
                    during=some_error_rate_while_broken)))
        ) \
        .then(all_of(
            _it_was_back_to_normal_at(RECOVERED_AT),
            _ran_for(ten_of_the_thirty_minutes),
            _the_rise_was(some_error_rate_while_broken - some_baseline_error_rate)
        ))


@pytest.mark.unit
def test_an_incident_still_broken_when_the_metrics_run_out_reports_no_recovery() -> None:
    # Not a recovery at the last minute read, which is what falling back to
    # the close amounts to. The read still has to end somewhere - a window
    # cannot be unbounded - so it ends at the close and the absent recovery is
    # the mark saying so. Every figure measured over it is then a lower bound,
    # and whatever renders them has to say which it is holding.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(evidence, some_sources())
        ) \
        .then(_it_never_recovered())


@pytest.mark.unit
def test_an_incident_watched_and_never_seen_to_recover_reports_no_recovery() -> None:
    # The recovery belongs to the party that was watching at the time, and so
    # does its absence: Mitigation watched and never saw the service come back.
    # Asked again of this window, a service that flaps shows a lull that reads as
    # a recovery in one run and not in the next.
    some_baseline_error_rate = 0.02
    some_error_rate_while_broken = 0.30

    Scenario() \
        .given(
            evidence := an_evidence_bundle(watched_and_never_recovered=True)
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(metrics=metrics_that_recovered(
                    baseline=some_baseline_error_rate,
                    during=some_error_rate_while_broken)))
        ) \
        .then(
            _it_never_recovered()
        )


@pytest.mark.unit
def test_a_recovery_read_off_the_series_is_never_dated_before_the_onset() -> None:
    # Where nothing recorded a recovery it is read off the series, and the series
    # opens an hour before the onset. On a service that flapped before this
    # incident, the first persisted run in it is the earlier episode, whose end
    # is a recovery from an incident that had not yet begun.
    the_minute_it_came_back = ONSET + timedelta(minutes=3)

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(evidence,
                            some_sources(metrics=_metrics_that_flapped_before_the_onset()))
        ) \
        .then(
            _it_was_back_to_normal_at(the_minute_it_came_back)
        )


def _metrics_that_flapped_before_the_onset() -> Metrics:
    """Calm, an earlier episode - higher than this incident, and over - calm
    again, then three minutes of the incident from `ONSET`, and calm to the
    close."""
    some_calm_rate = 0.01
    calm_before = [some_calm_rate] * 6
    earlier_episode = [some_calm_rate * 9, some_calm_rate * 18, some_calm_rate * 18]
    calm_between = [some_calm_rate] * 4
    the_incident = [some_calm_rate * 4] * 3
    calm_after = [some_calm_rate] * 28
    first_minute = ONSET - timedelta(
        minutes=len(calm_before) + len(earlier_episode) + len(calm_between)
    )

    def metrics_between(dont_care_start: datetime,
                        dont_care_end: datetime,
                        dont_care_rule: str | None) -> list[MetricBucket]:
        return [
            a_bucket(at=first_minute + timedelta(minutes=minute), error_rate=rate)
            for minute, rate in enumerate(
                calm_before + earlier_episode + calm_between + the_incident + calm_after
            )
        ]

    return metrics_between


@pytest.mark.unit
def test_where_the_service_came_back_is_judged_on_the_hour_before_it_only() -> None:
    # The calm read further back is for how far the rate varies. Where the
    # service came back is judged on the window it always was: a noisier
    # stretch hours earlier raises the bar a minute is told apart by, and
    # leaves a service that came back never back at all.
    the_minute_it_came_back = ONSET + timedelta(minutes=3)

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(evidence,
                            some_sources(metrics=_metrics_noisier_hours_before_the_onset()))
        ) \
        .then(
            _it_was_back_to_normal_at(the_minute_it_came_back)
        )


def _metrics_noisier_hours_before_the_onset() -> Metrics:
    """Five hours at three times the calm rate, the calm hour, three minutes of
    the incident from `ONSET`, and calm to the close."""
    some_calm_rate = 0.01
    hours_before = [some_calm_rate * 3] * 300
    the_hour = [some_calm_rate] * 60
    the_incident = [some_calm_rate * 4] * 3
    calm_after = [some_calm_rate] * 27
    first_minute = ONSET - timedelta(minutes=len(hours_before) + len(the_hour))

    def metrics_between(dont_care_start: datetime,
                        dont_care_end: datetime,
                        dont_care_rule: str | None) -> list[MetricBucket]:
        return [
            a_bucket(at=first_minute + timedelta(minutes=minute), error_rate=rate)
            for minute, rate in enumerate(hours_before + the_hour + the_incident + calm_after)
        ]

    return metrics_between


@pytest.mark.unit
def test_metrics_that_stopped_hours_before_the_onset_were_unobserved_from_it() -> None:
    # The calm is read back further than the hour, so a source whose rows
    # stopped two hours before the onset answers with them: it was read, and
    # collected nothing from the onset on - which is not a source that could
    # not answer.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(evidence,
                            some_sources(metrics=_metrics_that_stopped_hours_before_the_onset()))
        ) \
        .then(
            _it_was_unobserved_from(ONSET)
        )


def _metrics_that_stopped_hours_before_the_onset() -> Metrics:
    """Ten calm minutes ending two hours before `ONSET`, and nothing after -
    each minute answered only where the window asked for covers it."""
    some_calm_rate = 0.01
    collected = [ONSET - timedelta(hours=2, minutes=minute) for minute in range(1, 11)]

    def metrics_between(window_start: datetime,
                        window_end: datetime,
                        dont_care_rule: str | None) -> list[MetricBucket]:
        return [a_bucket(at=at, error_rate=some_calm_rate)
                for at in collected if window_start <= at <= window_end]

    return metrics_between


@pytest.mark.unit
def test_an_incident_whose_metrics_stop_at_the_onset_was_unobserved_from_it() -> None:
    # A lower bound is not the whole of it. "Still broken when the metrics ran
    # out" and "nothing was collected from the onset on" both leave no recovery,
    # and they are different facts: the first measured a service in trouble to
    # the end of the window, the second measured nothing at all after the onset.
    # A document that said only the first would be reporting a short window as
    # an incident.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(evidence,
                            some_sources(metrics=metrics_that_stop_at_the_onset()))
        ) \
        .then(all_of(
            _it_never_recovered(),
            _it_was_unobserved_from(ONSET)
        ))


@pytest.mark.unit
def test_an_incident_whose_metrics_went_on_was_observed_throughout() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(evidence, some_sources(metrics=metrics_that_recovered()))
        ) \
        .then(_it_was_observed_throughout())


@pytest.mark.unit
def test_metrics_that_could_not_be_read_say_nothing_of_being_unobserved() -> None:
    # An empty read is a source that did not answer, not a shop nobody collected
    # from. Saying it went unobserved would be a claim about the service drawn
    # from a failure of the read.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(evidence,
                            some_sources(metrics=metrics_that_answer_with_nothing()))
        ) \
        .then(_it_was_observed_throughout())


@pytest.mark.unit
def test_an_incident_closed_before_its_first_minute_could_be_reported_was_not_unobserved() -> None:
    # A read holds no minute the source has not reported yet, and the newest it
    # can hold by the close is the close's own minute less the source's lag. An
    # incident closed sooner than its first minute is reported finds no row after
    # it began however well the service was watched - the window had not arrived,
    # which is no loss of sight. A disproven alarm is the incident that closes
    # this fast.
    a_source_a_minute_late = 1
    alerted_at = ONSET + timedelta(seconds=7)
    closed_at = ONSET + timedelta(minutes=1, seconds=30)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(started_at=alerted_at,
                                           ended_at=closed_at,
                                           onset_at=None)
        ) \
        .when(
            lambda: measure(evidence,
                            some_sources(
                                metrics=metrics_that_stop_at_the_onset(),
                                metrics_reporting_lag_minutes=a_source_a_minute_late))
        ) \
        .then(_it_was_observed_throughout())


@pytest.mark.unit
def test_the_impact_ends_where_the_service_was_back_to_normal_after_its_recorded_recovery() -> None:
    # Mitigation records when the service fell off the incident's own level,
    # which is what its verdict needs. The harm is over when the service is
    # back inside the range it keeps when nothing is wrong, and a fix landing
    # mid-minute leaves the minutes between the two still broken. The metrics
    # here are broken until RECOVERED_AT and the record says RECORDED_RECOVERY_AT,
    # earlier: looking starts at the record and ends at the first normal minute.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(recorded_recovery_at=RECORDED_RECOVERY_AT)
        ) \
        .when(
            lambda: measure(evidence, some_sources(metrics=metrics_that_recovered()))
        ) \
        .then(
            _it_was_back_to_normal_at(RECOVERED_AT)
        )


@pytest.mark.unit
def test_no_minute_before_the_recorded_recovery_is_where_it_was_back_to_normal() -> None:
    # The record is where looking starts, and belongs to the party that was
    # watching: a lull before Mitigation saw the service leave the incident is
    # not the end of it.
    the_record = RECOVERED_AT + timedelta(minutes=2)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(recorded_recovery_at=the_record)
        ) \
        .when(
            lambda: measure(evidence, some_sources(metrics=metrics_that_recovered()))
        ) \
        .then(
            _it_was_back_to_normal_at(the_record)
        )


@pytest.mark.unit
def test_a_service_never_back_to_normal_after_its_recorded_recovery_reports_no_end() -> None:
    # Off the incident's level and never back inside its range by the last
    # minute read: every figure a lower bound, said as such, rather than an end
    # dated at the record the minutes after it contradict.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(recorded_recovery_at=RECORDED_RECOVERY_AT)
        ) \
        .when(
            lambda: measure(evidence, some_sources())
        ) \
        .then(
            _it_never_recovered()
        )


@pytest.mark.unit
def test_a_service_back_to_normal_in_the_minute_its_fix_landed_ended_at_the_fix() -> None:
    # The minute holding the action reads as normal, and only its seconds after
    # the action can be: it says nothing of the seconds before. The end is the
    # action, and nothing was back before it.
    the_fix = RECOVERED_AT + timedelta(seconds=20)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                recorded_recovery_at=RECORDED_RECOVERY_AT,
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED, taken_at=the_fix)])
        ) \
        .when(
            lambda: measure(evidence, some_sources(metrics=metrics_that_recovered()))
        ) \
        .then(all_of(
            _it_was_back_to_normal_at(the_fix),
            _back_before_the_action(False)
        ))


@pytest.mark.unit
def test_a_service_back_to_normal_before_its_fix_landed_is_found_so() -> None:
    # A whole normal minute ending before the action: the service was back
    # before Argus acted, so the action credited with it did not bring it back -
    # which the write-up has to say rather than end the incident at the action.
    the_fix = RECOVERED_AT + timedelta(minutes=2, seconds=30)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                recorded_recovery_at=RECORDED_RECOVERY_AT,
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED, taken_at=the_fix)])
        ) \
        .when(
            lambda: measure(evidence, some_sources(metrics=metrics_that_recovered()))
        ) \
        .then(all_of(
            _it_was_back_to_normal_at(RECOVERED_AT),
            _back_before_the_action(True)
        ))


@pytest.mark.unit
def test_how_long_argus_held_the_incident_is_measured_apart_from_the_fault() -> None:
    # Two clocks, and the whole defect was one field trying to be both. This
    # one starts at the alert rather than at the onset - the minutes before
    # anybody was told belong to the fault, not to the responder - and it is
    # the only figure on the page measuring Argus rather than the incident,
    # which is why it is kept and why it never stands in for the duration.
    twenty_of_the_thirty_minutes = 20 / 60

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: measure(evidence, some_sources(metrics=metrics_that_recovered()))
        ) \
        .then(all_of(
            _the_time_to_close_was(twenty_of_the_thirty_minutes),
            _ran_for(10 / 60)
        ))


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
def test_the_calm_is_read_back_as_far_as_the_rate_s_own_variation_needs() -> None:
    # Twenty stretches as long as the incident can come to - bounded by its
    # close, since how long it was broken is only known once the read is in.
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
            _asked_metrics_from(ONSET - calm_to_read_for(ENDED_AT - ONSET), windows_asked_for)
        )


@pytest.mark.unit
def test_the_metrics_are_read_for_the_rule_that_paged() -> None:
    # The document reports the rule series' own figures, and only a window read
    # for the rule carries that series. Read for no rule, the postmortem of an
    # incident only that series departed in would describe five series that
    # never moved.
    some_rule = "kuki-rule"
    rules_asked_for: Kept[str | None] = Kept()

    Scenario() \
        .given(
            evidence := an_evidence_bundle(rule=some_rule)
        ) \
        .when(
            lambda: measure(
                evidence,
                some_sources(metrics=metrics_recording_the_rule_into(rules_asked_for)))
        ) \
        .then(
            _asked_metrics_for_the_rule(some_rule, rules_asked_for)
        )


@pytest.mark.unit
def test_how_long_the_paging_rule_waits_is_read_for_the_rule_that_paged() -> None:
    # The rule as it is defined when the document is written, minutes after it
    # paged - the same rule the metrics are read for.
    some_rule = "kuki-rule"
    rules_asked_about: Kept[str] = Kept()

    Scenario() \
        .given(
            evidence := an_evidence_bundle(rule=some_rule)
        ) \
        .when(
            lambda: measure(evidence, some_sources(
                rule_wait=a_rule_waiting(300, asked=rules_asked_about)))
        ) \
        .then(
            all_of(
                _the_rule_waits(timedelta(minutes=5)),
                _asked_how_long_these_rules_wait([some_rule], rules_asked_about)
            )
        )


@pytest.mark.unit
def test_a_rule_whose_wait_could_not_be_read_is_measured_as_unread() -> None:
    # Unread is not "fires at once": a write-up told the rule waits for nothing
    # would call the rule's own wait slow detection.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(rule="dont-care-rule")
        ) \
        .when(
            lambda: measure(evidence, some_sources(rule_wait=a_rule_waiting(None)))
        ) \
        .then(
            _the_rule_wait_was_unread()
        )


@pytest.mark.unit
def test_an_incident_no_rule_paged_for_asks_no_rule_how_long_it_waits() -> None:
    rules_asked_about: Kept[str] = Kept()

    Scenario() \
        .given(
            evidence := an_evidence_bundle(rule=None)
        ) \
        .when(
            lambda: measure(evidence, some_sources(
                rule_wait=a_rule_waiting(300, asked=rules_asked_about)))
        ) \
        .then(
            all_of(
                _the_rule_waits(None),
                _asked_how_long_these_rules_wait([], rules_asked_about)
            )
        )


@pytest.mark.unit
def test_the_rules_series_is_measured_over_the_stretch_the_service_was_broken() -> None:
    # Over the same stretch as the error rate, bounded by the same onset and the
    # same recovery: a series measured to a different end would be a second
    # incident on the same page. The reading at the recovery minute is the worst
    # of all, so a stretch that ran past it would say so.
    some_calm_share = 0.95
    a_bad_minute = 0.42
    the_worst_minute = 0.38
    an_even_worse_minute_once_recovered = 0.10

    Scenario() \
        .given(
            evidence := an_evidence_bundle(recorded_recovery_at=ENDED_AT)
        ) \
        .when(
            lambda: measure(evidence, some_sources(metrics=metrics_whose_rule_series_went(
                baseline=some_calm_share,
                while_broken=a_bad_minute,
                at_its_worst=the_worst_minute,
                worse_when="below",
                once_recovered=an_even_worse_minute_once_recovered
            )))
        ) \
        .then(
            _the_rules_series_was(RuleSeriesLevels(
                baseline=some_calm_share,
                while_broken=(a_bad_minute + the_worst_minute) / 2,
                at_its_worst=the_worst_minute,
                worse_when="below"
            ))
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
        rates = measured.error_rates

        if rates is None or not isclose(rates.rise, expected):
            raise AssertionError(
                f"Expected a rise of [{expected}], got "
                f"[{rates.rise if rates else None}].")

        return True

    return assertion


def _the_rise_is_unknown() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.error_rates is not None:
            raise AssertionError(
                f"Expected no rise where the metrics could not be read, got "
                f"[{measured.error_rates}].")

        return True

    return assertion


def _it_was_back_to_normal_at(expected: datetime) -> Assertion[Measurements]:
    """That the incident was measured as ending at this instant.

    Read off the metrics, so it is a fact about the service. A test asserting
    it against the moment the walk closed the incident would be asserting a
    fact about Argus, which is the substitution all of this exists to undo.
    """
    def assertion(measured: Measurements) -> bool:
        if measured.back_to_normal_at != expected:
            raise AssertionError(
                f"Expected recovery at [{expected}], got "
                f"[{measured.back_to_normal_at}].")

        return True

    return assertion


def _back_before_the_action(expected: bool) -> Assertion[Measurements]:
    """Whether the service was found back to normal before the action credited
    with bringing it back - a finding about attribution, not about the end."""
    def assertion(measured: Measurements) -> bool:
        if measured.back_before_the_action != expected:
            raise AssertionError(
                f"Expected back before the action to be [{expected}], got "
                f"[{measured.back_before_the_action}].")

        return True

    return assertion


def _it_never_recovered() -> Assertion[Measurements]:
    """That the metrics ran out with the service still broken.

    Which makes every figure measured over the window a lower bound. Asserted
    on its own rather than folded into the duration, because a bound and a
    measurement can carry the same number and mean different things.
    """
    def assertion(measured: Measurements) -> bool:
        if measured.back_to_normal_at is not None:
            raise AssertionError(
                f"Expected the window to end still broken, and recovery was "
                f"measured at [{measured.back_to_normal_at}].")

        return True

    return assertion


def _it_was_unobserved_from(expected: datetime) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.unobserved_from != expected:
            raise AssertionError(
                f"Expected the service to be unobserved from [{expected}], got "
                f"[{measured.unobserved_from}].")

        return True

    return assertion


def _it_was_observed_throughout() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.unobserved_from is not None:
            raise AssertionError(
                f"Expected the metrics to cover the incident, and the service "
                f"was measured as unobserved from [{measured.unobserved_from}].")

        return True

    return assertion


def _the_time_to_close_was(expected: float) -> Assertion[Measurements]:
    """That the response clock reads this, whatever the fault's clock reads.

    The one figure measuring Argus rather than the incident, and the reason
    it is kept: the responder is what is under evaluation here. It is asserted
    separately from the duration for the same reason it is reported
    separately - one field answering both questions is where this began.
    """
    def assertion(measured: Measurements) -> bool:
        if not isclose(measured.time_to_close_in_hours, expected):
            raise AssertionError(
                f"Expected a time to close of [{expected}] hours, got "
                f"[{measured.time_to_close_in_hours}].")

        return True

    return assertion


def _the_response_took(expected: int) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if not isinstance(measured.engaged, EngagementAnswer):
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


def _the_rules_series_was(expected: RuleSeriesLevels) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        got = measured.rule_series

        if (
            got is None
            or not isclose(got.baseline, expected.baseline)
            or not isclose(got.while_broken, expected.while_broken)
            or not isclose(got.at_its_worst, expected.at_its_worst)
            or got.worse_when != expected.worse_when
        ):
            raise AssertionError(f"Expected the rule's series at {expected}, got [{got}].")

        return True

    return assertion


def _the_rule_waits(expected: timedelta | None) -> Assertion[Measurements]:
    """How long the paging rule waits, as read - and read, not unread."""
    def assertion(measured: Measurements) -> bool:
        if measured.rule_waits != expected or measured.rule_wait_unread:
            raise AssertionError(
                f"Expected the rule to wait [{expected}], read, got "
                f"[{measured.rule_waits}], unread [{measured.rule_wait_unread}].")

        return True

    return assertion


def _the_rule_wait_was_unread() -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.rule_waits is not None or not measured.rule_wait_unread:
            raise AssertionError(
                f"Expected how long the rule waits to be unread, got "
                f"[{measured.rule_waits}], unread [{measured.rule_wait_unread}].")

        return True

    return assertion


def _asked_how_long_these_rules_wait(rules: list[str],
                                     asked: Kept[str]) -> Assertion[Measurements]:
    def assertion(dont_care_measured: Measurements) -> bool:
        if asked.taken != rules:
            raise AssertionError(
                f"Expected the rules {rules} to be asked how long they wait, got "
                f"{asked.taken}.")

        return True

    return assertion


def _asked_metrics_for_the_rule(rule: str,
                                rules: Kept[str | None]) -> Assertion[Measurements]:
    def assertion(dont_care_measured: Measurements) -> bool:
        asked = rules.only()

        if asked != rule:
            raise AssertionError(
                f"Expected the metrics to be read for the rule [{rule}], "
                f"got [{asked}].")

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


def _asked_metrics_from(window_start: datetime,
                        windows: Kept[tuple[datetime, datetime]]) -> Assertion[Measurements]:
    def assertion(dont_care_measured: Measurements) -> bool:
        asked_from, _ = windows.only()

        if asked_from != window_start:
            raise AssertionError(
                f"Expected the metrics read from [{window_start}], got [{asked_from}].")

        return True

    return assertion


def _a_shop_taking(earlier: Decimal, just_before: Decimal, during: Decimal) -> Revenue:
    """Three stretches as long as an incident shorter than a week: the incident
    itself, the same hours a week before it, and the same hours a week before
    that - told apart by where each window starts."""
    def revenue_between(window_start: datetime,
                        dont_care_end: datetime) -> Mapping[str, Decimal] | None:
        if window_start >= ONSET:
            return {SOME_CURRENCY: during}

        return {SOME_CURRENCY: just_before if window_start >= ONSET - A_WEEK else earlier}

    return revenue_between


def _the_shop_varies_by(expected: Decimal) -> Assertion[Measurements]:
    def assertion(measured: Measurements) -> bool:
        if measured.variation != expected:
            raise AssertionError(
                f"Expected the two calm stretches to differ by [{expected}], got "
                f"[{measured.variation}].")

        return True

    return assertion


def _revenue_recording_the_windows_into(
        windows: Kept[tuple[datetime, datetime]]) -> Revenue:
    """A revenue source noting each window it was asked for, and answering
    that nothing was taken - what is asked of it is the question."""
    def revenue_between(window_start: datetime,
                        window_end: datetime) -> Mapping[str, Decimal] | None:
        windows.take((window_start, window_end))

        return {}

    return revenue_between


def _asked_for_the_takings_over(
        expected: list[tuple[datetime, datetime]],
        windows: Kept[tuple[datetime, datetime]]) -> Assertion[Measurements]:
    def assertion(dont_care_measured: Measurements) -> bool:
        if sorted(windows.taken) != sorted(expected):
            raise AssertionError(
                f"Expected the takings read over {sorted(expected)}, got "
                f"{sorted(windows.taken)}.")

        return True

    return assertion
