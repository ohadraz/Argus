"""Where the alert rule that paged stands, read from Grafana.

A channel offered to no model: Mitigation reads it, and nothing else does.
Mitigation judges an action on a series alert by whether the rule that
paged has stopped firing - the rule is what defines "acceptable" for the
service, as it would for a responder - so this says what the rule says, as of
an evaluation that can be dated, and how long the rule looks back.

Three of Grafana's reads meet here and none leaves the tier: the rule's
definition (its queries' ranges and `keep_firing_for`), its group (the interval
every rule in it is evaluated at), and its current state from the
Prometheus-compatible rules API. What comes out names no vendor.

Nothing here judges. Whether an evaluation came late enough after an action to
say anything about it is the caller's question, and the caller holds the action.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final, Protocol

import httpx2
from argus_core import SettingsSlice
from argus_core.models import AlertRuleStanding

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
