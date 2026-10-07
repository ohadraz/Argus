"""Where an alert rule stands, as the read tier answers it.

What Mitigation judges an action on a series alert by: whether the rule that
paged has stopped firing, as of an evaluation it can date, and how long the rule
looks back - which is what says how long a recovery takes to show in it.

Read from Grafana and answered in a shape that names no vendor. Nothing here
judges either: a rule that is normal is reported normal, and whether that
evaluation came late enough to say anything about an action is the caller's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import create_autospec

import httpx2
import pytest
from argus_core.models import AlertRuleStanding, WorseWhen
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from metrics_source import RuleSeries
from read_mcp_server.alert_rules import (
    CLASSIC_CONDITIONS,
    CONDITION,
    CONDITIONS,
    DATA,
    DATASOURCE_UID,
    EVALUATOR,
    EXPR,
    EXPRESSION,
    EXPRESSION_DATASOURCE,
    FOLDER_UID,
    FROM,
    GROUPS,
    GT,
    GTE,
    HEALTH,
    HEALTHY,
    INACTIVE,
    INTERVAL,
    KEEP_FIRING_FOR,
    LAST_EVALUATION,
    LT,
    LTE,
    MATH,
    MODEL,
    OUTSIDE_RANGE,
    PARAMS,
    QUERY,
    REDUCE,
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
    AlertRuleReadSettings,
    AlertRuleUnreadable,
    FetchFromGrafana,
    fetch_from_grafana,
    how_the_rule_stands,
    the_series_the_rule_watches,
)

SOME_RULE = "some-rule"
SOME_OTHER_RULE = "some-other-rule"
SOME_FOLDER = "some-folder"
SOME_GROUP = "some-group"
SOME_EVALUATION = datetime(2026, 10, 6, 10, 20, tzinfo=UTC)

DONT_CARE_PATH = "/some/path"

SOME_QUERY = "avg(some_confident_ratio)"
SOME_OTHER_QUERY = "avg(some_other_ratio)"

# Grafana's other words for a rule's state in its Prometheus-compatible answer,
# which Argus never reads by name: anything but inactive is not normal.
FIRING = "firing"
PENDING = "pending"

# And its other words for how the rule's last evaluation went.
ERRORED = "error"
NO_DATA = "nodata"


@pytest.mark.unit
def test_a_firing_rule_is_not_normal_as_of_its_last_evaluation() -> None:
    Scenario() \
        .when(
            lambda: how_the_rule_stands(SOME_RULE, fetch=a_grafana_holding(state=FIRING))
        ) \
        .then(all_of(
            _it_reads_normal(False),
            _it_was_evaluated_at(SOME_EVALUATION)
        ))


@pytest.mark.unit
def test_an_inactive_rule_is_normal() -> None:
    Scenario() \
        .when(
            lambda: how_the_rule_stands(SOME_RULE, fetch=a_grafana_holding(state=INACTIVE))
        ) \
        .then(_it_reads_normal(True))


@pytest.mark.unit
def test_a_pending_rule_is_not_normal() -> None:
    # Its condition holds and has not held long enough to fire. That is not a
    # rule that has stopped firing, which is the only thing "normal" may mean.
    Scenario() \
        .when(
            lambda: how_the_rule_stands(SOME_RULE, fetch=a_grafana_holding(state=PENDING))
        ) \
        .then(_it_reads_normal(False))


@pytest.mark.unit
def test_the_state_read_is_the_rules_own_among_the_others_grafana_lists() -> None:
    # The rules API answers in groups, and another rule listed first - firing,
    # while this one is not - is somebody else's incident.
    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE,
                fetch=a_grafana_holding(state=INACTIVE, others_firing=(SOME_OTHER_RULE,))
            )
        ) \
        .then(_it_reads_normal(True))


@pytest.mark.unit
def test_how_far_back_the_rule_looks_is_its_widest_query_range() -> None:
    # A rule built of several queries looks back as far as the widest of them,
    # and that is how long a recovery takes to show in it.
    narrow, wide = 120, 600

    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE, fetch=a_grafana_holding(ranges_seconds=(narrow, wide))
            )
        ) \
        .then(_it_looks_back_seconds(wide))


@pytest.mark.unit
def test_a_rule_with_no_ranged_query_looks_back_nothing() -> None:
    # A step that names no range adds nothing to how far back the rule looks.
    Scenario() \
        .when(
            lambda: how_the_rule_stands(SOME_RULE, fetch=a_grafana_holding(ranges_seconds=()))
        ) \
        .then(_it_looks_back_seconds(0))


@pytest.mark.unit
def test_the_interval_is_the_groups() -> None:
    # Grafana evaluates every rule in a group on the group's interval; the rule
    # itself carries none.
    some_interval_seconds = 30

    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE, fetch=a_grafana_holding(interval_seconds=some_interval_seconds)
            )
        ) \
        .then(_it_is_evaluated_every(some_interval_seconds))


@pytest.mark.unit
@pytest.mark.parametrize(("keep_firing_for", "expected"), [
    (None, timedelta()),
    ("0s", timedelta()),
    ("45s", timedelta(seconds=45)),
    ("1m30s", timedelta(minutes=1, seconds=30)),
    ("1h", timedelta(hours=1)),
    ("1h30m", timedelta(hours=1, minutes=30))
])
def test_keep_firing_for_is_read_from_the_rules_duration(keep_firing_for: str | None,
                                                         expected: timedelta) -> None:
    Scenario() \
        .when(
            lambda: how_the_rule_stands(
                SOME_RULE, fetch=a_grafana_holding(keep_firing_for=keep_firing_for)
            )
        ) \
        .then(_it_keeps_firing_for(expected))


@pytest.mark.unit
def test_a_rule_grafana_reports_no_state_for_is_unreadable() -> None:
    # Answered as normal, an absent rule would confirm whatever was just done.
    Scenario() \
        .when(
            attempting(lambda: how_the_rule_stands(
                SOME_RULE, fetch=a_grafana_holding(state=None)
            ))
        ) \
        .then(an_error_was_raised(AlertRuleUnreadable))


@pytest.mark.unit
@pytest.mark.parametrize("health", [ERRORED, NO_DATA])
def test_a_rule_whose_evaluation_measured_nothing_is_unreadable(health: str) -> None:
    # Grafana reports a rule whose query failed, or found no data, as inactive,
    # and says why only in its health. Read as normal, an evaluation that
    # measured nothing would confirm whatever was just done.
    Scenario() \
        .when(
            attempting(lambda: how_the_rule_stands(
                SOME_RULE, fetch=a_grafana_holding(state=INACTIVE, health=health)
            ))
        ) \
        .then(an_error_was_raised(AlertRuleUnreadable))


@pytest.mark.unit
@pytest.mark.parametrize(
    "missing", [FOLDER_UID, RULE_GROUP, INTERVAL, STATE, LAST_EVALUATION]
)
def test_an_answer_missing_a_field_it_is_read_by_is_unreadable(missing: str) -> None:
    # Whichever of the three reads it was, a shape Grafana did not answer in is
    # a standing nobody can vouch for - and not a reason to fail some other way.
    Scenario() \
        .when(
            attempting(lambda: how_the_rule_stands(
                SOME_RULE, fetch=a_grafana_holding(state=INACTIVE, missing=missing)
            ))
        ) \
        .then(an_error_was_raised(AlertRuleUnreadable))


@pytest.mark.unit
def test_grafana_answering_with_an_error_is_unreadable() -> None:
    a_refusing_get = create_autospec(httpx2.get)
    a_refusing_get.return_value = httpx2.Response(500, request=a_request())

    Scenario() \
        .when(
            attempting(lambda: fetch_from_grafana(DONT_CARE_PATH, a_settings(), get=a_refusing_get))
        ) \
        .then(an_error_was_raised(AlertRuleUnreadable))


@pytest.mark.unit
def test_grafana_out_of_reach_is_unreadable() -> None:
    an_unreachable_get = create_autospec(httpx2.get)
    an_unreachable_get.side_effect = httpx2.ConnectError("connection refused")

    Scenario() \
        .when(
            attempting(lambda: fetch_from_grafana(
                DONT_CARE_PATH, a_settings(), get=an_unreachable_get
            ))
        ) \
        .then(an_error_was_raised(AlertRuleUnreadable))


@pytest.mark.unit
def test_an_answer_that_is_not_json_is_unreadable() -> None:
    # What a proxy in front of Grafana answers with when Grafana is not there to.
    a_get_answering_a_page = create_autospec(httpx2.get)
    a_get_answering_a_page.return_value = httpx2.Response(
        200, text="<html>Bad Gateway</html>", request=a_request()
    )

    Scenario() \
        .when(
            attempting(lambda: fetch_from_grafana(
                DONT_CARE_PATH, a_settings(), get=a_get_answering_a_page
            ))
        ) \
        .then(an_error_was_raised(AlertRuleUnreadable))


@pytest.mark.unit
def test_a_credential_is_sent_as_a_bearer_token() -> None:
    some_token = "some-grafana-token"
    a_get = an_answering_get()

    Scenario() \
        .when(lambda: fetch_from_grafana(DONT_CARE_PATH, a_settings(some_token), get=a_get)) \
        .then(_it_asked_with_the_credential(a_get, f"Bearer {some_token}"))


@pytest.mark.unit
def test_no_credential_is_sent_where_none_is_configured() -> None:
    a_get = an_answering_get()

    Scenario() \
        .when(lambda: fetch_from_grafana(DONT_CARE_PATH, a_settings(token=""), get=a_get)) \
        .then(_it_asked_with_the_credential(a_get, None))


@pytest.mark.unit
@pytest.mark.parametrize(("evaluator", "worse_when"), [
    (GT, "above"),
    (GTE, "above"),
    (LT, "below"),
    (LTE, "below")
])
def test_a_threshold_over_a_reduced_query_is_followed_to_its_query_and_direction(
        evaluator: str, worse_when: WorseWhen) -> None:
    # Grafana's own default shape for a rule: a query, a reduce over it, and a
    # threshold over the reduce - the condition naming the threshold. Followed
    # from the condition back to the one query it reads.
    Scenario() \
        .when(
            lambda: the_series_the_rule_watches(
                SOME_RULE, fetch=a_grafana_defining(
                    a_query("A", SOME_QUERY),
                    a_reduce("B", of="A"),
                    a_threshold("C", of="B", evaluator=evaluator),
                    condition="C"
                )
            )
        ) \
        .then(_the_series_is(SOME_QUERY, worse_when))


@pytest.mark.unit
def test_a_classic_condition_is_followed_to_its_query_and_direction() -> None:
    # The older shape, still provisioned: one expression naming the query in
    # its own parameters and carrying the evaluator beside it.
    Scenario() \
        .when(
            lambda: the_series_the_rule_watches(
                SOME_RULE, fetch=a_grafana_defining(
                    a_query("A", SOME_QUERY),
                    a_classic_condition("B", of="A", evaluator=LT),
                    condition="B"
                )
            )
        ) \
        .then(_the_series_is(SOME_QUERY, "below"))


@pytest.mark.unit
def test_a_classic_condition_joining_two_clauses_watches_no_series_argus_can_follow() -> None:
    # Two clauses joined by AND or OR fire on two comparisons at once, so no one
    # series is what paged. And a rule Argus cannot follow costs the window its
    # sixth series - never the window itself.
    some_clause = {EVALUATOR: {TYPE: LT, PARAMS: [0.8]}, QUERY: {PARAMS: ["A"]}}

    Scenario() \
        .when(
            lambda: the_series_the_rule_watches(
                SOME_RULE, fetch=a_grafana_defining(
                    a_query("A", SOME_QUERY),
                    an_expression(
                        "B", {TYPE: CLASSIC_CONDITIONS, CONDITIONS: [some_clause, some_clause]}
                    ),
                    condition="B"
                )
            )
        ) \
        .then(_no_series_is_followed())


@pytest.mark.unit
def test_a_rule_with_a_math_step_watches_no_series_argus_can_follow() -> None:
    # A math expression between the query and the threshold changes what is
    # compared. The query's own series is not what fires the rule, and judging
    # it as though it were would date the onset off the wrong numbers.
    Scenario() \
        .when(
            lambda: the_series_the_rule_watches(
                SOME_RULE, fetch=a_grafana_defining(
                    a_query("A", SOME_QUERY),
                    a_reduce("B", of="A"),
                    a_math("C", expression="$B * 100"),
                    a_threshold("D", of="C", evaluator=GT),
                    condition="D"
                )
            )
        ) \
        .then(_no_series_is_followed())


@pytest.mark.unit
def test_a_rule_reading_two_queries_watches_no_series_argus_can_follow() -> None:
    Scenario() \
        .when(
            lambda: the_series_the_rule_watches(
                SOME_RULE, fetch=a_grafana_defining(
                    a_query("A", SOME_QUERY),
                    a_query("B", SOME_OTHER_QUERY),
                    a_reduce("C", of="A"),
                    a_threshold("D", of="C", evaluator=GT),
                    condition="D"
                )
            )
        ) \
        .then(_no_series_is_followed())


@pytest.mark.unit
def test_a_rule_firing_inside_or_outside_a_range_has_no_one_direction() -> None:
    # Worse above and worse below at once. A series with two bad sides cannot
    # be turned so that higher is worse.
    Scenario() \
        .when(
            lambda: the_series_the_rule_watches(
                SOME_RULE, fetch=a_grafana_defining(
                    a_query("A", SOME_QUERY),
                    a_reduce("B", of="A"),
                    a_threshold("C", of="B", evaluator=OUTSIDE_RANGE),
                    condition="C"
                )
            )
        ) \
        .then(_no_series_is_followed())


@pytest.mark.unit
def test_a_query_with_no_expression_watches_no_series_argus_can_follow() -> None:
    # A query step with no expression has nothing to ask the metrics backend. One
    # in some other language than PromQL is followed, and refused there instead.
    Scenario() \
        .when(
            lambda: the_series_the_rule_watches(
                SOME_RULE, fetch=a_grafana_defining(
                    a_query("A", None),
                    a_reduce("B", of="A"),
                    a_threshold("C", of="B", evaluator=GT),
                    condition="C"
                )
            )
        ) \
        .then(_no_series_is_followed())


@pytest.mark.unit
def test_a_rule_grafana_will_not_define_watches_no_series() -> None:
    # The rule's series is a sixth signal a window can do without. Grafana out
    # of reach costs the window that signal, and is not a reason to serve no
    # window at all.
    an_unreachable_grafana = create_autospec(FetchFromGrafana)
    an_unreachable_grafana.side_effect = AlertRuleUnreadable("dont-care")

    Scenario() \
        .when(
            lambda: the_series_the_rule_watches(
                SOME_RULE, fetch=cast(FetchFromGrafana, an_unreachable_grafana)
            )
        ) \
        .then(_no_series_is_followed())


def a_settings(token: str = "") -> AlertRuleReadSettings:
    return AlertRuleReadSettings(
        grafana_base_url="http://grafana.invalid", grafana_auth_token=token
    )


def a_request() -> httpx2.Request:
    return httpx2.Request("GET", "http://grafana.invalid/api")


def an_answering_get() -> Any:
    get = create_autospec(httpx2.get)
    get.return_value = httpx2.Response(200, json={}, request=a_request())

    return get


def a_grafana_holding(state: str | None = INACTIVE,
                      ranges_seconds: tuple[int, ...] = (60,),
                      interval_seconds: int = 60,
                      keep_firing_for: str | None = "0s",
                      health: str = HEALTHY,
                      others_firing: tuple[str, ...] = (),
                      missing: str | None = None) -> FetchFromGrafana:
    """A Grafana answering the three reads for `SOME_RULE`, in its own shapes.

    Each answer is served at its own path alone, the group's at the folder and
    group the definition names - so a read asked anywhere else fails the test
    that made it rather than finding an answer meant for another.

    `others_firing` are rules listed, firing, in a group ahead of this one's;
    `missing` is a field dropped from whichever answer carries it.
    """
    definition: dict[str, Any] = {
        FOLDER_UID: SOME_FOLDER,
        RULE_GROUP: SOME_GROUP,
        DATA: [
            *(
                {"refId": f"Q{index}", RELATIVE_TIME_RANGE: {FROM: seconds, "to": 0}}
                for index, seconds in enumerate(ranges_seconds)
            ),
            # A step naming no range.
            {"refId": "THRESHOLD"}
        ]
    }
    if keep_firing_for is not None:
        definition[KEEP_FIRING_FOR] = keep_firing_for
    group: dict[str, Any] = {INTERVAL: interval_seconds}
    # As Grafana writes it: RFC 3339, in UTC.
    evaluated = SOME_EVALUATION.isoformat().replace("+00:00", "Z")
    own: list[dict[str, Any]] = (
        []
        if state is None
        else [{
            UID: SOME_RULE,
            STATE: state,
            HEALTH: health,
            LAST_EVALUATION: evaluated
        }]
    )
    others = [{
        UID: other,
        STATE: FIRING,
        HEALTH: HEALTHY,
        LAST_EVALUATION: evaluated
    } for other in others_firing]
    rules = {DATA: {GROUPS: [{RULES: others}, {RULES: own}]}}

    if missing is not None:
        for body in (definition, group, *own):
            body.pop(missing, None)

    answers = {
        RULE_DEFINITION_PATH.format(rule=SOME_RULE): definition,
        RULE_GROUP_PATH.format(folder=SOME_FOLDER, group=SOME_GROUP): group,
        RULE_STATE_PATH.format(rule=SOME_RULE): rules
    }

    def answer(path: str) -> dict[str, Any]:
        if path not in answers:
            raise AssertionError(f"Grafana was asked for [{path}], which it does not serve.")

        return answers[path]

    fetch = create_autospec(FetchFromGrafana)
    fetch.side_effect = answer

    return cast(FetchFromGrafana, fetch)


def a_grafana_defining(*data: dict[str, Any], condition: str) -> FetchFromGrafana:
    """A Grafana answering `SOME_RULE`'s definition, with these steps and this
    condition, and nothing else."""
    definition = {CONDITION: condition, DATA: list(data)}

    def answer(path: str) -> dict[str, Any]:
        if path != RULE_DEFINITION_PATH.format(rule=SOME_RULE):
            raise AssertionError(f"Grafana was asked for [{path}], which it does not serve.")

        return definition

    fetch = create_autospec(FetchFromGrafana)
    fetch.side_effect = answer

    return cast(FetchFromGrafana, fetch)


def a_query(ref_id: str, expr: str | None) -> dict[str, Any]:
    """A data query against Prometheus, as a rule's definition carries one."""
    model: dict[str, Any] = {REF_ID: ref_id}

    if expr is not None:
        model[EXPR] = expr

    return {REF_ID: ref_id, DATASOURCE_UID: "some-prometheus", MODEL: model}


