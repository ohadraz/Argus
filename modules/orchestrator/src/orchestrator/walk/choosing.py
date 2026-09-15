"""Walking the candidates an investigation offered, one at a time."""

from __future__ import annotations

from argus_core import to_iso, utc_now
from argus_core.events import CandidateSelected, Publisher, nobody, publish
from argus_core.models import Attempt, IncidentStatus

from orchestrator.walk.candidates import the_next_worth_trying
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.routes import (
    FIXING_ROUTE,
    INVESTIGATING_ROUTE,
    MITIGATING_ROUTE,
)
from orchestrator.walk.state import IncidentState


def next_candidate_node(state: IncidentState,
                        max_rounds: int,
                        publisher: Publisher = nobody) -> StateDelta:
    """Decides what happens after an attempt settled nothing (spec §7.3).

    Reached two ways - the gate refusing an action, and the service refusing to
    recover after one - because "what now" has a single answer and splitting it
    across two nodes would be two chances to get it wrong.

    Three outcomes, in the order they are worth having. Another candidate above
    the mitigate threshold is tried, because the second explanation of a
    correlated change is usually still on the list. Failing that, another
    investigation is bought - and what buys it is the refutation, not a wider
    window: Argus changed production and the service did not answer, which is
    evidence no amount of re-reading produces and which the model has never
    seen. Gating that on leftover widening budget shut the door at exactly the
    wrong moment, since a hard incident spends its whole schedule reaching a
    confident first answer. Failing both, there are no moves left and a human is
    needed.

    What was just tried is remembered on the way past. That record is the one
    thing a later round knows that the first could not, and it belongs here,
    attached to the attempt that produced it, rather than being reconstructed
    later from a timeline.
    """
    attempts = [*state.attempts, *_what_was_just_tried(state)]
    next_up = the_next_worth_trying(
        state.candidates, attempts, start=state.candidate_index + 1
    )
    next_index = next_up[0] if next_up is not None else len(state.candidates)
    next_candidate = next_up[1] if next_up is not None else None

    if next_candidate is not None:
        # Published, and no transition behind it: the incident was mitigating
        # before this and is mitigating after. Moving to the next candidate is
        # progress through a phase, not out of one - so there is no move for the
        # walk's narration to account for, and this node's own event is the only
        # account there is of which explanation the lines after it are about.
        publish(
            CandidateSelected(
                incident_id=state.incident_id,
                hypothesis_id=next_candidate.id,
                summary=next_candidate.summary,
                confidence=next_candidate.confidence
            ),
            publisher
        )

        return StateDelta(
            attempts=attempts,
            candidate_index=next_index,
            hypothesis=next_candidate,
            confidence=next_candidate.confidence
        )

    if state.rounds < max_rounds:
        return StateDelta(
            attempts=attempts,
            candidate_index=next_index,
            narration=Narration(
                action="every explanation was refuted, investigating again"
            )
        )

    # Nothing reversible is left, and what remains is a permanent fix - which is
    # the one thing `fixing` means. Reported, not decided: the index past the end
    # of the list and a spent round budget are what say so.
    return StateDelta(
        attempts=attempts,
        candidate_index=next_index,
        narration=Narration(
            action="no explanation left to try",
            detail=(
                f"no explanation left to try - {len(attempts)} action(s) were "
                f"taken and undone, and the evidence offers nothing further"
            )
        )
    )


def _what_was_just_tried(state: IncidentState) -> list[Attempt]:
    """The attempt this node is reacting to, if production was actually changed.

    An action the gate refused never ran, so there is nothing to remember and
    nothing a later round could learn from it. Only a change that was made -
    and undone - is evidence about the cause it was made on.

    A cleared action is the whole of that test. It used to ask after the undo
    descriptor as well, back when an action could carry none; an action of a
    reversible kind cannot be built without one now, so that half of the
    condition could only ever be false - and nothing would have said so, since
    mypy is not asked to warn about unreachable code.
    """
    action = state.proposed_action

    if action is None:
        return []

    return [
        Attempt(
            subject=action.flag,
            enabled=action.enabled,
            occurred_at=to_iso(utc_now())
        )
    ]


def route_after_next_candidate(state: IncidentState) -> str:
    if state.status == IncidentStatus.MITIGATING:
        return MITIGATING_ROUTE

    if state.status == IncidentStatus.INVESTIGATING:
        return INVESTIGATING_ROUTE

    return FIXING_ROUTE
