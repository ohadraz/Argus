from __future__ import annotations

from unittest.mock import Mock

import pytest
from agent_investigator import investigate
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType


@pytest.mark.unit
def test_investigate_recognizes_feature_flag_toggle_from_logs() -> None:
    some_alert = an_alert_for("shuki")

    hypothesis = investigate(
        some_alert, incident_id=new_id(), fetch_logs=_feature_flag_toggle_logs
    )

    assert hypothesis.cause_type == CauseType.FEATURE_FLAG_TOGGLE


@pytest.mark.unit
def test_investigate_does_not_attribute_an_error_that_precedes_the_toggle() -> None:
    some_alert = an_alert_for("tuki")

    hypothesis = investigate(
        some_alert, incident_id=new_id(), fetch_logs=_error_before_any_toggle_logs
    )

    assert hypothesis.cause_type is None


@pytest.mark.unit
def test_investigate_reports_no_confidence_when_it_found_no_cause() -> None:
    # The honest failure this change exists for: nothing recognized means no
    # confidence at all, not a low one and not a fabricated hypothesis.
    some_alert = an_alert_for("kuki")

    hypothesis = investigate(some_alert, incident_id=new_id(), fetch_logs=_no_logs)

    assert hypothesis.cause_type is None
    assert hypothesis.confidence is None


@pytest.mark.unit
def test_investigate_summary_mentions_alert_and_service() -> None:
    some_service = "buki"
    some_alert_name = "HighErrorRate"
    some_alert = Alert(service=some_service, alert_name=some_alert_name)

    hypothesis = investigate(some_alert, incident_id=new_id(), fetch_logs=_no_logs)

    assert some_alert_name in hypothesis.summary
    assert some_service in hypothesis.summary


@pytest.mark.unit
def test_investigate_records_the_evidence_it_read() -> None:
    some_alert = an_alert_for("zuki")
    some_logs = _feature_flag_toggle_logs()

    hypothesis = investigate(
        some_alert, incident_id=new_id(), fetch_logs=lambda: some_logs
    )

    assert hypothesis.supporting_evidence == some_logs


@pytest.mark.unit
def test_investigate_belongs_to_the_incident_it_was_asked_about() -> None:
    some_incident_id = new_id()
    some_alert = an_alert_for("puki")

    hypothesis = investigate(
        some_alert, incident_id=some_incident_id, fetch_logs=_no_logs
    )

    assert hypothesis.incident_id == some_incident_id


@pytest.mark.unit
def test_investigate_calls_the_injected_fetch_logs() -> None:
    some_alert = an_alert_for("yok")
    fetch_logs = Mock(return_value=[])

    investigate(some_alert, incident_id=new_id(), fetch_logs=fetch_logs)

    fetch_logs.assert_called_once_with()


def an_alert_for(service: str) -> Alert:
    return Alert(service=service, alert_name="HighErrorRate")


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
