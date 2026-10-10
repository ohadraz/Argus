"""Where a node's account of itself becomes a row, and a status with it.

A node does its work and says what it did. Deriving where that leaves the
incident, writing it down and publishing it happen here, once, for every node
the graph runs - which is what makes "a status is written only when the incident
enters it" a property of the graph rather than a rule five nodes must remember.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Final

from argus_core.events import StatusChanged
from argus_core.models import IncidentStatus
from argus_incidents import EndedByAPerson, WaitForPeople

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.ports import TransitionIncident
from orchestrator.walk.state import IncidentState, status_after

logger = logging.getLogger(__name__)

# Every ending a person writes from outside the walk. What every node but the
# postmortem stops for: a withdrawal and a resolution are equally reasons not
# to take the next step.
EVERY_PERSONS_ENDING: Final = frozenset(
    status for status in IncidentStatus if status.is_a_persons_ending()
)


def waits_for_nobody(dont_care_incident_id: str, /) -> bool:
    """The wait a node with no next step is handed: the postmortem's, and every
    case that is about something else."""
    return False


def with_status(
    node: Callable[[IncidentState], StateDelta],
    max_rounds: int,
    transition_incident: TransitionIncident,
    ended_by_a_person: EndedByAPerson,
    stops_for: frozenset[IncidentStatus] = EVERY_PERSONS_ENDING,
    wait_for_people: WaitForPeople = waits_for_nobody,
) -> Callable[..., dict[str, Any]]:
    """Wraps a node so that the status it implies is derived, written and
    published in one place (spec §7.1, §10).

    The return type is `Callable[...]` rather than the exact one-argument
    signature, because that is what LangGraph's `add_node` overloads accept -
    the same shape `functools.partial` produced when nodes were registered
    directly.

    It takes no publisher. The status and the sentence about it are one write,
    made by `transition_incident` - a wrapper that published separately would
    be the second writer this arrangement exists to remove.

    Applied at registration time rather than called inside each node, because
    the guarantee wanted here - a status is written only when the incident
    enters it - is not one five nodes can be trusted to remember. They forgot it
    twice: a refuted action wrote `fixing` and was overwritten one node later,
    and an exhausted walk wrote `escalated` on its way into Code-Fix.

    The two inputs come from the two places that know them. The status comes
    from `status_after`, which is the state machine; the words come from the
    node, which is the only thing that knows what it just did. Which agent a
    node belongs to is no longer one of them: the account names its own
    speaker, and a transition is Argus moving the incident whichever of its
    agents did the work that moved it.

    **Narration accompanies a transition and nothing else.** A node that moves
    the incident must return one, and a node that does not may return one that
    is then unused - which is the case for the two that move on some outcomes
    and not others. Nothing is written for a node that stayed put: an account of
    work that settled nothing is the node's own published event now, not a
    sentence handed here to write into a second table. A new node with something
    to say and no status to change publishes it itself; returning narration for
    it would be returning something nobody reads.

    A node returns a `StateDelta` and this is the only place it becomes the
    mapping LangGraph merges. One boundary rather than seven: a key misspelt in
    a literal type-checks, runs, and silently drops whatever the walk turned on,
    and `StateDelta` is what makes that a type error instead.

    `narration` is read off the delta and left out of the updates. Passed on it
    would become a field of `IncidentState`, checkpointed with the incident
    forever, describing whichever node happened to run last.

    It is also where a walk finds out a person has ended the incident, for the
    same reason it is where a status is written: every node passes through
    here, so one question asked once stops all of them. Asked before the node
    rather than after - a node that has already toggled a flag cannot be
    stopped by anything done with its return value.

    `stops_for` is which endings stop this node, and it is every person's
    ending for every node but one. The postmortem stops only for a withdrawal:
    a person who reported the incident resolved is owed the write-up, and the
    person who took it back is not waiting to be told what Argus made of it.
    A node that runs on an incident a person already ended moves it nowhere -
    the row says how it ended, and nothing the node did changes that.

    Once a step is done and its status written, the walk waits for anybody
    Argus has asked to confirm the incident is over (`wait_for_people`) - after
    the step rather than before the next, so the press the wait was for is
    heard before the next step is even chosen, and that step is never entered.
    Here for the reason the ending is asked here: every node passes through, so
    no step can follow another while a person is being asked. A wait that
    waited asks the ending again. The default waits for nobody, for the cases
    about everything else and for the postmortem, after which there is no step
    to hold off; the graph hands every other node the real one.

    The answer is reported into the state rather than swallowed. A node that
    quietly did nothing leaves every field as it was, and the routers decide
    from those fields - so the same route would be chosen again, and again,
    until LangGraph's recursion limit ended the run as failed. The ending in
    the state is what `stopping_when_a_person_ended_it` reads to route the walk
    where that ending sends it. No transition is written for it: the row
    already says it, and whoever ended the incident recorded that.
    """
    def run(state: IncidentState) -> dict[str, Any]:
        updates = stepped(state)

        # A step that ended the walk has nobody to wait for: the person's
        # ending is already its answer.
        if updates.get("status") in stops_for or not wait_for_people(state.incident_id):
            return updates

        ending = ended_by_a_person(state.incident_id)

        if ending in stops_for:
            logger.info("ended by a person while the walk waited", extra={"ending": ending})
            return {**updates, "status": ending}

        return updates

    def stepped(state: IncidentState) -> dict[str, Any]:
        ending = ended_by_a_person(state.incident_id)

        if ending in stops_for:
            return StateDelta(status=ending).as_updates()

        delta = node(state)
        updates = delta.as_updates()

        # Asked again now the node has returned. A step that stopped because a
        # person ended the incident hands back nothing, so it implies no move
        # for the row to refuse below - and without this the routers would read
        # an unchanged status and carry on. Nothing is written: the row already
        # says why the walk is over.
        ending = ended_by_a_person(state.incident_id)

        if ending in stops_for:
            logger.info("ended by a person while a step ran",
                        extra={"from_status": state.status, "ending": ending})
            return {**updates, "status": ending}

        # A node this ending does not stop, running on an incident a person
        # has already ended. The status is theirs, and stays.
        if ending is not None:
            return updates

        narration = delta.narration
        next_status = status_after(state.model_copy(update=updates), max_rounds)

        if next_status == state.status:
            return updates

        # A node that can move the incident has to say why: a transition with no
        # account of itself is a row a human cannot read the incident from.
        if narration is None:
            raise ValueError(
                f"node moved incident [{state.incident_id}] to [{next_status}] "
                f"without narrating it"
            )

        # The row and the line about it go together - one call, one write. Said
        # separately they could disagree: a walk that stopped between them would
        # leave a status nothing accounts for, and the incident is read from the
        # account.
        moved = transition_incident(
            state.incident_id,
            next_status,
            narrating=StatusChanged(
                incident_id=state.incident_id,
                to_status=next_status,
                detail=narration.said(),
            ),
        )

        # Ended while the node ran, after the question asked after it - the row
        # refused the move, so the walk asks which ending it was and goes
        # where that sends it, as it would have had the answer come in time.
        # A refusal with no ending behind it is a row that has gone, which the
        # question itself reads as withdrawn; the fallback says the same.
        if not moved:
            ending = ended_by_a_person(state.incident_id) or IncidentStatus.WITHDRAWN
            logger.info("ended by a person while a step ran",
                        extra={"from_status": state.status, "to_status": next_status,
                               "ending": ending})
            return {**updates, "status": ending}

        logger.info("status changed", extra={"from_status": state.status,
                                             "to_status": next_status,
                                             "reason": narration.said()})

        return {**updates, "status": next_status}

    return run
