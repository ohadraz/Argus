"""Grafana's webhook payload, read as the one alert Argus works from.

The outermost edge of the system: a vendor's shape arrives here and nothing
downstream is allowed to know it. So both questions are about the boundary
rather than about the parsing - that the fields Argus needs were found where
Grafana puts them, and that Grafana's own nesting stopped here.

The second is the one with teeth. An `Alert` that carried `labels` through
would let every later reader reach for `alert.labels["service"]` instead of
`alert.service`, and the vendor's shape would be load-bearing everywhere by
the time anybody noticed.
"""

from __future__ import annotations

import pytest
from argus_core.models import Alert
from argus_testkit import Assertion, Scenario
from argus_web.grafana import parse_grafana_alert

from argus_web_test.framework.builders import a_grafana_payload


@pytest.mark.unit
def test_parse_grafana_alert_maps_labels_to_alert_fields() -> None:
    some_service = "checkout"
    some_alert_name = "HighErrorRate"

    Scenario() \
        .given(
            payload := a_grafana_payload(service=some_service, alert_name=some_alert_name)
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _it_read(
                service=some_service, alert_name=some_alert_name, severity="critical"
            )
        )


@pytest.mark.unit
def test_parse_grafana_alert_does_not_leak_grafana_labels_nesting() -> None:
    Scenario() \
        .given(
            payload := a_grafana_payload()
        ) \
        .when(
            lambda: parse_grafana_alert(payload)
        ) \
        .then(
            _nothing_of_grafanas_came_through("labels")
        )


def _it_read(service: str, alert_name: str, severity: str) -> Assertion[Alert]:
    """The three fields lifted out of Grafana's labels, checked together.

    Together because they are read out of one nested mapping by three separate
    lookups: a parser that reached into the wrong alert of the list, or the
    wrong key, gets more than one of them wrong at once, and a run of
    assertions stopping at the first would describe a narrower fault than the
    one that happened.
    """
    def assertion(alert: Alert) -> bool:
        wanted = {"service": service, "alert_name": alert_name, "severity": severity}
        wrong = {
            field: (expected, getattr(alert, field))
            for field, expected in wanted.items()
            if getattr(alert, field) != expected
        }
        if wrong:
            raise AssertionError(
                f"Expected the alert to read {wanted}, and {wrong} differed "
                f"(expected, got)."
            )

        return True

    return assertion


def _nothing_of_grafanas_came_through(*fields: str) -> Assertion[Alert]:
    """That the vendor's own field names are absent from what Argus carries.

    Asserted by name rather than by comparing whole shapes, because what is
    being prevented is specific: a later reader finding `alert.labels` and
    using it. An `Alert` that grew other fields is not this failure.
    """
    def assertion(alert: Alert) -> bool:
        leaked = [field for field in fields if hasattr(alert, field)]

        if leaked:
            raise AssertionError(f"Expected Grafana's {leaked} not to survive parsing.")

        return True

    return assertion
