"""The ports a postmortem reads, each answered by this deployment's provider.

The metrics port is asked about here because it is the one answered over a
connection somebody already holds, so its question can be watched on the way
to the read tier without anything being reached. The HR source is asked only
what is logged when it cannot be read; which vendor answers it, and how that
vendor refuses, is the adapter's suite's.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from unittest.mock import Mock, create_autospec

import httpx
import psycopg
import pytest
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged, the_answer_was
from core import get_settings, to_iso
from core.anomaly import AnomalyThresholds
from core.models import AlertRuleStanding, MetricBucket, SeriesQuery
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData
from mcp_transport import McpClient, McpToolError, McpUnreachable
from orchestrator.sources import the_real_sources
from pay_band_source import PayBandsByTitle, PayBandsUnavailable
from postgres import Connections
from postmortem_writing import Sources
from read_mcp_client import ReadTier

DONT_CARE_START = datetime(2026, 9, 2, 11, 0, tzinfo=UTC)
DONT_CARE_END = datetime(2026, 9, 2, 12, 30, tzinfo=UTC)
DONT_CARE_INCIDENT_ID = "kuki-123"
DONT_CARE_RULE = "dont-care-rule"
# What a read that failed says, which nothing here reads.
SOME_FAILURE = "some failure"

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
@pytest.mark.parametrize("failure", [McpToolError(SOME_FAILURE),
                                     McpUnreachable(SOME_FAILURE),
                                     McpError(ErrorData(code=httpx.codes.REQUEST_TIMEOUT,
                                                        message=SOME_FAILURE))],
                         ids=["tool-failed", "unreachable", "timed-out"])
def test_metrics_the_read_tier_cannot_read_are_answered_as_none_read(
    failure: Exception,
    caplog: pytest.LogCaptureFixture
) -> None:
    # Nothing read, which the document already says in its own words: no minute
    # of the service's metrics could be read. Raised instead, a read of the shop
    # that timed out failed the run of an incident already mitigated, and no
    # postmortem was written for it.
    Scenario() \
        .given(read := _a_session_whose_tool_fails(failure)) \
        .when(lambda: _the_sources_over(read).metrics(DONT_CARE_START, DONT_CARE_END,
                                                      DONT_CARE_RULE)) \
        .then(
            all_of(
                the_answer_was([]),
                one_record_was_logged(caplog, "orchestrator.sources", logging.WARNING,
                                      "metrics could not be read",
                                      failure=type(failure))
            )
        )


@pytest.mark.unit
def test_metrics_one_window_of_which_cannot_be_read_are_none_read() -> None:
    # Never the windows that answered alone. A read whose rows stop where the
    # failed window begins is what a metrics outage looks like, and the document
    # would say the service's metrics stopped where only the read did.
    span = timedelta(minutes=get_settings().metrics_window_minutes)
    some_end = DONT_CARE_START + 2 * span

    Scenario() \
        .given(
            read := _a_session_answering([_a_minute(DONT_CARE_START)],
                                         McpToolError(SOME_FAILURE))
        ) \
        .when(
            lambda: _the_sources_over(read).metrics(DONT_CARE_START, some_end, None)
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
def test_pay_bands_that_cannot_be_read_are_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    Scenario() \
        .given(sources := _the_sources_whose_bands_cannot_be_read()) \
        .when(lambda: sources.bands()) \
        .then(
            one_record_was_logged(caplog, "orchestrator.sources", logging.WARNING,
                                  "pay bands could not be read",
                                  failure=PayBandsUnavailable)
        )


@pytest.mark.unit
def test_the_paging_rule_is_asked_of_the_read_tier() -> None:
    # The rule's own definition, over the session the metrics are read on - its
    # standing whole, which says how long it waits and what series it watches.
    some_rule = "kuki-rule"
    some_standing = AlertRuleStanding(rule=some_rule,
                                      is_normal=True,
                                      evaluated_at=DONT_CARE_END,
                                      range_seconds=60,
                                      interval_seconds=60,
                                      keep_firing_for_seconds=0,
                                      pending_seconds=300,
                                      series_query=SeriesQuery("avg(some_confident_ratio)"))

    Scenario() \
        .given(
            read := _a_session_answering_the_rule(some_standing)
        ) \
        .when(
            lambda: _the_sources_over(read).alert_rule(some_rule)
        ) \
        .then(
            all_of(
                the_answer_was(some_standing),
                _the_rules_asked_for_were(read, [some_rule])
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("failure", [McpToolError(SOME_FAILURE),
                                     McpUnreachable(SOME_FAILURE),
                                     McpError(ErrorData(code=httpx.codes.REQUEST_TIMEOUT,
                                                        message=SOME_FAILURE))],
                         ids=["tool-failed", "unreachable", "timed-out"])
def test_a_rule_the_read_tier_cannot_read_is_answered_as_unread(
    failure: Exception,
    caplog: pytest.LogCaptureFixture
) -> None:
    # `None`, never a standing made up: a rule that fires at once and one nobody
    # could read are told to the model differently. A read that got no answer
    # in time - which the SDK raises as its own timeout, asked twice - read the
    # rule no more than one refused; raised instead, it loses the postmortem.
    Scenario() \
        .given(read := _a_session_whose_tool_fails(failure)) \
        .when(lambda: _the_sources_over(read).alert_rule(DONT_CARE_RULE)) \
        .then(
            all_of(
                the_answer_was(None),
                one_record_was_logged(caplog, "orchestrator.sources", logging.WARNING,
                                      "alert rule could not be read",
                                      failure=type(failure))
            )
        )


def _the_sources_over(session: McpClient) -> Sources:
    """Every source, the read tier among them over `session`, and every vendor
    read one that must not be made."""
    return the_real_sources(
        get_settings(), _connections_that_must_not_be_opened(), ReadTier(session),
        DONT_CARE_THRESHOLDS, oncall=None,
        charges=_never_read("the payment provider"),
        published=_never_read("the rate provider"),
        bands=_never_read("the HR source")
    )


def _the_sources_whose_bands_cannot_be_read() -> Sources:
    """Every source, the HR source among them refusing as an unreadable one does."""
    def unreadable() -> PayBandsByTitle:
        raise PayBandsUnavailable(SOME_FAILURE)

    return the_real_sources(
        get_settings(),
        _connections_that_must_not_be_opened(),
        ReadTier(_a_session_that_remembers_what_it_was_asked()),
        DONT_CARE_THRESHOLDS,
        oncall=None,
        charges=_never_read("the payment provider"),
        published=_never_read("the rate provider"),
        bands=unreadable
    )


def _never_read(source: str) -> Callable[..., NoReturn]:
    def read(*dont_care_args: object, **dont_care_keywords: object) -> NoReturn:
        raise AssertionError(f"Expected nothing to be read from {source}.")

    return read


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


def _a_session_answering(*answers: list[MetricBucket] | Exception) -> Mock:
    """A client answering each call with the next of `answers`, in turn - or
    raising it, where it is a failure."""
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.side_effect = list(answers)

    return client


def _a_session_answering_the_rule(standing: AlertRuleStanding) -> Mock:
    """A client answering with the rule's standing."""
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.return_value = standing

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
