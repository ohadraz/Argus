"""The metrics channel: the minutes the onset was measured from.

The channel with nothing to get wrong, and that is the design rather than an
accident - the span belongs to the metrics source, so the model is not offered
a window it could narrow past the onset it was handed. What is left to test is
that the anchor is the alert, that the buckets actually reach the model, and
that an alert with no start time still gets read.
"""

from __future__ import annotations

from unittest.mock import Mock, call, create_autospec

import pytest
from agent_investigator.retrieval import MetricsFetcher
from agent_investigator.tools import METRICS_TOOL
from agent_investigator.tools.metrics import metrics_tool
from argus_core.models import MetricBucket, ToolDefinition, ToolResult
from argus_testkit import Assertion, Scenario

from agent_investigator_test.framework.assertions.tool_results import the_result_failed
from agent_investigator_test.framework.builders.dispatcher import (
    AN_ALERT_TIME,
    a_call_to,
    a_dispatcher,
)

# The column the paging rule's own series is carried under, restated rather than
# imported: it is the name the model reads, and a test that imported it would
# agree with whatever it was renamed to.
THE_RULES_COLUMN = "rule_reading"


@pytest.mark.unit
def test_a_metrics_call_reads_the_span_around_the_alert() -> None:
    # The alert is the anchor because it is the one moment Argus knows the
    # service was unhealthy. The onset is inferred from these very buckets, so
    # anchoring on it would be reading the answer back into the question.
    some_fetch_metrics = create_autospec(MetricsFetcher, instance=True, return_value=[])

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_metrics=some_fetch_metrics)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(METRICS_TOOL))
        ) \
        .then(
            _the_metrics_read_were_anchored_on(some_fetch_metrics, AN_ALERT_TIME)
        )


@pytest.mark.unit
def test_a_metrics_call_reads_the_series_the_rule_watches() -> None:
    # The model's own re-read is the read the loop made before its first turn,
    # and has to come back with the same minutes. Read for no rule, it would come
    # back without the one column a quality incident departs in - and a model
    # comparing the two would watch that series vanish.
    some_rule = "kuki-rule"
    some_fetch_metrics = create_autospec(MetricsFetcher, instance=True, return_value=[])

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_metrics=some_fetch_metrics, rule=some_rule)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(METRICS_TOOL))
        ) \
        .then(
            _the_metrics_read_were_anchored_on(some_fetch_metrics, AN_ALERT_TIME, some_rule)
        )


@pytest.mark.unit
def test_the_buckets_that_came_back_are_what_the_model_is_shown() -> None:
    # A channel that reads correctly and reports nothing is the failure this
    # catches: the model would see an empty result and conclude the minutes
    # were unremarkable, which is not what was retrieved.
    a_bucket_that_came_back = _a_bucket(bucket_id="2026-08-29T22:16:00Z", error_rate=0.42)
    some_fetch_metrics = create_autospec(
        MetricsFetcher, instance=True, return_value=[a_bucket_that_came_back]
    )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_metrics=some_fetch_metrics)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(METRICS_TOOL))
        ) \
        .then(
            _the_result_shows(a_bucket_that_came_back)
        )


@pytest.mark.unit
def test_an_alert_with_no_start_time_still_reads_the_metrics() -> None:
    # An alert that never said when it started is not a reason to skip the
    # channel the onset came from. The metrics source has its own idea of
    # where to look when it is given no anchor, and that is the honest thing
    # to pass on rather than an anchor invented here.
    some_fetch_metrics = create_autospec(MetricsFetcher, instance=True, return_value=[])

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_metrics=some_fetch_metrics, alert_time=None)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(METRICS_TOOL))
        ) \
        .then(
            _the_metrics_read_were_anchored_on(some_fetch_metrics, None)
        )


@pytest.mark.unit
def test_the_metrics_tool_offers_no_window_to_narrow() -> None:
    # The span is the metrics source's own and is already wider than any log
    # window. Offering bounds here would invite the model to narrow the one
    # view that can show it an onset earlier than the one it was given.
    Scenario() \
        .when(
            lambda: metrics_tool()
        ) \
        .then(
            _the_tool_takes_no_arguments()
        )


