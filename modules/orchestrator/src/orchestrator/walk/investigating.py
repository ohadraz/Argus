"""One round of investigation: what it found, and its account of finding it."""

from __future__ import annotations

from typing import Any

from agent_investigator import investigate as _investigate
from argus_core.events import AgentInvoked, Publisher, nobody, publish
from argus_core.models.actor import Actor
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both.
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing

from orchestrator.walk.candidates import the_next_worth_trying
from orchestrator.walk.narrating import Narration
from orchestrator.walk.ports import Investigate, RecordHypothesis
from orchestrator.walk.routes import ESCALATED_ROUTE, MITIGATING_ROUTE


def investigator_node(
    state: IncidentState,
    record_hypothesis: RecordHypothesis,
    investigate: Investigate = _investigate,
    publisher: Publisher = nobody,
    recorder: Recorder = records_nothing,
) -> dict[str, Any]:
    """Forms a hypothesis, records every candidate it considered, and reports
    whether any of them is worth acting on (spec §7.2, §10).

    It does not decide the incident's status. What it reports -
    `nothing_worth_trying`, the candidate list, the index of the one to try - is
    what the status is derived from, one place further out.

    `investigate`/`record_hypothesis` default to the real investigation call and
    repository write, injectable so this node's logic can be unit tested without
    a live Target Service or database - mirroring the seams
    `agent_investigator.investigate()` establishes for its own retrieval and
    model calls."""
    publish(AgentInvoked(incident_id=state.incident_id, agent=Actor.INVESTIGATOR), publisher)

    findings = investigate(
        alert=state.alert,
        incident_id=state.incident_id,
        # Handed down rather than left to the agent's own default, so the
        # Investigator's account of what it read and this node's account of
        # what it did are one narration instead of two.
        publisher=publisher,
        # The same handing-down for the receipts. The agent's own default
        # records nowhere, which is right for a unit test and wrong for a run
        # nobody can afford to repeat.
        recorder=recorder,
        # Both empty on a first round. On a later one they are what makes the
        # round worth paying for: what earlier rounds already read, and what has
        # already been tried and did not help.
        already_read=state.already_read,
        already_refuted=state.attempts,
    )
    # Routing reads the best answer, as it always has. The rest are what the
    # walk moves on to when this one is refuted.
    # The best answer this round has that the walk has not already disproved.
    # On a first round that is simply the best answer; on a later one it matters,
    # because a re-investigation is free to reach the same conclusion as the one
    # that was just refuted, and acting on it again would change the same flag
    # back and forth until the round budget ran out.
    next_up = the_next_worth_trying(findings.candidates, state.attempts, start=0)
    hypothesis = next_up[1] if next_up is not None else findings.candidates[0]
    # A named cause is enough to start the walk. Confidence used to gate this,
    # and gating it here was answering the wrong question: a mitigation that is
    # taken alone, confirmed against the service and put back when it does not
    # help costs two minutes, so what admits it is whether there is anything to
    # try - not how sure the model is that this one is right. An ambiguous
    # incident is exactly the case that produced middling confidence and no
    # action at all, which is the case the walk exists for.
    #
    # Reported rather than acted on. That this round found nothing worth trying
    # is what the investigation learned, and it is the one thing that tells an
    # investigation with nothing to offer apart from a walk that has worked
    # through everything it was offered - the two leave the same list behind.
    nothing_worth_trying = next_up is None
    # Every candidate, not only the one about to be tried. The incident's
    # record should say what was considered as well as what was acted on - a
    # runner-up that never reached the table is a finding a human picking the
    # incident up cannot see Argus ever having had.
    for candidate in findings.candidates:
        record_hypothesis(candidate)

    return {
        "hypothesis": hypothesis,
        "candidates": findings.candidates,
        "candidate_index": next_up[0] if next_up is not None else 0,
        # Everything read across this incident, not only this round's, so a
        # third round is told about the first as well as the second.
        "already_read": [*state.already_read, *findings.already_read],
        "rounds": state.rounds + 1,
        "confidence": hypothesis.confidence,
        "nothing_worth_trying": nothing_worth_trying,
        "narration": Narration(
            action=_what_the_investigation_did(hypothesis),
            result=hypothesis.summary,
            confidence=hypothesis.confidence,
        ),
    }


def _what_the_investigation_did(hypothesis: Hypothesis) -> str:
    """What the timeline records the Investigator as having done (spec §11.2).

    Two escalations reach this line for different reasons, and the timeline is
    where a human finds out which. A named cause below the threshold means a
    hypothesis was formed and is on file to be doubted; no cause at all means
    the loop read everything it was allowed to and still had nothing - the
    next step there is more evidence, not a second opinion on the first.
    """
    return "hypothesis formed" if hypothesis.cause_type is not None else "insufficient evidence"


def route_after_investigation(state: IncidentState) -> str:
    return MITIGATING_ROUTE if state.status == IncidentStatus.MITIGATING else ESCALATED_ROUTE