def a_reduce(ref_id: str, of: str) -> dict[str, Any]:
    return an_expression(ref_id, {TYPE: REDUCE, EXPRESSION: of, "reducer": "mean"})


def a_math(ref_id: str, expression: str) -> dict[str, Any]:
    return an_expression(ref_id, {TYPE: MATH, EXPRESSION: expression})


def a_threshold(ref_id: str, of: str, evaluator: str) -> dict[str, Any]:
    return an_expression(ref_id, {
        TYPE: THRESHOLD,
        EXPRESSION: of,
        CONDITIONS: [{EVALUATOR: {TYPE: evaluator, PARAMS: [0.8]}}]
    })


def a_classic_condition(ref_id: str, of: str, evaluator: str) -> dict[str, Any]:
    return an_expression(ref_id, {
        TYPE: CLASSIC_CONDITIONS,
        CONDITIONS: [{
            EVALUATOR: {TYPE: evaluator, PARAMS: [0.8]},
            QUERY: {PARAMS: [of]},
            "reducer": {TYPE: "avg"}
        }]
    })


def an_expression(ref_id: str, model: dict[str, Any]) -> dict[str, Any]:
    """A server-side expression step - the datasource Grafana names every
    expression by."""
    return {
        REF_ID: ref_id,
        DATASOURCE_UID: EXPRESSION_DATASOURCE,
        MODEL: {REF_ID: ref_id, **model}
    }


