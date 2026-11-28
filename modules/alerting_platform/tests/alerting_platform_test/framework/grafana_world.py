"""A Grafana, in-process, serving one `AlertingState` in Grafana's own shapes.

The port's suite runs the Grafana adapter against this through its `get` seam,
beside the in-memory double built from the same seed. So this answers every
path the adapter asks - a rule's definition, its group, its state in the
Prometheus-compatible rules API and the dashboard its panel is on - in the
shapes `test_grafana.py` pins on the wire. Every word of Grafana's it speaks is
imported from the adapter, so the two cannot spell one differently; whether
each means what the adapter takes it to is a contract question.

How a held rule is said:
- Its one query is step `A`, on a real datasource, looking back over the
  rule's range, its model's expression the series' query.
- With a series, a threshold step over `A` is the condition: its evaluator says
  the direction and whether a reading on the line fires, and its parameters the
  line - none where the series has no line, and then `gt` for above and `lt`
  for below, since either of each pair says the direction alone. With none,
  the condition is `A` itself, which the adapter follows to no series.
- With a unit, the rule names a panel, and the dashboard's panel shows that
  unit - whether or not the rule has a series, so the adapter's "no unit without
  a series" is what is held.
- `for` and `keep_firing_for` in seconds, the group's interval, and a state of
  `inactive` for a normal rule and `firing` for one that is not, with a health
  of `ok` for an evaluation that measured something and `nodata` for one that
  did not.

Behaviours of Grafana's the adapter only reads, never meets here: a path the
seed does not hold is a 404.
"""

from __future__ import annotations

from typing import Any, Final

import httpx2
from alerting_platform import RuleEvaluation
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
    FIRES_ON_THE_LINE,
    FOLDER_UID,
    FOR,
    FROM,
    GROUPS,
    HEALTH,
    HEALTHY,
    ID,
    INACTIVE,
    INTERVAL,
    KEEP_FIRING_FOR,
    LAST_EVALUATION,
    MODEL,
    PANEL_ID_ANNOTATION,
    PANELS,
    PARAMS,
    REF_ID,
    RELATIVE_TIME_RANGE,
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
    UNITS,
    WORSE_WHEN,
    GrafanaSettings,
)
from alerting_platform_double import AlertingState
from core.models import RuleSeries, Unit

# Where the stand-in is addressed. Nothing listens there: `get` answers.
_BASE_URL: Final = "http://grafana.invalid"

# Grafana's words for a rule that is not normal and for an evaluation that
# measured nothing - which the adapter never reads by name, since anything but
# `inactive` is not normal and anything but `ok` measured nothing. Declared
# here for every suite of the adapter's that serves them.
FIRING: Final = "firing"
NO_DATA: Final = "nodata"

# The names the world gives what the adapter only follows: the folder every
# rule is filed in, its two steps, the datasource its query reads, and the
# panel its unit is shown on.
_FOLDER: Final = "some-folder"
_QUERY_STEP: Final = "A"
_THRESHOLD_STEP: Final = "C"
_A_DATASOURCE: Final = "some-prometheus"
_PANEL: Final = 4
_SECONDS: Final = "s"

# Each unit Argus can say, as the id Grafana shows it by.
_UNIT_IDS: Final[dict[Unit, str]] = {unit: grafana_id for grafana_id, unit in UNITS.items()}

# The evaluator that says a direction and whether a reading on the line fires,
# as the adapter pairs them.
_EVALUATORS: Final = {(WORSE_WHEN[kind], kind in FIRES_ON_THE_LINE): kind for kind in WORSE_WHEN}


def grafana_settings() -> GrafanaSettings:
    """The adapter's settings, addressed at the stand-in."""
    return GrafanaSettings(grafana_base_url=_BASE_URL)


