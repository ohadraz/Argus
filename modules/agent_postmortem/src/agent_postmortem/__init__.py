"""The Postmortem agent (spec §7.6): the last thing said about an incident.

Every figure it reports is computed here and none is taken from the model. The
model writes prose and nothing else: what the incident cost is the difference
between what the shop was taking before it and what it took during it, both
read from the payment provider, and a document whose numbers came partly from
a model is a document nobody can check.

No tool loop. By the time this runs the evidence is settled, so the one thing
it fetches for itself is metrics, over a window spanning the whole incident:
the Investigator stops reading the moment it has a cause, and the recovery
between the mitigation and the end is exactly what its window does not cover.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from argus_core.llm.client import LLMClient
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn

from agent_postmortem.checking import faults_in
from agent_postmortem.document import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
    ONSET_UNKNOWN_ASSUMPTION,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    PostmortemDocument,
)
from agent_postmortem.estimate import (
    BASELINE_WINDOW_HOURS,
    duration_in_hours,
    error_rate_delta,
    in_the_reporting_currency,
    loss_between,
)
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.prompting import (
    ASSUMPTIONS_FIELD,
    EXECUTIVE_SUMMARY_FIELD,
    ROOT_CAUSE_FIELD,
    SUBMIT_POSTMORTEM,
    SUBMIT_TOOL_NAME,
    opening_ask,
    opening_ask_again,
    rejecting,
)
from agent_postmortem.sources import (
    Engagement,
    EngagementAnswer,
    Metrics,
    Rates,
    RateTable,
    Revenue,
)

__all__ = [
    "ENGAGEMENT_UNAVAILABLE_ASSUMPTION",
    "EXCHANGE_RATE_ASSUMPTION_LABEL",
    "EXCLUDED_CURRENCY_ASSUMPTION_LABEL",
    "ONSET_UNKNOWN_ASSUMPTION",
    "REVENUE_UNAVAILABLE_ASSUMPTION",
    "IncidentEvidence",
    "PostmortemDocument",
    "write_postmortem",
]

_BASELINE_WINDOW = timedelta(hours=BASELINE_WINDOW_HOURS)


def write_postmortem(evidence: IncidentEvidence,
                     *,
                     revenue: Revenue,
                     rates: Rates,
                     engagement: Engagement,
                     metrics: Metrics,
                     llm: LLMClient) -> PostmortemDocument:
    """The whole document: measure, ask once, then write down both.

    Everything is measured before the model is asked, and the figures are
    passed into the ask - so the prose describes the same incident the numbers
    do, and nothing the model says can move them.

    The incident is dated from its onset rather than from the alert. Those two
    differ by however long the alert took to fire, and counting those minutes
    as calm trade would raise the baseline using the very minutes the shop was
    already failing in.
    """
    # The alert's own time where nothing measured an onset. It is the wrong
    # instant to cost an incident from - which is why no estimate is published
    # without an onset, below - but it is the right one to describe it from,
    # and the metrics window is the model's context rather than a figure.
    began = evidence.onset_at or evidence.started_at
    duration = duration_in_hours(began, evidence.ended_at)
    delta = error_rate_delta(
        metrics(began - _BASELINE_WINDOW, evidence.ended_at),
        began,
        evidence.ended_at
    )
    table = rates()
    before = revenue(began - _BASELINE_WINDOW, began)
    during = revenue(began, evidence.ended_at)
    baseline_revenue, left_out = _as_one_figure(before, table)
    revenue_during, _ = _as_one_figure(during, table)
    estimate = (_loss(baseline_revenue, revenue_during, duration)
                if evidence.onset_at is not None else None)

    answer, faults = _answer_worth_writing(llm, evidence, duration, delta, estimate)
    engaged = engagement(evidence.incident_id)

    return PostmortemDocument(
        root_cause=_text(answer, ROOT_CAUSE_FIELD),
        executive_summary=_text(answer, EXECUTIVE_SUMMARY_FIELD),
        customer_loss_estimate=estimate,
        estimate_currency=table.base if table is not None and estimate is not None
                          else None,
        engineer_minutes=engaged.minutes * engaged.responders if engaged else None,
        responders=engaged.responders if engaged else None,
        tokens_spent=evidence.tokens_spent,
        assumptions=_assumptions(answer, baseline_revenue, engaged, before, table,
                                 left_out, evidence.onset_at),
        checklist_complete=not faults
    )


def _as_one_figure(taken: Mapping[str, Decimal] | None,
                   table: RateTable | None) -> tuple[Decimal | None, list[str]]:
    """What the shop took, stated in the one currency the document reports in,
    and whatever could not be stated there at all.

    A quiet window took nothing, and nothing is a measurement: an empty
    mapping is zero rather than an unanswered question.

    Everything else needs the table, because the table is what says which
    currency this document is written in. Without it there is no figure to
    publish even where only one currency was taken - naming that currency
    would be a guess, and a guess about which money this is would be a worse
    failure than an absent estimate.
    """
    if taken is None or table is None:
        return None, []

    return in_the_reporting_currency(taken, table)


def _answer_worth_writing(llm: LLMClient,
                          evidence: IncidentEvidence,
                          duration: float,
                          delta: float | None,
                          estimate: Decimal | None
                          ) -> tuple[dict[str, Any], list[str]]:
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

    first = _reading_of(submitted, estimate)
    _, faults = first
    if not faults:
        return first

    return _reading_of(llm.converse(_asking_again(asked, submitted, faults),
                                    [SUBMIT_POSTMORTEM]),
                       estimate)


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
                estimate: Decimal | None) -> tuple[dict[str, Any], list[str]]:
    """What one turn amounts to: its answer and whatever is wrong with it.

    The estimate is no longer computed from anything the model said, so it is
    passed in rather than derived here - the only thing a turn can still get
    wrong about it is naming a different number in its prose.
    """
    answer = _answer_from(turn)

    return answer, faults_in(answer, estimate)


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
          revenue_during: Decimal | None,
          duration: float) -> Decimal | None:
    """The estimate, or nothing when either window went unread.

    Nothing, never zero: an unreadable revenue source and a shop that lost no
    money are different findings, and only one of them is a measurement. Both
    windows are needed, because a loss is the difference between them - one
    alone is half a subtraction.
    """
    if baseline_revenue is None or revenue_during is None:
        return None

    return loss_between(baseline_revenue, BASELINE_WINDOW_HOURS,
                        revenue_during, duration)


def _assumptions(answer: dict[str, Any],
                 baseline_revenue: Decimal | None,
                 engaged: EngagementAnswer | None,
                 taken: Mapping[str, Decimal] | None,
                 table: RateTable | None,
                 left_out: list[str],
                 onset_at: datetime | None) -> list[str]:
    """What the document admits to having assumed rather than measured.

    The conversions come first - they are the only step between the money the
    provider reported and the figure published - then whatever the model says
    it assumed in its prose, then the absences, each saying which question went
    unanswered.
    """
    assumptions: list[str] = []

    if onset_at is None:
        assumptions.append(ONSET_UNKNOWN_ASSUMPTION)

    assumptions.extend(_rates_applied(taken, table))
    assumptions.extend(
        f"{EXCLUDED_CURRENCY_ASSUMPTION_LABEL}: takings in {currency} are not in "
        f"the figure, because no rate was published for it"
        for currency in left_out
    )

    assumptions.extend(str(stated) for stated in answer.get(ASSUMPTIONS_FIELD, []))

    if baseline_revenue is None:
        assumptions.append(REVENUE_UNAVAILABLE_ASSUMPTION)
    if engaged is None:
        assumptions.append(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)

    return assumptions


def _rates_applied(taken: Mapping[str, Decimal] | None,
                   table: RateTable | None) -> list[str]:
    """Every conversion that went into the figure, one line each.

    Only the currencies actually taken, so a document about a shop trading in
    dollars does not recite thirty rates it never used. A window needing no
    conversion says nothing, which is correct: there is no assumption to
    disclose.
    """
    if taken is None or table is None:
        return []

    return [
        f"{EXCHANGE_RATE_ASSUMPTION_LABEL}: {currency} converted at "
        f"{table.per_unit[currency]} per {table.base}, published "
        f"{table.on.isoformat()}"
        for currency in taken
        if currency != table.base and currency in table.per_unit
    ]


def _text(answer: dict[str, Any], field: str) -> str | None:
    value = answer.get(field)

    return str(value) if value is not None else None
