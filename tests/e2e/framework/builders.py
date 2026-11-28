from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from alert_source.grafana import (
    ALERT_NAME_LABEL,
    ALERTS,
    ANNOTATIONS,
    FINGERPRINT,
    GENERATOR_URL,
    GRAFANA_MANAGED,
    GROUP_KEY,
    LABELS,
    SERVICE_LABEL,
    SEVERITY_LABEL,
    STARTS_AT,
    STATUS,
    SUMMARY_ANNOTATION,
    THE_ALERTING_PATH,
)
from core import to_iso

from tests.framework.grafana import (
    COMMON_ANNOTATIONS,
    COMMON_LABELS,
    ENDS_AT,
    EXTERNAL_URL,
    FIRING,
    GROUP_LABELS,
    NOT_ENDED,
    RECEIVER,
    VERSION,
)

# Where the alerts are said to come from: the Grafana the stack's alerts name.
A_GRAFANA: Final = "http://grafana.local"

# The words the shop's own monitoring pages with wherever its other rules do not
# fire: its error-rate rule's summary (`_BY_DEFAULT` in the demo app's
# `monitoring.py`). A case whose scenario trips another rule passes that rule's
# words, as its alert name names that rule.
THE_ERROR_RATE_RULES_WORDS = "Error rate above threshold for 5m"

# The uid of the rule those words are the summary of (`HIGH_ERROR_RATE` in the
# demo app's `alert_rules.py`), which an alert links where no scenario is staged.
# Grafana's webhook names the rule that fired only in its link, so a link naming
# no rule the shop has is an alert no real Grafana sends - and one whose rule
# Argus asks for and is told does not exist.
THE_ERROR_RATE_RULE = "io-shop-high-error-rate"


def a_grafana_style_alert_with(service: str = "some-service",
                                alert_name: str = "some-error-name",
                                severity: str = "some-severity",
                                started_at: datetime | None = None,
                                summary: str = THE_ERROR_RATE_RULES_WORDS) -> dict[str, Any]:
    """A Grafana webhook payload, as Grafana would send it.

    `startsAt` is left to whoever sends it, which stamps it with the moment it
    is sent, unless `started_at` is given. That default matters twice over:
    retrieval is anchored on the alert time, and the Target Service seeds a
    scenario relative to the moment it was seeded. A hardcoded timestamp puts
    the metrics window somewhere the fixture's minutes are not, so Argus
    retrieves nothing and honestly reports that it found nothing - a green
    test turning red for a reason that has nothing to do with Argus. And a
    stamp taken here is taken before the case seeds, by however long the seed
    waited, which can put the alert before the rule could have fired.

    `summary` is the words the alert was sent with, which Argus reads as the
    sender's own account of what it measured and names the paging rule's
    series by. Three latency rules share one alert name, so the words are the
    only thing in the page that says which percentile moved.

    The link names the error-rate rule, whose words the summary is by default.
    Where a scenario is staged, sending the alert links its own rule instead.
    """
    starts_at = {STARTS_AT: to_iso(started_at)} if started_at is not None else {}

    return {
        RECEIVER: "argus-webhook",
        STATUS: FIRING,
        ALERTS: [
            {
                STATUS: FIRING,
                LABELS: {
                    ALERT_NAME_LABEL: alert_name,
                    SERVICE_LABEL: service,
                    SEVERITY_LABEL: severity
                },
                ANNOTATIONS: {
                    SUMMARY_ANNOTATION: summary
                },
                **starts_at,
                ENDS_AT: NOT_ENDED,
                GENERATOR_URL: a_link_to_the_rule(THE_ERROR_RATE_RULE),
                FINGERPRINT: "abc123def456"
            }
        ],
        GROUP_LABELS: {ALERT_NAME_LABEL: alert_name},
        COMMON_LABELS: {ALERT_NAME_LABEL: alert_name, SERVICE_LABEL: service},
        COMMON_ANNOTATIONS: {SUMMARY_ANNOTATION: summary},
        EXTERNAL_URL: A_GRAFANA,
        VERSION: "1",
        GROUP_KEY: f'{{}}/{{{ALERT_NAME_LABEL}="{alert_name}"}}'
    }


def a_link_to_the_rule(rule_uid: str) -> str:
    """The link to a rule, in the shape Grafana's releases build it - the one
    place its webhook names the rule that fired."""
    return f"{A_GRAFANA}{THE_ALERTING_PATH}{GRAFANA_MANAGED}/{rule_uid}/view"
