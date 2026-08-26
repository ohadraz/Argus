from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from argus_core.anthropic_llm import AnthropicLLMClient
from argus_core.config import get_settings
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.change_event import ChangeEvent, ChangeKind
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
# rounds of 25 on 2026-08-26, came back 50/50 on all four. Fifty clean samples
# put the true per-call rate at 0.94 or better with 95% confidence, and at that
# pessimistic bound a 9-of-10 bar would cry wolf on 12% of runs while 8-of-10
# does so on 2%. Eight still fires on a regression worth knowing about: a drop
# to a 70% per-call rate passes this bar only 38% of the time.
#
# All four get the same number because the measurement gave them the same
# score. Re-measure and re-set these after any prompt change - that is the
# whole point of them. This set was measured against the prompt as of the
# change-event work: a change section that does not discount itself, a named
# change window, and calibrated confidence bands in the system prompt. The
# same fixtures under the previous wording scored the deploy case at 0.65
# rather than 0.80, which is what those three edits were worth.
MUST_IDENTIFY_THE_FLAG_TOGGLE = 8
MUST_STAY_UNDETERMINED = 8
MUST_IDENTIFY_THE_BAD_DEPLOYMENT = 8
MUST_NOT_BLAME_THE_UNRELATED_CHANGE = 8

ONSET = datetime(2026, 3, 2, 10, 5, tzinfo=UTC)
# Which bucket the incident actually starts in. Every fixture below opens with
# three calm minutes, so the departure - error rate or latency - lands here.
ONSET_OFFSET_MINUTES = 1

CALM_ERROR_RATE = 0.01
SPIKED_ERROR_RATE = 0.38
CALM_P50_MS = 45
CALM_P95_MS = 220
SLOW_P50_MS = 900
SLOW_P95_MS = 4800

A_SUCCESS = "INFO checkout: request succeeded"
A_SLOW_SUCCESS = "INFO checkout: request succeeded in 4820ms"
A_FLAG_TOGGLED_ON = "WARN checkout: feature flag 'checkout-v2' toggled from 'off' to 'on'"
A_FAILURE_IN_THE_FLAGGED_PATH = (
    "ERROR checkout: request failed - unhandled exception in checkout-v2 path"
)
A_FAILURE_FROM_UPSTREAM = "ERROR checkout: request failed - upstream returned 503"

A_PRICING_REWRITE = "checkout: replace the cached pricing lookup with a per-item query"
A_LOG_LEVEL_BUMP = "checkout: raise the structured-log level from info to debug"


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


@pytest.mark.eval
@needs_the_real_api
def test_a_deploy_before_a_latency_departure_is_identified() -> None:
    # What the third channel is for. The deploy appears in no log line and
    # lands before the log window even opens, so this is a cause that logs
    # alone could not have reached at any widening - and the deploy says what
    # it changed, never that it was slow. Reading a per-item query as a
    # latency regression is the judgement being measured.
    some_evidence = an_incident_where_a_deploy_slowed_the_service()

    Scenario() \
        .given(
            some_evidence
        ) \
        .when(
            lambda: _the_real_model_judges_repeatedly(some_evidence)
        ) \
        .then(
            at_least(
                MUST_IDENTIFY_THE_BAD_DEPLOYMENT,
                the_cause_was_identified_as(CauseType.BAD_DEPLOYMENT),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_change_that_does_not_explain_the_symptoms_is_not_blamed() -> None:
    # The cost of the third channel, measured. This is the undetermined case
    # above with one deploy added and nothing else touched, so a drop here
    # says precisely one thing: handing the model something that *looks* like
    # an actor made it name a cause it had no evidence for. A log-level bump
    # does not return 503s from somebody else's service.
    some_evidence = an_incident_with_an_unrelated_change()

    Scenario() \
        .given(
            some_evidence
        ) \
        .when(
            lambda: _the_real_model_judges_repeatedly(some_evidence)
        ) \
        .then(
            at_least(MUST_NOT_BLAME_THE_UNRELATED_CHANGE, no_cause_was_determined())
        )


def an_incident_where_a_flag_was_toggled_on() -> Evidence:
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(0, A_FLAG_TOGGLED_ON),
            a_log_line_at(1, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(2, A_FAILURE_IN_THE_FLAGGED_PATH),
        ],
        changes=[],
    )


def an_incident_with_no_change_event() -> Evidence:
    # Same spike, same buckets, one thing missing: anything that changed. The
    # two fixtures share `_a_calm_stretch_then_a_spike` so they cannot drift
    # apart in some second way - if they did, the eval would be measuring the
    # fixture rather than the model.
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=_an_upstream_outage(),
        changes=[],
    )


