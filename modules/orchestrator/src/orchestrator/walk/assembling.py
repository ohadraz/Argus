"""Everything a walk is supplied with, and where a deployment supplies it.

`ports` says what each collaborator's shape is; this says that the list of them
is the Orchestrator's whole contract with the process running it. One record
rather than nineteen arguments: a node names what it needs, the graph hands it
over, and the only thing here that knows a database can be had is `against`.

Which is what makes the walk testable without one. A test builds its own
record and gets the real nodes, the real state machine and the real routers,
with only the agents and the repositories standing in for themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_investigator import investigate as _investigate
from agent_mitigation import take_action
from agent_mitigation.tools import argus_changed_flag_since, fetch_recent_flag_changes
from argus_core.db import Connections
from argus_core.events import Publisher
from argus_core.replay import Recorder
from argus_incidents.publishing import calls_into, events_into, events_into_connection
from argus_incidents.withdrawal import IsStillWanted, wanted_via

from orchestrator.gathering import write_postmortem_for
from orchestrator.records import Records
from orchestrator.walk.ports import (
    ActionAlreadyTaken,
    ActionClaimedAt,
    ChangeLanded,
    CompleteAction,
    FetchFlagChanges,
    Investigate,
    RecordAction,
    RecordHypothesis,
    RecordNote,
    RecordOutcome,
    RecordPostmortem,
    TakeAction,
    TransitionIncident,
    WritePostmortem,
)


@dataclass(frozen=True)
class Collaborators:
    """What the graph hands to its nodes, in one value.

    The agents Argus delegates to, the repositories it writes through, and the
    three the wrapper needs to say where an incident stands and whether anybody
    still wants it. Nothing here is defaulted: a default would be the real
    Anthropic-backed investigator quietly reached by a test that forgot to name
    one, and forgetting is exactly what this record exists to make impossible.
    """

    investigate: Investigate
    record_hypothesis: RecordHypothesis
    fetch_flag_changes: FetchFlagChanges
    record_outcome: RecordOutcome
    take: TakeAction
    record_action: RecordAction
    complete_action: CompleteAction
    already_taken: ActionAlreadyTaken
    claimed_at: ActionClaimedAt
    change_landed: ChangeLanded
    write_postmortem: WritePostmortem
    record_postmortem: RecordPostmortem
    transition_incident: TransitionIncident
    record_note: RecordNote
    publisher: Publisher
    recorder: Recorder
    still_wanted: IsStillWanted


def against(connections: Connections) -> Collaborators:
    """The real ones, for a process that has a database and a model.

    Built once where the process starts. Everything derived from `connections`
    is a closure over it rather than an open connection, so assembling a graph
    reaches nothing - a walk is what opens one, when a node actually runs.
    """
    records = Records(connections, events_into_connection)
    recorder = calls_into(connections)

    return Collaborators(
        investigate=_investigate,
        record_hypothesis=records.hypothesis,
        fetch_flag_changes=fetch_recent_flag_changes,
        record_outcome=records.outcome,
        take=take_action,
        record_action=records.claim_action,
        complete_action=records.complete_action,
        already_taken=records.action_outcome,
        claimed_at=records.action_claimed_at,
        change_landed=argus_changed_flag_since,
        write_postmortem=lambda incident_id: write_postmortem_for(
            incident_id, connections=connections, recorder=recorder),
        record_postmortem=records.postmortem,
        transition_incident=records.transition,
        record_note=records.note,
        publisher=events_into(connections),
        recorder=recorder,
        still_wanted=wanted_via(connections)
    )
