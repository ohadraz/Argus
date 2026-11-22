"""The alerting platform's one adapter: Grafana, and the only module that knows it.

Three of Grafana's reads meet here and none leaves the adapter: the rule's
definition (its queries' ranges, `keep_firing_for` and `for`), its group (the
interval every rule in it is evaluated at), and its current state from the
Prometheus-compatible rules API. What comes out names no vendor.

The definition is also read for the series the rule watches - the query its
condition is evaluated over, and which side of the threshold is worse - so the
metrics read for an alert can carry the series that paged. That is followed only
where the rule's shape leaves no doubt what the series is; anywhere else the
answer is none, which costs a window its sixth series and never invents one.
The query is carried as the rule says it and never read: what it measures is
the metrics source's to say.

And for the unit Grafana shows that series in. Grafana's rule has no field for
one; its route to a unit is the panel the rule names in two annotations, whose
field defaults carry it, as one of Grafana's unit ids. Where the rule names no
panel, the panel no unit Argus can say - a unit set only in an override, or in
a library panel, is not in the defaults - or the dashboard cannot be read, the
answer is no unit, and the read tier asks the metrics source instead. A
dashboard out of reach costs the unit and nothing else: how a level is said is
no reason to judge a mitigation by nothing.

Nothing here judges. Whether an evaluation came late enough after an action to
say anything about it is the caller's question, and the caller holds the action.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final, Protocol

import httpx2
from core import AdapterSettings
from core.models import RuleLine, RuleSeries, SeriesQuery, Unit, WorseWhen

from alerting_platform.failures import AlertRuleUnreadable
from alerting_platform.port import RuleEvaluation

logger = logging.getLogger(__name__)

# Where each of the three reads is asked, and the dashboard a rule's panel is on.
RULE_DEFINITION_PATH: Final = "/api/v1/provisioning/alert-rules/{rule}"
RULE_GROUP_PATH: Final = "/api/v1/provisioning/folder/{folder}/rule-groups/{group}"
RULE_STATE_PATH: Final = "/api/prometheus/grafana/api/v1/rules?rule_uid={rule}"
DASHBOARD_PATH: Final = "/api/dashboards/uid/{uid}"

# How a rule names its panel - two annotations, both strings - and the parts of
# a dashboard read for that panel's unit. A panel's `id` is a number, so the two
# are compared as text.
ANNOTATIONS: Final = "annotations"
DASHBOARD_UID_ANNOTATION: Final = "__dashboardUid__"
PANEL_ID_ANNOTATION: Final = "__panelId__"
DASHBOARD: Final = "dashboard"
PANELS: Final = "panels"
ID: Final = "id"
FIELD_CONFIG: Final = "fieldConfig"
DEFAULTS: Final = "defaults"
UNIT: Final = "unit"
# Grafana's unit ids for the units Argus can say, and what each is. Any other -
# its two plain-number formats, `none` and `short`, which are ways to show a
# number rather than units of one, among them - is no unit here, and the
# metric's name is asked instead.
PERCENT_OF_ONE_UNIT: Final = "percentunit"
PERCENT_UNIT: Final = "percent"
MILLISECONDS_UNIT: Final = "ms"
SECONDS_UNIT: Final = "s"
BYTES_UNIT: Final = "bytes"
_UNITS: Final = {
    PERCENT_OF_ONE_UNIT: Unit.SHARE_OF_ONE,
    PERCENT_UNIT: Unit.PERCENT,
    MILLISECONDS_UNIT: Unit.MILLISECONDS,
    SECONDS_UNIT: Unit.SECONDS,
    BYTES_UNIT: Unit.BYTES
}

# Grafana's wire vocabulary for the parts of its answers read here, named once
# because a typo in one is a silent `None`.
FOLDER_UID: Final = "folderUID"
RULE_GROUP: Final = "ruleGroup"
# Snake case in the provisioning API's rule, where the export format and the
# rules API spell it `keepFiringFor`.
KEEP_FIRING_FOR: Final = "keep_firing_for"
# How long the condition has to hold before the rule fires - its pending period.
FOR: Final = "for"
DATA: Final = "data"
RELATIVE_TIME_RANGE: Final = "relativeTimeRange"
FROM: Final = "from"
INTERVAL: Final = "interval"
GROUPS: Final = "groups"
RULES: Final = "rules"
UID: Final = "uid"
STATE: Final = "state"
HEALTH: Final = "health"
LAST_EVALUATION: Final = "lastEvaluation"

# The parts of a rule's definition that say what it evaluates: the step its
# condition names, each step's `refId`, model and datasource, and the fields of
# the expression steps between the query and the threshold. Spelled as
# Grafana's provisioning API spells them.
CONDITION: Final = "condition"
REF_ID: Final = "refId"
MODEL: Final = "model"
DATASOURCE_UID: Final = "datasourceUid"
# The datasource every server-side expression is addressed by. A query step names
# the real datasource it reads instead.
EXPRESSION_DATASOURCE: Final = "__expr__"
TYPE: Final = "type"
EXPRESSION: Final = "expression"
CONDITIONS: Final = "conditions"
EVALUATOR: Final = "evaluator"
QUERY: Final = "query"
PARAMS: Final = "params"
# A Prometheus query's PromQL, in the query step's model.
EXPR: Final = "expr"

# The expression types followed, and one that is not: a math step changes what
# is compared, so the query behind it is not the series the rule fires on.
THRESHOLD: Final = "threshold"
REDUCE: Final = "reduce"
CLASSIC_CONDITIONS: Final = "classic_conditions"
MATH: Final = "math"

# A threshold's evaluator types that have one bad side. The range evaluators
# (`within_range`, `outside_range` and their `_included` variants) have two, and
# a series bad on both sides cannot be turned so that higher is worse.
GT: Final = "gt"
GTE: Final = "gte"
LT: Final = "lt"
LTE: Final = "lte"
OUTSIDE_RANGE: Final = "outside_range"
_WORSE_WHEN: Final[dict[str, WorseWhen]] = {
    GT: "above",
    GTE: "above",
    LT: "below",
    LTE: "below"
}
# The evaluators a reading exactly on the threshold fires under.
_FIRES_ON_THE_LINE: Final = frozenset({GTE, LTE})

# The state Grafana's rules API gives a rule that is not firing or pending.
INACTIVE: Final = "inactive"
# The health it gives a rule whose last evaluation measured something. A query
# that failed or found no data leaves the rule `inactive` and says so only here.
HEALTHY: Final = "ok"

# A Grafana duration: `90s`, `5m`, `1h30m`.
_A_DURATION_PART: Final = re.compile(r"(\d+)([hms])")
_SECONDS_IN: Final = {"h": 3600, "m": 60, "s": 1}

REQUEST_TIMEOUT_SECONDS: Final = 10.0


class GrafanaSettings(AdapterSettings):
    """Where the rules are read from, and under what credential.

    Read by the read tier's root. Whether the rule that paged has stopped firing
    is what a mitigation on a series alert is judged by.
    """

    # The demo Target Service stands in for Grafana under `/grafana`, so the
    # default points at it; a real Grafana is its root URL and nothing else.
    grafana_base_url: str = "http://localhost:8080/grafana"
    # Empty means no credential is sent - the stand-in needs none, and a real
    # Grafana issues a service-account token for this.
    grafana_auth_token: str = ""


HttpGet = Callable[..., httpx2.Response]


class FetchFromGrafana(Protocol):
    """How this module asks Grafana for one path's JSON.

    A `Protocol` rather than a `Callable` alias, so a test stands it in with
    `create_autospec`. Where Grafana is and under what credential was decided
    where the process started.
    """

    def __call__(self, path: str, /) -> dict[str, Any]: ...


class Grafana:
    """The alerting platform, answered by Grafana: the port's two questions,
    each one line naming the function below that answers it.

    Built where the read server is wired, and handed on typed as
    `AlertingPlatform`.
    """

    def __init__(self, settings: GrafanaSettings, get: HttpGet = httpx2.get) -> None:
        self._settings = settings
        self._get = get

    def evaluation_of(self, rule: str, /) -> RuleEvaluation:
        return the_evaluation_of(rule, fetch=self._fetch)

    def series_of(self, rule: str, /) -> RuleSeries | None:
        return the_series_the_rule_watches(rule, fetch=self._fetch)

    def _fetch(self, path: str, /) -> dict[str, Any]:
        return fetch_from_grafana(path, self._settings, self._get)


def fetch_from_grafana(path: str,
                       settings: GrafanaSettings,
                       get: HttpGet = httpx2.get) -> dict[str, Any]:
    """Asks Grafana for one path. Any failure to get an answer - unreachable
    host, error status, unreadable body - becomes `AlertRuleUnreadable`."""
    url = f"{settings.grafana_base_url}{path}"
    headers = (
        {"Authorization": f"Bearer {settings.grafana_auth_token}"}
        if settings.grafana_auth_token
        else {}
    )

    try:
        response = get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except Exception as error:
        raise AlertRuleUnreadable(f"could not read [{url}]: {error}") from error

    return body


def the_evaluation_of(rule: str, *, fetch: FetchFromGrafana) -> RuleEvaluation:
    """Where `rule` stands now, and how it reads its service - the series it
    watches among it, followed as the metrics read follows it, and the unit its
    panel shows that series in."""
    definition = fetch(RULE_DEFINITION_PATH.format(rule=rule))

    try:
        group = fetch(RULE_GROUP_PATH.format(
            folder=definition[FOLDER_UID], group=definition[RULE_GROUP]
        ))
        state = _the_state_of(rule, fetch(RULE_STATE_PATH.format(rule=rule)))

        if state.get(HEALTH) != HEALTHY:
            # An evaluation that measured nothing says nothing about the
            # service, and Grafana reports it as `inactive` - which, taken for a
            # rule that stopped firing, would confirm whatever was just done.
            logger.warning("alert rule unhealthy",
                           extra={"rule": rule, "health": state.get(HEALTH)})

            raise AlertRuleUnreadable(
                f"rule [{rule}]'s last evaluation measured nothing: its health is "
                f"[{state.get(HEALTH)}]"
            )

        series = _the_series_followed_in(definition)

        return RuleEvaluation(
            rule=rule,
            is_normal=state[STATE] == INACTIVE,
            evaluated_at=datetime.fromisoformat(state[LAST_EVALUATION]),
            range_seconds=max(
                (
                    int(query[RELATIVE_TIME_RANGE][FROM])
                    for query in definition.get(DATA, [])
                    if RELATIVE_TIME_RANGE in query
                ),
                default=0
            ),
            interval_seconds=int(group[INTERVAL]),
            keep_firing_for_seconds=_seconds_in(definition.get(KEEP_FIRING_FOR)),
            pending_seconds=_seconds_in(definition.get(FOR)),
            series=series,
            series_unit=(_the_panels_unit(rule, definition, fetch)
                         if series is not None
                         else None)
        )
    except AlertRuleUnreadable:
        raise
    except Exception as error:
        raise AlertRuleUnreadable(
            f"Grafana's answers for rule [{rule}] could not be read: {error}"
        ) from error


def the_series_the_rule_watches(rule: str, *,
                                fetch: FetchFromGrafana) -> RuleSeries | None:
    """The query `rule` is evaluated over and which way it is worse, or `None`
    where that cannot be said for certain.

    Followed from the step the rule's condition names back to the one query it
    reads: through a threshold, which says the direction, and a reduce, which
    says nothing about it - or through a classic condition, which says both in
    one step. Anything else between them, a second query, an evaluator with two
    bad sides, or a query step with no expression, and the answer is `None`. A
    query in some other language than the metrics source's is followed like any
    other, and refused by the metrics source, which answers it with no reading.

    `None` too where Grafana will not answer, or answers with a query that is
    not text. The series is a sixth signal a window can do without, and an
    unreadable rule is a reason to read the window without it rather than to
    serve no window.
    """
    try:
        definition = fetch(RULE_DEFINITION_PATH.format(rule=rule))

        return _the_series_followed_in(definition)
    except (AlertRuleUnreadable, _QueryNotText):
        logger.warning("alert rule definition could not be read", exc_info=True,
                       extra={"rule": rule})

        return None


class _QueryNotText(Exception):
    """A rule whose series' query Grafana answered as something other than text.

    Not a shape this declines to follow, which is no series: an answer nobody
    can vouch for. The standing is refused for it, as for any answer of
    Grafana's that could not be read, and the metrics read goes without it.
    """


def _the_series_followed_in(definition: dict[str, Any]) -> RuleSeries | None:
    """The series a definition's condition reads, or `None` where its shape is
    not one this follows - the one rule for which series a rule watches, for
    the metrics read and the standing alike. Raises `_QueryNotText` where the
    query it is followed to is not text."""
    try:
        return _the_series_in(definition)
    except (KeyError, IndexError, TypeError):
        return None


def _the_series_in(definition: dict[str, Any]) -> RuleSeries | None:
    """The series a definition's condition reads, followed step by step."""
    steps = {step[REF_ID]: step for step in definition.get(DATA, [])}
    queries = [
        step for step in steps.values()
        if step.get(DATASOURCE_UID) != EXPRESSION_DATASOURCE
    ]

    if len(queries) != 1:
        return None

    worse_when: WorseWhen | None = None
    line: RuleLine | None = None
    reference = definition.get(CONDITION)

    # At most one step each, so a definition whose steps name each other in a
    # circle ends rather than following itself for ever.
    for _ in steps:
        step = steps.get(reference)

        if step is None or step.get(DATASOURCE_UID) != EXPRESSION_DATASOURCE:
            break

        model = step[MODEL]
        kind = model.get(TYPE)

        if kind == REDUCE:
            reference = model[EXPRESSION]
        elif kind in (THRESHOLD, CLASSIC_CONDITIONS) and worse_when is None:
            # One comparison or none followed: clauses joined by AND or OR fire
            # on several at once, and no one series is what paged.
            if len(model[CONDITIONS]) != 1:
                return None

            [condition] = model[CONDITIONS]
            worse_when = _WORSE_WHEN.get(condition[EVALUATOR][TYPE])

            if worse_when is None:
                return None

            line = _the_line_of(condition[EVALUATOR])

            reference = (
                model[EXPRESSION]
                if kind == THRESHOLD
                else condition[QUERY][PARAMS][0]
            )
        else:
            return None

    query = steps.get(reference)

    if worse_when is None or query is None or query is not queries[0]:
        return None

    expr = query.get(MODEL, {}).get(EXPR)

    if expr is not None and not isinstance(expr, str):
        raise _QueryNotText(f"the query of its series is a {type(expr).__name__}, not text")

    return RuleSeries(query=SeriesQuery(expr), worse_when=worse_when, line=line) if expr else None


