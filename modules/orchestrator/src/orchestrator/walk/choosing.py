"""Walking the candidates an investigation offered, one at a time."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from argus_core import to_iso
from argus_core.events import CandidateSelected, Publisher, nobody, publish
from argus_core.models import (
    Attempt,
    IncidentStatus,
    Platform,
    the_actions_through,
    the_direction_of,
    the_identity_of,
)

from orchestrator.walk.candidates import (
    the_circumstances,
    the_next_worth_trying,
    what_each_would_do,
)
from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.routes import (
    ESCALATED_ROUTE,
    FIXING_ROUTE,
    INVESTIGATING_ROUTE,
    MITIGATING_ROUTE,
)
from orchestrator.walk.state import IncidentState, another_round_is_bought

logger = logging.getLogger(__name__)


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
    investigation is bought - and what buys it is a refutation since the latest
    round began, not a wider window: Argus changed production and the service
    did not answer, which is evidence no amount of re-reading produces and which
    the model has never seen. Gating that on leftover widening budget shut the
    door at exactly the wrong moment, since a hard incident spends its whole
    schedule reaching a confident first answer. A list spent with nothing
    refuted buys nothing, because the next round would be handed what the last
    one was. Failing both, there are no moves left and a human is needed.

    What was just tried is remembered on the way past. That record is the one
    thing a later round knows that the first could not, and it belongs here,
    attached to the attempt that produced it, rather than being reconstructed
    later from a timeline.
    """
    attempts = [*state.attempts, *_what_was_just_tried(state)]
    # The same history the round was reasoned from, and the same question
    # asked of it. What disqualifies a candidate is that the action answering
    # it has already been taken, so the candidates have to be asked what they
    # would be answered with before any of them can be skipped.
    #
    # Built as the investigation built them, alert's keys included: one of
    # those answers is addressed to entries no candidate names, and asked
    # without them a divergence comes back answered by nothing - so two
    # wordings of one stale cache would read as two experiments and the walk
    # would discard the same entries once per wording.
    next_up = the_next_worth_trying(
        what_each_would_do(
            state.candidates,
            the_circumstances(
                state.alert, state.flag_changes, state.deployments, state.placement,
                deployment_changes=state.deployment_changes, onset=state.onset
            )
        ),
        attempts,
        start=state.candidate_index + 1,
        # What an earlier attempt found was not answering. Passed in rather than
        # asked here, because the fact was learnt by an action and only the node
        # that took one could know it - and a candidate on a platform that is
        # down is not worth an experiment for the same reason one already tried
        # is not: the answer is known before it is asked.
        unreachable_platforms=state.unreachable_platforms
    )
    next_index = next_up[0] if next_up is not None else len(state.candidates)
    next_candidate = next_up[1] if next_up is not None else None

    if next_candidate is not None:
        logger.info("candidate chosen", extra={"hypothesis": next_candidate.summary,
                                               "confidence": next_candidate.confidence})

        # Published, and no transition behind it: the incident was mitigating
        # before this and is mitigating after. Moving to the next candidate is
        # progress through a phase, not out of one - so there is no move for the
        # walk's narration to account for, and this node's own event is the only
        # account there is of which explanation the lines after it are about.
        publish(
            CandidateSelected(
                incident_id=state.incident_id,
                hypothesis_id=next_candidate.id,
                candidate_number=next_candidate.number
            ),
            publisher
        )

        return StateDelta(
            attempts=attempts,
            candidate_index=next_index,
            hypothesis=next_candidate,
            confidence=next_candidate.confidence
        )

    # Nothing left that Argus can still reach, which is a different ending from
    # nothing left at all - and it is asked before both of the endings below
    # because each of them would say something false here. Another round would
    # re-read evidence that is perfectly good and arrive at candidates on the same
    # dead platform; a permanent fix is not what an incident needs when what
    # failed is the means of acting on it.
    #
    # Names the actions rather than the platform alone, and derives them from the
    # kinds rather than listing them, so a further mitigation cannot leave this
    # sentence stale. A reader told only that a platform is down has to work out
    # which of Argus's seven went with it, which is what saying anything here is
    # for.
    if state.unreachable_platforms:
        return StateDelta(
            attempts=attempts,
            candidate_index=next_index,
            narration=Narration(
                action="no explanation left that Argus can still act on",
                detail=_what_the_platforms_took_away(state.unreachable_platforms)
            )
        )

    # Asked of the state as this node leaves it, the attempt just made
    # included, which is what `status_after` will be asked of.
    if another_round_is_bought(state.model_copy(update={"attempts": attempts}),
                               max_rounds):
        # Not "every explanation was refuted": a candidate the gate refused or
        # the tier could not act on was never tested, and a line saying it was
        # refuted puts a measurement in the record that never happened.
        return StateDelta(
            attempts=attempts,
            candidate_index=next_index,
            narration=Narration(
                action="no explanation left to try, investigating again"
            )
        )

    # No mitigation is left, and what remains is a permanent fix - which is
    # the one thing `fixing` means. Reported, not decided: the index past the end
    # of the list, and no round left to buy, are what say so.
    return StateDelta(
        attempts=attempts,
        candidate_index=next_index,
        narration=nothing_left_to_try(attempts)
    )


