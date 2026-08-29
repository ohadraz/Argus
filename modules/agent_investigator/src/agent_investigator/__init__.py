from __future__ import annotations

from datetime import timedelta

from argus_core.anomaly import earliest_bucket_is_anomalous, find_onset
from argus_core.config import get_settings
from argus_core.models.alert import Alert
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso

from agent_investigator.reasoning import HypothesisProposer, propose_hypothesis
from agent_investigator.retrieval import (
    ChangeFetcher,
    LogFetcher,
    MetricsFetcher,
    fetch_change_events,
    fetch_logs,
    fetch_metrics,
)
from agent_investigator.widening import widening_schedule


def investigate(
    alert: Alert,
    incident_id: str,
    fetch_metrics: MetricsFetcher = fetch_metrics,
    fetch_logs: LogFetcher = fetch_logs,
    fetch_change_events: ChangeFetcher = fetch_change_events,
    propose_hypothesis: HypothesisProposer = propose_hypothesis,
) -> Hypothesis:
    """Investigates one incident as a bounded ReAct loop (spec §9), returning
    what it concluded - including that it concluded nothing.

    Each iteration reads the log window around the onset and asks the model
    what caused the incident; an answer confident enough to act on ends the
    loop, and anything less buys another iteration reaching further back,
    until the widening schedule runs out.

    Confidence alone is not quite enough to end it. When the metrics window
    opens mid-incident the onset is only a lower bound, so the first log
    window provably did not contain the incident's start - and that is exactly
    the case where a confident answer is least trustworthy and least
    detectable. There, one widening is the price of being believed.

    The change channel weakens that argument without retiring it, so the rule
    stays. A change event is a candidate to be judged, not proof, and the
    channel can legitimately come back empty - a flag toggle has no change
    source yet and is still read out of log prose - which puts the loop right
    back to a model reading the tail of an incident whose start it never saw.
    Widening does not re-read the changes, but it does reach the log window
    further back, and that is where the prose tying a candidate change to the
    symptoms lives.

    Two things are deliberately *not* the model's to decide: which minute the
    incident started, and how far to reach. Both are computed here, from the
    metrics, so the same incident retrieves the same evidence on every run -
    a loop whose control flow depends on the model's own sense of having seen
    enough cannot be evaluated or reproduced.

    The four collaborators are default-argument seams: the real retrieval
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

    # Also fetched once, and only now that the onset is known - it is what the
    # change window is anchored on. Wider than any log window the schedule
    # reaches and read in full the first time, so re-reading it per iteration
    # would return the same handful of rows at the same cost.
    change_window_start, change_window_end = _change_window_before(onset)
    change_events = fetch_change_events(alert.service, change_window_start, change_window_end)

    schedule = widening_schedule(
        settings.log_initial_lookback_minutes,
        settings.log_max_window_minutes,
        settings.investigation_max_iterations,
    )

    # The metrics window opens already elevated, so its earliest minute is a
    # lower bound on the onset, not the onset itself - the incident started
    # before anything Argus can see. A first-pass answer therefore comes from
    # a log window that never contained the cause, and confidence cannot
    # detect that: the model cannot miss what it was never shown. So the first
    # answer costs one widening before it is believed.
    the_onset_is_only_a_lower_bound = earliest_bucket_is_anomalous(metric_buckets)

    log_lines: list[str] = []
    confident_hypothesis: Hypothesis | None = None

    for iteration, lookback_minutes in enumerate(schedule):
        window_start, window_end = _window_around(onset, lookback_minutes, alert_time)
        log_lines = fetch_logs(window_start, window_end)

        hypothesis = propose_hypothesis(
            Evidence(
                incident_id=incident_id,
                alert=alert,
                metric_buckets=metric_buckets,
                log_lines=log_lines,
                change_events=change_events,
                log_window_start=window_start,
                log_window_end=window_end,
                change_window_start=change_window_start,
                change_window_end=change_window_end,
            )
        )

        if not hypothesis.is_confident_enough(settings.mitigate_threshold):
            continue

        # Held rather than returned when trust is withheld: withholding trust
        # is not the same as throwing the finding away. If every wider look
        # comes back unsure, this is still the best thing the investigation
        # learned, and reporting "no cause" over it would misdescribe Argus's
        # own evidence.
        confident_hypothesis = hypothesis

        if not (the_onset_is_only_a_lower_bound and iteration == 0):
            return hypothesis

    if confident_hypothesis is not None:
        return confident_hypothesis

    return _undetermined(alert, incident_id, metric_buckets, log_lines)


def _change_window_before(onset: str) -> tuple[str, str]:
    """The window the change channel is asked about, anchored on the onset.

    It *ends* at the onset: a change made after the incident began did not
    begin it. It reaches back by the configured lookback rather than by the
    widening schedule, because the lag between a change and the symptoms it
    causes is unbounded - how far back a cause may plausibly lie is the
    operator's judgement, not something the loop can infer from the metrics.
    """
    settings = get_settings()
    lookback = timedelta(minutes=settings.change_lookback_minutes)

    return to_iso(parse_iso(onset) - lookback), onset


def _window_around(onset: str, lookback_minutes: int, alert_time: str | None) -> tuple[str, str]:
    """The log window one iteration reads: from before the onset to the alert.

    It starts strictly *before* the onset because that is where the cause is:
    a flag toggle or a deploy lands in a minute that still looks healthy, and
    the error rate only reacts to it afterwards. A window starting at the
    onset would structurally exclude the very event it is looking for.

    It ends at the alert, which is the one moment Argus knows for certain the
    service was unhealthy. The onset is inferred and can be wrong; the alert
    happened. Ending a fixed few minutes past the onset instead makes a
    mislocated onset unrecoverable - every widening reaches further back from
    a minute nothing happened in, and never reaches the minutes someone
    actually complained about. Ending at the alert makes the same mistake cost
    log lines rather than the evidence.

    The span is held within `log_max_window_minutes` here rather than left to
    the retrieval tool, which clamps a too-wide window by dropping its tail -
    and the tail is now the half that is certainly inside the incident.
    """
    settings = get_settings()
    onset_at = parse_iso(onset)

    end = onset_at + timedelta(minutes=settings.log_initial_lookahead_minutes)
    if alert_time is not None:
        end = max(end, parse_iso(alert_time))

    start = onset_at - timedelta(minutes=lookback_minutes)
    earliest_affordable = end - timedelta(minutes=settings.log_max_window_minutes)

    return to_iso(max(start, earliest_affordable)), to_iso(end)


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
