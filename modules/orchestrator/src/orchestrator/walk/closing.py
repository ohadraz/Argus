"""The last node: the incident is over, and this is what is left to say."""

from __future__ import annotations

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.ports import RecordPostmortem, WritePostmortem
from orchestrator.walk.state import IncidentState


def postmortem_node(
    state: IncidentState,
    write: WritePostmortem,
    record: RecordPostmortem,
) -> StateDelta:
    """Writes the incident up, and stores whatever was written (spec §7.6).

    The last node, and the only one whose work nothing downstream reads - which
    is why it stores a partial document rather than discarding one. A page
    finding nothing where a postmortem should be cannot tell "never written"
    from "lost", and the incident is over either way.

    Both collaborators are injected for the usual reason: what a postmortem
    says belongs to the agent and how a row is stored belongs to the
    repository, so this node's own logic - that the two are joined at all - can
    be tested without a database or a model.
    """
    record(state.incident_id, write(state.incident_id))

    return StateDelta()
