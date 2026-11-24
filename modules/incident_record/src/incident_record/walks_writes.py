"""Every write the walk makes to the incident record.

Moving the incident, the candidates it forms and what came of each, the action
claimed for one and how far it got, the fix Code-Fix claimed, what an
interrupted step wrote taken back, the write-ups, what the Investigator made of
a lead, and what putting a change back did.

On a connection its caller holds and commits, and nothing else: each of these
is written in one unit of work with the line that accounts for it, published
beside it on the same connection - so the caller opens the unit, writes here,
publishes, and commits once. A role that committed for itself would split the
decision from its account.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import psycopg
from core.models import (
    ActionProgress,
    ActionType,
    ClaimAnswer,
    ClaimedFix,
    ExecutiveSynopsisDocument,
    Hypothesis,
    IncidentStatus,
    Planned,
    PostmortemDocument,
    Reference,
    UndoDescriptor,
    Undone,
    Verdict,
    Weighing,
)

from incident_record.repository import (
    conversation,
    events,
    fix_claims,
    hypotheses,
    incidents,
    postmortems,
    synopses,
    taken_actions,
)


class TheWalksWrites(Protocol):
    """The walk's writes to the incident record."""

    def transition(self, incident_id: str, to_status: IncidentStatus, /, *,
                   at: datetime) -> bool:
        """Moves the incident, where no person's ending stands in the way, and
        says whether it moved."""
        ...

    def hypothesis(self, hypothesis: Hypothesis, /) -> None:
        """Writes a candidate the Investigator formed."""
        ...

    def outcome(self, hypothesis_id: str, /, *, tested: bool, result: str) -> None:
        """Fills in what the walk found out about a candidate it reached."""
        ...

    def take_back_step(self, incident_id: str, step: int, /) -> int:
        """Takes back every line one step of the walk said and every candidate
        it formed, and answers how many rows there were."""
        ...

    def claim(self, incident_id: str, /, hypothesis_id: str, action_type: ActionType,
              subject: str | None, at: datetime, *,
              planned: Planned[Any] | None = None) -> ClaimAnswer:
        """Claims the right to act for one candidate, or says whose it is."""
        ...

    def complete(self, incident_id: str, /, hypothesis_id: str, outcome: Verdict,
                 undo_descriptor: UndoDescriptor | None, performed: bool = True, *,
                 left_behind_known: bool, undone: Undone | None = None) -> None:
        """Records what came of a claimed action."""
        ...

    def advance(self, incident_id: str, /, hypothesis_id: str, to: ActionProgress,
                undo_descriptor: UndoDescriptor | None, *,
                performed_at: datetime | None = None) -> None:
        """Moves a claimed action on."""
        ...

    def plan_the_claim(self, incident_id: str, /, hypothesis_id: str,
                       planned: Planned[Any]) -> None:
        """Writes the plan a resumed walk takes its action on onto a claim
        written with none."""
        ...

    def owe_a_put_back(self, incident_id: str, /, hypothesis_id: str, because: str) -> None:
        """Records a refuted change as owed back, with what the wait found."""
        ...

    def record_undone(self, action_id: str, undone: Undone, /) -> None:
        """Records what putting an action's change back did."""
        ...

    def claim_fix(self, incident_id: str, fix: ClaimedFix, /, *,
                  at: datetime) -> ClaimedFix:
        """Claims the fix Code-Fix is about to write, where the incident has
        none claimed, and answers the claim that stands."""
        ...

    def postmortem(self, incident_id: str, document: PostmortemDocument, /, *,
                   at: datetime) -> None:
        """Stores the incident's write-up, replacing any it had."""
        ...

    def synopsis(self, incident_id: str, synopsis: ExecutiveSynopsisDocument, /, *,
                 at: datetime) -> None:
        """Stores the incident's executive synopsis, replacing any it had."""
        ...

    def weighed(self, message: Reference, weighing: Weighing, /) -> None:
        """Keeps what the Investigator made of a lead."""
        ...


class _OnAConnection:
    """The walk's writes, on a connection somebody else holds and commits."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def transition(self, incident_id: str, to_status: IncidentStatus, /, *,
                   at: datetime) -> bool:
        return incidents.transition(self._conn, incident_id, to_status, at=at)

    def hypothesis(self, hypothesis: Hypothesis, /) -> None:
        hypotheses.record(self._conn, hypothesis)

    def outcome(self, hypothesis_id: str, /, *, tested: bool, result: str) -> None:
        hypotheses.record_outcome(self._conn, hypothesis_id, tested=tested, result=result)

    def take_back_step(self, incident_id: str, step: int, /) -> int:
        return (events.delete_by_step(self._conn, incident_id, step)
                + hypotheses.delete_by_step(self._conn, incident_id, step))

    def claim(self, incident_id: str, /, hypothesis_id: str, action_type: ActionType,
              subject: str | None, at: datetime, *,
              planned: Planned[Any] | None = None) -> ClaimAnswer:
        return taken_actions.claim(self._conn, incident_id, hypothesis_id=hypothesis_id,
                                   action_type=action_type, subject=subject, at=at,
                                   planned=planned)

    def complete(self, incident_id: str, /, hypothesis_id: str, outcome: Verdict,
                 undo_descriptor: UndoDescriptor | None, performed: bool = True, *,
                 left_behind_known: bool, undone: Undone | None = None) -> None:
        taken_actions.complete(self._conn, incident_id, hypothesis_id=hypothesis_id,
                               outcome=outcome, undo_descriptor=undo_descriptor,
                               performed=performed, left_behind_known=left_behind_known,
                               undone=undone)

    def advance(self, incident_id: str, /, hypothesis_id: str, to: ActionProgress,
                undo_descriptor: UndoDescriptor | None, *,
                performed_at: datetime | None = None) -> None:
        taken_actions.advance(self._conn, incident_id, hypothesis_id=hypothesis_id, to=to,
                              undo_descriptor=undo_descriptor, performed_at=performed_at)

    def plan_the_claim(self, incident_id: str, /, hypothesis_id: str,
                       planned: Planned[Any]) -> None:
        taken_actions.plan_the_claim(self._conn, incident_id, hypothesis_id=hypothesis_id,
                                     planned=planned)

    def owe_a_put_back(self, incident_id: str, /, hypothesis_id: str, because: str) -> None:
        taken_actions.owe_a_put_back(self._conn, incident_id, hypothesis_id=hypothesis_id,
                                     because=because)

    def record_undone(self, action_id: str, undone: Undone, /) -> None:
        taken_actions.record_undone(self._conn, action_id, undone)

    def claim_fix(self, incident_id: str, fix: ClaimedFix, /, *,
                  at: datetime) -> ClaimedFix:
        return fix_claims.claim(self._conn, incident_id, fix, at=at)

    def postmortem(self, incident_id: str, document: PostmortemDocument, /, *,
                   at: datetime) -> None:
        postmortems.record(self._conn, incident_id, document, at=at)

    def synopsis(self, incident_id: str, synopsis: ExecutiveSynopsisDocument, /, *,
                 at: datetime) -> None:
        synopses.record(self._conn, incident_id, synopsis, at=at)

    def weighed(self, message: Reference, weighing: Weighing, /) -> None:
        conversation.weighed(self._conn, message, weighing)


def the_walks_writes_on(conn: psycopg.Connection) -> TheWalksWrites:
    """The walk's writes, on `conn`, which the caller holds and commits with the
    line it publishes beside each."""
    return _OnAConnection(conn)