def _the_panels_unit(rule: str,
                     definition: dict[str, Any],
                     fetch: FetchFromGrafana) -> Unit | None:
    """The unit the panel the rule names shows its values in, or `None` where
    the rule names no panel, the panel names no unit Argus can say - a
    plain-number format among them - or the dashboard could not be read.

    Every step of the dashboard is checked for its shape rather than trusted:
    an answer in a shape this does not read costs the unit, and an exception
    out of here would cost the rule's whole standing."""
    annotations = _an_object(definition.get(ANNOTATIONS))
    dashboard_uid = annotations.get(DASHBOARD_UID_ANNOTATION)
    panel_id = annotations.get(PANEL_ID_ANNOTATION)

    if not dashboard_uid or not panel_id:
        return None

    try:
        dashboard = _an_object(_an_object(fetch(DASHBOARD_PATH.format(uid=dashboard_uid)))
                               .get(DASHBOARD))
    except AlertRuleUnreadable:
        logger.warning("the rule's dashboard could not be read", exc_info=True,
                       extra={"rule": rule, "dashboard": dashboard_uid})

        return None

    # A collapsed row keeps its panels inside it; an expanded one beside it.
    tops = [top for top in _a_list(dashboard.get(PANELS)) if isinstance(top, dict)]
    panels = [
        panel
        for top in tops
        for panel in (top, *_a_list(top.get(PANELS)))
        if isinstance(panel, dict)
    ]
    found = next((panel for panel in panels if str(panel.get(ID)) == str(panel_id)), {})
    unit = _an_object(_an_object(found.get(FIELD_CONFIG)).get(DEFAULTS)).get(UNIT)

    return _UNITS.get(unit) if isinstance(unit, str) else None


