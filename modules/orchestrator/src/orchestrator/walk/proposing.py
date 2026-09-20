"""Choosing the mitigation that answers the hypothesis, and only that."""

from __future__ import annotations

from agent_mitigation import propose_action

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.state import IncidentState


def mitigation_proposal_node(state: IncidentState) -> StateDelta:
    """Chooses the mitigation that answers the hypothesis, and stops
    there (spec §7.3).

    Nothing here changes anything, and nothing here reads anything either: it
    asks Mitigation which action follows from the cause the Investigator named
    and the history the round already read, deterministically and without a
    model. Separating this from the node that acts is what leaves somewhere for
    the gate to stand - a gate the acting code could skip is not a gate.

    The history is not fetched here, though it used to be. It is read once at
    the top of the round, because deciding which candidate to try at all needs
    to know what each one would be answered with - and a second read here
    would let the node that proposes an action and the node that chose the
    candidate reason about two different accounts of the same provider.

    A provider that could not be read arrives as `None` rather than as an empty
    history, and proposes nothing. "I could not find out what changed" and
    "nothing changed" lead to the same place - no action, and a human - and
    neither is a reason to fail the graph.
    """
    if state.hypothesis is None or state.flag_changes is None:
        return StateDelta(proposed_action=None)

    # The alert's service, because an action addressed to a service is
    # addressed to the one the incident is about. The candidate's subject says
    # what is wrong in prose and names nothing a platform could be asked to
    # restart.
    return StateDelta(
        proposed_action=propose_action(
            state.hypothesis, state.flag_changes, state.alert.service
        )
    )
