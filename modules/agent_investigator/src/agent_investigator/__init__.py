from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from argus_core.anomaly import earliest_bucket_is_anomalous, find_onset
from argus_core.config import get_settings
from argus_core.events import (
    ChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    Publisher,
    RetrievalChannel,
    RetrievalRequested,
    nobody,
    publish,
)
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso

from agent_investigator.reasoning import HypothesisProposer, propose_hypotheses
from agent_investigator.retrieval import (
    ChangeFetcher,
    LogFetcher,
    MetricsFetcher,
    fetch_change_events,
    fetch_logs,
    fetch_metrics,
)
from agent_investigator.widening import widening_schedule


@dataclass(frozen=True)
class Findings:
    """What one investigation concluded, and how much of its budget it spent.

    Named for the product rather than the process: an `Investigation` is the
    thing that runs, and this is what it hands back.

    `candidates` is every explanation the model offered, best first, and is
    never empty - an investigation that identified no cause says so in one
    candidate carrying the reason. Whether any of them is worth acting on is
    the mitigate threshold's business, not this type's.

    `can_widen` is the half a caller cannot work out for itself. The loop stops
    at its first confident answer, so a successful investigation usually leaves
    most of its widening budget unspent - and that unspent budget is exactly
    what a later round has to offer once these candidates have been tried and
    refuted. False means every step of the schedule has been taken and a
    further round would re-read evidence already read.


    `resumes_from` is where that later round starts. `can_widen` says one is
    available; this says where it begins, which the caller cannot work out for
    itself - the widening schedule is derived inside the investigation exactly
    so that how far to reach is never a caller's decision.
    """

    candidates: list[Hypothesis]
    can_widen: bool
    resumes_from: int = 0