def _an_object(value: Any) -> dict[str, Any]:
    """`value` where it is a JSON object, and an empty one where it is not."""
    return value if isinstance(value, dict) else {}


def _a_list(value: Any) -> list[Any]:
    """`value` where it is a JSON array, and an empty one where it is not."""
    return value if isinstance(value, list) else []


def _the_line_of(evaluator: dict[str, Any]) -> RuleLine | None:
    """The threshold an evaluator compares with, or `None` where it names no
    number - a series is still followed without one, and judged by its
    direction alone."""
    params = evaluator.get(PARAMS) or []
    at = params[0] if params else None

    if isinstance(at, bool) or not isinstance(at, int | float):
        return None

    return RuleLine(at=float(at), fires_on_it=evaluator[TYPE] in _FIRES_ON_THE_LINE)


def _the_state_of(rule: str, answer: dict[str, Any]) -> dict[str, Any]:
    """The rule's own entry in the rules API's answer, refused where absent."""
    for group in answer.get(DATA, {}).get(GROUPS, []):
        for entry in group.get(RULES, []):
            if entry.get(UID) == rule:
                found: dict[str, Any] = entry
                return found

    raise AlertRuleUnreadable(f"Grafana reports no state for rule [{rule}].")


def _seconds_in(duration: str | None) -> int:
    """A Grafana duration in seconds; absent or empty is none at all."""
    return sum(
        int(amount) * _SECONDS_IN[unit]
        for amount, unit in _A_DURATION_PART.findall(duration or "")
    )
