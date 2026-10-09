"""The ports a postmortem reads, each answered by this deployment's provider.

The metrics port is asked about here because it is the one answered over a
connection somebody already holds, so its question can be watched on the way
to the read tier without anything being reached. The on-call and HR ports are
asked only what they log when they cannot be read, which each says before
reaching anybody when it holds no credential.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock, create_autospec

import psycopg
import pytest
from agent_postmortem import Sources
from argus_core import Connections, get_settings
from argus_core.anomaly import AnomalyThresholds
from argus_core.mcp_transport import McpClient
from argus_testkit import Assertion, Scenario, one_record_was_logged
from orchestrator.sources import the_real_sources
from responder_rate_source import PayBandsUnavailable

DONT_CARE_START = datetime(2026, 9, 2, 11, 0, tzinfo=UTC)
DONT_CARE_END = datetime(2026, 9, 2, 12, 30, tzinfo=UTC)
DONT_CARE_INCIDENT_ID = "kuki-123"

# Unread by the metrics port, but `Sources` carries them and has no default.
DONT_CARE_THRESHOLDS = AnomalyThresholds(
    deviations_from_baseline=3.0,
    persistence_minutes=2,
    recovery_fraction_of_the_rise=0.8
)


@pytest.mark.unit
def test_the_postmortems_metrics_are_read_for_the_rule_that_paged() -> None:
    # The rule travels to the read tier as the tool's own argument, because the
    # read tier is where it is resolved into a query. A source that dropped it
    # would come back with the five fixed series, and the document would report
    # nothing of the series that paged.
    some_rule = "kuki-rule"

    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            lambda: _the_sources_over(read).metrics(DONT_CARE_START, DONT_CARE_END, some_rule)
        ) \
        .then(
            _the_rules_asked_for_were(read, [some_rule])
        )


@pytest.mark.unit
def test_pay_bands_that_cannot_be_read_are_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    Scenario() \
        .given(sources := _the_sources_holding_no_credential()) \
        .when(lambda: sources.bands()) \
        .then(
            one_record_was_logged(caplog, "orchestrator.sources", logging.WARNING,
                                  "pay bands could not be read",
                                  failure=PayBandsUnavailable)
        )


def _the_sources_over(read: McpClient) -> Sources:
    return the_real_sources(
        get_settings(), _connections_that_must_not_be_opened(), read, DONT_CARE_THRESHOLDS,
        oncall=None
    )


def _the_sources_holding_no_credential() -> Sources:
    """Every source configured with nothing to authenticate with, which each one
    refuses before reaching anybody."""
    return the_real_sources(
        get_settings().model_copy(update={"hr_api_key": ""}),
        _connections_that_must_not_be_opened(),
        _a_session_that_remembers_what_it_was_asked(),
        DONT_CARE_THRESHOLDS,
        oncall=None
    )


def _a_session_that_remembers_what_it_was_asked() -> Mock:
    """A client that answers nothing and records the question."""
    client: Mock = create_autospec(McpClient, instance=True)

    return client


def _connections_that_must_not_be_opened() -> Connections:
    @contextmanager
    def no_connections() -> Generator[psycopg.Connection]:
        raise AssertionError("Reading the metrics must not open a connection.")
        yield  # unreachable, and what makes this a generator

    return no_connections


def _the_rules_asked_for_were(read: Mock, rules: list[str]) -> Assertion[Any]:
    """Which rule each call to the tier named."""
    def assertion(dont_care_result: Any) -> bool:
        asked = [call.kwargs.get("rule") for call in read.call.call_args_list]

        if asked != rules:
            raise AssertionError(
                f"Expected the read tier to be asked for the rules {rules}, got {asked}."
            )

        return True

    return assertion
