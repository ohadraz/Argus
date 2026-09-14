"""What Mitigation proposes to do (spec §7.3, §13).

The pure half of the agent. Choosing an action is a deterministic function of
the cause the Investigator named and the changes the provider recorded - no
model, no I/O. The Investigator already made the judgement; a model standing
between a verdict and a write can only hallucinate, or pick a tool that exists
anyway.

*Which* action answers a given cause is not decided here: that is one thing per
cause, and it lives with the strategy for it in `strategies.py`. What is here is
the lookup, and the answer for a cause no strategy is registered for.

Keeping the choice separate from the doing is what makes §13's gate more than a
comment: the Orchestrator can reject an action before anything mutating is
called, where a gate inside the function that also performs the write would
guard nothing.

`Action`, `RevertFeatureFlag`, `Outcome` and `Verdict` themselves live in
`argus_core.models.action` - they cross into the Orchestrator's graph state and
into the `action` table, so they belong to no single agent - and are re-exported
here because this is where a caller reasoning about mitigation looks for them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from argus_core.models import (
    REVERT_FEATURE_FLAG,
    Action,
    FlagChange,
    Hypothesis,
    Outcome,
    RevertFeatureFlag,
    Undone,
    Verdict,
)
from pydantic import BaseModel

from agent_mitigation.strategies import DEFAULT_STRATEGIES, Strategies

__all__ = [
    "REVERT_FEATURE_FLAG",
    "Action",
    "ActionTaker",
    "Outcome",
    "RevertFeatureFlag",
    "UndoAttempt",
    "Undone",
    "Verdict",
    "propose_action",
    "state_name",
]

class ActionTaker(Protocol):
    """What `mitigate` needs from whatever performs an action.

    A `Protocol` rather than a `Callable` alias so a test can stand it in with
    `create_autospec`, which needs something introspectable. Specing against
    `take_action` would be specing against the wrong shape: that one takes the
    configuration it runs under, and what asks for an action holds none.
    """

    def __call__(self, action: Action) -> Outcome: ...


def state_name(enabled: bool) -> str:
    """How a flag's state is spelled in anything a human reads.

    Here rather than beside either caller because both halves of the agent
    write it - taking an action narrates what it set, putting one back narrates
    what it restored - and two spellings of the same state would read as two
    different things having happened.
    """
    return "on" if enabled else "off"


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


def propose_action(hypothesis: Hypothesis,
                   flag_changes: Sequence[FlagChange],
                   strategies: Strategies = DEFAULT_STRATEGIES) -> Action | None:
    """The reversible action that answers `hypothesis`, or `None` where none
    does (spec §7.3).

    A lookup, and nothing else. What to do about a given cause is the
    strategy's to say; what this adds is that a cause nobody registered one for
    is answered with `None` rather than with an exception - the walk has a
    place to go when Argus has nothing to offer, and it is the same place as
    "there was a strategy and it found nothing to reverse". A candidate that
    named no cause at all reaches that same answer: there is nothing to look a
    strategy up by, which is not a different situation from having looked and
    found none.

    Pure: `flag_changes` arrives as a value rather than being fetched here, so
    that choosing an action cannot depend on a provider being reachable, and
    the Orchestrator can gate the choice before any I/O happens on its behalf.

    `strategies` is a parameter so a caller can ask what a different set of
    them would propose. The default is the real registry rather than nothing,
    because proposing is policy: a caller that had to supply the policy in
    order to ask the question would be answering it.
    """
    if hypothesis.cause_type is None:
        return None

    strategy = strategies.get(hypothesis.cause_type)

    if strategy is None:
        return None

    return strategy.propose(hypothesis, flag_changes)