def an_incident_with_an_unrelated_change() -> Evidence:
    # Deliberately `an_incident_with_no_change_event` plus one deploy, sharing
    # its alert, its buckets and its log lines. The single difference between
    # the two fixtures is the difference the two scores are allowed to
    # attribute anything to.
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=_an_upstream_outage(),
        changes=[a_deploy_at(-2, "4d1b90c", A_LOG_LEVEL_BUMP)],
    )


def an_incident_where_a_deploy_slowed_the_service() -> Evidence:
    return _an_incident(
        alert=a_latency_alert(),
        buckets=_a_calm_stretch_then_a_latency_departure(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(1, A_SLOW_SUCCESS),
            a_log_line_at(2, A_SLOW_SUCCESS),
        ],
        # Four minutes before the earliest bucket, so it is outside the log
        # window this evidence declares and reachable only through the change
        # channel.
        changes=[a_deploy_at(-6, "a3f9c21", A_PRICING_REWRITE)],
    )


def an_error_rate_alert() -> Alert:
    return Alert(
        service="checkout",
        alert_name="HighErrorRate",
        severity="critical",
        summary="error rate above 25% for 5 minutes",
    )


def a_latency_alert() -> Alert:
    return Alert(
        service="checkout",
        alert_name="HighLatency",
        severity="critical",
        summary="p95 latency above 2s for 5 minutes",
    )


def a_bucket_at(
    offset_minutes: int,
    error_rate: float,
    p50_ms: int = CALM_P50_MS,
    p95_ms: int = CALM_P95_MS,
) -> MetricBucket:
    return MetricBucket(
        bucket_id=_minute(offset_minutes),
        error_rate=error_rate,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        request_volume=1200,
    )


def a_log_line_at(offset_minutes: int, message: str) -> str:
    return f"{_minute(offset_minutes)} {message}"


def a_deploy_at(offset_minutes: int, revision: str, summary: str) -> ChangeEvent:
    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=_minute(offset_minutes),
        reference=revision,
        summary=summary,
        actor="release-bot",
        source="https://github.com/acme/k8s-configs/apps/checkout/production",
    )


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


def _a_calm_stretch_then_a_latency_departure() -> list[MetricBucket]:
    """The same shape, moved to the other axis: p50 and p95 depart, error rate
    does not.

    A slow service is still a serving service, so nothing here reads as a
    failure - which is what stops the model from reaching for the flag-toggle
    or upstream-outage stories the other fixtures tell.
    """
    return [
        a_bucket_at(-2, CALM_ERROR_RATE),
        a_bucket_at(-1, CALM_ERROR_RATE),
        a_bucket_at(0, CALM_ERROR_RATE),
        a_bucket_at(1, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS),
        a_bucket_at(2, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS),
    ]


def _an_upstream_outage() -> list[str]:
    """Failures the service reports but does not own - the fault is somebody
    else's, and nothing the service deployed would account for them."""
    return [
        a_log_line_at(-1, A_SUCCESS),
        a_log_line_at(1, A_FAILURE_FROM_UPSTREAM),
        a_log_line_at(2, A_FAILURE_FROM_UPSTREAM),
    ]


def _minute(offset_minutes: int) -> str:
    return (ONSET + timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:00Z")


def _an_incident(
    alert: Alert,
    buckets: list[MetricBucket],
    log_lines: list[str],
    changes: list[ChangeEvent],
) -> Evidence:
    # The change window is the one `investigate` would have asked for: the
    # configured lookback, ending at the onset. Stated rather than left out
    # because the prompt names it, and evidence that omitted it would measure
    # a prompt shape production never sends.
    lookback_minutes = get_settings().change_lookback_minutes

    return Evidence(
        incident_id=new_id(),
        alert=alert,
        metric_buckets=buckets,
        log_lines=log_lines,
        change_events=changes,
        log_window_start=buckets[0].bucket_id,
        log_window_end=buckets[-1].bucket_id,
        change_window_start=_minute(ONSET_OFFSET_MINUTES - lookback_minutes),
        change_window_end=_minute(ONSET_OFFSET_MINUTES),
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
