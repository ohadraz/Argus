from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from agent_investigator import Findings, investigate
from agent_investigator.budget import Bound, Budget
from argus_core.config import get_settings
from argus_core.events import RetrievalChannel
from argus_core.ids import new_id
from argus_core.llm.client_selection import get_llm_client
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn
from argus_core.timestamps import parse_iso
from argus_testkit.assertions import Assertion, all_of, at_least
from argus_testkit.scenario import Scenario

from tests.framework.assertions import no_cause_was_determined, the_cause_was_identified_as

# An eval judges the model's judgement, not Argus's plumbing, so it talks to the
# real API and spends tokens every run. Each run is now a whole investigation -
# the model chooses which channel to read, over what window, and when it has
# seen enough - which is the thing worth measuring: the loop hands it three
# tools and no sequence, so what it does with them *is* the behaviour.
#
# The evidence below is pinned in this file rather than pulled from the Target
# Service on purpose: if the fixture can drift, a change in the score no longer
# tells you anything about the model. The retrieval seams serve it as the real
# ones would - a window in, only what falls inside it out - so a cause outside
# the window the model asked for is genuinely not in front of it, and widening
# is a decision it has to make rather than one the fixture makes for it.
needs_the_real_api = pytest.mark.skipif(
    not get_settings().anthropic_api_key,
    reason="no ANTHROPIC_API_KEY: an eval has nothing to measure without the real model",
)

# The model samples, so one call is a draw and not a verdict. Each case is run
# this many times and scored as a rate.
RUNS_PER_CASE = 10

# **Provisional, and inherited rather than measured.** The 8-of-10 bar below
# was derived from 50 samples of each case against the single-shot prompt this
# loop replaces - one question, one answer, the whole evidence handed over
# unasked. Nothing about that measurement carries over to a model that chooses
# its own reads: the same fixture can now be failed by reading the wrong window
# as well as by judging the evidence wrongly.
#
# So these are a starting bar, not a finding. Run the suite a few times, take
# the rates it actually scores, and re-set each of these from them - and
# re-measure after any change to `BRIEF`, to a tool description, or to the
# budget, which is the whole point of them.
MUST_IDENTIFY_THE_FLAG_TOGGLE = 8
MUST_STAY_UNDETERMINED = 8
MUST_IDENTIFY_THE_BAD_DEPLOYMENT = 8
MUST_NOT_BLAME_THE_UNRELATED_CHANGE = 8
MUST_READ_PAST_THE_LOWER_BOUND = 8

# The budget every case is measured under, pinned here for the same reason the
# evidence is: a rate that moved with a deployment's `.env` would say nothing
# about the model. These are the configured defaults as they stand, restated so
# that changing them is a change to this file and shows up in review beside the
# thresholds it would invalidate.
MAX_TOOL_CALLS = 12
MAX_TOKENS = 150_000
MAX_SECONDS = 300.0

ONSET = datetime(2026, 3, 2, 10, 5, tzinfo=UTC)
# Which bucket the incident actually starts in. The four fixtures that open
# calm depart here - error rate or latency - three minutes into their window.
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

# Where the toggle sits in the widening fixture: far enough before the onset
# that the default log window - which reaches back `log_initial_lookback_minutes`
# - cannot contain it, and well inside the ceiling on a widened one, so reading
# it is affordable rather than merely permitted.
TOGGLED_LONG_BEFORE_THE_WINDOW_OPENS = -45