@pytest.mark.unit
def test_the_metrics_tool_says_what_the_rules_column_is() -> None:
    # A column the model is not told about is a number it has to guess the
    # meaning of, and this is the one reading whose direction its name does not
    # give away: a share of confident answers is worse falling.
    Scenario() \
        .when(
            lambda: metrics_tool()
        ) \
        .then(
            _the_tool_description_names(THE_RULES_COLUMN)
        )


@pytest.mark.unit
def test_a_metrics_tier_that_would_not_answer_costs_one_channel_not_the_walk() -> None:
    # The one channel whose reader lets a failure out. Logs, changes and
    # dependencies each catch what their fetch raises and come back as a result
    # the model can read and recover from; metrics does not, so a read tier that
    # will not answer leaves `dispatch` by exception, leaves `investigate` with
    # it, and ends the run - with every minute already retrieved thrown away and
    # the incident stranded mid-walk, no verdict and nothing said about why.
    #
    # The same read failing *before* the conversation is already handled: it
    # comes back as an investigation with one candidate and no turn bought. So
    # this is the identical failure treated two ways depending on when it lands,
    # and the later one is the expensive way round.
    #
    # `logs.py` gives the reason in as many words: a tier that would not answer
    # is the least of the reasons to throw an investigation away, because it says
    # nothing about the incident at all. Measured on the stack, this ended 2 of 3
    # walks.
    some_fetch_metrics = create_autospec(
        MetricsFetcher,
        instance=True,
        side_effect=TimeoutError("the read tier did not answer in time")
    )

    Scenario() \
        .given(
            some_dispatcher := a_dispatcher(reads_metrics=some_fetch_metrics)
        ) \
        .when(
            lambda: some_dispatcher.dispatch(a_call_to(METRICS_TOOL))
        ) \
        .then(
            the_result_failed()
        )


def _the_metrics_read_were_anchored_on(reader: Mock,
                                       alert_time: str | None,
                                       rule: str | None = None) -> Assertion[ToolResult]:
    """What the metrics channel was actually anchored on, and for which rule.

    Compared against `call_args` rather than through `assert_called_once_with`,
    which does not survive a spec built from a `Protocol`: `self` is left on the
    signature, so every comparison fails while printing identically.
    """
    def assertion(dont_care_result: ToolResult) -> bool:
        if reader.call_count != 1 or reader.call_args != call(alert_time, rule):
            raise AssertionError(
                f"Expected the metrics to be read once anchored on [{alert_time}] "
                f"for the rule [{rule}], and they were read {reader.call_count} "
                f"time(s) as {reader.call_args}."
            )

        return True

    return assertion


def _the_result_shows(bucket: MetricBucket) -> Assertion[ToolResult]:
    """The minute, and what it looked like, both legible to the model."""
    def assertion(result: ToolResult) -> bool:
        missing = [
            str(value) for value in (bucket.bucket_id, bucket.error_rate)
            if str(value) not in result.content
        ]
        if missing:
            raise AssertionError(
                f"Expected the result to show {missing}, got [{result.content}]."
            )

        return True

    return assertion


def _the_tool_description_names(column: str) -> Assertion[ToolDefinition]:
    """That the offer tells the model about one column by its name."""
    def assertion(tool: ToolDefinition) -> bool:
        if column not in tool.description:
            raise AssertionError(
                f"Expected {tool.name}'s description to name [{column}], "
                f"got [{tool.description}]."
            )

        return True

    return assertion


def _the_tool_takes_no_arguments() -> Assertion[ToolDefinition]:
    """Nothing to name is what makes this channel's span reproducible."""
    def assertion(tool: ToolDefinition) -> bool:
        if tool.properties or tool.required:
            raise AssertionError(
                f"Expected {tool.name} to take no arguments, but it offers "
                f"{sorted(tool.properties)} and requires {tool.required}."
            )

        return True

    return assertion


def _a_bucket(bucket_id: str, error_rate: float) -> MetricBucket:
    """One minute of metrics, with only the two numbers a test names.

    The rest are required by the model and irrelevant to every test here, so
    they are fixed rather than parameterised.
    """
    return MetricBucket(
        bucket_id=bucket_id,
        error_rate=error_rate,
        p50_ms=40,
        p95_ms=120,
        p99_ms=220,
        request_volume=500,
        memory_used_bytes=440 * 1024**2,
        process_start_time_seconds=1_756_000_000.0,
        cpu_used_cores=0.77,
        cpu_limit_cores=3.0
    )
