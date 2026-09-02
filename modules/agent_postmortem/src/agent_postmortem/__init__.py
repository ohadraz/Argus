"""The Postmortem agent (spec §7.6): the last thing said about an incident.

Every figure it reports is computed here and none is taken from the model.
The model writes prose and supplies exactly one number - how much of the
affected path carried revenue - which is a judgment, arrives with its
reasoning, and is published as a stated assumption rather than as a
measurement.

No tool loop. By the time this runs the evidence is settled, so the one thing
it fetches for itself is metrics, over a window spanning the whole incident:
the Investigator stops reading the moment it has a cause, and the recovery
between the mitigation and the end is exactly what its window does not cover.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from argus_core.llm.client import LLMClient
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn

from agent_postmortem.checking import faults_in
from agent_postmortem.document import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    IMPACT_WEIGHT_ASSUMPTION_LABEL,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    PostmortemDocument,
)
from agent_postmortem.estimate import (
    BASELINE_WINDOW_HOURS,
    duration_in_hours,
    error_rate_delta,
    loss_estimate,
    revenue_per_hour,
)
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.prompting import (
    ASSUMPTIONS_FIELD,
    EXECUTIVE_SUMMARY_FIELD,
    IMPACT_WEIGHT_FIELD,
    IMPACT_WEIGHT_REASON_FIELD,
    ROOT_CAUSE_FIELD,
    SUBMIT_POSTMORTEM,
    SUBMIT_TOOL_NAME,
    opening_ask,
    opening_ask_again,
    rejecting,
)
from agent_postmortem.sources import Engagement, EngagementAnswer, Metrics, Revenue

__all__ = [
    "ENGAGEMENT_UNAVAILABLE_ASSUMPTION",
    "IMPACT_WEIGHT_ASSUMPTION_LABEL",
    "REVENUE_UNAVAILABLE_ASSUMPTION",
    "IncidentEvidence",
    "PostmortemDocument",
    "write_postmortem",
]

_BASELINE_WINDOW = timedelta(hours=BASELINE_WINDOW_HOURS)


def write_postmortem(evidence: IncidentEvidence,
                     *,
                     revenue: Revenue,
                     engagement: Engagement,
                     metrics: Metrics,
                     llm: LLMClient) -> PostmortemDocument:
    """The whole document: measure, ask once, then write down both.

    The order matters in one place only - the model is asked before the
    estimate is computed, because the weight it supplies is one of the
    estimate's terms. Everything else is known before the call and is passed
    into it, so that the prose describes the same incident the figures do.
    """
    duration = duration_in_hours(evidence.started_at, evidence.ended_at)
    delta = error_rate_delta(
        metrics(evidence.started_at - _BASELINE_WINDOW, evidence.ended_at),
        evidence.started_at,
        evidence.ended_at
    )
    baseline_revenue = revenue(evidence.started_at - _BASELINE_WINDOW,
                               evidence.started_at)

    answer, estimate, faults = _answer_worth_writing(
        llm, evidence, duration, delta, baseline_revenue)
    engaged = engagement(evidence.incident_id)

    return PostmortemDocument(
        root_cause=_text(answer, ROOT_CAUSE_FIELD),
        executive_summary=_text(answer, EXECUTIVE_SUMMARY_FIELD),
        customer_loss_estimate_usd=estimate,
        engineer_minutes=engaged.minutes * engaged.responders if engaged else None,
        responders=engaged.responders if engaged else None,
        tokens_spent=evidence.tokens_spent,
        assumptions=_assumptions(answer, baseline_revenue, engaged),
        checklist_complete=not faults
    )


def _answer_worth_writing(llm: LLMClient,
                          evidence: IncidentEvidence,
                          duration: float,
                          delta: float | None,
                          baseline_revenue: Decimal | None
                          ) -> tuple[dict[str, Any], Decimal | None, list[str]]:
    """The model's answer, its estimate, and whatever is still wrong with it.

    Two attempts at most (spec §7.6). The second is worth making because the
    faults are nameable - a missing field, a figure Argus never computed - and
    a model told which is a model that can fix it. A third would not be: an
    answer wrong twice in ways it was told about is not one attempt away from
    right, and the incident is over either way.

    Returns the faults rather than acting on them, because the caller is the
    one writing the document that has to admit to them.
    """
    asked = opening_ask(evidence, duration, delta)
    submitted = llm.converse(asked, [SUBMIT_POSTMORTEM])

    first = _reading_of(submitted, duration, delta, baseline_revenue)
    _, _, faults = first
    if not faults:
        return first

    return _reading_of(llm.converse(_asking_again(asked, submitted, faults),
                                    [SUBMIT_POSTMORTEM]),
                       duration, delta, baseline_revenue)


def _asking_again(asked: Transcript, submitted: Turn, faults: list[str]) -> Transcript:
    """How the second attempt is put, which depends on what the first was.

    A submission is refused through the result of the call that made it, so
    the model sees its own answer and what was wrong with it. A model that
    made no call submitted nothing there is anything to refuse - so it is
    asked again from the start, which is the only shape left and the reason
    the choice lives here rather than in the prompt module.
    """
    if not submitted.tool_calls:
        return opening_ask_again(asked, faults)

    return rejecting(asked, submitted, faults)


def _reading_of(turn: Turn,
                duration: float,
                delta: float | None,
                baseline_revenue: Decimal | None
                ) -> tuple[dict[str, Any], Decimal | None, list[str]]:
    """What one turn amounts to: its answer, its estimate, its faults."""
    answer = _answer_from(turn)
    estimate = _loss(baseline_revenue, duration, delta, answer)

    return answer, estimate, faults_in(answer, estimate)


def _answer_from(turn: Turn) -> dict[str, Any]:
    """What the model submitted, or nothing at all.

    A turn carrying no call to the tool it was offered is an answer in the
    wrong shape rather than a failure to answer, and it is read as an empty
    one: the document is then written incomplete, which is what
    `checklist_complete` exists to say.
    """
    for call in turn.tool_calls:
        if call.name == SUBMIT_TOOL_NAME:
            return call.arguments

    return {}


def _loss(baseline_revenue: Decimal | None,
          duration: float,
          delta: float | None,
          answer: dict[str, Any]) -> Decimal | None:
    """The estimate, or nothing when any term of it is unknown.

    Nothing, never zero: an unreadable revenue source and a service that lost
    no money are different findings, and only one of them is a measurement.
    """
    weight = answer.get(IMPACT_WEIGHT_FIELD)
    if baseline_revenue is None or delta is None or weight is None:
        return None

    return loss_estimate(revenue_per_hour(baseline_revenue, BASELINE_WINDOW_HOURS),
                         duration,
                         delta,
                         float(weight))


def _assumptions(answer: dict[str, Any],
                 baseline_revenue: Decimal | None,
                 engaged: EngagementAnswer | None) -> list[str]:
    """What the document admits to having assumed rather than measured.

    The weight comes first because it is the one judgment inside a figure that
    otherwise reads as arithmetic; the absences follow, each saying which
    question went unanswered.
    """
    assumptions: list[str] = []

    weight = answer.get(IMPACT_WEIGHT_FIELD)
    if weight is not None:
        assumptions.append(
            f"{IMPACT_WEIGHT_ASSUMPTION_LABEL} {weight}: "
            f"{answer.get(IMPACT_WEIGHT_REASON_FIELD, 'no reason given')}"
        )

    assumptions.extend(str(stated) for stated in answer.get(ASSUMPTIONS_FIELD, []))

    if baseline_revenue is None:
        assumptions.append(REVENUE_UNAVAILABLE_ASSUMPTION)
    if engaged is None:
        assumptions.append(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)

    return assumptions


def _text(answer: dict[str, Any], field: str) -> str | None:
    value = answer.get(field)

    return str(value) if value is not None else None
