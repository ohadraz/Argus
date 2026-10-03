"""Choosing an action and taking it in one call (spec §7.3).

The composed form, for callers with no gate to run between the halves. The
Orchestrator does have one (§13) and uses `propose_action` and `take_action`
directly, which is why this is a convenience rather than the way in.
"""

from __future__ import annotations

from collections.abc import Sequence

from argus_core.models import Hypothesis

from agent_mitigation.actions import ActionTaker, Outcome, Verdict, propose_action
from agent_mitigation.tools import FlagChangeFetcher

__all__ = ["mitigate"]


def mitigate(hypothesis: Hypothesis,
             fetch_flag_changes: FlagChangeFetcher,
             take: ActionTaker,
             service: str,
             stale_entry_keys: Sequence[str] = ()) -> Outcome:
    """Answers `hypothesis` with a generic mitigation and a verdict (spec §7.3).

    Takes the whole `Hypothesis` rather than its summary text because
    `failure_mode` is what selects the action - deterministically, in code. A
    summary is prose written for a human, and deriving a production write from
    it would mean parsing or a second model call.

    `service` is the one the alert is about, and it is asked of the caller for
    the reason `propose_action` asks it: an action addressed to a service has
    to be addressed to a service somebody named, and the candidate names only
    what is wrong.

    `stale_entry_keys` is asked of the caller for a sharper version of the same
    reason, and it is the one input here that is an address rather than a
    description. A cache key belongs to whoever wrote the store, so nothing in
    Argus may compose one - the addresses the incident's evidence carried are
    the whole of what a discard can be worked out from. Defaulted to nothing
    because five of the six causes answered here need none of them, and a
    caller that has none has an alert that mentioned no cache.

    What it costs to leave out is worth stating, because the failure is quiet:
    a divergence asked without the addresses is answered by no action at all,
    and this reports that no mitigation answers the cause. That reads as a mode
    Argus has nothing for, where what happened is that the only thing the
    action could have been addressed to never arrived.

    This composes the two halves for callers that have no gate to run between
    them. The Orchestrator does have one (§13), and calls `propose_action` and
    `take_action` either side of it instead.
    """
    action = propose_action(
        hypothesis, fetch_flag_changes(), service, stale_entry_keys
    )

    if action is None:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=f"no mitigation answers a cause of [{hypothesis.failure_mode}]",
        )

    return take(action)
