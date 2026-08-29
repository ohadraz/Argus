"""What Mitigation proposes to do (spec §7.3, §13).

The pure half of the agent. Choosing an action is a deterministic function of
the cause the Investigator named and the changes the provider recorded - no
model, no I/O. The Investigator already made the judgement; a model standing
between a verdict and a write can only hallucinate, or pick a tool that exists
anyway.

Keeping the choice separate from the doing is what makes §13's gate more than a
comment: the Orchestrator can reject an action before anything mutating is
called, where a gate inside the function that also performs the write would
guard nothing.

`Action`, `Outcome` and `Verdict` themselves live in `argus_core.models.action`
- they cross into the Orchestrator's graph state and into the `action` table,
so they belong to no single agent - and are re-exported here because this is
where a caller reasoning about mitigation looks for them.
"""

from __future__ import annotations

from collections.abc import Sequence

from argus_core.models.action import Action, Outcome, Verdict
from argus_core.models.cause import CauseType
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis

__all__ = [
    "REVERT_FEATURE_FLAG",
    "SET_FEATURE_FLAG_TOOL",
    "Action",
    "Outcome",
    "Verdict",
    "propose_action",
]

REVERT_FEATURE_FLAG = "revert-feature-flag"

SET_FEATURE_FLAG_TOOL = "set_feature_flag"


def propose_action(hypothesis: Hypothesis,
                   flag_changes: Sequence[FlagChange]) -> Action | None:
    """The reversible action that answers `hypothesis`, or `None` where none
    does (spec §7.3).

    Pure: `flag_changes` arrives as a value rather than being fetched here, so
    that choosing an action cannot depend on a provider being reachable, and
    the Orchestrator can gate the choice before any I/O happens on its behalf.

    Which flag comes from what the provider recorded as changing, never from
    Argus's configuration and never from which flags are currently on. A
    configured flag name would hardcode the demo's answer into the agent, and
    current state cannot see half the problem: a flag switched off into an
    incident is off now, exactly like every flag that has been off for a year.

    Exactly one changed flag is the flag. Zero, or several, yields `None` -
    "the evidence says a flag, and I cannot tell which" is a real state, and a
    human resolves it in seconds where a coin flip changes production.
    """
    if hypothesis.cause_type is not CauseType.FEATURE_FLAG_TOGGLE:
        return None

    change = _the_one_changed_flag(flag_changes)

    if change is None:
        return None

    return Action(
        action_type=REVERT_FEATURE_FLAG,
        flag=change.flag,
        enabled=not change.enabled,
        undo_descriptor={
            "tool": SET_FEATURE_FLAG_TOOL,
            "flag": change.flag,
            "was_enabled": change.enabled,
        },
    )


def _the_one_changed_flag(flag_changes: Sequence[FlagChange]) -> FlagChange | None:
    """The single flag the window says changed, or `None` where that is not
    one flag.

    A flag toggled more than once counts once, and it is its *latest* change
    that is undone: the incident is happening now, so the state to put back is
    the one the service is in now, not whatever it was at the far edge of the
    window. `flag_changes` arrives oldest first, so the last mention of a flag
    is the current one.
    """
    latest_per_flag: dict[str, FlagChange] = {
        change.flag: change for change in flag_changes
    }

    if len(latest_per_flag) != 1:
        return None

    return next(iter(latest_per_flag.values()))
