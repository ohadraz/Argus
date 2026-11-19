"""The Mitigator: what to do about a cause, and doing it (spec §7.3).

Five modules carry the Mitigator behind one public name. `strategies.py` says which
action answers which cause, `admitting.py` says which kinds Argus may take
unasked, `actions.py` chooses one without touching anything, `trying.py`
performs one and judges what the service did, and `kinds.py` holds what differs
between kinds of action - the write, the words, the wait and the way back. The
split follows §13's gate: the Orchestrator has to be able to reach the choice,
and the question of admission, without reaching the write.
`accelerators.py`, `attribution.py` and `binding.py` are what those five work
with - which card a pin holds a deployment to, how Argus tells its own
deployments from everybody else's, and where those capabilities are bound to the
tier they run over.

`tools.py` is behind the same door rather than a module of its own to import.
What a caller running the Mitigator has to supply - the settings slice it behaves
by, the flag history it reads, whether the walk is still wanted - is named here;
how those reach the provider is not, and stays inside.

Several are built from a connection, and their `*_over` builders are doors for
that reason: a caller hands over the client it holds to a tier and gets back the
flag history, the metrics, a rollout's progress or the writes, without ever
learning which tool answers or where that server is.
"""

from __future__ import annotations

from core.budget import StillWanted

from mitigation.actions import (
    REVERT_FEATURE_FLAG,
    Action,
    Outcome,
    RevertFeatureFlag,
    UndoAttempt,
    Undone,
    Verdict,
    propose_action,
)
from mitigation.admitting import (
    GENERIC_MITIGATIONS,
    AdmittedMitigations,
    is_a_generic_mitigation,
    is_within_reach,
)
from mitigation.binding import an_undo_over
from mitigation.kinds import Performed, arrival_of, performed_as_recorded, still_argus_s
from mitigation.strategies import (
    MitigationStrategy,
    PinToAcceleratorStrategy,
    Reasons,
    RestartDependencyStrategy,
    RestartServiceStrategy,
    ScaleOutStrategy,
    Strategies,
    why_no_mitigation_answers,
    why_nothing_was_proposed,
)
from mitigation.tools import (
    DeploymentsBetween,
    FlagChangesSince,
    MitigationSettings,
    PerformingWrites,
    ServiceRestarter,
    deployment_restorer_over,
    deployment_roller_over,
    deployments_over,
    fetch_recent_deployments,
    fetch_recent_flag_changes,
    flag_changes_over,
    flag_setter_over,
    performing_writes_over,
    recent_metrics_over,
    rollout_progress_over,
    rules_read_over,
)
from mitigation.trying import (
    ChangeMade,
    NobodyCanSay,
    PutBackOwed,
    UndoChange,
    plan_action,
    settle_the_refutation,
    stopped_before_it_was_taken,
    take_action,
    watch_what_was_performed,
    whether_it_was_made,
)

__all__ = [
    "GENERIC_MITIGATIONS",
    "REVERT_FEATURE_FLAG",
    "Action",
    "AdmittedMitigations",
    "ChangeMade",
    "DeploymentsBetween",
    "FlagChangesSince",
    "MitigationSettings",
    "MitigationStrategy",
    "NobodyCanSay",
    "Outcome",
    "Performed",
    "PerformingWrites",
    "PinToAcceleratorStrategy",
    "PutBackOwed",
    "Reasons",
    "RestartDependencyStrategy",
    "RestartServiceStrategy",
    "RevertFeatureFlag",
    "ScaleOutStrategy",
    "ServiceRestarter",
    "StillWanted",
    "Strategies",
    "UndoAttempt",
    "UndoChange",
    "Undone",
    "Verdict",
    "an_undo_over",
    "arrival_of",
    "deployment_restorer_over",
    "deployment_roller_over",
    "deployments_over",
    "fetch_recent_deployments",
    "fetch_recent_flag_changes",
    "flag_changes_over",
    "flag_setter_over",
    "is_a_generic_mitigation",
    "is_within_reach",
    "performed_as_recorded",
    "performing_writes_over",
    "plan_action",
    "recent_metrics_over",
    "rollout_progress_over",
    "rules_read_over",
    "propose_action",
    "settle_the_refutation",
    "still_argus_s",
    "stopped_before_it_was_taken",
    "take_action",
    "watch_what_was_performed",
    "whether_it_was_made",
    "why_no_mitigation_answers",
    "why_nothing_was_proposed"
]