def nothing_left_to_try(attempts: Sequence[Attempt]) -> Narration:
    """What the walk says on its way to Code-Fix with its list spent.

    Public because two nodes spend a list: this one, out of candidates, and
    the investigation, whose round named only what the walk had already
    tried. One sentence for both, so the two roads to the same move cannot
    come to say it differently.

    How many actions, and nothing about what became of them: a restart puts
    nothing back and a change left as found was not put back, and where a
    change was put back or left as found, its verdict's own line says so.
    """
    return Narration(
        action="no explanation left to try",
        detail=(
            f"no explanation left to try - {_how_many_were_taken(len(attempts))}, "
            f"and the evidence offers nothing further"
        )
    )


def _how_many_were_taken(count: int) -> str:
    """The count of actions the walk took, said as a count."""
    if count == 0:
        return "no action was taken"

    if count == 1:
        return "1 action was taken"

    return f"{count} actions were taken"


def _what_the_platforms_took_away(platforms: Sequence[Platform]) -> str:
    """The escalation's own sentence: which platform, and what went with it.

    Both halves, because a reader acts on the second. "The deployment platform
    is not answering" sends somebody to look at one thing; naming the four
    actions it carries tells them what Argus could not do about the incident
    they are now holding, which is the question they actually have.

    Derived from the kinds rather than written out, so that the day a further
    mitigation is added this sentence is right without anybody remembering it.
    """
    return "; ".join(
        f"[{platform}] did not answer, so "
        f"{', '.join(the_actions_through(platform))} could not be used"
        for platform in platforms
    )


def _what_was_just_tried(state: IncidentState) -> list[Attempt]:
    """The attempt this node is reacting to, if production was actually changed.

    An action the gate refused never ran, so there is nothing to remember and
    nothing a later round could learn from it. Only a change that was made is
    evidence about the cause it was made on.

    A cleared action is the whole of that test, and it is the whole of it for
    every kind. It used to ask after the undo descriptor as well, which stopped
    being a question twice over: a flag revert cannot be built without one, and
    an action that leaves nothing to put back is still an action that changed
    the running service - a restart that did not help is evidence about the
    cause exactly as a reverted flag is.

    Dated by when the action was taken, not by when the walk moved on from it.
    A later round reads the attempt beside the flag provider's record of the
    same change, and this node runs after the verification wait -
    dated here, the two disagreed by the length of that wait, and the round
    read two changes where there was one.
    """
    action = state.proposed_action

    if action is None or state.acted_at is None:
        return []

    return [
        Attempt(
            identity=the_identity_of(action),
            enabled=the_direction_of(action),
            occurred_at=to_iso(state.acted_at),
            # Always a refutation's reason here: this node is reached after a
            # refuted action, and an escalated one ends the walk before it.
            # `None` only where the walk resumed from a claim, whose recorded
            # outcome carries the verdict and not the reason.
            refuted_because=state.action_because
        )
    ]


def route_after_next_candidate(state: IncidentState) -> str:
    if state.status == IncidentStatus.MITIGATING:
        return MITIGATING_ROUTE

    if state.status == IncidentStatus.INVESTIGATING:
        return INVESTIGATING_ROUTE

    # Named rather than left to the tail below, which is where it used to land.
    # That was right while nothing could derive an escalation here: the list
    # running out meant another round or a permanent fix, and both are `fixing`
    # eventually. A platform that is not answering derives one now, and a
    # permanent fix is the wrong destination for it - Code-Fix would propose a
    # change to code that is not what failed, while what actually needs a person
    # is that Argus cannot act at all.
    if state.status == IncidentStatus.ESCALATED:
        return ESCALATED_ROUTE

    return FIXING_ROUTE
