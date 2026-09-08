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

from collections.abc import Callable, Sequence
from enum import StrEnum

from argus_core.models.action import Action, Outcome, Verdict
from argus_core.models.cause import CauseType
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from pydantic import BaseModel

__all__ = [
    "REVERT_FEATURE_FLAG",
    "SET_FEATURE_FLAG_TOOL",
    "Action",
    "ActionTaker",
    "Outcome",
    "UndoAttempt",
    "Undone",
    "Verdict",
    "propose_action",
    "state_name",
]

ActionTaker = Callable[[Action], Outcome]


def state_name(enabled: bool) -> str:
    """How a flag's state is spelled in anything a human reads.

    Here rather than beside either caller because both halves of the agent
    write it - taking an action narrates what it set, putting one back narrates
    what it restored - and two spellings of the same state would read as two
    different things having happened.
    """
    return "on" if enabled else "off"


class Undone(StrEnum):
    """What became of one attempt to put a change back.

    Three answers, not two, because "nothing was written" has two meanings and
    a caller's next move differs between them. `LEFT_AS_FOUND` is a decision:
    the flag holds something Argus did not set, so somebody changed it and it
    is no longer Argus's to restore. `NOT_ESTABLISHED` is an absence: the
    provider could not say what the flag holds, and writing on a reading that
    never came back is the blind restore the check exists to prevent.

    Reported rather than raised. An unwind runs over every change an incident
    made, and one flag nobody can read must not stop the others being put back.
    """

    RESTORED = "restored"
    LEFT_AS_FOUND = "left-as-found"
    NOT_ESTABLISHED = "not-established"


class UndoAttempt(BaseModel):
    """What happened to one change somebody tried to put back.

    The flag travels with the answer because the caller unwinding an incident
    holds several of these at once and has to say which is which - and reading
    it back out of the descriptor it passed in would make the record depend on
    the caller having kept it.

    `detail` is the sentence a human reads on the timeline. The outcome is what
    anything else branches on.
    """

    flag: str
    outcome: Undone
    detail: str

REVERT_FEATURE_FLAG = "revert-feature-flag"

SET_FEATURE_FLAG_TOOL = "set_feature_flag"


def propose_action(hypothesis: Hypothesis,
                   flag_changes: Sequence[FlagChange]) -> Action | None:
    """The reversible action that answers `hypothesis`, or `None` where none
    does (spec §7.3).

    Pure: `flag_changes` arrives as a value rather than being fetched here, so
    that choosing an action cannot depend on a provider being reachable, and
    the Orchestrator can gate the choice before any I/O happens on its behalf.

    Which flag comes from the hypothesis, confirmed against what the provider
    recorded as changing - never from Argus's configuration and never from
    which flags are currently on. A configured flag name would hardcode the
    demo's answer into the agent, and current state cannot see half the
    problem: a flag switched off into an incident is off now, exactly like
    every flag that has been off for a year.

    Reading the Investigator's conclusion is not a second investigation. This
    stays a pure function of the hypothesis and the changes handed to it: no
    retrieval, no model, and no judgement of its own about what caused the
    incident. Which way the flag moved still comes from the record, never from
    the hypothesis, so prose that described the toggle backwards cannot turn a
    flag the wrong way.
    """
    if hypothesis.cause_type is not CauseType.FEATURE_FLAG_TOGGLE:
        return None

    change = _the_change_to_undo(hypothesis.subject, flag_changes)

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


def _the_change_to_undo(subject: str | None,
                        flag_changes: Sequence[FlagChange]) -> FlagChange | None:
    """The recorded change this action should reverse, or `None` where the
    evidence does not identify one.

    A flag toggled more than once counts once, and it is its *latest* change
    that is undone: the incident is happening now, so the state to put back is
    the one the service is in now, not whatever it was at the far edge of the
    window. `flag_changes` arrives oldest first, so the last mention of a flag
    is the current one.

    A hypothesis that named a flag selects it from among these; a hypothesis
    that named none falls back to the window being unambiguous by itself.
    """
    latest_per_flag: dict[str, FlagChange] = {
        change.flag: change for change in flag_changes
    }

    if subject is not None:
        return latest_per_flag.get(subject)

    if len(latest_per_flag) != 1:
        return None

    return next(iter(latest_per_flag.values()))
