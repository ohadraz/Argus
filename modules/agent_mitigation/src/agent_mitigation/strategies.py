"""What Argus knows how to do about one kind of cause (spec §7.3, §13).

Proposing is policy, and policy has no lifetime: which action answers which
cause is a fact about Argus, not about the process it is running in. So a
strategy is built here, at import, and carries nothing that has to be reached
over a network. Performing an action is the other half and is not here - that
is I/O, it already has its seam in `ActionTaker` and in the Orchestrator's
`Collaborators`, and a registry built to dispatch between one member would be
the second action type's machinery bought before the second action type.

Two questions are asked of a strategy, by two different callers holding two
different things. `propose_action` holds a cause and asks what to do about it.
The Orchestrator's gate holds an `Action` and asks whether an action of that
kind can be put back at all - which is a fact about the kind, not about the
instance, since an instance that reached the gate without a way back is a shape
the models no longer allow.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from argus_core.models import (
    REVERT_FEATURE_FLAG,
    Action,
    ActionType,
    FailureMode,
    FlagChange,
    FlagUndo,
    Hypothesis,
    RevertFeatureFlag,
)

__all__ = [
    "DEFAULT_STRATEGIES",
    "MitigationStrategy",
    "RevertFeatureFlagStrategy",
    "Strategies",
    "can_be_undone"
]


class MitigationStrategy(Protocol):
    """One kind of reversible change, and what Argus can say about it.

    `action_type` is on the strategy rather than only on what it proposes,
    because the gate arrives holding an action and no cause: the index it looks
    up by is derived from this, so a strategy cannot be registered without
    saying which actions it answers for.
    """

    action_type: ActionType

    def propose(self,
                hypothesis: Hypothesis,
                flag_changes: Sequence[FlagChange]) -> Action | None: ...

    def can_be_undone(self) -> bool: ...


class RevertFeatureFlagStrategy:
    """Answering a flag that was toggled by putting it back.

    Which flag comes from the hypothesis, confirmed against what the provider
    recorded as changing - never from Argus's configuration and never from
    which flags are currently on. A configured flag name would hardcode the
    demo's answer into the agent, and current state cannot see half the
    problem: a flag switched off into an incident is off now, exactly like
    every flag that has been off for a year.
    """

    action_type: ActionType = REVERT_FEATURE_FLAG

    def propose(self,
                hypothesis: Hypothesis,
                flag_changes: Sequence[FlagChange]) -> Action | None:
        """The flag change to reverse, or `None` where the evidence names none.

        Reading the Investigator's conclusion is not a second investigation.
        This stays a pure function of the hypothesis and the changes handed to
        it: no retrieval, no model, and no judgement of its own about what
        caused the incident. Which way the flag moved still comes from the
        record, never from the hypothesis, so prose that described the toggle
        backwards cannot turn a flag the wrong way.
        """
        change = _the_change_to_undo(hypothesis.subject, flag_changes)

        if change is None:
            return None

        return RevertFeatureFlag(
            flag=change.flag,
            enabled=not change.enabled,
            undo_descriptor=FlagUndo(
                flag=change.flag,
                was_enabled=change.enabled
            )
        )

    def can_be_undone(self) -> bool:
        """A flag Argus set can be set back, in either direction."""
        return True


Strategies = Mapping[FailureMode, MitigationStrategy]

DEFAULT_STRATEGIES: Strategies = {
    FailureMode.FEATURE_FLAG_TOGGLE: RevertFeatureFlagStrategy()
}


def can_be_undone(action: Action,
                  strategies: Strategies = DEFAULT_STRATEGIES) -> bool:
    """Whether an action of this kind is one Argus can put back (spec §13).

    What the Orchestrator's gate asks before anything mutating is called. A
    kind nobody registered a strategy for answers `False`: an action Argus
    cannot say how to undo is exactly what §13 refuses to take autonomously,
    and a missing entry is not a reason to assume the best about one.

    The index is derived from what each strategy says it answers for, rather
    than kept as a second mapping beside the first. Two registries of one fact
    are two registries that can disagree about it, and the one that disagreed
    here would be admitting an action nothing can reverse.
    """
    for strategy in strategies.values():
        if strategy.action_type == action.action_type:
            return strategy.can_be_undone()

    return False


def _the_change_to_undo(subject: str | None,
                        flag_changes: Sequence[FlagChange]) -> FlagChange | None:
    """The recorded change an action should reverse, or `None` where the
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
