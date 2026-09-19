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

import logging
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

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
from argus_core import Connections, Settings, get_settings
from argus_core.anomaly import AnomalyThresholds
from argus_core.embedding import an_embedder
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
from incident_memory.records import RememberedIncident

from orchestrator.gathering import write_postmortem_for
from orchestrator.records import Records
from orchestrator.sources import the_real_sources
from orchestrator.walk.ports import (
    ActionAlreadyTaken,
    ActionsTaken,
    ChangeLanded,
    CompleteAction,
    FetchFlagChanges,
    Investigate,
    ProposeFix,
    RecallSimilar,
    RecordAction,
    RecordHypothesis,
    RecordOutcome,
    RecordPostmortem,
    RememberIncident,
    Reversible,
    TakeAction,
    TransitionIncident,
    WritePostmortem,
)

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

_logger = logging.getLogger(__name__)


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
    actions_taken: ActionsTaken
    recall_similar: RecallSimilar
    remember_incident: RememberIncident
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


@contextmanager
def the_store_for(settings: Settings) -> Generator[QdrantClient | None]:
    """The one vector store a process holds, for as long as it runs. Or none.

    Opened where a process starts and closed when it stops, beside the pool and
    the two MCP sessions - because that is what it is: a session to a server,
    and a resource with two openers and no closer is the one nobody owns.

    `None` where this deployment keeps no long-term memory, which is a real
    configuration rather than a switched-off feature (§21 asks what memory is
    worth, and two runs differing in exactly one thing are how that is asked).
    Read here rather than by the factories below, so that whether there is a
    store to speak of is settled once, by the process, before a graph exists.

    Not a `with` around the client itself: `QdrantClient` closes but is not a
    context manager, which is the same bargain `code_index`'s reconciler makes.
    """
    if not settings.incident_memory_enabled:
        yield None

        return

    from qdrant_client import QdrantClient

    store = QdrantClient(url=settings.qdrant_url)

    try:
        yield store
    finally:
        store.close()


def against(connections: Connections,
            read: McpClient,
            write: McpClient,
            store: QdrantClient | None) -> Collaborators:
    """The real ones, for a process that has a database, a model and two tiers.

    Built once where the process starts. Everything derived from `connections`
    is a closure over it rather than an open connection, so assembling a graph
    reaches nothing - a walk is what opens one, when a node actually runs. The
    two clients are the same bargain: each is one session to one server, opened
    by the process that owns it and handed here rather than dialled per call.
    So is the store, which both memory factories are handed rather than each
    opening one: `None` there says this process remembers nothing.

    Being handed the store is what keeps a test off the network, and not only
    tidy. Constructing a `QdrantClient` starts a daemon thread that asks the
    configured address for its version, and every failure of that thread is
    swallowed into a warning - so a unit test that built one reached out, and
    reached out silently. Passing `None`, or a double, is the only way that
    does not happen, and it is available only because nothing here constructs
    a client.

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
        actions_taken=records.actions_taken,
        recall_similar=_recalling(settings, store),
        remember_incident=_remembering(settings, store),
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


def _recalling(settings: Settings, store: QdrantClient | None) -> RecallSimilar:
    """What earlier incidents this one resembles, or nothing at all.

    Nothing where the process holds no store, and nothing where the store
    cannot answer. The two are the same answer on purpose: every decision
    recall informs has an answer without it, and an incident that stalled
    because a cache of old incidents was unreachable would be a worse system
    than one with no memory.

    Deliberately every exception. What can go wrong is a store that is down, a
    collection that does not exist yet, or a model that will not load, and none
    of them is a fact about the incident in front of the walk.
    """
    if store is None:
        return lambda dont_care_description, dont_care_service: []

    from incident_memory.keeping import recalling_from

    recall = recalling_from(
        store,
        settings.incident_memory_collection,
        an_embedder(settings.incident_memory_embedding_model),
        limit=settings.incident_memory_recall_limit,
        floor=settings.incident_memory_similarity_floor
    )

    def recall_what_it_can(described_as: str, service: str) -> list[RememberedIncident]:
        try:
            return recall(described_as, service)
        except Exception:
            _logger.warning("long-term memory could not be searched", exc_info=True)

            return []

    return recall_what_it_can


def _remembering(settings: Settings, store: QdrantClient | None) -> RememberIncident:
    """Where a finished incident's record goes, or nowhere.

    Nowhere is a real configuration rather than a way of switching off something
    broken - the process opened no store, and the node above cannot tell that
    from one that was written to.

    The model is built here, once, for the reason every other collaborator is:
    a walk is not where a process discovers its configuration, and loading an
    ONNX runtime per incident would be paying for the model at exactly the
    wrong moment. It is loaded lazily and cached on its name, so naming it
    here and in `_recalling` is one model, not two.
    """
    if store is None:
        return lambda dont_care_record: None

    from incident_memory.keeping import kept_in

    return kept_in(
        store,
        settings.incident_memory_collection,
        an_embedder(settings.incident_memory_embedding_model)
    )
