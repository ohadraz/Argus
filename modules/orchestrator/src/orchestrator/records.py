"""Every write a node makes, against one source of connections."""

from __future__ import annotations

from datetime import datetime

from agent_postmortem import PostmortemDocument
from argus_core.db import Connections
from argus_core.events import IncidentEvent
from argus_core.models.actor import Actor
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.undo_descriptor import UndoDescriptor
from argus_incidents.publishing import PublisherFor, narrate
from argus_incidents.repository import (
    hypotheses,
    incidents,
    postmortems,
    taken_actions,
)


class Records:
    """Every write a node makes, against one source of connections.

    One object rather than nine functions taking a tenth argument: each of its
    methods is already the shape of the `Protocol` a node asks for, so a bound
    method goes straight in where the node expects a collaborator and the
    database stops appearing in any node's signature.

    Built once where the graph is assembled, from whatever that process holds -
    a pool while Argus is running, a single connection in a script.
    """

    def __init__(self,
                 connections: Connections,
                 publisher_for: PublisherFor) -> None:
        self._connections = connections
        self._publisher_for = publisher_for

    def hypothesis(self, hypothesis: Hypothesis, /) -> None:
        with self._connections() as conn:
            hypotheses.record(conn, hypothesis)

    def outcome(self, hypothesis_id: str, tested: bool, result: str) -> None:
        with self._connections() as conn:
            hypotheses.record_outcome(conn, hypothesis_id, tested=tested, result=result)

    def transition(
        self,
        incident_id: str,
        to_status: IncidentStatus,
        actor: Actor,
        action: str,
        narrating: IncidentEvent,
        result: str | None = None,
        confidence: float | None = None,
    ) -> None:
        """Moves the incident, and says so, in one write.

        `narrating` is required rather than optional because there is no such
        thing as a transition nobody accounts for: the timeline is what the
        incident is read from, and a status that arrived without a sentence
        about it is a row a human cannot act on.

        One connection for both, so the two commit together - and the account
        written last, inside a savepoint of its own, so it can fail without
        taking the transition with it.
        """
        with self._connections() as conn:
            incidents.transition(
                conn, incident_id, to_status, actor=actor, action=action,
                result=result, confidence=confidence,
            )
            narrate(conn, narrating, self._publisher_for(conn))

    def note(
        self,
        incident_id: str,
        actor: Actor,
        action: str,
        result: str | None = None,
        confidence: float | None = None,
    ) -> None:
        with self._connections() as conn:
            incidents.record_note(
                conn, incident_id, actor=actor, action=action,
                result=result, confidence=confidence,
            )

    def claim_action(
        self,
        incident_id: str,
        hypothesis_id: str,
        action_type: str,
    ) -> bool:
        with self._connections() as conn:
            return taken_actions.claim(
                conn,
                incident_id,
                hypothesis_id=hypothesis_id,
                action_type=action_type,
            )

    def complete_action(
        self,
        incident_id: str,
        hypothesis_id: str,
        outcome: str,
        undo_descriptor: UndoDescriptor | None,
        narrating: IncidentEvent,
    ) -> None:
        """Records what came of the action, and says so, in one write.

        The same pairing a transition gets, for the same reason and in the same
        order: the verdict is written first and the sentence about it second,
        inside a savepoint. Published separately - and it used to be published
        *first* - a walk that stopped in between announced a verdict that was
        never recorded against the action it was about.
        """
        with self._connections() as conn:
            taken_actions.complete(
                conn,
                incident_id,
                hypothesis_id=hypothesis_id,
                outcome=outcome,
                undo_descriptor=undo_descriptor,
            )
            narrate(conn, narrating, self._publisher_for(conn))

    def action_outcome(self, incident_id: str, hypothesis_id: str) -> str | None:
        with self._connections() as conn:
            taken_action = taken_actions.get_action_for_hypothesis(
                conn, incident_id, hypothesis_id)

        return taken_action.outcome if taken_action is not None else None

    def action_claimed_at(self,
                          incident_id: str,
                          hypothesis_id: str) -> datetime | None:
        with self._connections() as conn:
            taken_action = taken_actions.get_action_for_hypothesis(
                conn, incident_id, hypothesis_id)

        return taken_action.taken_at if taken_action is not None else None

    def postmortem(self, incident_id: str, document: PostmortemDocument, /) -> None:
        with self._connections() as conn:
            postmortems.record(conn, incident_id, document)
