from __future__ import annotations

import pytest
from agent_investigator import STUB_CONFIDENCE, investigate
from argus_core.models.alert import Alert


@pytest.mark.unit
def test_investigate_returns_confidence_above_mitigate_threshold() -> None:
    some_service = "kuki"
    some_alert_name = "HighErrorRate"
    alert = Alert(service=some_service, alert_name=some_alert_name)

    _, confidence = investigate(alert)

    assert confidence == STUB_CONFIDENCE
    assert confidence >= 0.75


@pytest.mark.unit
def test_investigate_hypothesis_mentions_alert_and_service() -> None:
    some_service = "buki"
    some_alert_name = "HighErrorRate"
    alert = Alert(service=some_service, alert_name=some_alert_name)

    hypothesis, _ = investigate(alert)

    assert some_alert_name in hypothesis
    assert some_service in hypothesis
