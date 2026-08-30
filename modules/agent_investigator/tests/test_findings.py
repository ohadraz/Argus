from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_investigator import Findings, investigate
from agent_investigator.reasoning import propose_hypotheses
from agent_investigator.retrieval import fetch_change_events, fetch_logs, fetch_metrics
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import to_iso_minute

"""What an investigation hands back, and how a later one picks up where it left.

The loop itself - which window it reads, when it widens - is `test_investigate`.
This is about the result: every explanation the model offered rather than only
its best, and enough about where the widening schedule got to that a second
round can carry on rather than start again.

The distinction matters because widening is the expensive half. An
investigation that answered confidently from the first, narrow window has spent
almost none of its budget, and the point of resuming is to spend it only once
the cheap window's answers have actually been tried and failed.
"""

AN_ALERT_TIME = datetime(2026, 8, 20, 11, 8, tzinfo=UTC)
A_WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)

A_CONFIDENT_ANSWER = 0.95
AN_UNCONVINCING_ANSWER = 0.10


@pytest.mark.unit
def test_an_investigation_reports_every_explanation_the_model_offered() -> None:
    # The runners-up are the whole point: they are what a refuted mitigation
    # moves on to. An investigation that returned only the best answer would
    # throw them away at the one moment they become useful.
    some_incident_id = new_id()
    the_best_answer = a_hypothesis_for(some_incident_id, confidence=0.90)
    a_runner_up = a_hypothesis_for(some_incident_id, confidence=0.60)

    findings = _investigating(the_model_answers=[the_best_answer, a_runner_up])

    assert findings.candidates == [the_best_answer, a_runner_up]


@pytest.mark.unit
def test_an_investigation_that_found_nothing_still_reports_a_candidate() -> None:
    # It carries the reason nothing was found, which a human reads and a later
    # round is entitled to. An empty list would leave that homeless, and would
    # state in a second way what the mitigate threshold already states.
    findings = _investigating(
        the_model_answers=[an_undetermined_hypothesis(new_id())]
    )

    assert len(findings.candidates) == 1
    assert findings.candidates[0].cause_type is None


@pytest.mark.unit
def test_a_confident_first_look_leaves_the_widening_budget_unspent() -> None:
    # The loop stops at its first confident answer, so the schedule is barely
    # touched. Reporting that is what lets a later round reach further back
    # instead of re-reading the window that has already been read.
    findings = _investigating(
        the_model_answers=[a_hypothesis_for(new_id(), A_CONFIDENT_ANSWER)]
    )

    assert findings.can_widen


@pytest.mark.unit
def test_an_investigation_that_read_everything_cannot_widen_further() -> None:
    # Nothing the model said was confident enough to stop on, so every step of
    # the schedule was taken. There is no wider look left to buy, and a walk
    # that asked for one would pay for the same evidence twice.
    findings = _investigating(
        the_model_answers=[a_hypothesis_for(new_id(), AN_UNCONVINCING_ANSWER)]
    )

    assert not findings.can_widen


@pytest.mark.unit
def test_an_investigation_says_where_a_later_round_should_pick_up() -> None:
    # `can_widen` says a wider look exists; this says where it starts. The
    # caller cannot work it out - the widening schedule is derived inside the
    # investigation precisely so that how far to reach is never a caller's
    # decision - so it has to come back with the answer.
    findings = _investigating(
        the_model_answers=[a_hypothesis_for(new_id(), A_CONFIDENT_ANSWER)]
    )

    assert findings.resumes_from == 1


@pytest.mark.unit
def test_a_resumed_investigation_picks_up_after_the_step_that_answered() -> None:
    findings = _investigating(
        the_model_answers=[a_hypothesis_for(new_id(), A_CONFIDENT_ANSWER)],
        resume_from=1,
    )

    assert findings.resumes_from == 2


@pytest.mark.unit
def test_a_resumed_investigation_reads_further_back_than_the_first_did() -> None:
    # The point of resuming: the first round's window has been read and its
    # answers tried. Starting over would spend a model call on exactly the
    # evidence that produced the answers already refuted.
    the_first_round = _a_log_fetcher()
    a_later_round = _a_log_fetcher()

    _investigating(
        the_model_answers=[a_hypothesis_for(new_id(), A_CONFIDENT_ANSWER)],
        log_fetcher=the_first_round,
    )
    _investigating(
        the_model_answers=[a_hypothesis_for(new_id(), A_CONFIDENT_ANSWER)],
        log_fetcher=a_later_round,
        resume_from=1,
    )

    assert _the_window_start_of(a_later_round) < _the_window_start_of(the_first_round)


