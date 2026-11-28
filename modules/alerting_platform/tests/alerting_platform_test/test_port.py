"""The alerting platform's port, as every adapter of it answers.

What the port promises, asked of each adapter over one seed: the Grafana adapter
against a Grafana served in-process (`framework.grafana_world`), and the
in-memory double (`alerting_platform_double`). A promise one of them keeps and
the other does not fails here, so the double cannot drift from the port, and the
port names nothing only Grafana's wire could answer.

The promises and nothing beyond them. Which rule shapes a series is followed
through, and how each of Grafana's answers is read, is `test_grafana.py`'s.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import pytest
from alerting_platform import AlertingPlatform, AlertRuleUnreadable, RuleEvaluation
from alerting_platform.grafana import Grafana
from alerting_platform_double import AlertingState, HeldRule, InMemoryAlertingPlatform
from argus_testkit import Scenario, an_error_was_raised, attempting, the_answer_was
from core.models import RuleLine, RuleSeries, SeriesQuery, Unit, WorseWhen

from alerting_platform_test.framework import GrafanaWorld, grafana_settings

SOME_RULE = "some-rule"
SOME_OTHER_RULE = "some-other-rule"
NO_SUCH_RULE = "no-such-rule"

SOME_QUERY = SeriesQuery("avg(rate(some_errors_total[1m]))")
SOME_LINE_AT = 0.05

# To the microsecond, so a moment the platform cuts is seen cut.
SOME_EVALUATION = datetime(2026, 11, 28, 9, 30, 15, 417000, tzinfo=UTC)

SOME_RANGE_SECONDS = 300
SOME_INTERVAL_SECONDS = 60
SOME_KEEP_FIRING_FOR_SECONDS = 120
SOME_PENDING_SECONDS = 90

SOME_SERIES = RuleSeries(query=SOME_QUERY, worse_when="above",
                         line=RuleLine(at=SOME_LINE_AT, fires_on_it=False))
SOME_OTHER_SERIES = RuleSeries(query=SeriesQuery("max(some_latency_seconds)"), worse_when="below",
                               line=None)
SOME_UNIT = Unit.SHARE_OF_ONE


def _an_evaluation(rule: str = SOME_RULE,
                   *,
                   is_normal: bool = True,
                   series: RuleSeries | None = SOME_SERIES,
                   series_unit: Unit | None = SOME_UNIT) -> RuleEvaluation:
    """A rule's evaluation, every duration a different number - here rather
    than among the helpers below, since the cases' parameters are built from
    it."""
    return RuleEvaluation(rule=rule,
                          is_normal=is_normal,
                          evaluated_at=SOME_EVALUATION,
                          range_seconds=SOME_RANGE_SECONDS,
                          interval_seconds=SOME_INTERVAL_SECONDS,
                          keep_firing_for_seconds=SOME_KEEP_FIRING_FOR_SECONDS,
                          pending_seconds=SOME_PENDING_SECONDS,
                          series=series,
                          series_unit=series_unit)


class _StandsUp(Protocol):
    def __call__(self, state: AlertingState, *, unreachable: bool = ...) -> AlertingPlatform:
        ...


def _in_memory(state: AlertingState, *, unreachable: bool = False) -> AlertingPlatform:
    return InMemoryAlertingPlatform(state, unreachable=unreachable)


def _grafana(state: AlertingState, *, unreachable: bool = False) -> AlertingPlatform:
    return Grafana(grafana_settings(), get=GrafanaWorld(state, unreachable=unreachable).get)


EVERY_ADAPTER = pytest.mark.parametrize("stand_up", [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_grafana, id="grafana")
])


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("is_normal", [
    pytest.param(True, id="normal"),
    pytest.param(False, id="firing")
])
@pytest.mark.parametrize(("worse_when", "line"), [
    pytest.param("above", RuleLine(at=SOME_LINE_AT, fires_on_it=False), id="above-the-line"),
    pytest.param("above", RuleLine(at=SOME_LINE_AT, fires_on_it=True), id="on-or-above-the-line"),
    pytest.param("below", RuleLine(at=SOME_LINE_AT, fires_on_it=False), id="below-the-line"),
    pytest.param("below", RuleLine(at=SOME_LINE_AT, fires_on_it=True), id="on-or-below-the-line"),
    pytest.param("above", None, id="above-no-line"),
    pytest.param("below", None, id="below-no-line")
])
def test_an_evaluation_is_the_rule_as_the_platform_keeps_it(
    stand_up: _StandsUp, is_normal: bool, worse_when: WorseWhen, line: RuleLine | None
) -> None:
    # Another rule held first, so an adapter answering the first rule it holds
    # would be caught.
    evaluation = _an_evaluation(is_normal=is_normal,
                                series=RuleSeries(query=SOME_QUERY, worse_when=worse_when,
                                                  line=line))

    Scenario() \
        .given(platform := stand_up(_a_platform_holding(
            _an_evaluation(SOME_OTHER_RULE, is_normal=not is_normal, series=None), evaluation
        ))) \
        .when(lambda: platform.evaluation_of(SOME_RULE)) \
        .then(the_answer_was(evaluation))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("unit", list(Unit))
def test_the_unit_a_rule_s_series_is_shown_in_is_answered_beside_it(
    stand_up: _StandsUp, unit: Unit
) -> None:
    Scenario() \
        .given(platform := stand_up(_a_platform_holding(_an_evaluation(series_unit=unit)))) \
        .when(lambda: platform.evaluation_of(SOME_RULE).series_unit) \
        .then(the_answer_was(unit))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_rule_with_no_series_has_no_unit_whatever_its_panel_shows(
    stand_up: _StandsUp
) -> None:
    # The panel shows a unit, and there is no series for it to be the unit of
    # - so a unit handed on would be one no series query stands beside.
    Scenario() \
        .given(platform := stand_up(_a_platform_holding(
            _an_evaluation(series=None, series_unit=SOME_UNIT)
        ))) \
        .when(lambda: platform.evaluation_of(SOME_RULE)) \
        .then(the_answer_was(_an_evaluation(series=None, series_unit=None)))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("rule", "measured", "unreachable"), [
    pytest.param(NO_SUCH_RULE, True, False, id="a rule the platform does not evaluate"),
    pytest.param(SOME_RULE, False, False, id="an evaluation that measured nothing"),
    pytest.param(SOME_RULE, True, True, id="a platform nothing reaches")
])
def test_an_evaluation_the_platform_cannot_vouch_for_is_refused_rather_than_normal(
    stand_up: _StandsUp, rule: str, measured: bool, unreachable: bool
) -> None:
    # Normal, as held: an adapter that answered at all would answer normal.
    Scenario() \
        .given(platform := stand_up(
            AlertingState(rules=(HeldRule(evaluation=_an_evaluation(), measured=measured),)),
            unreachable=unreachable
        )) \
        .when(attempting(lambda: platform.evaluation_of(rule))) \
        .then(an_error_was_raised(AlertRuleUnreadable))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("measured", [
    pytest.param(True, id="measured"),
    pytest.param(False, id="measured-nothing")
])
def test_the_series_a_rule_watches_is_its_own_whatever_its_last_evaluation_measured(
    stand_up: _StandsUp, measured: bool
) -> None:
    # Another rule, watching another series, held first.
    Scenario() \
        .given(platform := stand_up(AlertingState(rules=(
            HeldRule(evaluation=_an_evaluation(SOME_OTHER_RULE, series=SOME_OTHER_SERIES)),
            HeldRule(evaluation=_an_evaluation(), measured=measured)
        )))) \
        .when(lambda: platform.series_of(SOME_RULE)) \
        .then(the_answer_was(SOME_SERIES))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("rule", "unreachable"), [
    pytest.param(SOME_OTHER_RULE, False, id="a rule with no series"),
    pytest.param(NO_SUCH_RULE, False, id="a rule the platform does not evaluate"),
    pytest.param(SOME_RULE, True, id="a platform nothing reaches")
])
def test_a_series_that_cannot_be_said_is_none_rather_than_refused(
    stand_up: _StandsUp, rule: str, unreachable: bool
) -> None:
    Scenario() \
        .given(platform := stand_up(_a_platform_holding(
            _an_evaluation(), _an_evaluation(SOME_OTHER_RULE, series=None)
        ), unreachable=unreachable)) \
        .when(lambda: platform.series_of(rule)) \
        .then(the_answer_was(None))


def _a_platform_holding(*evaluations: RuleEvaluation) -> AlertingState:
    """A platform whose every rule's last evaluation measured something."""
    return AlertingState(rules=tuple(HeldRule(evaluation=each) for each in evaluations))
