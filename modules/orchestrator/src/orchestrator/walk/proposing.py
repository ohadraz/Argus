"""Choosing the mitigation that answers the hypothesis, and only that."""

from __future__ import annotations

from agent_mitigation import propose_action
from argus_core.events import FlagChangesRetrieved, Publisher, nobody, publish

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.ports import FetchFlagChanges
from orchestrator.walk.state import IncidentState


def mitigation_proposal_node(
    state: IncidentState,
    fetch_flag_changes: FetchFlagChanges,
    publisher: Publisher = nobody,
) -> StateDelta:
    """Chooses the mitigation that answers the hypothesis, and stops
    there (spec §7.3).

    Nothing here changes anything: it reads what the provider recorded as
    having changed and asks Mitigation which action follows, deterministically
    and without a model. Separating this from the node that acts is what leaves
    somewhere for the gate to stand - a gate the acting code could skip is not
    a gate.

    A provider that cannot be read proposes nothing rather than raising. "I
    could not find out what changed" and "nothing changed" lead to the same
    place - no action, and a human - and neither is a reason to fail the graph.
    """
    if state.hypothesis is None:
        return StateDelta(proposed_action=None)

    try:
        flag_changes = fetch_flag_changes()
    except Exception:
        # Deliberately unpublished. An empty history here would state that
        # nothing had changed, where what happened is that nobody could say -
        # and the two look identical on a page while meaning opposite things.
        return StateDelta(proposed_action=None)

    # The whole basis of the action about to be proposed: which flag moved,
    # which way, and when. Published from the node that reads it, because by
    # the time an action exists this history has already been reduced to a
    # single decision about a single flag.
    publish(
        FlagChangesRetrieved(incident_id=state.incident_id, changes=list(flag_changes)),
        publisher,
    )

    # The alert's service, because an action addressed to a service is
    # addressed to the one the incident is about. The candidate's subject says
    # what is wrong in prose and names nothing a platform could be asked to
    # restart.
    return StateDelta(
        proposed_action=propose_action(
            state.hypothesis, flag_changes, state.alert.service
        )
    )
