"""Where a node's account of itself becomes a row, and a status with it.

A node does its work and says what it did. Deriving where that leaves the
incident, writing it down and publishing it happen here, once, for every node
the graph runs - which is what makes "a status is written only when the incident
enters it" a property of the graph rather than a rule five nodes must remember.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from argus_core.events import StatusChanged
from argus_core.models.actor import Actor
from argus_core.models.incident_state import IncidentState
from argus_core.models.incident_status import IncidentStatus, status_after
from argus_incidents.withdrawal import IsStillWanted
from pydantic import BaseModel

from orchestrator.walk.ports import RecordNote, TransitionIncident


class Narration(BaseModel):
    """What a node says it just did, on its way past.

    Three of these are the `timeline_event` columns a human reads the incident
    from. `detail` is what the published `StatusChanged` carries, which is not
    always the same sentence: the Investigator's event names what the
    investigation did, while Mitigation's names what came back from the action.
    Defaulting it to `action` keeps the ordinary case to one field.

    A node returns this alongside its work and never writes it anywhere. Nothing
    about narration is a node's to decide except the words.
    """

    action: str
    result: str | None = None
    confidence: float | None = None
    detail: str | None = None

    def published_detail(self) -> str:
        return self.detail if self.detail is not None else self.action


def with_status(
    node: Callable[[IncidentState], dict[str, Any]],
    actor: Actor,
    max_rounds: int,
    transition_incident: TransitionIncident,
    record_note: RecordNote,
    still_wanted: IsStillWanted,
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

    The three inputs to a row come from three places that actually know them.
    The status comes from `status_after`, which is the state machine. The words
    come from the node, which is the only thing that knows what it just did. The
    actor comes from this call, because which agent a node belongs to is fixed
    when the graph is built and was being repeated inside every node as a
    constant.

    `narration` is popped rather than passed on. Left in the updates it would
    become a field of `IncidentState`, checkpointed with the incident forever,
    describing whichever node happened to run last.

    It is also where a walk finds out it is no longer wanted, for the same
    reason it is where a status is written: every node passes through here, so
    one question asked once stops all of them. Asked before the node rather
    than after - a node that has already toggled a flag cannot be stopped by
    anything done with its return value.

    The answer is reported into the state rather than swallowed. A node that
    quietly did nothing leaves every field as it was, and the routers decide
    from those fields - so the same route would be chosen again, and again,
    until LangGraph's recursion limit ended the run as failed. `withdrawn` in
    the state is what `stopping_when_withdrawn` reads to route out of the walk.
    No transition is written for it: the row already says `withdrawn`, and
    whoever withdrew it recorded that.
    """
    def run(state: IncidentState) -> dict[str, Any]:
        if not still_wanted(state.incident_id):
            return {"status": IncidentStatus.WITHDRAWN}

        updates = dict(node(state))
        narration = updates.pop("narration", None)
        next_status = status_after(state.model_copy(update=updates), max_rounds)

        if next_status == state.status:
            if narration is not None:
                record_note(
                    state.incident_id,
                    actor=actor,
                    action=narration.action,
                    result=narration.result,
                    confidence=narration.confidence,
                )

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
        transition_incident(
            state.incident_id,
            next_status,
            actor=actor,
            action=narration.action,
            result=narration.result,
            confidence=narration.confidence,
            narrating=StatusChanged(
                incident_id=state.incident_id,
                to_status=next_status,
                detail=narration.published_detail(),
            ),
        )

        return {**updates, "status": next_status}

    return run
