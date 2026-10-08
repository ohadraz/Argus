"""How an incident is walked. Starting one is `argus_incidents.intake`.

The two live apart because importing this builds the graph and everything
under it: a process that can reach here can run an investigation, and the
process receiving alerts must not be able to. Nothing about a run depends on
the connection the alert arrived on, which is what makes an investigation
survive a gateway timeout - and what makes the checkpointer worth having, since
a run nobody is holding can be picked up by whoever comes next.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from argus_core import Connections, get_settings
from argus_core.events import StatusChanged
from argus_core.mcp_transport import McpClient
from argus_core.models import Alert, IncidentStatus
from argus_core.telemetry import (
    ARGUS_INCIDENT_ID,
    ARGUS_INCIDENT_OUTCOME,
    ARGUS_INCIDENT_WALK_DURATION,
    ARGUS_INCIDENT_WALKS,
    ERROR_TYPE,
    UNIT_SECONDS,
    UNIT_WALKS,
)
from argus_incidents import events_into_connection, publish_beside
from argus_incidents.repository import incidents
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph.state import CompiledStateGraph
from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.trace import Status, StatusCode, Tracer

from orchestrator.walk.assembling import against
from orchestrator.walk.graph import build_graph, recursion_limit
from orchestrator.walk.state import IncidentState

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

# Where the graph a walk runs on comes from. A parameter rather than a global
# reached through: the thread a resumed run continues on is the whole of what
# makes a resume a resume, and it is not assertable through a module-level
# builder that wants a database, a checkpointer and a model behind it.
type GraphOf = Callable[[], CompiledStateGraph[IncidentState]]

# Reading the clock a walk's duration is measured on, so a test can hand over
# one that reads exactly what it says.
type Clock = Callable[[], float]

# What one walk is called in a trace: the root every step of it hangs from.
WALK_SPAN: Final = "walk"

# How a walk ended when it did not end at all - it raised, and the worker marks
# the run failed. Not an incident status: the incident is wherever the walk left
# it, and what the measurement is about is the walk.
WALK_FAILED_OUTCOME: Final = "failed"

# The instrumentation scope a walk's span and measurements are reported under.
_SCOPE = __name__


def graph_for(connections: Connections,
              read: McpClient,
              write: McpClient,
              store: QdrantClient | None) -> GraphOf:
    """The compiled graph, built once for the process that asks and kept.

    Built lazily and held, because compiling it sets up a checkpointer and the
    whole node wiring, and a walk should not pay for that on every run. Held by
    the closure rather than at module level, so two processes - or a suite and
    the application inside it - are two graphs against two sets of connections
    rather than one that whichever ran first got to decide.

    The three clients are passed through rather than built here, for the same
    reason `connections` is: what this function owns is when the graph is
    compiled, not what the process it belongs to has opened.

    The checkpointer's context manager is kept alongside the graph deliberately:
    it owns the connection the checkpointer writes on, and letting it be
    collected would close that out from under the compiled graph.
    """
    graph: CompiledStateGraph[IncidentState] | None = None
    checkpointer_cm: object | None = None

    def compiled() -> CompiledStateGraph[IncidentState]:
        nonlocal graph, checkpointer_cm

        if graph is None:
            checkpointer_cm = PostgresSaver.from_conn_string(
                get_settings().database_url
            )
            checkpointer = checkpointer_cm.__enter__()
            checkpointer.setup()
            graph = build_graph(
                checkpointer, against(connections, read, write, store)
            )

        return graph

    return compiled


def run_incident(incident_id: str,
                 connections: Connections,
                 graph_of: GraphOf,
                 tracer: Tracer | None = None,
                 meter: Meter | None = None,
                 clock: Clock = time.monotonic) -> None:
    """Walks one incident's graph to whatever end it reaches.

    Called by the worker that claimed the run, never by the alert endpoint.
    The alert is read back from the incident rather than carried alongside the
    run: it is already recorded there, and a second copy travelling with the
    run would be a second version of the same fact to keep in step.

    Invoked on the incident's own id as the thread, so a run taken up after
    its worker stopped resumes against what the checkpointer already holds
    instead of walking the incident a second time.

    `graph_of` is a parameter so that which thread a walk resumes on can be
    asserted without a model, an MCP server or a real checkpointer behind it -
    the one property of this function that a test has any business pinning.

    The walk is one trace. Its span is the root every step's span hangs from,
    opened around the graph rather than inside it so that what the graph does
    before its first node - and a failure that never reached one - is inside it
    too. Counted and timed by how the incident ended. `tracer` and `meter`
    default to the process's own, no-ops until telemetry is started.
    """
    with connections() as conn:
        incident = incidents.get(conn, incident_id)

    if incident is None:
        raise LookupError(f"no incident [{incident_id}] to run")

    # The first thing a walk does, before any node runs: the incident stops
    # being one nobody is on. Written here rather than by a node, because a
    # node's status is derived from the work it did (`status_after`) and this
    # one is derived from the fact that work has started at all.
    #
    # Idempotent by way of the status it writes: a resumed run re-announces an
    # investigation that is already under way, which is true again each time it
    # is taken up.
    #
    # Not said where the row refused it. A withdrawal can land between the
    # worker asking and this write, and then the incident stays withdrawn - an
    # account announcing an investigation of it would contradict the row. The
    # walk is still invoked, and its first node hears the withdrawal and stops.
    with connections() as conn:
        taken_up = incidents.transition(conn, incident_id, IncidentStatus.INVESTIGATING)

        if taken_up:
            # Beside the status, on the same connection, for the reason every
            # other transition publishes beside its own: this is the only
            # account there is, and a walk that started without saying so
            # leaves a reader looking at an incident that was acknowledged and
            # then simply changed.
            publish_beside(
                conn,
                StatusChanged(
                    incident_id=incident_id,
                    to_status=IncidentStatus.INVESTIGATING,
                    detail="a worker took the incident up"
                ),
                events_into_connection(conn)
            )

    settings = get_settings()
    initial_state = IncidentState(
        incident_id=incident_id,
        alert=Alert.model_validate(incident.alert_payload),
        status=IncidentStatus.INVESTIGATING,
    )
    measured_by = meter if meter is not None else metrics.get_meter(_SCOPE)
    walks = measured_by.create_counter(
        ARGUS_INCIDENT_WALKS, unit=UNIT_WALKS,
        description="Walks that ran to an end, by how the incident ended."
    )
    walk_duration = measured_by.create_histogram(
        ARGUS_INCIDENT_WALK_DURATION, unit=UNIT_SECONDS,
        description="How long a walk took, by how the incident ended."
    )
    walking = tracer if tracer is not None else trace.get_tracer(_SCOPE)

    with walking.start_as_current_span(
        WALK_SPAN,
        attributes={ARGUS_INCIDENT_ID: incident_id},
        set_status_on_exception=False
    ) as span:
        started_at = clock()
        logger.info("walk started")

        try:
            ended = graph_of().invoke(
                initial_state,
                config={
                    "configurable": {"thread_id": incident_id},
                    # The walk is a real cycle in the graph, so the default
                    # budget of 25 traversals is one an ordinary incident can
                    # exhaust. Derived from the settings that bound the walk,
                    # never guessed.
                    "recursion_limit": recursion_limit(
                        settings.investigation_max_rounds,
                        settings.investigation_max_candidates,
                    ),
                },
            )
        except Exception as error:
            span.set_attribute(ERROR_TYPE, type(error).__name__)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            _measured(walks, walk_duration, clock() - started_at, WALK_FAILED_OUTCOME)
            raise

        outcome = _how_it_ended(ended)
        walked = clock() - started_at
        span.set_attribute(ARGUS_INCIDENT_OUTCOME, outcome)
        _measured(walks, walk_duration, walked, outcome)
        logger.info("walk ended", extra={"outcome": outcome, "duration_s": walked})


def _how_it_ended(ended: Any) -> str:
    """The status the walk left the incident in, as LangGraph hands the state back.

    A mapping of the state's fields rather than an `IncidentState` - that is
    what `invoke` returns for a Pydantic state.
    """
    return str(ended["status"])


def _measured(walks: Counter, duration: Histogram, seconds: float, outcome: str) -> None:
    labelled = {ARGUS_INCIDENT_OUTCOME: outcome}
    walks.add(1, labelled)
    duration.record(seconds, labelled)