def investigate(
    alert: Alert,
    incident_id: str,
    fetch_metrics: MetricsFetcher = fetch_metrics,
    fetch_logs: LogFetcher = fetch_logs,
    fetch_change_events: ChangeFetcher = fetch_change_events,
    propose_hypotheses: HypothesisProposer = propose_hypotheses,
    resume_from: int = 0,
    already_refuted: list[Attempt] | None = None,
    publisher: Publisher = nobody,
) -> Findings:
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

    `resume_from` and `already_refuted` are how a second round differs from a
    first. A round is bought only when the previous round's candidates have all
    been tried and refuted, so it must not pay again for what has already been
    read: it starts at the schedule step after the one that answered, and it
    carries what those attempts did. The second is the more valuable of the
    two - the window may reach further back, but the refutations are evidence
    the model has never seen and could not infer.

    The four collaborators are default-argument seams: the real retrieval
    calls and the real model in production, doubles in a test, and no
    monkeypatching either way. `publisher` is a fifth of the same kind, and the
    only one whose absence changes nothing: the loop publishes an account of
    what it read and concluded, and reaches the same conclusion whether or not
    anybody is listening (spec §4 principle 6).
    """
    settings = get_settings()
    alert_time = to_iso(alert.started_at) if alert.started_at is not None else None

    def say(event: IncidentEvent) -> None:
        """Narrates one step. Never raises - see `argus_core.events.publish`."""
        publish(event, publisher)

    # Fetched once, outside the loop: the metrics window is a single fixed
    # span (spec §16), so re-reading it each iteration would return the same
    # four numbers a minute and locate the same onset. Widening is what the
    # *log* window does.
    # Anchored on the alert rather than bounded, which is what the event says:
    # the span is the metrics tool's own (spec §16), not this loop's to name.
    say(RetrievalRequested(
        incident_id=incident_id,
        channel=RetrievalChannel.METRICS,
        window_start=alert_time,
    ))
    metric_buckets = fetch_metrics(alert_time)
    say(MetricsRetrieved(
        incident_id=incident_id,
        window_start=metric_buckets[0].bucket_id if metric_buckets else None,
        window_end=metric_buckets[-1].bucket_id if metric_buckets else None,
        buckets=metric_buckets,
    ))

    onset = find_onset(metric_buckets)

    if onset is None:
        # Nothing was read, so nothing was spent - but there is also nothing a
        # wider log window could fix. The onset is located from the metrics,
        # which are a single fixed span that widening does not touch.
        undetermined = _undetermined(alert, incident_id, metric_buckets, log_lines=[])
        say(_formed(undetermined))

        return Findings(
            candidates=[undetermined],
            can_widen=False,
            resumes_from=resume_from,
        )

    say(OnsetDetected(incident_id=incident_id, onset=onset))

    # Also fetched once, and only now that the onset is known - it is what the
    # change window is anchored on. Wider than any log window the schedule
    # reaches and read in full the first time, so re-reading it per iteration
    # would return the same handful of rows at the same cost.
    change_window_start, change_window_end = _change_window_before(onset)
    say(RetrievalRequested(
        incident_id=incident_id,
        channel=RetrievalChannel.CHANGES,
        window_start=change_window_start,
        window_end=change_window_end,
    ))
    change_events = fetch_change_events(alert.service, change_window_start, change_window_end)
    say(ChangesRetrieved(
        incident_id=incident_id,
        window_start=change_window_start,
        window_end=change_window_end,
        changes=change_events,
    ))

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
    confident_candidates: list[Hypothesis] | None = None
    candidates: list[Hypothesis] = []
    # Where the schedule got to, so the caller can tell an investigation that
    # stopped early - and has budget left to spend on a later round - from one
    # that read everything there is.
    # A resumed round that has run out of schedule still reads - it re-reads the
    # widest window. The round was bought by an attempt that failed, and that
    # refutation is evidence this loop has never been shown, so asking again over
    # the same window is asking a different question. Skipping the body instead
    # would spend a round to answer "no cause" without consulting anything.
    start_at = min(resume_from, len(schedule) - 1)
    reached = max(start_at - 1, 0)

    for iteration, lookback_minutes in enumerate(schedule):
        if iteration < start_at:
            continue

        window_start, window_end = _window_around(onset, lookback_minutes, alert_time)
        say(RetrievalRequested(
            incident_id=incident_id,
            channel=RetrievalChannel.LOGS,
            window_start=window_start,
            window_end=window_end,
        ))
        log_lines = fetch_logs(window_start, window_end)
        say(LogsRetrieved(
            incident_id=incident_id,
            window_start=window_start,
            window_end=window_end,
            lines=log_lines,
        ))

        reached = iteration
        candidates = propose_hypotheses(
            Evidence(
                incident_id=incident_id,
                alert=alert,
                metric_buckets=metric_buckets,
                log_lines=log_lines,
                change_events=change_events,
                log_window_start=window_start,
                log_window_end=window_end,
                attempts=already_refuted or [],
                change_window_start=change_window_start,
                change_window_end=change_window_end,
            )
        )

        for candidate in candidates:
            say(_formed(candidate))

        # The loop's control flow reads the best answer, as it always has. The
        # rest ride along for the walk that tries them when this one fails.
        hypothesis = candidates[0]

        # Confidence decides whether to keep *looking*, which is the question it
        # is good for: an unsure answer is a reason to buy more evidence while
        # there is any left to buy. It no longer decides whether the answer may
        # be acted on - a reversible mitigation is admitted by naming a cause,
        # and this loop returning something unsure is how the walk gets started
        # on an ambiguous incident instead of stopping at one.
        if not hypothesis.is_confident_enough(settings.mitigate_threshold):
            continue

        # Held rather than returned when trust is withheld: withholding trust
        # is not the same as throwing the finding away. If every wider look
        # comes back unsure, this is still the best thing the investigation
        # learned, and reporting "no cause" over it would misdescribe Argus's
        # own evidence.
        confident_candidates = candidates

        if not (the_onset_is_only_a_lower_bound and iteration == 0):
            return Findings(candidates, _can_widen(reached, schedule), reached + 1)

    if confident_candidates is not None:
        return Findings(confident_candidates, _can_widen(reached, schedule), reached + 1)

    # The schedule is spent and no answer cleared the bar. What the loop has is
    # still what the evidence supports - the widest look's own explanations,
    # offered without confidence - and it is reported rather than discarded.
    #
    # Discarding it was this loop deciding, on the caller's behalf, that an
    # unsure answer is the same as no answer. It is not: a named cause is an
    # experiment a reversible mitigation can run in two minutes, and "no cause
    # determined" over the top of one the model actually gave is Argus
    # misdescribing its own evidence to a human who then has to find it again.
    if candidates:
        return Findings(candidates, _can_widen(reached, schedule), reached + 1)

    return Findings(
        candidates=[_undetermined(alert, incident_id, metric_buckets, log_lines)],
        can_widen=_can_widen(reached, schedule),
        resumes_from=reached + 1,
    )


def _formed(hypothesis: Hypothesis) -> HypothesisFormed:
    """One candidate as the narration carries it.

    The candidate's own id travels with it, so the story and the walk are the
    same hypothesis seen twice rather than two accounts to be reconciled.
    """
    return HypothesisFormed(
        incident_id=hypothesis.incident_id,
        hypothesis_id=hypothesis.id,
        summary=hypothesis.summary,
        cause_type=hypothesis.cause_type,
        confidence=hypothesis.confidence,
        subject=hypothesis.subject,
        rank=hypothesis.rank,
        evidence=hypothesis.supporting_evidence,
    )


def _can_widen(reached: int, schedule: list[int]) -> bool:
    """Whether a later round would read anything the loop has not already read.

    False at the schedule's last step, because its final lookback is the
    configured maximum - a further round would ask for the same window and pay
    a model call for the same evidence.
    """
    return reached < len(schedule) - 1


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
