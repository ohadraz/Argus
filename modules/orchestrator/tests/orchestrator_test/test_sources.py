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
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock, create_autospec

import psycopg
import pytest
from agent_postmortem import Sources
from argus_core import Connections, get_settings, to_iso
from argus_core.anomaly import AnomalyThresholds
from argus_core.mcp_transport import McpClient, McpToolError, McpUnreachable
from argus_core.models import AlertRuleStanding, MetricBucket
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged, the_answer_was
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
def test_an_incident_longer_than_the_read_tier_serves_is_read_whole_in_turns() -> None:
    # The tier serves one window of its configured span and cuts anything
    # wider down to it, from the start - it bounds what a model is handed. The
    # postmortem is code, not a model, and a week-long incident read as its
    # first six hours is one whose recovery, and most of whose failing, was
    # never seen. So it asks in consecutive windows the tier will serve whole.
    span = timedelta(minutes=get_settings().metrics_window_minutes)
    some_start = DONT_CARE_START
    some_end = some_start + 2 * span + timedelta(minutes=30)

    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            lambda: _the_sources_over(read).metrics(some_start, some_end, None)
        ) \
        .then(
            _the_windows_asked_for_were(read, [(some_start, some_start + span),
                                               (some_start + span, some_start + 2 * span),
                                               (some_start + 2 * span, some_end)])
        )


@pytest.mark.unit
def test_the_minute_two_windows_share_is_read_once() -> None:
    # A range read answers for both its ends, so the minute where one window
    # stops and the next starts comes back from each. Read twice, it would
    # weigh double in every level the document reports.
    span = timedelta(minutes=get_settings().metrics_window_minutes)
    the_shared_minute = DONT_CARE_START + span
    the_last_minute = DONT_CARE_START + 2 * span

    Scenario() \
        .given(
            read := _a_session_answering(
                [_a_minute(DONT_CARE_START), _a_minute(the_shared_minute)],
                [_a_minute(the_shared_minute), _a_minute(the_last_minute)])
        ) \
        .when(
            lambda: [bucket.bucket_id for bucket in
                     _the_sources_over(read).metrics(DONT_CARE_START, the_last_minute, None)]
        ) \
        .then(
            the_answer_was([_a_minute(DONT_CARE_START).bucket_id,
                            _a_minute(the_shared_minute).bucket_id,
                            _a_minute(the_last_minute).bucket_id])
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


@pytest.mark.unit
def test_how_long_the_paging_rule_waits_is_asked_of_the_read_tier() -> None:
    # The rule's own definition, over the session the metrics are read on.
    some_rule = "kuki-rule"

    Scenario() \
        .given(
            read := _a_session_answering_that_the_rule_waits(some_rule, 300)
        ) \
        .when(
            lambda: _the_sources_over(read).rule_wait(some_rule)
        ) \
        .then(
            all_of(
                the_answer_was(300),
                _the_rules_asked_for_were(read, [some_rule])
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("failure", [McpToolError("some failure"),
                                     McpUnreachable("some failure")],
                         ids=["tool-failed", "unreachable"])
def test_a_rule_the_read_tier_cannot_read_waits_for_no_known_time(
    failure: Exception,
    caplog: pytest.LogCaptureFixture
) -> None:
    # `None`, never nothing: a rule that fires at once and one nobody could read
    # are told to the model differently.
    Scenario() \
        .given(read := _a_session_whose_tool_fails(failure)) \
        .when(lambda: _the_sources_over(read).rule_wait("dont-care-rule")) \
        .then(
            all_of(
                the_answer_was(None),
                one_record_was_logged(caplog, "orchestrator.sources", logging.WARNING,
                                      "alert rule could not be read",
                                      failure=type(failure))
            )
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


def _the_windows_asked_for_were(read: Mock,
                                windows: list[tuple[datetime, datetime]]) -> Assertion[Any]:
    """Which window each call to the tier named, in the order asked."""
    def assertion(dont_care_result: Any) -> bool:
        asked = [(call.kwargs.get("window_start"), call.kwargs.get("window_end"))
                 for call in read.call.call_args_list]
        expected = [(to_iso(start), to_iso(end)) for start, end in windows]

        if asked != expected:
            raise AssertionError(
                f"Expected the read tier to be asked for the windows {expected}, got {asked}."
            )

        return True

    return assertion


def _a_session_answering(*answers: list[MetricBucket]) -> Mock:
    """A client answering each call with the next of `answers`, in turn."""
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.side_effect = list(answers)

    return client


def _a_session_answering_that_the_rule_waits(rule: str, seconds: int) -> Mock:
    """A client answering the rule's standing, every part of it arbitrary but
    which rule it is and how long it waits before firing."""
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.return_value = AlertRuleStanding(rule=rule,
                                                 is_normal=True,
                                                 evaluated_at=DONT_CARE_END,
                                                 range_seconds=60,
                                                 interval_seconds=60,
                                                 keep_firing_for_seconds=0,
                                                 pending_seconds=seconds)

    return client


def _a_session_whose_tool_fails(failure: Exception) -> Mock:
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.side_effect = failure

    return client


def _a_minute(at: datetime) -> MetricBucket:
    """One minute of metrics, every reading in it arbitrary but its minute."""
    return MetricBucket(
        bucket_id=at.strftime("%Y-%m-%dT%H:%MZ"),
        error_rate=0.02,
        p50_ms=20,
        p95_ms=40,
        p99_ms=90,
        request_volume=1_000,
        memory_used_bytes=440 * 1024**2,
        process_start_time_seconds=1_756_000_000.0,
        cpu_used_cores=0.77,
        cpu_limit_cores=3.0
    )