@pytest.mark.unit
def test_a_resumed_investigation_shows_the_model_what_was_already_tried() -> None:
    # The one thing the second round knows that the first could not. Without
    # it the model is being asked the same question over the same evidence and
    # invited to give a different answer, which is not reasoning.
    hypothesis_proposer = _a_hypothesis_proposer_answering(
        [a_hypothesis_for(new_id(), A_CONFIDENT_ANSWER)]
    )
    a_refuted_attempt = an_attempt_on("monthly-spend-feature", enabled=False)

    _investigating(
        the_model_answers=[],
        hypothesis_proposer=hypothesis_proposer,
        already_refuted=[a_refuted_attempt],
    )

    assert _the_evidence_shown_to(hypothesis_proposer).attempts == [a_refuted_attempt]


@pytest.mark.unit
def test_a_first_investigation_shows_the_model_no_attempts() -> None:
    hypothesis_proposer = _a_hypothesis_proposer_answering(
        [a_hypothesis_for(new_id(), A_CONFIDENT_ANSWER)]
    )

    _investigating(the_model_answers=[], hypothesis_proposer=hypothesis_proposer)

    assert _the_evidence_shown_to(hypothesis_proposer).attempts == []


def _investigating(
    the_model_answers: list[Hypothesis],
    log_fetcher: Any = None,
    hypothesis_proposer: Any = None,
    resume_from: int = 0,
    already_refuted: list[Attempt] | None = None,
) -> Findings:
    """Runs one investigation over a window that plainly departs from baseline.

    The retrieval seams are doubles because what is under test is the shape of
    the answer, not where the evidence came from - `test_investigate` owns that
    question and asks it properly.
    """
    metrics_fetcher = create_autospec(fetch_metrics)
    metrics_fetcher.return_value = a_window_that_breaks()

    change_fetcher = create_autospec(fetch_change_events)
    change_fetcher.return_value = []

    return investigate(
        an_alert(),
        incident_id=new_id(),
        fetch_metrics=metrics_fetcher,
        fetch_logs=log_fetcher or _a_log_fetcher(),
        fetch_change_events=change_fetcher,
        propose_hypotheses=(
            hypothesis_proposer or _a_hypothesis_proposer_answering(the_model_answers)
        ),
        resume_from=resume_from,
        already_refuted=already_refuted or [],
    )


def _a_log_fetcher() -> Any:
    fetcher = create_autospec(fetch_logs)
    fetcher.return_value = ["some log line"]
    return fetcher


def _a_hypothesis_proposer_answering(hypotheses: list[Hypothesis]) -> Any:
    proposer = create_autospec(propose_hypotheses)
    proposer.return_value = hypotheses
    return proposer


def _the_window_start_of(log_fetcher: Any) -> str:
    window_start, _ = log_fetcher.call_args.args
    return str(window_start)


def _the_evidence_shown_to(hypothesis_proposer: Any) -> Any:
    return hypothesis_proposer.call_args.args[0]


def an_alert() -> Alert:
    return Alert(service="kuki", alert_name="HighErrorRate", started_at=AN_ALERT_TIME)


def a_window_that_breaks() -> list[MetricBucket]:
    """Calm minutes, then plainly broken ones - so an onset exists to anchor on
    and the window does not open already elevated, which would cost the loop a
    widening before it believed anything."""
    return [
        MetricBucket(
            bucket_id=to_iso_minute(A_WINDOW_START.replace(minute=minute)),
            error_rate=0.01 if minute < 5 else 0.35,
            p50_ms=45,
            p95_ms=220,
            request_volume=1200,
        )
        for minute in range(9)
    ]


def a_hypothesis_for(incident_id: str, confidence: float) -> Hypothesis:
    return Hypothesis(
        incident_id=incident_id,
        summary="a feature flag was toggled on just before the errors began",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=confidence,
        supporting_evidence=["some log line"],
        subject="monthly-spend-feature",
    )


def an_undetermined_hypothesis(incident_id: str) -> Hypothesis:
    return Hypothesis(
        incident_id=incident_id,
        summary="no cause determined from the evidence retrieved",
        cause_type=None,
        confidence=None,
        supporting_evidence=[],
    )


def an_attempt_on(subject: str, enabled: bool) -> Attempt:
    return Attempt(
        subject=subject,
        enabled=enabled,
        occurred_at=to_iso_minute(AN_ALERT_TIME),
    )