def _the_series_is(query: str,
                   worse_when: WorseWhen) -> Assertion[RuleSeries | None]:
    def assertion(followed: RuleSeries | None) -> bool:
        if followed != RuleSeries(query=query, worse_when=worse_when):
            raise AssertionError(
                f"Expected the rule to be followed to [{query}], worse "
                f"[{worse_when}], and it was followed to [{followed}]."
            )

        return True

    return assertion


def _no_series_is_followed() -> Assertion[RuleSeries | None]:
    def assertion(followed: RuleSeries | None) -> bool:
        if followed is not None:
            raise AssertionError(
                f"Expected no series Argus could follow, and the rule was "
                f"followed to [{followed}]."
            )

        return True

    return assertion


def _it_reads_normal(expected: bool) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        if standing.is_normal is not expected:
            raise AssertionError(
                f"Expected the rule to read normal [{expected}], got "
                f"[{standing.is_normal}]."
            )

        return True

    return assertion


def _it_was_evaluated_at(expected: datetime) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        if standing.evaluated_at != expected:
            raise AssertionError(
                f"Expected the rule's last evaluation [{expected}], got "
                f"[{standing.evaluated_at}]."
            )

        return True

    return assertion


def _it_looks_back_seconds(expected: int) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        if standing.range_seconds != expected:
            raise AssertionError(
                f"Expected the rule to look back [{expected}]s, got "
                f"[{standing.range_seconds}]s."
            )

        return True

    return assertion


def _it_is_evaluated_every(expected: int) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        if standing.interval_seconds != expected:
            raise AssertionError(
                f"Expected the rule to be evaluated every [{expected}]s, got "
                f"[{standing.interval_seconds}]s."
            )

        return True

    return assertion


def _it_keeps_firing_for(expected: timedelta) -> Assertion[AlertRuleStanding]:
    def assertion(standing: AlertRuleStanding) -> bool:
        if standing.keep_firing_for_seconds != expected.total_seconds():
            raise AssertionError(
                f"Expected the rule to keep firing for [{expected.total_seconds():.0f}]s, "
                f"got [{standing.keep_firing_for_seconds}]s."
            )

        return True

    return assertion


def _it_asked_with_the_credential(get: Any, expected: str | None) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        sent = get.call_args.kwargs.get("headers", {}).get("Authorization")

        if sent != expected:
            raise AssertionError(
                f"Expected the request to carry the credential [{expected}], got [{sent}]."
            )

        return True

    return assertion
