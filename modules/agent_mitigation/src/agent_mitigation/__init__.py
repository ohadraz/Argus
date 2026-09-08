"""The Mitigation agent: what to do about a cause, and doing it (spec §7.3).

Four modules behind one public name. `actions.py` chooses an action without
touching anything, `trying.py` performs one and judges what the service did,
`undoing.py` puts a recorded change back, and `mitigating.py` composes the
choice and the doing for callers that need no gate between them. The split
follows §13's gate: the Orchestrator has to be able to reach the choice without
reaching the write.
"""

from __future__ import annotations

from agent_mitigation.actions import (
    REVERT_FEATURE_FLAG,
    Action,
    ActionTaker,
    Outcome,
    UndoAttempt,
    Undone,
    Verdict,
    propose_action,
    state_name,
)
from agent_mitigation.mitigating import mitigate
from agent_mitigation.trying import UndoChange, take_action
from agent_mitigation.undoing import undo_change

__all__ = [
    "REVERT_FEATURE_FLAG",
    "Action",
    "ActionTaker",
    "Outcome",
    "UndoAttempt",
    "UndoChange",
    "Undone",
    "Verdict",
    "mitigate",
    "propose_action",
    "state_name",
    "take_action",
    "undo_change",
]
