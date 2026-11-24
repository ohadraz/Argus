"""Where a node's run becomes a numbered step of the walk.

Every node the graph runs passes through here, for the reason every node
passes through `traced`: a property all of them must have is one none of them
can be trusted to remember. Here the property is that every row a node writes
says which step wrote it, so a step run again from its checkpoint can take back
what its interrupted attempt wrote (`discarding`).

A step is numbered by how many the walk took before it (`IncidentState.steps`),
and the number travels in the checkpoint: a step run again reads the number
its interrupted attempt read, and the step after it reads one more. The thread
a walk is checkpointed on is its incident's, and no checkpoint is ever
deleted, so the number only rises - one incident's steps never share one.

Its own wrapper rather than part of `traced`, which says what a step was in
the trace and passes whatever the node returned through untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from incident_record import within_step

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.state import IncidentState


def stepped(
    node: Callable[[IncidentState], dict[str, Any] | StateDelta]
) -> Callable[[IncidentState], dict[str, Any]]:
    """Wraps a node so that it runs as the walk's next step: every write made
    while it runs is that step's, and the walk has taken one more step once it
    returns.

    The node's result is a mapping where `with_status` already made it one, and
    a `StateDelta` for the two nodes it does not wrap - both become the
    mapping LangGraph merges, with the count of steps in it.
    """
    def run(state: IncidentState) -> dict[str, Any]:
        with within_step(state.steps):
            result = node(state)

        updates = result.as_updates(state) if isinstance(result, StateDelta) else result

        return {**updates, "steps": state.steps + 1}

    return run