@pytest.mark.eval
@needs_the_real_api
def test_a_flag_toggled_on_before_the_error_spike_is_identified() -> None:
    some_incident = an_incident_where_a_flag_was_toggled_on()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            at_least(
                MUST_IDENTIFY_THE_FLAG_TOGGLE,
                _a_run_where(the_cause_was_identified_as(CauseType.FEATURE_FLAG_TOGGLE)),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_an_error_spike_with_no_change_event_is_left_undetermined() -> None:
    # The honest-failure path, measured. Nothing in this evidence explains the
    # spike, and a model that names a cause anyway is the failure mode the
    # whole "undetermined is a valid answer" instruction exists to prevent.
    # It is also the case a tool loop makes easier to fail: a model that can
    # keep asking has more chances to talk itself into something.
    some_incident = an_incident_with_no_change_event()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            at_least(MUST_STAY_UNDETERMINED, _a_run_where(no_cause_was_determined()))
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_deploy_before_a_latency_departure_is_identified() -> None:
    # What the third channel is for, and now a decision rather than a gift.
    # The deploy appears in no log line and lands before any log window the
    # model can afford, so this cause is reachable only by choosing to read the
    # change channel at all - and the deploy says what it changed, never that
    # it was slow. Reading a per-item query as a latency regression is the
    # judgement being measured; reaching for the channel that holds it is the
    # judgement the loop added.
    some_incident = an_incident_where_a_deploy_slowed_the_service()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            at_least(
                MUST_IDENTIFY_THE_BAD_DEPLOYMENT,
                _a_run_where(the_cause_was_identified_as(CauseType.BAD_DEPLOYMENT)),
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
    some_incident = an_incident_with_an_unrelated_change()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            at_least(
                MUST_NOT_BLAME_THE_UNRELATED_CHANGE,
                _a_run_where(no_cause_was_determined()),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_an_onset_that_is_only_a_lower_bound_is_read_past() -> None:
    # The judgement the widening schedule used to make for the model, now the
    # model's own. Every minute retrieved is inside the incident, so the onset
    # is a lower bound and the opening message says so; the toggle that caused
    # it happened before the window opens, and the default log window cannot
    # reach it. A model that reads the default window and answers has answered
    # from evidence that never contained the cause.
    #
    # What is scored is the reach, not the verdict. Whether it then names the
    # toggle is the flag-toggle case above; what is measured here is that it
    # asked for a window earlier than the one it was given for free - the one
    # move no amount of confidence would prompt, since it cannot miss what it
    # was never shown.
    some_incident = an_incident_underway_before_the_window_opens()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            at_least(
                MUST_READ_PAST_THE_LOWER_BOUND,
                _a_run_where_the_logs_were_read_before(_the_default_log_window_opens_at()),
            )
        )


@dataclass(frozen=True)
class Incident:
    """One pinned incident, as the three retrieval channels would serve it.

    The alert and the metrics are what the loop reads before the model's first
    turn. The log lines and the changes are what is *available* to be read -
    which is not the same as what the model will see, and the difference is
    most of what these evals measure.
    """

    alert: Alert
    buckets: list[MetricBucket]
    log_lines: list[str]
    changes: list[ChangeEvent]


@dataclass(frozen=True)
class Run:
    """One whole investigation, and what it cost.

    The budget is asked afterwards rather than inferred from the summary: an
    investigation that ran out says so in prose meant for a human, and a score
    that depended on that wording would fail the day it is reworded.
    """

    findings: Findings
    ran_out_of: list[Bound]


def an_incident_where_a_flag_was_toggled_on() -> Incident:
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(0, A_FLAG_TOGGLED_ON),
            a_log_line_at(1, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(2, A_FAILURE_IN_THE_FLAGGED_PATH)
        ],
        changes=[]
    )


def an_incident_with_no_change_event() -> Incident:
    # Same spike, same buckets, one thing missing: anything that changed. The
    # two fixtures share `_a_calm_stretch_then_a_spike` so they cannot drift
    # apart in some second way - if they did, the eval would be measuring the
    # fixture rather than the model.
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=_an_upstream_outage(),
        changes=[]
    )


def an_incident_with_an_unrelated_change() -> Incident:
    # Deliberately `an_incident_with_no_change_event` plus one deploy, sharing
    # its alert, its buckets and its log lines. The single difference between
    # the two fixtures is the difference the two scores are allowed to
    # attribute anything to.
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=_an_upstream_outage(),
        changes=[a_deploy_at(-2, "4d1b90c", A_LOG_LEVEL_BUMP)]
    )


def an_incident_where_a_deploy_slowed_the_service() -> Incident:
    return _an_incident(
        alert=a_latency_alert(),
        buckets=_a_calm_stretch_then_a_latency_departure(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(1, A_SLOW_SUCCESS),
            a_log_line_at(2, A_SLOW_SUCCESS)
        ],
        # Six minutes before the onset and in no log line at all: the change
        # channel is the only place this exists, whatever window the model
        # reads the logs over.
        changes=[a_deploy_at(-6, "a3f9c21", A_PRICING_REWRITE)]
    )


