"""What the incident cost the business, term by term.

Two quantities, measured separately and never multiplied: the loss itself,
which is a subtraction between two sums a payment provider reported, and the
rise in errors, which no figure rests on and which exists to tell the model
what happened.

Every case here is arithmetic. Nothing asks a model anything - a figure a
model could be talked out of is not a measurement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import isclose

import pytest
from agent_postmortem.estimate import (
    ErrorRates,
    RuleSeriesLevels,
    Unmeasured,
    beyond_the_variation,
    calm_to_read_for,
    error_rates_over,
    rule_series_over,
    why_no_error_rates,
)
from argus_core.models import MetricBucket, RuleReading, WorseWhen
from argus_testkit import Assertion, Scenario, the_answer_was

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)

DONT_CARE_ERROR_RATE = 0.5


@pytest.mark.unit
def test_the_rise_is_measured_against_the_calm_minutes_before_it() -> None:
    # Not the raw rate while it was broken. A service that always fails two
    # requests in a hundred did not start doing so because of this incident,
    # and charging those to it overstates every estimate by the same amount.
    some_baseline_error_rate = 0.02
    some_error_rate_while_broken = 0.30
    some_recovery = INCIDENT_END
    some_time_before_the_incident = timedelta(minutes=2)
    some_time_into_the_incident = timedelta(minutes=5)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - some_time_before_the_incident,
                          error_rate=some_baseline_error_rate),
                _a_bucket(at=INCIDENT_START + some_time_into_the_incident,
                          error_rate=some_error_rate_while_broken)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, some_recovery)
        ) \
        .then(
            _is_a_rise_of(some_error_rate_while_broken - some_baseline_error_rate)
        )


@pytest.mark.unit
def test_the_levels_are_measured_beside_the_rise() -> None:
    # Two questions, two numbers. The model reached past the rise for the
    # per-minute figures because severity is what it was being asked, and the
    # rise cannot answer that - a service that idles at 30% and one that idles
    # at nothing can rise by the same amount and be in very different trouble.
    some_baseline_error_rate = 0.02
    a_bad_minute = 0.30
    the_worst_minute = 0.34
    some_recovery = INCIDENT_END

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          error_rate=some_baseline_error_rate),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          error_rate=a_bad_minute),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=6),
                          error_rate=the_worst_minute)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, some_recovery)
        ) \
        .then(
            _the_levels_are(baseline=some_baseline_error_rate,
                            while_broken=(a_bad_minute + the_worst_minute) / 2,
                            at_its_worst=the_worst_minute)
        )


@pytest.mark.unit
def test_minutes_after_the_service_recovered_are_not_counted() -> None:
    # The defect this whole change is about. The window used to run to the
    # moment the walk closed the incident, which is minutes or hours of
    # healthy traffic after the mitigation landed - and averaging those in
    # drags the figure towards the baseline until the rise reads as nothing,
    # or as less than nothing.
    some_baseline_error_rate = 0.02
    some_error_rate_while_broken = 0.32
    a_healthy_minute_after_it = 0.01
    the_minute_it_recovered = INCIDENT_START + timedelta(minutes=6)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          error_rate=some_baseline_error_rate),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          error_rate=some_error_rate_while_broken),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=20),
                          error_rate=a_healthy_minute_after_it)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, the_minute_it_recovered)
        ) \
        .then(
            _is_a_rise_of(some_error_rate_while_broken - some_baseline_error_rate)
        )


@pytest.mark.unit
def test_the_requests_that_failed_are_counted_over_the_broken_minutes() -> None:
    # What a reader asks after how long and how bad: how many it hit. Each
    # broken minute's requests at that minute's rate, and no calm minute's.
    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2), error_rate=0.02),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5), error_rate=0.30),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=6), error_rate=0.25)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _counts_failed_requests(550)
        )


@pytest.mark.unit
def test_the_baseline_is_the_hour_before_it_began_however_far_back_the_calm_was_read() -> None:
    # The calm is read further back than the hour for how far the rate varies
    # on its own. The level a rise is measured from stays the last hour's:
    # hours earlier is another part of the day.
    some_rate_hours_earlier = 0.10
    some_baseline_error_rate = 0.02
    some_error_rate_while_broken = 0.30

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(hours=3),
                          error_rate=some_rate_hours_earlier),
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          error_rate=some_baseline_error_rate),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          error_rate=some_error_rate_while_broken)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _is_a_rise_of(some_error_rate_while_broken - some_baseline_error_rate)
        )


@pytest.mark.unit
def test_a_calm_stretch_noisier_than_the_broken_one_reports_a_negative_rise() -> None:
    # Deliberately not clamped. Once the window is bounded by the signal
    # rather than by the workflow, a negative rise is no longer an artefact of
    # counting healthy minutes - it says the hour before the incident was
    # worse than the incident, which is a defect report about the baseline or
    # the onset and is worth seeing rather than rounding away.
    a_noisy_calm_hour = 0.40
    a_milder_broken_stretch = 0.05
    some_recovery = INCIDENT_END

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          error_rate=a_noisy_calm_hour),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          error_rate=a_milder_broken_stretch)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, some_recovery)
        ) \
        .then(
            _is_a_rise_of(a_milder_broken_stretch - a_noisy_calm_hour)
        )


@pytest.mark.unit
def test_how_high_the_rate_goes_on_its_own_is_read_from_stretches_as_long_in_the_calm() -> None:
    # A rise is only a rise where the broken stretch went higher than the calm
    # goes by itself over as long - the 95th percentile of every stretch that
    # long before it began, averaged, and its worst minute. Two broken minutes
    # here, so thirty-nine two-minute stretches - twenty of them apart - in
    # forty calm minutes rising by a point each.
    Scenario() \
        .given(
            buckets := [
                *(_a_bucket(at=INCIDENT_START - timedelta(minutes=40 - minute),
                            error_rate=minute / 100)
                  for minute in range(40)),
                _a_bucket(at=INCIDENT_START, error_rate=DONT_CARE_ERROR_RATE),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=1),
                          error_rate=DONT_CARE_ERROR_RATE)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, INCIDENT_START + timedelta(minutes=2))
        ) \
        .then(
            _goes_on_its_own_to(usual_ceiling=0.366, usual_worst=0.371)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("calm_minutes", "broken_minutes"), [
    pytest.param(5, 1, id="five-stretches"),
    pytest.param(40, 3, id="thirteen-stretches-apart-of-thirty-eight-overlapping")
])
def test_a_calm_too_short_to_hold_twenty_stretches_apart_says_nothing_of_how_high_it_goes(
    calm_minutes: int, broken_minutes: int
) -> None:
    # The 95th percentile is the value one stretch in twenty passes, and with
    # fewer than twenty there is no such value to hold the broken stretch to.
    # Twenty that do not share a minute: stretches overlapping each other are
    # mostly the same minutes, and thirty-eight of them say no more of how the
    # rate varies than the thirteen that are apart.
    Scenario() \
        .given(
            buckets := [
                *(_a_bucket(at=INCIDENT_START - timedelta(minutes=minute),
                            error_rate=DONT_CARE_ERROR_RATE)
                  for minute in range(1, calm_minutes + 1)),
                *(_a_bucket(at=INCIDENT_START + timedelta(minutes=minute),
                            error_rate=DONT_CARE_ERROR_RATE)
                  for minute in range(broken_minutes))
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START,
                                     INCIDENT_START + timedelta(minutes=broken_minutes))
        ) \
        .then(
            _goes_on_its_own_to(usual_ceiling=None, usual_worst=None)
        )


@pytest.mark.unit
def test_a_calm_as_long_as_the_read_for_a_span_holds_enough_stretches_to_vary_in() -> None:
    # The read is sized before the broken stretch is known, from the longest it
    # can come to. Never seen to recover, the stretch runs to the read's end,
    # and a range read answers for both its ends: ten minutes from one minute's
    # start to another's is eleven minutes read.
    some_span = timedelta(minutes=10)
    calm_minutes = calm_to_read_for(some_span) // timedelta(minutes=1)

    Scenario() \
        .given(
            buckets := [
                *(_a_bucket(at=INCIDENT_START - timedelta(minutes=minute))
                  for minute in range(1, calm_minutes + 1)),
                *(_a_bucket(at=INCIDENT_START + timedelta(minutes=minute))
                  for minute in range(11))
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, None)
        ) \
        .then(
            _its_variation_is_known()
        )


@pytest.mark.unit
@pytest.mark.parametrize(("span", "calm"), [
    pytest.param(timedelta(minutes=1), timedelta(hours=1), id="never-less-than-the-hour"),
    pytest.param(timedelta(days=30), timedelta(weeks=1), id="never-more-than-a-week")
])
def test_the_calm_read_for_a_span_is_never_shorter_than_the_hour_or_longer_than_a_week(
    span: timedelta, calm: timedelta
) -> None:
    # The hour is the baseline's, whatever the span. A week covers incidents of
    # most of a working day, inside the fortnight a metrics store keeps by
    # default; past it the calm is too short and the variation says so.
    Scenario() \
        .when(
            lambda: calm_to_read_for(span)
        ) \
        .then(
            the_answer_was(calm)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("while_broken", "at_its_worst", "usual", "rose", "peaked"), [
    pytest.param(0.011, 0.015, (0.012, 0.02), False, False, id="within-its-variation"),
    pytest.param(0.30, 0.34, (0.012, 0.02), True, True, id="beyond-its-variation"),
    pytest.param(0.30, 0.34, (None, None), None, None, id="variation-unknown")
])
def test_a_rise_is_beyond_the_rate_s_own_variation_only_above_how_high_it_goes_alone(
    while_broken: float,
    at_its_worst: float,
    usual: tuple[float | None, float | None],
    rose: bool | None,
    peaked: bool | None
) -> None:
    Scenario() \
        .given(
            some_rates := ErrorRates(baseline=0.01, while_broken=while_broken,
                                     at_its_worst=at_its_worst,
                                     usual_ceiling=usual[0], usual_worst=usual[1])
        ) \
        .when(
            lambda: (some_rates.rose_beyond_its_variation, some_rates.peaked_beyond_its_variation)
        ) \
        .then(
            the_answer_was((rose, peaked))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("while_broken", "usual_ceiling", "measured"), [
    pytest.param(0.30, 0.012, True, id="beyond-its-variation"),
    pytest.param(0.011, 0.012, False, id="within-its-variation"),
    pytest.param(0.009, 0.005, False, id="below-the-baseline"),
    pytest.param(0.30, None, False, id="variation-unknown")
])
def test_a_rise_in_failed_requests_is_measured_only_above_the_baseline_and_beyond_its_variation(
        while_broken: float, usual_ceiling: float | None, measured: bool) -> None:
    # A rise nobody can tell from the rate's own noise is no rise measured, and
    # nor is one whose noise nobody could measure, nor a stretch better than the
    # calm before it. Both the brief and the impact cards say "no rise" from
    # this one answer, so the two cannot disagree about it.
    Scenario() \
        .given(
            some_rates := ErrorRates(baseline=0.01, while_broken=while_broken,
                                     at_its_worst=while_broken,
                                     usual_ceiling=usual_ceiling, usual_worst=None)
        ) \
        .when(
            lambda: some_rates.a_rise_was_measured
        ) \
        .then(
            the_answer_was(measured)
        )


@pytest.mark.unit
def test_a_window_with_no_calm_minutes_measures_nothing_at_all() -> None:
    # A delta against nothing is not a small delta - there is no baseline to
    # say what "normal" was, and answering zero would report an incident that
    # cost nothing rather than a question nobody could answer.
    some_time_after_the_incident = timedelta(minutes=5)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START + some_time_after_the_incident,
                          error_rate=DONT_CARE_ERROR_RATE)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _nothing_could_be_measured()
        )


@pytest.mark.unit
def test_a_window_with_no_minutes_inside_the_broken_stretch_measures_nothing() -> None:
    # The mirror case, and the one a too-narrow window produces: metrics that
    # stop before the incident starts describe a service that was fine.
    some_time_before_the_incident = timedelta(minutes=2)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - some_time_before_the_incident,
                          error_rate=DONT_CARE_ERROR_RATE)
            ]
        ) \
        .when(
            lambda: error_rates_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _nothing_could_be_measured()
        )


@pytest.mark.unit
def test_a_read_that_returned_no_minute_is_unmeasured_for_want_of_any() -> None:
    # The rates can be missing for three reasons, and a reader is owed which: a
    # read that came back empty is an outage of the metrics, not of the shop.
    Scenario() \
        .given(
            buckets := list[MetricBucket]()
        ) \
        .when(
            lambda: why_no_error_rates(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            the_answer_was(Unmeasured.NOTHING_READ)
        )


@pytest.mark.unit
def test_no_minute_before_the_onset_is_unmeasured_for_want_of_a_calm_stretch() -> None:
    # A fault found a week after it began: the read reaches back only so far,
    # every minute it holds is after the onset, and nothing is left to call
    # normal. The metrics were read - they did not reach.
    Scenario() \
        .given(
            buckets := [_a_bucket(at=INCIDENT_START + timedelta(minutes=5))]
        ) \
        .when(
            lambda: why_no_error_rates(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            the_answer_was(Unmeasured.NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET)
        )


@pytest.mark.unit
def test_calm_read_only_before_the_hour_measures_nothing_and_says_why() -> None:
    # A gap in the metrics across the hour before the onset, with calm further
    # back: there is a variation to read and no level to measure a rise from.
    # Said as the hour that is missing - "nothing before the onset" would be
    # false, and a mean of no minutes is no figure at all.
    Scenario() \
        .given(
            buckets := [_a_bucket(at=INCIDENT_START - timedelta(hours=3)),
                        _a_bucket(at=INCIDENT_START + timedelta(minutes=5))]
        ) \
        .when(
            lambda: (error_rates_over(buckets, INCIDENT_START, INCIDENT_END),
                     why_no_error_rates(buckets, INCIDENT_START, INCIDENT_END))
        ) \
        .then(
            the_answer_was((None, Unmeasured.NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET))
        )


@pytest.mark.unit
def test_no_minute_inside_the_broken_stretch_is_unmeasured_for_want_of_one() -> None:
    # Metrics that stop before the incident starts: a calm hour, and nothing
    # read of the trouble itself.
    Scenario() \
        .given(
            buckets := [_a_bucket(at=INCIDENT_START - timedelta(minutes=2))]
        ) \
        .when(
            lambda: why_no_error_rates(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            the_answer_was(Unmeasured.NO_MINUTE_WHILE_BROKEN)
        )


@pytest.mark.unit
def test_rates_that_could_be_measured_are_missing_for_no_reason() -> None:
    Scenario() \
        .given(
            buckets := [_a_bucket(at=INCIDENT_START - timedelta(minutes=2)),
                        _a_bucket(at=INCIDENT_START + timedelta(minutes=5))]
        ) \
        .when(
            lambda: why_no_error_rates(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_the_rules_series_is_measured_at_the_levels_the_error_rate_is() -> None:
    # The one series a fault in what the service answers moves, so the one a
    # reader of that incident needs the levels of: what it was before, what it
    # was while broken, and how bad it got. Its worst is its lowest here, because
    # the rule calls it worse falling - a share of confident answers at its
    # highest is the service at its best.
    some_calm_share = 0.95
    a_bad_minute = 0.42
    the_worst_minute = 0.38

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          rule_reading=RuleReading(value=some_calm_share, worse_when="below")),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          rule_reading=RuleReading(value=a_bad_minute, worse_when="below")),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=6),
                          rule_reading=RuleReading(value=the_worst_minute, worse_when="below"))
            ]
        ) \
        .when(
            lambda: rule_series_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _the_rules_levels_are(RuleSeriesLevels(
                baseline=some_calm_share,
                while_broken=(a_bad_minute + the_worst_minute) / 2,
                at_its_worst=the_worst_minute,
                worse_when="below"
            ))
        )


@pytest.mark.unit
def test_the_rules_series_is_measured_from_the_hour_before_it_began_only() -> None:
    # As the error rate is: the calm read further back is for how far a rate
    # varies, and the level the incident is measured from is the last hour's.
    some_reading_hours_earlier = 0.60
    some_calm_share = 0.95
    the_worst_minute = 0.38

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(hours=3),
                          rule_reading=RuleReading(value=some_reading_hours_earlier,
                                                   worse_when="below")),
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          rule_reading=RuleReading(value=some_calm_share, worse_when="below")),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          rule_reading=RuleReading(value=the_worst_minute, worse_when="below"))
            ]
        ) \
        .when(
            lambda: rule_series_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _the_rules_levels_are(RuleSeriesLevels(
                baseline=some_calm_share,
                while_broken=the_worst_minute,
                at_its_worst=the_worst_minute,
                worse_when="below"
            ))
        )


@pytest.mark.unit
def test_the_worst_of_a_series_its_rule_calls_worse_rising_is_its_highest() -> None:
    # The other direction, and the reason the rule's own is carried: the same
    # three minutes have a different worst depending on which way the rule
    # fires, and only the rule knows.
    some_calm_level = 0.10
    a_bad_minute = 0.60
    the_worst_minute = 0.75

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          rule_reading=RuleReading(value=some_calm_level, worse_when="above")),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          rule_reading=RuleReading(value=the_worst_minute, worse_when="above")),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=6),
                          rule_reading=RuleReading(value=a_bad_minute, worse_when="above"))
            ]
        ) \
        .when(
            lambda: rule_series_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _the_rules_levels_are(RuleSeriesLevels(
                baseline=some_calm_level,
                while_broken=(a_bad_minute + the_worst_minute) / 2,
                at_its_worst=the_worst_minute,
                worse_when="above"
            ))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("worse_when", "while_broken", "got_worse"), [
    pytest.param("below", 0.46, True, id="fell-where-falling-is-worse"),
    pytest.param("below", 0.95, False, id="rose-where-falling-is-worse"),
    pytest.param("above", 0.95, True, id="rose-where-rising-is-worse"),
    pytest.param("above", 0.46, False, id="fell-where-rising-is-worse"),
    pytest.param("below", 0.90, False, id="held")
])
def test_a_series_got_worse_only_where_it_sat_on_its_rule_s_worse_side_of_before(
        worse_when: WorseWhen, while_broken: float, got_worse: bool) -> None:
    # On average while broken, and by the rule's own direction: a share of
    # confident answers is worse lower, a latency worse higher. No band of
    # usual variation, as the error rate has - the rule fired on this series,
    # so it crossed a line its owner drew.
    Scenario() \
        .given(
            some_levels := RuleSeriesLevels(baseline=0.90, while_broken=while_broken,
                                            at_its_worst=while_broken, worse_when=worse_when)
        ) \
        .when(
            lambda: some_levels.got_worse
        ) \
        .then(
            the_answer_was(got_worse)
        )


@pytest.mark.unit
def test_a_window_carrying_no_rules_series_measures_none() -> None:
    # A window read for no rule has no such series, and none is not a level of
    # zero: a series nobody read reported as having sat at nothing would be an
    # incident that broke its answers entirely.
    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2)),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5))
            ]
        ) \
        .when(
            lambda: rule_series_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _no_rules_series_was_measured()
        )


@pytest.mark.unit
def test_a_reading_once_the_service_recovered_is_not_counted_in_the_rules_series() -> None:
    # The bound the error rate keeps, and the one a series is likelier to test:
    # a share of confident answers can go on sagging past the minute the service
    # came back, and the recovery minute itself is the first one that is not the
    # incident however it reads.
    some_calm_share = 0.95
    the_worst_minute_while_broken = 0.42
    an_even_worse_minute_once_recovered = 0.10
    the_minute_it_recovered = INCIDENT_START + timedelta(minutes=6)

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          rule_reading=RuleReading(value=some_calm_share, worse_when="below")),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          rule_reading=RuleReading(value=the_worst_minute_while_broken,
                                                   worse_when="below")),
                _a_bucket(at=the_minute_it_recovered,
                          rule_reading=RuleReading(value=an_even_worse_minute_once_recovered,
                                                   worse_when="below"))
            ]
        ) \
        .when(
            lambda: rule_series_over(buckets, INCIDENT_START, the_minute_it_recovered)
        ) \
        .then(
            _the_rules_levels_are(RuleSeriesLevels(
                baseline=some_calm_share,
                while_broken=the_worst_minute_while_broken,
                at_its_worst=the_worst_minute_while_broken,
                worse_when="below"
            ))
        )


@pytest.mark.unit
def test_a_minute_without_a_reading_does_not_count_towards_the_rules_series() -> None:
    # A minute the series was not read in has no level of it, and counting it
    # as one - as zero, or as the minute before - would put a figure in the mean
    # that nobody measured.
    some_calm_share = 0.95
    the_one_broken_reading = 0.42

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2),
                          rule_reading=RuleReading(value=some_calm_share, worse_when="below")),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          rule_reading=RuleReading(value=the_one_broken_reading,
                                                   worse_when="below")),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=6))
            ]
        ) \
        .when(
            lambda: rule_series_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _the_rules_levels_are(RuleSeriesLevels(
                baseline=some_calm_share,
                while_broken=the_one_broken_reading,
                at_its_worst=the_one_broken_reading,
                worse_when="below"
            ))
        )


@pytest.mark.unit
def test_a_rules_series_with_no_calm_reading_measures_none() -> None:
    # Read only once the service was broken, the series has levels and nothing
    # to say they are worse than - and a level against nothing is an unanswered
    # question, not a small answer.
    dont_care_reading = 0.42

    Scenario() \
        .given(
            buckets := [
                _a_bucket(at=INCIDENT_START - timedelta(minutes=2)),
                _a_bucket(at=INCIDENT_START + timedelta(minutes=5),
                          rule_reading=RuleReading(value=dont_care_reading,
                                                   worse_when="below"))
            ]
        ) \
        .when(
            lambda: rule_series_over(buckets, INCIDENT_START, INCIDENT_END)
        ) \
        .then(
            _no_rules_series_was_measured()
        )


@pytest.mark.unit
def test_a_shop_that_took_more_than_before_lost_nothing_rather_than_less_than_nothing() -> None:
    # A quiet stretch before a busy incident. The subtraction goes negative and
    # the answer does not: a negative loss is not a small loss, it is a
    # category error, and zero here is a measurement rather than an absence.
    some_busier_incident_s_shortfall = Decimal("-800")
    some_shop_that_never_varies = Decimal(0)

    Scenario() \
        .when(
            lambda: beyond_the_variation(some_busier_incident_s_shortfall,
                                         some_shop_that_never_varies)
        ) \
        .then(
            _estimates(Decimal(0))
        )


@pytest.mark.unit
def test_a_shortfall_no_larger_than_the_shop_s_own_variation_is_no_loss() -> None:
    # Two calm stretches back to back differ by some amount on their own. A
    # shortfall inside that is the shop being the shop - and scaled out over a
    # week it became six figures nobody lost.
    some_variation = Decimal("300")
    some_shortfall_within_it = Decimal("250")

    Scenario() \
        .when(
            lambda: beyond_the_variation(some_shortfall_within_it, some_variation)
        ) \
        .then(
            _estimates(Decimal(0))
        )


@pytest.mark.unit
def test_a_shortfall_beyond_the_shop_s_own_variation_is_lost_in_full() -> None:
    # Not less the variation: the variation says whether anything was lost,
    # and the shortfall says how much.
    some_variation = Decimal("300")
    some_shortfall_beyond_it = Decimal("4500")

    Scenario() \
        .when(
            lambda: beyond_the_variation(some_shortfall_beyond_it, some_variation)
        ) \
        .then(
            _estimates(some_shortfall_beyond_it)
        )


def _estimates(expected: Decimal) -> Assertion[Decimal]:
    def assertion(estimate: Decimal) -> bool:
        if estimate != expected:
            raise AssertionError(f"Expected a loss of [{expected}], got [{estimate}].")

        return True

    return assertion


def _a_bucket(at: datetime,
              error_rate: float = DONT_CARE_ERROR_RATE,
              rule_reading: RuleReading | None = None) -> MetricBucket:
    return MetricBucket(
        bucket_id=at.strftime("%Y-%m-%dT%H:%M"),
        error_rate=error_rate,
        p50_ms=20,
        p95_ms=40,
        p99_ms=90,
        request_volume=1_000,
        memory_used_bytes=440 * 1024**2,
        process_start_time_seconds=1_756_000_000.0,
        cpu_used_cores=0.77,
        cpu_limit_cores=3.0,
        rule_reading=rule_reading
    )


def _counts_failed_requests(expected: int) -> Assertion[ErrorRates | None]:
    def assertion(measured: ErrorRates | None) -> bool:
        if measured is None or measured.failed_requests != expected:
            raise AssertionError(
                f"Expected [{expected}] failed requests, got "
                f"[{measured.failed_requests if measured else None}].")

        return True

    return assertion


def _is_a_rise_of(expected: float) -> Assertion[ErrorRates | None]:
    def assertion(measured: ErrorRates | None) -> bool:
        if measured is None or not isclose(measured.rise, expected):
            raise AssertionError(
                f"Expected a rise of [{expected}], got "
                f"[{measured.rise if measured else None}]."
            )
        return True

    return assertion


def _goes_on_its_own_to(usual_ceiling: float | None,
                        usual_worst: float | None) -> Assertion[ErrorRates | None]:
    def assertion(measured: ErrorRates | None) -> bool:
        said = (measured.usual_ceiling, measured.usual_worst) if measured else None

        if said is None or not all(
                (got is None and wanted is None)
                or (got is not None and wanted is not None and isclose(got, wanted))
                for got, wanted in zip(said, (usual_ceiling, usual_worst), strict=True)):
            raise AssertionError(
                f"Expected the error rate to go on its own to [{usual_ceiling}] on average "
                f"and [{usual_worst}] at worst, got {said}.")

        return True

    return assertion


def _its_variation_is_known() -> Assertion[ErrorRates | None]:
    def assertion(measured: ErrorRates | None) -> bool:
        said = (measured.usual_ceiling, measured.usual_worst) if measured else None

        if said is None or None in said:
            raise AssertionError(
                f"Expected how high the rate goes on its own to be known, got {said}.")

        return True

    return assertion


def _the_levels_are(baseline: float,
                    while_broken: float,
                    at_its_worst: float) -> Assertion[ErrorRates | None]:
    """That all three levels came back, not only the rise.

    The rise answers attribution - how much of the traffic failed that would
    not have failed anyway - and the levels answer severity. One number was
    being asked both questions, and the labelling defect is what that looked
    like from the outside.
    """
    def assertion(measured: ErrorRates | None) -> bool:
        if measured is None:
            raise AssertionError("Expected three levels, nothing was measured.")

        got = (measured.baseline, measured.while_broken, measured.at_its_worst)
        expected = (baseline, while_broken, at_its_worst)

        if not all(isclose(one, other) for one, other in zip(got, expected, strict=True)):
            raise AssertionError(f"Expected levels {expected}, got {got}")

        return True

    return assertion


def _the_rules_levels_are(expected: RuleSeriesLevels) -> Assertion[RuleSeriesLevels | None]:
    def assertion(measured: RuleSeriesLevels | None) -> bool:
        if measured is None:
            raise AssertionError(
                f"Expected the rule's series measured at {expected}, nothing was measured.")

        got = (measured.baseline, measured.while_broken, measured.at_its_worst)
        wanted = (expected.baseline, expected.while_broken, expected.at_its_worst)

        if (
            not all(isclose(one, other) for one, other in zip(got, wanted, strict=True))
            or measured.worse_when != expected.worse_when
        ):
            raise AssertionError(f"Expected the rule's series at {expected}, got {measured}.")

        return True

    return assertion


def _no_rules_series_was_measured() -> Assertion[RuleSeriesLevels | None]:
    def assertion(measured: RuleSeriesLevels | None) -> bool:
        if measured is not None:
            raise AssertionError(
                f"Expected the rule's series left unmeasured, got [{measured}].")

        return True

    return assertion


def _nothing_could_be_measured() -> Assertion[ErrorRates | None]:
    def assertion(measured: ErrorRates | None) -> bool:
        if measured is not None:
            raise AssertionError(
                f"Expected no measurement where one side of it is missing, "
                f"got [{measured}].")
        return True

    return assertion
