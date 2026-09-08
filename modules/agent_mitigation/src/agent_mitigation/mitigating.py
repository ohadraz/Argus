"""Choosing an action and taking it in one call (spec §7.3).

The composed form, for callers with no gate to run between the halves. The
Orchestrator does have one (§13) and uses `propose_action` and `take_action`
directly, which is why this is a convenience rather than the way in.
"""

from __future__ import annotations

from argus_core.models.hypothesis import Hypothesis

from agent_mitigation.actions import ActionTaker, Outcome, Verdict, propose_action
from agent_mitigation.tools import FlagChangeFetcher, fetch_recent_flag_changes
from agent_mitigation.trying import take_action

__all__ = ["mitigate"]


def mitigate(hypothesis: Hypothesis,
             fetch_flag_changes: FlagChangeFetcher = fetch_recent_flag_changes,
             take: ActionTaker = take_action) -> Outcome:
    """Answers `hypothesis` with a reversible action and a verdict (spec §7.3).

    Takes the whole `Hypothesis` rather than its summary text because
    `cause_type` is what selects the action - deterministically, in code. A
    summary is prose written for a human, and deriving a production write from
    it would mean parsing or a second model call.

    This composes the two halves for callers that have no gate to run between
    them. The Orchestrator does have one (§13), and calls `propose_action` and
    `take_action` either side of it instead.
    """
    action = propose_action(hypothesis, fetch_flag_changes())

    if action is None:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=f"no reversible action answers a cause of [{hypothesis.cause_type}]",
        )

    return take(action)