class GrafanaWorld:
    """Grafana, holding `state`, as the adapter's `get` asks it.

    `unreachable` builds one nothing reaches: every request fails as one that
    never arrived.
    """

    def __init__(self, state: AlertingState, *, unreachable: bool = False) -> None:
        self._answers: dict[str, dict[str, Any]] = {}
        self._unreachable = unreachable

        for held in state.rules:
            self._hold(held.evaluation, measured=held.measured)

    def get(self, url: str, **dont_care_options: Any) -> httpx2.Response:
        """The answer at `url`, its timeout and headers passed over - or a 404
        for a path nothing here holds."""
        request = httpx2.Request("GET", url)

        if self._unreachable:
            raise httpx2.ConnectError("Grafana is not reachable", request=request)

        answer = self._answers.get(url.removeprefix(_BASE_URL))

        if answer is None:
            return httpx2.Response(404, json={"message": "not found"}, request=request)

        return httpx2.Response(200, json=answer, request=request)

    def _hold(self, evaluation: RuleEvaluation, *, measured: bool) -> None:
        # A group and a dashboard of its own, so no two rules' intervals or
        # units are read off one answer.
        rule = evaluation.rule
        group = f"{rule}-group"
        dashboard = f"{rule}-dashboard"

        self._answers[RULE_DEFINITION_PATH.format(rule=rule)] = {
            UID: rule,
            FOLDER_UID: _FOLDER,
            RULE_GROUP: group,
            FOR: f"{evaluation.pending_seconds}{_SECONDS}",
            KEEP_FIRING_FOR: f"{evaluation.keep_firing_for_seconds}{_SECONDS}",
            CONDITION: _THRESHOLD_STEP if evaluation.series is not None else _QUERY_STEP,
            DATA: _the_steps_of(evaluation),
            ANNOTATIONS: (
                {DASHBOARD_UID_ANNOTATION: dashboard, PANEL_ID_ANNOTATION: str(_PANEL)}
                if evaluation.series_unit is not None else {}
            )
        }
        self._answers[RULE_GROUP_PATH.format(folder=_FOLDER, group=group)] = {
            INTERVAL: evaluation.interval_seconds
        }
        self._answers[RULE_STATE_PATH.format(rule=rule)] = {DATA: {GROUPS: [{RULES: [{
            UID: rule,
            STATE: INACTIVE if evaluation.is_normal else FIRING,
            HEALTH: HEALTHY if measured else NO_DATA,
            LAST_EVALUATION: evaluation.evaluated_at.isoformat()
        }]}]}}

        if evaluation.series_unit is not None:
            self._answers[DASHBOARD_PATH.format(uid=dashboard)] = {DASHBOARD: {PANELS: [{
                ID: _PANEL,
                FIELD_CONFIG: {DEFAULTS: {UNIT: _UNIT_IDS[evaluation.series_unit]}}
            }]}}


def _the_steps_of(evaluation: RuleEvaluation) -> list[dict[str, Any]]:
    """The rule's query, and the threshold over it where it has a series."""
    query = {
        REF_ID: _QUERY_STEP,
        DATASOURCE_UID: _A_DATASOURCE,
        RELATIVE_TIME_RANGE: {FROM: evaluation.range_seconds},
        MODEL: {EXPR: evaluation.series.query} if evaluation.series is not None else {}
    }

    if evaluation.series is None:
        return [query]

    return [query, {
        REF_ID: _THRESHOLD_STEP,
        DATASOURCE_UID: EXPRESSION_DATASOURCE,
        MODEL: {
            TYPE: THRESHOLD,
            EXPRESSION: _QUERY_STEP,
            CONDITIONS: [{EVALUATOR: _the_evaluator_of(evaluation.series)}]
        }
    }]


def _the_evaluator_of(series: RuleSeries) -> dict[str, Any]:
    """With no line, the evaluator a reading on a line would not fire under:
    either of each pair says the direction alone."""
    if series.line is None:
        return {TYPE: _EVALUATORS[(series.worse_when, False)], PARAMS: []}

    return {TYPE: _EVALUATORS[(series.worse_when, series.line.fires_on_it)],
            PARAMS: [series.line.at]}
