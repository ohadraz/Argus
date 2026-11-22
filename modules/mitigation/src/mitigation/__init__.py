"""The Mitigator: what to do about a cause, and doing it (spec §7.3).

Four modules carry the Mitigator behind one public name. `strategies.py` says which
action answers which cause, `actions.py` chooses one without touching anything,
`trying.py` performs one and judges what the service did, and `kinds.py` holds
what differs between kinds of action - the write, the words, the wait and the
way back. The split follows §13's gate: the Orchestrator has to be able to reach
the choice without reaching the write.

Which kinds Argus may take unasked is not the Mitigator's to say. It lives in
`core.autonomy`, the policy the gate applies, and `take_action` accepts only
what that policy admitted (`Admitted`). Only the walk asks the policy for an
admission - the layering guard refuses `admit` named anywhere here - so nothing
changed here can widen what Argus does on its own authority without failing
the build.

`accelerators.py` and `binding.py` are what those four work with - which card
a pin holds a deployment to, and where those capabilities are bound to the tier
they run over. How Argus tells its own changes from everybody else's is not
here: each change says, as the adapter that read it was able to tell.

`tools.py` is behind the same door rather than a module of its own to import.
What a caller running the Mitigator has to supply - the settings slice it behaves
by, the flag history it reads, whether the walk is still wanted - is named here;
how those reach the provider is not, and stays inside.

Every read it makes is a `Protocol` the read or write tier's own method
satisfies, so a composition root binds `read.get_alert_rule` or
`write.get_recent_flag_changes` to it directly. The two bundles are the
exception, and their builders are doors for that reason: a caller hands over the
write tier it holds and gets back every write that performs a mitigation
(`performing_writes_over`) or a way to put one back (`an_undo_over`), without
assembling either member by member.
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
    fetch_recent_deployments,
    fetch_recent_flag_changes,
    performing_writes_over,
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
    "REVERT_FEATURE_FLAG",
    "Action",
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
    "fetch_recent_deployments",
    "fetch_recent_flag_changes",
    "performed_as_recorded",
    "performing_writes_over",
    "plan_action",
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