def an_incident_underway_before_the_window_opens() -> Incident:
    """Every retrieved minute is inside the incident, and the cause is outside.

    The metrics never return to a true baseline - the worst minutes are the
    ones the window opens on, and the rest merely ease off - so the onset lands
    on the earliest bucket and is reported to the model as a lower bound.

    The toggle that explains all of it sits far enough back that the default
    log window cannot contain it, while the failures it produced are visible
    throughout. So the evidence in front of a model that does not widen is a
    service failing in a code path, with nothing that says when that path
    changed.
    """
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_window_that_opens_inside_the_incident(),
        log_lines=[
            a_log_line_at(TOGGLED_LONG_BEFORE_THE_WINDOW_OPENS - 1, A_SUCCESS),
            a_log_line_at(TOGGLED_LONG_BEFORE_THE_WINDOW_OPENS, A_FLAG_TOGGLED_ON),
            a_log_line_at(TOGGLED_LONG_BEFORE_THE_WINDOW_OPENS + 1, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(0, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(1, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(3, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(5, A_FAILURE_IN_THE_FLAGGED_PATH)
        ],
        changes=[]
    )


def an_error_rate_alert() -> Alert:
    return Alert(
        service="checkout",
        alert_name="HighErrorRate",
        severity="critical",
        summary="error rate above 25% for 5 minutes"
    )


def a_latency_alert() -> Alert:
    return Alert(
        service="checkout",
        alert_name="HighLatency",
        severity="critical",
        summary="p95 latency above 2s for 5 minutes"
    )


def a_bucket_at(offset_minutes: int,
                error_rate: float,
                p50_ms: int = CALM_P50_MS,
                p95_ms: int = CALM_P95_MS) -> MetricBucket:
    return MetricBucket(
        bucket_id=_minute(offset_minutes),
        error_rate=error_rate,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        request_volume=1200
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
        source="https://github.com/acme/k8s-configs/apps/checkout/production"
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
        a_bucket_at(2, SPIKED_ERROR_RATE)
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
        a_bucket_at(2, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS)
    ]


def _a_window_that_opens_inside_the_incident() -> list[MetricBucket]:
    """No calm stretch anywhere: the worst minutes are the first ones.

    Every rate here is ruinous - the quietest of them is twenty times the
    baseline the other fixtures idle at - but a departure is measured against
    the window's own quiet half, and this window's quiet half is merely the
    less-bad end of an incident. So the onset lands on the earliest bucket,
    which is exactly what makes it a lower bound rather than an onset.
    """
    return [
        a_bucket_at(0, 0.38),
        a_bucket_at(1, 0.36),
        a_bucket_at(2, 0.22),
        a_bucket_at(3, 0.21),
        a_bucket_at(4, 0.20),
        a_bucket_at(5, 0.21)
    ]


def _an_upstream_outage() -> list[str]:
    """Failures the service reports but does not own - the fault is somebody
    else's, and nothing the service deployed would account for them."""
    return [
        a_log_line_at(-1, A_SUCCESS),
        a_log_line_at(1, A_FAILURE_FROM_UPSTREAM),
        a_log_line_at(2, A_FAILURE_FROM_UPSTREAM)
    ]


def _minute(offset_minutes: int) -> str:
    return (ONSET + timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:00Z")


def _an_incident(alert: Alert,
                 buckets: list[MetricBucket],
                 log_lines: list[str],
                 changes: list[ChangeEvent]) -> Incident:
    return Incident(alert=alert, buckets=buckets, log_lines=log_lines, changes=changes)


def _the_default_log_window_opens_at() -> str:
    """Where the log window starts when the model names no bounds of its own.

    Derived from the setting the tool reads rather than restated, because what
    is being measured is "earlier than the free window" - and a hard-coded copy
    of it would keep passing after the setting moved while measuring something
    else.
    """
    lookback = get_settings().log_initial_lookback_minutes

    return _minute(-lookback)


def _the_real_model_investigates_repeatedly(incident: Incident) -> list[Run]:
    """Investigates the same incident `RUNS_PER_CASE` times, concurrently.

    Concurrently because a whole tool-use investigation at high effort is
    minutes of wall clock, and ten of them in sequence is most of an hour. The
    SDK client is safe to share across threads, so one client serves all of
    them and they share a connection pool.

    Each run gets its own budget: a shared one would have the first
    investigation to finish spending the tenth one's tokens, and every case
    would score whatever the scheduler happened to do.

    Nothing is recorded and nothing is published. What an eval reads is the
    findings and what they cost, and a run that also filed receipts would be
    measuring the same model through more code.
    """
    client = get_llm_client()

    def speak(transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
        return client.converse(transcript, tools)

    def investigate_once(_: int) -> Run:
        spend = Budget(
            max_tool_calls=MAX_TOOL_CALLS, max_tokens=MAX_TOKENS, max_seconds=MAX_SECONDS
        )
        findings = investigate(
            incident.alert,
            new_id(),
            fetch_metrics=_the_metrics_of(incident),
            fetch_logs=_the_logs_of(incident),
            fetch_change_events=_the_changes_of(incident),
            converse=speak,
            budget=spend
        )

        return Run(findings=findings, ran_out_of=spend.bounds_reached())

    with ThreadPoolExecutor(max_workers=RUNS_PER_CASE) as pool:
        return list(pool.map(investigate_once, range(RUNS_PER_CASE)))


def _the_metrics_of(incident: Incident) -> Callable[[str | None], list[MetricBucket]]:
    """The whole metrics span, whatever it is anchored on.

    The anchor is ignored on purpose: the metrics channel has one span and the
    model is told so, and a fixture that varied it by anchor would be inventing
    a retrieval the real one does not offer.
    """
    def fetch(dont_care_alert_time: str | None) -> list[MetricBucket]:
        return list(incident.buckets)

    return fetch


def _the_logs_of(incident: Incident) -> Callable[[str, str], list[str]]:
    """Only the lines inside the window asked for - which is the whole point.

    A fetcher that returned everything would hand the model the cause however
    narrow its window, and every widening question this file asks would answer
    itself.
    """
    def fetch(window_start: str, window_end: str) -> list[str]:
        start = parse_iso(window_start)
        end = parse_iso(window_end)

        return [line for line in incident.log_lines if start <= _when(line) <= end]

    return fetch


def _the_changes_of(incident: Incident) -> Callable[[str, str, str], list[ChangeEvent]]:
    def fetch(dont_care_service: str,
              window_start: str,
              window_end: str) -> list[ChangeEvent]:
        start = parse_iso(window_start)
        end = parse_iso(window_end)

        return [
            change for change in incident.changes
            if start <= parse_iso(change.occurred_at) <= end
        ]

    return fetch


def _when(log_line: str) -> datetime:
    """The instant a log line reports, read off its own prefix."""
    return parse_iso(log_line.split(" ", 1)[0])


def _a_run_where(satisfy: Assertion[Hypothesis]) -> Assertion[Run]:
    """Judges a run by its best candidate, and by what it spent getting there.

    The best candidate rather than the list: whether the model's *first* answer
    names the right cause is the question these thresholds were derived from,
    and the alternatives are the mitigation walk's business.

    Every case carries the budget assertion, rather than one case existing to
    measure exhaustion. Running out is a way of failing every one of these -
    the model that never finished reading did not judge anything - and folding
    it in means each rate is "answered, and answered correctly", which is the
    thing production actually needs. The failure message keeps the two apart.
    """
    return all_of(_of_the_best_candidate(satisfy), _the_budget_was_not_exhausted())


def _a_run_where_the_logs_were_read_before(instant: str) -> Assertion[Run]:
    """As `_a_run_where`, for a claim about the reading rather than the verdict."""
    return all_of(_the_logs_were_read_before(instant), _the_budget_was_not_exhausted())


def _of_the_best_candidate(satisfy: Assertion[Hypothesis]) -> Assertion[Run]:
    def assertion(run: Run) -> bool:
        return satisfy(run.findings.candidates[0])

    return assertion


def _the_logs_were_read_before(instant: str) -> Assertion[Run]:
    """That some log window the model asked for began earlier than `instant`.

    Read from what was actually served rather than from the transcript: a
    window the dispatcher refused - inverted, or already read - is a window the
    model never got, and crediting it would score the asking instead of the
    reading.
    """
    def assertion(run: Run) -> bool:
        opened_at = parse_iso(instant)
        reached_back = [
            reading for reading in run.findings.already_read
            if reading.channel is RetrievalChannel.LOGS
            and reading.window_start is not None
            and parse_iso(reading.window_start) < opened_at
        ]

        if not reached_back:
            raise AssertionError(
                f"Expected a log window beginning before {instant}, got "
                f"{[str(reading) for reading in run.findings.already_read]}."
            )

        return True

    return assertion


def _the_budget_was_not_exhausted() -> Assertion[Run]:
    def assertion(run: Run) -> bool:
        if run.ran_out_of:
            spent = ", ".join(bound.value for bound in run.ran_out_of)
            raise AssertionError(
                f"Expected an answer within the budget, but the investigation ran out "
                f"of {spent}. Model said: {run.findings.candidates[0].summary}"
            )

        return True

    return assertion
