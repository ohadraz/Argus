"""Where the alert rule that paged stands, read from Grafana.

Where the rule stands is a channel offered to no model: Mitigation reads it,
and nothing else does. Mitigation judges an action on a series alert by whether the rule that
paged has stopped firing - the rule is what defines "acceptable" for the
service, as it would for a responder - so this says what the rule says, as of
an evaluation that can be dated, and how long the rule looks back.

Three of Grafana's reads meet here and none leaves the tier: the rule's
definition (its queries' ranges and `keep_firing_for`), its group (the interval
every rule in it is evaluated at), and its current state from the
Prometheus-compatible rules API. What comes out names no vendor.

The definition is also read for the series the rule watches - the query its
condition is evaluated over, and which side of the threshold is worse - so the
metrics read for an alert can carry the series that paged. That is followed only
where the rule's shape leaves no doubt what the series is; anywhere else the
answer is none, which costs a window its sixth series and never invents one.

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
from argus_core import SettingsSlice
from argus_core.models import AlertRuleStanding, WorseWhen
from metrics_source import RuleSeries

logger = logging.getLogger(__name__)

# Where each of the three reads is asked.
RULE_DEFINITION_PATH: Final = "/api/v1/provisioning/alert-rules/{rule}"
RULE_GROUP_PATH: Final = "/api/v1/provisioning/folder/{folder}/rule-groups/{group}"
RULE_STATE_PATH: Final = "/api/prometheus/grafana/api/v1/rules?rule_uid={rule}"

# Grafana's wire vocabulary for the parts of its answers read here, named once
# because a typo in one is a silent `None`.
FOLDER_UID: Final = "folderUID"
RULE_GROUP: Final = "ruleGroup"
# Snake case in the provisioning API's rule, where the export format and the
# rules API spell it `keepFiringFor`.
KEEP_FIRING_FOR: Final = "keep_firing_for"
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

# The state Grafana's rules API gives a rule that is not firing or pending.
INACTIVE: Final = "inactive"
# The health it gives a rule whose last evaluation measured something. A query
# that failed or found no data leaves the rule `inactive` and says so only here.
HEALTHY: Final = "ok"

# A Grafana duration: `90s`, `5m`, `1h30m`.
_A_DURATION_PART: Final = re.compile(r"(\d+)([hms])")
_SECONDS_IN: Final = {"h": 3600, "m": 60, "s": 1}

REQUEST_TIMEOUT_SECONDS: Final = 10.0


class AlertRuleReadSettings(SettingsSlice):
    """Where the rules are read from, and under what credential.

    Empty token means no credential is sent, which is what the demo's stand-in
    needs; a real Grafana issues service-account tokens for this.
    """

    grafana_base_url: str
    grafana_auth_token: str


HttpGet = Callable[..., httpx2.Response]


class AlertRuleUnreadable(Exception):
    """Grafana would not say where the rule stands.

    Raised rather than answered as normal, because "normal" is the answer that
    confirms whatever was just done.
    """


class FetchFromGrafana(Protocol):
    """How this module asks Grafana for one path's JSON.

    A `Protocol` rather than a `Callable` alias, so a test stands it in with
    `create_autospec`. Where Grafana is and under what credential was decided
    where the process started.
    """

    def __call__(self, path: str, /) -> dict[str, Any]: ...


def fetch_from_grafana(path: str,
                       settings: AlertRuleReadSettings,
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


def how_the_rule_stands(rule: str, *, fetch: FetchFromGrafana) -> AlertRuleStanding:
    """Where `rule` stands now, and how it reads its service."""
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

        return AlertRuleStanding(
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
            keep_firing_for_seconds=_seconds_in(definition.get(KEEP_FIRING_FOR))
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
    query in some other language than PromQL is followed like any other, and
refused by the metrics backend, which answers it with no reading.

    `None` too where Grafana will not answer. The series is a sixth signal a
    window can do without, and an unreadable rule is a reason to read the
    window without it rather than to serve no window.
    """
    try:
        definition = fetch(RULE_DEFINITION_PATH.format(rule=rule))
    except AlertRuleUnreadable:
        logger.warning("alert rule definition could not be read", exc_info=True,
                       extra={"rule": rule})

        return None

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

    return RuleSeries(query=expr, worse_when=worse_when) if expr else None


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
