from __future__ import annotations

from datetime import timedelta

from argus_core.config import get_settings
from argus_core.models.alert import Alert
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso

from agent_investigator.anomaly import earliest_bucket_is_anomalous, find_onset
from agent_investigator.reasoning import HypothesisProposer, propose_hypothesis
from agent_investigator.retrieval import LogFetcher, MetricsFetcher, fetch_logs, fetch_metrics
from agent_investigator.widening import widening_schedule


def investigate(
    alert: Alert,
    incident_id: str,
    fetch_metrics: MetricsFetcher = fetch_metrics,
    fetch_logs: LogFetcher = fetch_logs,
    propose_hypothesis: HypothesisProposer = propose_hypothesis,
) -> Hypothesis:
    """Investigates one incident as a bounded ReAct loop (spec §9), returning
    what it concluded - including that it concluded nothing.

    Each iteration reads the log window around the onset and asks the model
    what caused the incident; an answer confident enough to act on ends the
    loop immediately, and anything less buys another iteration reaching
    further back, until the widening schedule runs out.

    Two things are deliberately *not* the model's to decide: which minute the
    incident started, and how far to reach. Both are computed here, from the
    metrics, so the same incident retrieves the same evidence on every run -
    a loop whose control flow depends on the model's own sense of having seen
    enough cannot be evaluated or reproduced.

    The three collaborators are default-argument seams: the real retrieval
    calls and the real model in production, doubles in a test, and no
    monkeypatching either way.
    """
    settings = get_settings()
    alert_time = to_iso(alert.started_at) if alert.started_at is not None else None

    # Fetched once, outside the loop: the metrics window is a single fixed
    # span (spec §16), so re-reading it each iteration would return the same
    # four numbers a minute and locate the same onset. Widening is what the
    # *log* window does.
    metric_buckets = fetch_metrics(alert_time)
    onset = find_onset(metric_buckets)

    if onset is None:
        return _undetermined(alert, incident_id, metric_buckets, log_lines=[])

    schedule = widening_schedule(
        settings.log_initial_lookback_minutes,
        settings.log_max_window_minutes,
        settings.investigation_max_iterations,
    )

    log_lines: list[str] = []

    for lookback_minutes in schedule:
        window_start, window_end = _window_around(onset, lookback_minutes)
        log_lines = fetch_logs(window_start, window_end)

        hypothesis = propose_hypothesis(
            Evidence(
                incident_id=incident_id,
                alert=alert,
                metric_buckets=metric_buckets,
                log_lines=log_lines,
                log_window_start=window_start,
                log_window_end=window_end,
            )
        )

        if hypothesis.is_confident_enough(settings.mitigate_threshold):
            return hypothesis

    return _undetermined(alert, incident_id, metric_buckets, log_lines)


def _window_around(onset: str, lookback_minutes: int) -> tuple[str, str]:
    """The log window one iteration reads, anchored on the onset.

    It starts strictly *before* the onset because that is where the cause is:
    a flag toggle or a deploy lands in a minute that still looks healthy, and
    the error rate only reacts to it afterwards. A window starting at the
    onset would structurally exclude the very event it is looking for.
    """
    settings = get_settings()
    onset_at = parse_iso(onset)

    return (
        to_iso(onset_at - timedelta(minutes=lookback_minutes)),
        to_iso(onset_at + timedelta(minutes=settings.log_initial_lookahead_minutes)),
    )


def _undetermined(
    alert: Alert,
    incident_id: str,
    metric_buckets: list[MetricBucket],
    log_lines: list[str],
) -> Hypothesis:
    """The honest outcome: no cause, and no confidence to go with it.

    Carries no `cause_type` and no `confidence` at all - the model refuses to
    hold one without the other - so that whoever picks the incident up can
    tell "nothing identified" from a real diagnosis. The summary says *why*
    it stopped, since "the incident began before anything I can read" and "I
    read everything and still could not tell" call for different next steps.
    """
    return Hypothesis(
        incident_id=incident_id,
        summary=(
            f"no cause determined for {alert.alert_name} on {alert.service}: "
            f"{_reason_nothing_was_found(metric_buckets)}"
        ),
        cause_type=None,
        confidence=None,
        supporting_evidence=log_lines,
    )


def _reason_nothing_was_found(metric_buckets: list[MetricBucket]) -> str:
    if not metric_buckets:
        return "no metrics were retrieved for the incident window"

    if find_onset(metric_buckets) is None:
        return "no minute in the metrics window departs from the service's baseline"

    if earliest_bucket_is_anomalous(metric_buckets):
        return (
            "the incident was already under way at the start of the metrics window, "
            "so its onset - and any cause - predates everything retrievable"
        )

    return "the retrieved evidence did not identify one"
