from __future__ import annotations

import pytest
from agent_investigator import STUB_CONFIDENCE, investigate
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType


@pytest.mark.unit
def test_investigate_returns_confidence_above_mitigate_threshold() -> None:
    some_service = "kuki"
    some_alert_name = "HighErrorRate"
    alert = Alert(service=some_service, alert_name=some_alert_name)

    _, confidence, _ = investigate(alert, fetch_logs=_no_logs)

    assert confidence == STUB_CONFIDENCE
    assert confidence >= 0.75


@pytest.mark.unit
def test_investigate_hypothesis_mentions_alert_and_service() -> None:
    some_service = "buki"
    some_alert_name = "HighErrorRate"
    alert = Alert(service=some_service, alert_name=some_alert_name)

    hypothesis, _, _ = investigate(alert, fetch_logs=_no_logs)

    assert some_alert_name in hypothesis
    assert some_service in hypothesis


@pytest.mark.unit
def test_investigate_recognizes_feature_flag_toggle_from_logs() -> None:
    alert = Alert(service="kuki", alert_name="HighErrorRate")

    _, _, cause_type = investigate(alert, fetch_logs=_feature_flag_toggle_logs)

    assert cause_type == CauseType.FEATURE_FLAG_TOGGLE


@pytest.mark.unit
def test_investigate_does_not_attribute_an_error_that_precedes_the_toggle() -> None:
    alert = Alert(service="kuki", alert_name="HighErrorRate")

    _, _, cause_type = investigate(alert, fetch_logs=_error_before_any_toggle_logs)

    assert cause_type is None


def _no_logs() -> list[str]:
    return []


def _feature_flag_toggle_logs() -> list[str]:
    return [
        "INFO target-service: feature flag 'checkout-v2' is off, request succeeded",
        "WARN target-service: feature flag 'checkout-v2' toggled from 'off' to 'on'",
        "ERROR target-service: request failed - feature flag 'checkout-v2' is on, "
            "error rate elevated",
    ]


def _error_before_any_toggle_logs() -> list[str]:
    return [
        "ERROR target-service: request failed - unrelated timeout",
        "WARN target-service: feature flag 'checkout-v2' toggled from 'off' to 'on'",
    ]
