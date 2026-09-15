"""The Mitigation agent: what to do about a cause, and doing it (spec §7.3).

Five modules behind one public name. `strategies.py` says which action answers
which cause and which kinds of action can be put back at all, `actions.py`
chooses one without touching anything, `trying.py` performs one and judges what
the service did, `undoing.py` puts a recorded change back, and `mitigating.py`
composes the choice and the doing for callers that need no gate between them.
The split follows §13's gate: the Orchestrator has to be able to reach the
choice, and the question of reversibility, without reaching the write.

`tools.py` is behind the same door rather than a sixth module of its own to
import. What a caller running this agent has to supply - the settings slice it
behaves by, the flag history it reads, whether the walk is still wanted - is
named here; how those reach the provider is not, and stays inside.

Three of those are built from a connection, and the three builders are doors for
that reason: a caller hands over the client it holds to a tier and gets back the
flag history, the metrics or the one write, without ever learning which tool
answers or where that server is.
"""

from __future__ import annotations

from agent_mitigation.actions import (
    REVERT_FEATURE_FLAG,
    Action,
    ActionTaker,
    Outcome,
    RevertFeatureFlag,
    UndoAttempt,
    Undone,
    Verdict,
    propose_action,
    state_name,
)
from agent_mitigation.mitigating import mitigate
from agent_mitigation.strategies import (
    DEFAULT_STRATEGIES,
    MitigationStrategy,
    Strategies,
    can_be_undone,
)
from agent_mitigation.tools import (
    FlagChangesSince,
    MitigationSettings,
    StillWanted,
    argus_changed_flag_since,
    fetch_recent_flag_changes,
    flag_changes_over,
    flag_setter_over,
    recent_metrics_over,
    somebody_else_changed_flag_since,
)
from agent_mitigation.trying import UndoChange, take_action
from agent_mitigation.undoing import undo_change

__all__ = [
    "DEFAULT_STRATEGIES",
    "REVERT_FEATURE_FLAG",
    "Action",
    "ActionTaker",
    "FlagChangesSince",
    "MitigationSettings",
    "MitigationStrategy",
    "Outcome",
    "RevertFeatureFlag",
    "StillWanted",
    "Strategies",
    "UndoAttempt",
    "UndoChange",
    "Undone",
    "Verdict",
    "argus_changed_flag_since",
    "can_be_undone",
    "fetch_recent_flag_changes",
    "flag_changes_over",
    "flag_setter_over",
    "mitigate",
    "recent_metrics_over",
    "propose_action",
    "somebody_else_changed_flag_since",
    "state_name",
    "take_action",
    "undo_change",
]
