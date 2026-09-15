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
from functools import partial

from agent_codefix import FixSettings, fixes_over
from agent_investigator import changes_over, logs_over, metrics_over
from agent_investigator import investigate as _investigate
from agent_investigator.budget import InvestigationSettings
from agent_mitigation import (
    MitigationSettings,
    argus_changed_flag_since,
    can_be_undone,
    fetch_recent_flag_changes,
    flag_changes_over,
    flag_setter_over,
    recent_metrics_over,
    somebody_else_changed_flag_since,
    take_action,
    undo_change,
)
from argus_core import Connections, get_settings
from argus_core.anomaly import AnomalyThresholds
from argus_core.events import Publisher
from argus_core.llm import build_llm_client
from argus_core.mcp_transport import McpClient
from argus_core.replay import Recorder
from argus_incidents import (
    IsStillWanted,
    calls_into,
    events_into,
    events_into_connection,
    wanted_via,
)

from orchestrator.gathering import write_postmortem_for
from orchestrator.records import Records
from orchestrator.sources import the_real_sources
from orchestrator.walk.ports import (
    ActionAlreadyTaken,
    ChangeLanded,
    CompleteAction,
    FetchFlagChanges,
    Investigate,
    ProposeFix,
    RecordAction,
    RecordHypothesis,
    RecordOutcome,
    RecordPostmortem,
    Reversible,
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
    reversible: Reversible
    take: TakeAction
    record_action: RecordAction
    complete_action: CompleteAction
    already_taken: ActionAlreadyTaken
    change_landed: ChangeLanded
    propose_fix: ProposeFix
    write_postmortem: WritePostmortem
    record_postmortem: RecordPostmortem
    transition_incident: TransitionIncident
    publisher: Publisher
    recorder: Recorder
    still_wanted: IsStillWanted
    # How many times one incident may be investigated. On the record
    # rather than read by the graph, because it is a fact about the
    # deployment and `build_graph` is where a walk is assembled, not
    # where configuration is discovered (V7b).
    max_rounds: int


def against(connections: Connections,
            read: McpClient,
            write: McpClient) -> Collaborators:
    """The real ones, for a process that has a database, a model and two tiers.

    Built once where the process starts. Everything derived from `connections`
    is a closure over it rather than an open connection, so assembling a graph
    reaches nothing - a walk is what opens one, when a node actually runs. The
    two clients are the same bargain: each is one session to one server, opened
    by the process that owns it and handed here rather than dialled per call.

    Which tier answers which question is decided here and nowhere else. The read
    client serves every retrieval channel and the verification metrics; the write
    client serves the one write Argus makes and the provider's own history of
    who made it - which lives on the write tier because the provider serves that
    history to admin credentials alone (spec §12.1).
    """
    settings = get_settings()
    mitigation = MitigationSettings.of(settings)
    # Asked of the provider four different ways below, over one connection.
    flag_history = flag_changes_over(write)
    # Whether anybody but Argus has been in since it wrote. Bound once because
    # both the action and the undo it may need consult the same question of the
    # same provider with the same notion of who Argus is.
    outside = partial(
        somebody_else_changed_flag_since, settings=mitigation, fetch=flag_history
    )
    # Where the algorithm draws its lines, read from the deployment and
    # handed to both agents that measure against them. A domain value
    # rather than a slice: `argus_core.anomaly` decides what counts as an
    # incident starting, and that rule has no business reading config.
    thresholds = AnomalyThresholds(
        deviations_from_baseline=settings.anomaly_deviations_from_baseline,
        persistence_minutes=settings.anomaly_persistence_minutes,
        recovery_fraction_of_the_rise=settings.recovery_fraction_of_the_rise
    )
    records = Records(connections, events_into_connection)
    recorder = calls_into(connections)
    # Built once rather than per postmortem: which provider answers which
    # question is a fact about the deployment, and the only thing that differs
    # between two incidents is which incident is being written up.
    sources = the_real_sources(settings, connections, read)

    return Collaborators(
        # Bound here because this is where a deployment's configuration meets
        # the agents it configures. `Collaborators` says nothing is defaulted,
        # and an investigation that read its own budget would be a default in
        # everything but name.
        investigate=partial(
            _investigate,
            settings=InvestigationSettings.of(settings),
            thresholds=thresholds,
            # The three channels, each over the tier that answers it. The change
            # channel takes both, because a deploy and a flag flip are recorded
            # by two systems and the Investigator reads one history.
            fetch_metrics=metrics_over(read),
            fetch_logs=logs_over(read),
            fetch_change_events=changes_over(read, write)
        ),
        record_hypothesis=records.hypothesis,
        # Mitigation's three collaborators, each bound to the configuration
        # this deployment holds. The lookback, the name Argus writes under and
        # the wait for the service are read once, here, rather than by the
        # agent every time it is asked a question.
        fetch_flag_changes=partial(
            fetch_recent_flag_changes, mitigation, flag_history
        ),
        record_outcome=records.outcome,
        # The gate's question, answered by the agent that would have to perform
        # the undo. Bound here rather than imported by the gate, so that the one
        # check standing between a proposal and production is asked of something
        # a test can replace.
        reversible=can_be_undone,
        take=partial(
            take_action,
            settings=mitigation,
            thresholds=thresholds,
            set_state=flag_setter_over(write),
            fetch_metrics=recent_metrics_over(read),
            changed_from_outside=outside,
            undo=partial(
                undo_change,
                changed_from_outside=outside,
                set_state=flag_setter_over(write)
            )
        ),
        record_action=records.claim_action,
        complete_action=records.complete_action,
        already_taken=records.claimed_action,
        change_landed=partial(
            argus_changed_flag_since, settings=mitigation, fetch=flag_history
        ),
        # Both tiers, because proposing a fix is the one act that spans them:
        # the repository is read from the process that cannot write, and the
        # branch and the draft pull request come from the one that can (§13).
        propose_fix=fixes_over(read, write, FixSettings.of(settings), recorder),
        write_postmortem=lambda incident_id: write_postmortem_for(
            incident_id,
            connections=connections,
            sources=sources,
            client_for=build_llm_client,
            recorder=recorder),
        record_postmortem=records.postmortem,
        transition_incident=records.transition,
        publisher=events_into(connections),
        recorder=recorder,
        still_wanted=wanted_via(connections),
        max_rounds=settings.investigation_max_rounds
    )
