from __future__ import annotations

from unittest.mock import Mock, create_autospec

import pytest
from agent_investigator.retrieval import fetch_metrics
from agent_investigator.tools import METRICS_TOOL
from agent_investigator.tools.metrics import metrics_tool
from argus_core.models.metrics import MetricBucket
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import ToolResult
from argus_testkit import Assertion, Scenario

from ..framework.builders.dispatcher import AN_ALERT_TIME, a_call_to, a_dispatcher

"""The metrics channel: the minutes the onset was measured from.

The channel with nothing to get wrong, and that is the design rather than an
accident - the span belongs to the metrics source, so the model is not offered
a window it could narrow past the onset it was handed. What is left to test is
that the anchor is the alert, that the buckets actually reach the model, and
that an alert with no start time still gets read.
"""


@pytest.mark.unit
def test_a_metrics_call_reads_the_span_around_the_alert() -> None:
    # The alert is the anchor because it is the one moment Argus knows the
    # service was unhealthy. The onset is inferred from these very buckets, so
    # anchoring on it would be reading the answer back into the question.
    some_fetch_metrics = create_autospec(fetch_metrics, return_value=[])

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
def test_the_buckets_that_came_back_are_what_the_model_is_shown() -> None:
    # A channel that reads correctly and reports nothing is the failure this
    # catches: the model would see an empty result and conclude the minutes
    # were unremarkable, which is not what was retrieved.
    a_bucket_that_came_back = _a_bucket(bucket_id="2026-08-29T22:16:00Z", error_rate=0.42)
    some_fetch_metrics = create_autospec(
        fetch_metrics, return_value=[a_bucket_that_came_back]
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
    some_fetch_metrics = create_autospec(fetch_metrics, return_value=[])

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


def _the_metrics_read_were_anchored_on(reader: Mock,
                                       alert_time: str | None) -> Assertion[ToolResult]:
    """What the metrics channel was actually anchored on."""
    def assertion(dont_care_result: ToolResult) -> bool:
        reader.assert_called_once_with(alert_time)

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
        request_volume=500
    )
