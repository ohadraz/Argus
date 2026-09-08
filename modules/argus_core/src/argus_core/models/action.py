from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from argus_core.models.undo_descriptor import UndoDescriptor


class Verdict(StrEnum):
    """What an attempted mitigation says about the hypothesis behind it.

    `CONFIRMED` and `REFUTED` are the two answers spec §7.3 asks Mitigation
    for. A confirmed action resolves the incident; a refuted one leaves it
    where it was, in `mitigating`, for the next explanation on the list.
    `ESCALATED` is not a third opinion on the hypothesis - it means no verdict
    was reached at all, because nothing could be done or because the
    environment was left in a state Argus cannot account for.

    `WITHDRAWN` is the other way no verdict is reached: the action was taken and
    then abandoned, because somebody took the incident back while the service
    was still being watched. It is not `REFUTED` - nothing was measured, and
    recording evidence against a hypothesis nobody finished testing is the one
    thing a stopped experiment must not leave behind. The change it made is
    still out there, which is why the outcome carries its undo descriptor.
    """

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    ESCALATED = "escalated"
    WITHDRAWN = "withdrawn"


class Action(BaseModel):
    """A reversible action, chosen but not yet taken (spec §7.3, §13).

    Here rather than in `agent_mitigation` for the same reason `Hypothesis` is
    here: it crosses agent boundaries. Mitigation proposes one, the
    Orchestrator's gate node inspects it, the graph's state carries it between
    the two, and the `action` table stores what became of it - so it belongs to
    no single agent.

    `enabled` is the state to leave the flag in, which is whatever undoes the
    change that caused the incident - off for a flag that was switched on, on
    for one that was switched off. Stating the target state rather than "revert
    it" is what lets one action type serve both directions.

    `undo_descriptor` is populated at proposal time, before anything is called,
    because the gate node's job is to reject an action that has none *before*
    the write. A descriptor filled in by the write it exists to guard would
    guard nothing.

    It is optional for what the gate is *for*: an action type with no way back
    is exactly what §13 refuses to take autonomously, and the gate can only
    refuse one if such an action can be expressed. Today's one action type
    always carries a descriptor; the check is about the next one.
    """

    action_type: str
    flag: str
    enabled: bool
    undo_descriptor: UndoDescriptor | None


class Outcome(BaseModel):
    """What happened when an action was taken.

    `detail` is for the human reading the timeline, and carries what the
    verdict alone cannot - which flag was changed, and, where a restore failed,
    what the provider said about it. `undo_descriptor` is the one the write
    tier returned, which is the record of what was actually changed rather than
    what was intended; it is absent when nothing was changed at all.
    """

    verdict: Verdict
    detail: str
    undo_descriptor: UndoDescriptor | None = None
