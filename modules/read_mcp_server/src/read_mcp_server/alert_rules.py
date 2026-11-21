"""Where the alert rule that paged stands, said whole.

Where the rule stands is offered to no model as a tool: Mitigation reads it,
and the postmortem reads how long the rule waits and the series it watches.
Mitigation judges an action on a series alert by whether the rule that paged
has stopped firing - the rule is what defines "acceptable" for the service, as
it would for a responder - so this says what the rule says, as of an
evaluation that can be dated, and how long the rule looks back.

Two ports answer it, and this is where their answers meet. The alerting
platform says where the rule stands, which series it watches, and the unit its
dashboard shows that series in. The metrics source says what that series
measures, and the unit its metric's name carries - the query is in its
language, and nothing else reads one. The platform's unit wins where it says
one, since a dashboard is somebody saying what the series is in; the name's is
the fallback, and past both the unit is unknown.
"""

from __future__ import annotations

from alerting_platform import AlertingPlatform
from core.models import AlertRuleStanding
from metrics_source import Measure, SeriesClassifier


def how_the_rule_stands(rule: str,
                        *,
                        rules: AlertingPlatform,
                        classify: SeriesClassifier) -> AlertRuleStanding:
    """Where `rule` stands now, and how it reads its service.

    Raises `AlertRuleUnreadable` where the platform will not say, rather than
    answering normal: "normal" is the answer that confirms whatever was just
    done. The series is classified only where the platform could follow the
    rule to one."""
    evaluation = rules.evaluation_of(rule)
    series = evaluation.series
    kind = classify(series.query) if series is not None else None

    return AlertRuleStanding(
        rule=evaluation.rule,
        is_normal=evaluation.is_normal,
        evaluated_at=evaluation.evaluated_at,
        range_seconds=evaluation.range_seconds,
        interval_seconds=evaluation.interval_seconds,
        keep_firing_for_seconds=evaluation.keep_firing_for_seconds,
        pending_seconds=evaluation.pending_seconds,
        series_query=series.query if series is not None else None,
        series_unit=evaluation.series_unit or (kind.unit if kind is not None else None),
        series_is_the_error_rate=kind is not None and kind.measures is Measure.ERROR_RATE,
        series_is_a_latency=kind is not None and kind.measures is Measure.LATENCY
    )
