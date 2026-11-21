"""Where an alert rule stands, as the read tier answers it: two ports' answers,
met.

The alerting platform says where the rule stands, which series it watches and
the unit its dashboard shows that series in. The metrics source says what the
series measures and the unit its metric's name carries. What is decided here is
only how the two meet: the dashboard's unit before the name's, and the series
classified only where there is one.

The `integration` cases at the end compose the standing from the real Grafana
adapter, reading a faked Grafana over its HTTP client, and the real Prometheus
classifier - so the query the one reads out of a rule is the query the other
says the meaning of, with nothing between.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import create_autospec

import httpx2
import pytest
from alerting_platform import AlertingPlatform, AlertRuleUnreadable, RuleEvaluation
from alerting_platform.grafana import (
    ANNOTATIONS,
    CONDITION,
    CONDITIONS,
    DASHBOARD,
    DASHBOARD_PATH,
    DASHBOARD_UID_ANNOTATION,
    DATA,
    DATASOURCE_UID,
    DEFAULTS,
    EVALUATOR,
    EXPR,
    EXPRESSION,
    EXPRESSION_DATASOURCE,
    FIELD_CONFIG,
    FOLDER_UID,
    GROUPS,
    GT,
    HEALTH,
    HEALTHY,
    ID,
    INACTIVE,
    INTERVAL,
    LAST_EVALUATION,
    MILLISECONDS_UNIT,
    MODEL,
    PANEL_ID_ANNOTATION,
    PANELS,
    PARAMS,
    REDUCE,
    REF_ID,
    RULE_DEFINITION_PATH,
    RULE_GROUP,
    RULE_GROUP_PATH,
    RULE_STATE_PATH,
    RULES,
    STATE,
    THRESHOLD,
    TYPE,
    UID,
    UNIT,
    Grafana,
    GrafanaSettings,
)
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised, the_answer_was
from argus_testkit.scenario import Scenario, attempting
from core.models import AlertRuleStanding, RuleLine, RuleSeries, SeriesQuery, Unit
from metrics_source import Measure, SeriesClassifier, SeriesKind
from metrics_source.prometheus_adapter import QUERIES, what_the_series_is
from read_mcp_server.alert_rules import how_the_rule_stands

SOME_RULE = "some-rule"
SOME_EVALUATION = datetime(2026, 10, 6, 10, 20, tzinfo=UTC)
SOME_QUERY = SeriesQuery("avg(some_confident_ratio)")
SOME_SERIES = RuleSeries(query=SOME_QUERY, worse_when="below",
                         line=RuleLine(at=0.8, fires_on_it=False))

# Where the faked Grafana answers, and the folder, group, dashboard and panel
# its rule names.
SOME_BASE_URL = "http://grafana.invalid"
SOME_FOLDER = "some-folder"
SOME_GROUP = "some-group"
SOME_DASHBOARD = "some-dashboard"
SOME_PANEL = 4
# Required by a rule's shape and read by nothing these cases assert.
DONT_CARE_DATASOURCE = "some-prometheus"
DONT_CARE_THRESHOLD = 0.8
DONT_CARE_INTERVAL_SECONDS = 60
# The query the metrics read takes the slowest one request in twenty by -
# rescaled to milliseconds from a metric named in seconds, so only the panel
# says its unit rightly.
THE_P95_QUERY = QUERIES["p95_ms"]
# A ratio the metrics read takes no figure by, whose metric's name ends in
# `_ratio` - which the name route reads as a share of one.
A_RATIO_QUERY = SeriesQuery("avg(some_confident_ratio)")


@pytest.mark.unit
def test_the_standing_is_where_the_platform_says_the_rule_stands() -> None:
    # Every duration as the platform read it, and the series by its query.
    the_platforms = RuleEvaluation(rule=SOME_RULE, is_normal=False, evaluated_at=SOME_EVALUATION,
                                   range_seconds=300, interval_seconds=60,
                                   keep_firing_for_seconds=120, pending_seconds=180,
                                   series=SOME_SERIES)

    Scenario() \
        .when(
            lambda: how_the_rule_stands(SOME_RULE,
                                        rules=a_platform_answering(the_platforms),
                                        classify=a_classifier(Measure.OTHER, unit=None))
        ) \
        .then(
            the_answer_was(AlertRuleStanding(
                rule=the_platforms.rule,
                is_normal=the_platforms.is_normal,
                evaluated_at=the_platforms.evaluated_at,
                range_seconds=the_platforms.range_seconds,
                interval_seconds=the_platforms.interval_seconds,
                keep_firing_for_seconds=the_platforms.keep_firing_for_seconds,
                pending_seconds=the_platforms.pending_seconds,
                series_query=SOME_SERIES.query
            ))
        )


@pytest.mark.unit
def test_the_unit_the_platform_shows_the_series_in_is_its_unit() -> None:
    # A dashboard is somebody saying what the series is in. A query rescaled to
    # milliseconds names a metric in seconds, and the name would say it wrongly.
    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE,
                rules=a_platform_answering(an_evaluation(series_unit=Unit.MILLISECONDS)),
                classify=a_classifier(Measure.OTHER, unit=Unit.SECONDS)
            )
        ) \
        .then(_its_series_is_in(Unit.MILLISECONDS))


@pytest.mark.unit
def test_where_the_platform_shows_no_unit_the_series_is_in_its_metric_s() -> None:
    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE,
                rules=a_platform_answering(an_evaluation(series_unit=None)),
                classify=a_classifier(Measure.OTHER, unit=Unit.SECONDS)
            )
        ) \
        .then(_its_series_is_in(Unit.SECONDS))


@pytest.mark.unit
def test_a_series_neither_the_platform_nor_its_name_says_the_unit_of_has_none() -> None:
    # Unknown rather than guessed: a level said in the wrong unit is wrong by
    # its scale.
    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE,
                rules=a_platform_answering(an_evaluation(series_unit=None)),
                classify=a_classifier(Measure.OTHER, unit=None)
            )
        ) \
        .then(_its_series_is_in(None))


@pytest.mark.unit
@pytest.mark.parametrize(("measures", "the_error_rate", "a_latency"), [
    (Measure.ERROR_RATE, True, False),
    (Measure.LATENCY, False, True),
    (Measure.OTHER, False, False)
], ids=["the-error-rate", "a-latency", "something-else"])
def test_the_standing_says_what_the_metrics_source_says_its_series_measures(
        measures: Measure, the_error_rate: bool, a_latency: bool) -> None:
    # Then what the rule watched is a figure every reader is already given, and
    # whoever says both would say it twice.
    Scenario() \
        .when(
            lambda: how_the_rule_stands(SOME_RULE,
                                        rules=a_platform_answering(an_evaluation()),
                                        classify=a_classifier(measures, unit=None))
        ) \
        .then(_it_watches(the_error_rate=the_error_rate, a_latency=a_latency))


@pytest.mark.unit
def test_a_rule_followed_to_no_series_is_not_classified() -> None:
    # No query, so nothing for the metrics source to read - and a standing that
    # watches nothing in particular, in no unit.
    classify = a_classifier(Measure.ERROR_RATE, unit=Unit.SECONDS)

    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE,
                rules=a_platform_answering(an_evaluation(series=None)),
                classify=classify
            )
        ) \
        .then(all_of(
            _its_series_query_is(None),
            _it_watches(the_error_rate=False, a_latency=False),
            _its_series_is_in(None),
            _the_metrics_source_was_not_asked(classify)
        ))


@pytest.mark.unit
def test_a_rule_the_platform_cannot_read_is_unreadable() -> None:
    # Answered as normal, it would confirm whatever was just done.
    platform = create_autospec(AlertingPlatform, instance=True)
    platform.evaluation_of.side_effect = AlertRuleUnreadable("dont-care")

    Scenario() \
        .when(
            attempting(lambda: how_the_rule_stands(
                SOME_RULE,
                rules=cast(AlertingPlatform, platform),
                classify=a_classifier(Measure.OTHER, unit=None)
            ))
        ) \
        .then(an_error_was_raised(AlertRuleUnreadable))


@pytest.mark.integration
def test_a_latency_rule_reads_as_a_latency_in_the_unit_its_panel_shows() -> None:
    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE,
                rules=Grafana(a_grafana_settings(), get=a_grafana_over_http(
                    THE_P95_QUERY, panel_unit=MILLISECONDS_UNIT)),
                classify=what_the_series_is
            )
        ) \
        .then(
            _the_series_reads(query=THE_P95_QUERY, unit=Unit.MILLISECONDS,
                              the_error_rate=False, a_latency=True)
        )


@pytest.mark.integration
def test_a_rule_whose_panel_shows_no_unit_reads_in_the_unit_its_metric_s_name_carries() -> None:
    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE,
                rules=Grafana(a_grafana_settings(), get=a_grafana_over_http(A_RATIO_QUERY,
                                                                           panel_unit=None)),
                classify=what_the_series_is
            )
        ) \
        .then(
            _the_series_reads(query=A_RATIO_QUERY, unit=Unit.SHARE_OF_ONE,
                              the_error_rate=False, a_latency=False)
        )


def an_evaluation(series: RuleSeries | None = SOME_SERIES,
                  series_unit: Unit | None = None) -> RuleEvaluation:
    return RuleEvaluation(rule=SOME_RULE, is_normal=True, evaluated_at=SOME_EVALUATION,
                          range_seconds=60, interval_seconds=60, keep_firing_for_seconds=0,
                          pending_seconds=0, series=series, series_unit=series_unit)


def a_platform_answering(evaluation: RuleEvaluation) -> AlertingPlatform:
    platform = create_autospec(AlertingPlatform, instance=True)
    platform.evaluation_of.return_value = evaluation

    return cast(AlertingPlatform, platform)


def a_classifier(measures: Measure, unit: Unit | None) -> SeriesClassifier:
    classify = create_autospec(SeriesClassifier, instance=True)
    classify.return_value = SeriesKind(measures=measures, unit=unit)

    return cast(SeriesClassifier, classify)


def _its_series_query_is(expected: SeriesQuery | None) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        if standing.series_query != expected:
            raise AssertionError(
                f"Expected the rule's series query to be [{expected}], got "
                f"[{standing.series_query}]."
            )

        return True

    return assertion


def _its_series_is_in(expected: Unit | None) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        if standing.series_unit != expected:
            raise AssertionError(
                f"Expected the rule's series to be in [{expected}], got "
                f"[{standing.series_unit}]."
            )

        return True

    return assertion


def _it_watches(the_error_rate: bool, a_latency: bool) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        said = (standing.series_is_the_error_rate, standing.series_is_a_latency)

        if said != (the_error_rate, a_latency):
            raise AssertionError(
                f"Expected the rule's series to be the error rate [{the_error_rate}] and a "
                f"latency [{a_latency}], got [{said[0]}] and [{said[1]}]."
            )

        return True

    return assertion


def _the_metrics_source_was_not_asked(classify: Any) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if classify.call_args_list:
            raise AssertionError(
                f"Expected no series to be classified, got {classify.call_args_list}."
            )

        return True

    return assertion


def a_grafana_settings() -> GrafanaSettings:
    return GrafanaSettings(grafana_base_url=SOME_BASE_URL, grafana_auth_token="")


def a_grafana_over_http(query: str, panel_unit: str | None) -> Any:
    """Grafana's HTTP answers for `SOME_RULE`: a definition reading `query`
    through a reduce and a threshold and naming its panel, the group, the
    rule's state, and the dashboard holding the panel - its unit in its field
    defaults where it has one. Any other URL fails the test that asked it."""
    definition = {
        FOLDER_UID: SOME_FOLDER,
        RULE_GROUP: SOME_GROUP,
        CONDITION: "C",
        ANNOTATIONS: {DASHBOARD_UID_ANNOTATION: SOME_DASHBOARD,
                      PANEL_ID_ANNOTATION: str(SOME_PANEL)},
        DATA: [
            {REF_ID: "A", DATASOURCE_UID: DONT_CARE_DATASOURCE,
             MODEL: {REF_ID: "A", EXPR: query}},
            _an_expression("B", {TYPE: REDUCE, EXPRESSION: "A"}),
            _an_expression("C", {
                TYPE: THRESHOLD,
                EXPRESSION: "B",
                CONDITIONS: [{EVALUATOR: {TYPE: GT, PARAMS: [DONT_CARE_THRESHOLD]}}]
            })
        ]
    }
    state = {DATA: {GROUPS: [{RULES: [{
        UID: SOME_RULE,
        STATE: INACTIVE,
        HEALTH: HEALTHY,
        LAST_EVALUATION: SOME_EVALUATION.isoformat().replace("+00:00", "Z")
    }]}]}}
    defaults = {UNIT: panel_unit} if panel_unit is not None else {}
    dashboard = {DASHBOARD: {UID: SOME_DASHBOARD,
                             PANELS: [{ID: SOME_PANEL, FIELD_CONFIG: {DEFAULTS: defaults}}]}}
    answers = {
        RULE_DEFINITION_PATH.format(rule=SOME_RULE): definition,
        RULE_GROUP_PATH.format(folder=SOME_FOLDER, group=SOME_GROUP):
            {INTERVAL: DONT_CARE_INTERVAL_SECONDS},
        RULE_STATE_PATH.format(rule=SOME_RULE): state,
        DASHBOARD_PATH.format(uid=SOME_DASHBOARD): dashboard
    }

    def answer(url: str, **_: Any) -> httpx2.Response:
        path = url.removeprefix(SOME_BASE_URL)

        if path not in answers:
            raise AssertionError(f"Grafana was asked for [{path}], which it does not serve.")

        return httpx2.Response(200, json=answers[path], request=httpx2.Request("GET", url))

    get = create_autospec(httpx2.get)
    get.side_effect = answer

    return get


def _an_expression(ref_id: str, model: dict[str, Any]) -> dict[str, Any]:
    return {REF_ID: ref_id, DATASOURCE_UID: EXPRESSION_DATASOURCE, MODEL: {REF_ID: ref_id, **model}}


def _the_series_reads(query: str, unit: Unit, the_error_rate: bool,
                      a_latency: bool) -> Assertion[AlertRuleStanding]:
    """The standing's series, every part of it at once: a composition that lost
    two parts reports both."""
    def assertion(standing: AlertRuleStanding) -> bool:
        expected = (SeriesQuery(query), unit, the_error_rate, a_latency)
        read = (standing.series_query, standing.series_unit,
                standing.series_is_the_error_rate, standing.series_is_a_latency)

        if read != expected:
            raise AssertionError(
                f"Expected the series as (query, unit, the error rate, a latency) "
                f"{expected}, got {read}."
            )

        return True

    return assertion
