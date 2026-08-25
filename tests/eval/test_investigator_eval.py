from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from argus_core.anthropic_llm import AnthropicLLMClient
from argus_core.config import get_settings
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_testkit.assertions import at_least
from argus_testkit.scenario import Scenario

from tests.framework.assertions import no_cause_was_determined, the_cause_was_identified_as

# An eval judges the model's answer, not Argus's plumbing, so it talks to the
# real API and spends tokens every run. The evidence below is pinned in this
# file rather than pulled from the Target Service on purpose: if the fixture
# can drift, a change in the score no longer tells you anything about the model.
needs_the_real_api = pytest.mark.skipif(
    not get_settings().anthropic_api_key,
    reason="no ANTHROPIC_API_KEY: an eval has nothing to measure without the real model",
)

# The model samples, so one call is a draw and not a verdict. Each case is run
# this many times and scored as a rate.
RUNS_PER_CASE = 10

# Measured, not guessed: 50 samples of each case on claude-opus-5, taken in two
# rounds of 25 on 2026-08-25, came back 50/50 on both. Fifty clean samples put
# the true per-call rate at 0.94 or better with 95% confidence, and at that
# pessimistic bound a 9-of-10 bar would cry wolf on 12% of runs while 8-of-10
# does so on 2%. Eight still fires on a regression worth knowing about: a drop
# to a 70% per-call rate passes this bar only 38% of the time.
#
# Both cases get the same number because the measurement gave them the same
# score. Re-measure and re-set these after any prompt change - that is the
# whole point of them.
MUST_IDENTIFY_THE_FLAG_TOGGLE = 8
MUST_STAY_UNDETERMINED = 8

ONSET = datetime(2026, 3, 2, 10, 5, tzinfo=UTC)
CALM_ERROR_RATE = 0.01
SPIKED_ERROR_RATE = 0.38
STEADY_P95_MS = 220

A_SUCCESS = "INFO checkout: request succeeded"
A_FLAG_TOGGLED_ON = "WARN checkout: feature flag 'checkout-v2' toggled from 'off' to 'on'"
A_FAILURE_IN_THE_FLAGGED_PATH = (
    "ERROR checkout: request failed - unhandled exception in checkout-v2 path"
)
A_FAILURE_FROM_UPSTREAM = "ERROR checkout: request failed - upstream returned 503"


@pytest.mark.eval
@needs_the_real_api
def test_a_flag_toggled_on_before_the_error_spike_is_identified() -> None:
    some_evidence = an_incident_where_a_flag_was_toggled_on()

    Scenario() \
        .given(
            some_evidence
        ) \
        .when(
            lambda: _the_real_model_judges_repeatedly(some_evidence)
        ) \
        .then(
            at_least(
                MUST_IDENTIFY_THE_FLAG_TOGGLE,
                the_cause_was_identified_as(CauseType.FEATURE_FLAG_TOGGLE),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_an_error_spike_with_no_change_event_is_left_undetermined() -> None:
    # The honest-failure path, measured. Nothing in this evidence explains the
    # spike, and a model that names a cause anyway is the failure mode the
    # whole "undetermined is a valid answer" instruction exists to prevent.
    some_evidence = an_incident_with_no_change_event()

    Scenario() \
        .given(
            some_evidence
        ) \
        .when(
            lambda: _the_real_model_judges_repeatedly(some_evidence)
        ) \
        .then(
            at_least(MUST_STAY_UNDETERMINED, no_cause_was_determined())
        )


def an_incident_where_a_flag_was_toggled_on() -> Evidence:
    return _an_incident(
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(0, A_FLAG_TOGGLED_ON),
            a_log_line_at(1, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(2, A_FAILURE_IN_THE_FLAGGED_PATH),
        ],
    )


def an_incident_with_no_change_event() -> Evidence:
    # Same spike, same buckets, one thing missing: anything that changed. The
    # two fixtures share `_a_calm_stretch_then_a_spike` so they cannot drift
    # apart in some second way - if they did, the eval would be measuring the
    # fixture rather than the model.
    return _an_incident(
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(1, A_FAILURE_FROM_UPSTREAM),
            a_log_line_at(2, A_FAILURE_FROM_UPSTREAM),
        ],
    )


def a_bucket_at(offset_minutes: int, error_rate: float) -> MetricBucket:
    return MetricBucket(
        bucket_id=_minute(offset_minutes),
        error_rate=error_rate,
        p50_ms=45,
        p95_ms=STEADY_P95_MS,
        request_volume=1200,
    )


def a_log_line_at(offset_minutes: int, message: str) -> str:
    return f"{_minute(offset_minutes)} {message}"


def _a_calm_stretch_then_a_spike() -> list[MetricBucket]:
    """Three calm minutes, then two spiked ones - onset at offset 1.

    Latency and volume stay flat throughout, so error rate is the only thing
    that moved and a deploy-shaped explanation has nothing to stand on.
    """
    return [
        a_bucket_at(-2, CALM_ERROR_RATE),
        a_bucket_at(-1, CALM_ERROR_RATE),
        a_bucket_at(0, CALM_ERROR_RATE),
        a_bucket_at(1, SPIKED_ERROR_RATE),
        a_bucket_at(2, SPIKED_ERROR_RATE),
    ]


def _minute(offset_minutes: int) -> str:
    return (ONSET + timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:00Z")


def _an_incident(buckets: list[MetricBucket], log_lines: list[str]) -> Evidence:
    return Evidence(
        incident_id=new_id(),
        alert=Alert(
            service="checkout",
            alert_name="HighErrorRate",
            severity="critical",
            summary="error rate above 25% for 5 minutes",
        ),
        metric_buckets=buckets,
        log_lines=log_lines,
        log_window_start=buckets[0].bucket_id,
        log_window_end=buckets[-1].bucket_id,
    )


def _the_real_model_judges_repeatedly(evidence: Evidence) -> list[Hypothesis]:
    """Asks the same question `RUNS_PER_CASE` times, concurrently.

    Concurrently because ten sequential Opus calls at high effort is minutes of
    wall clock, and the SDK client is safe to share across threads. One client
    for all of them, so they share a connection pool.
    """
    client = AnthropicLLMClient(get_settings())

    with ThreadPoolExecutor(max_workers=RUNS_PER_CASE) as pool:
        return list(pool.map(lambda _: client.propose_hypothesis(evidence), range(RUNS_PER_CASE)))
