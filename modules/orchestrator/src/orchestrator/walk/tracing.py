"""Where a step of the walk becomes a span, and an agent's step names its agent.

Every node the graph runs passes through here, for the reason every node passes
through `with_status`: a property all of them must have is one none of them can
be trusted to remember. Wrapped at registration, so a node added tomorrow is
traced by being registered.

A step that belongs to an agent is the GenAI conventions' `invoke_agent` span,
and leaves the agent's name in the baggage for as long as it runs. That is how a
model call made deep inside the Investigator - by a client built once and
handed around, that was never told whose it is - still says which agent made
it, on its own span and on the metrics it records.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from argus_core.models import Actor
from argus_core.telemetry import (
    ARGUS_AGENT,
    ARGUS_INCIDENT_ID,
    ARGUS_WALK_STEP,
    ERROR_TYPE,
    GEN_AI_AGENT_NAME,
    GEN_AI_INVOKE_AGENT_OPERATION,
    GEN_AI_OPERATION_NAME,
)
from opentelemetry import baggage, context, trace
from opentelemetry.trace import Status, StatusCode, Tracer
from opentelemetry.util.types import AttributeValue

from orchestrator.walk.state import IncidentState

# The instrumentation scope a step's span is reported under.
_SCOPE = __name__


class Step[R](Protocol):
    """A node as the graph registers one: called with the state, by that name.

    Not a bare `Callable`, because LangGraph's own node protocol names its
    parameter `state`, and a callable that promises no name is one it may not
    be able to call by it."""

    def __call__(self, state: IncidentState) -> R: ...


def traced[R](step: str,
              actor: Actor,
              node: Callable[[IncidentState], R],
              tracer: Tracer | None = None) -> Step[R]:
    """Wraps a node so that it runs inside a span of its own.

    `step` is the node's name in the graph and `actor` whose work it is. The
    orchestrator's own steps - proposing, gating, choosing the next candidate,
    remembering - are spans named for the step; every other actor's step is an
    `invoke_agent` span named for the agent, which is the name a reader of a
    trace looks for.

    `tracer` defaults to the process's own, looked up when the step runs
    rather than when the graph is built, so a graph compiled before telemetry
    was started still reports to it.
    """
    is_an_agent = actor is not Actor.ORCHESTRATOR
    name = f"{GEN_AI_INVOKE_AGENT_OPERATION} {actor}" if is_an_agent else step

    def run(state: IncidentState) -> R:
        attributes: dict[str, AttributeValue] = {
            ARGUS_INCIDENT_ID: state.incident_id,
            ARGUS_WALK_STEP: step,
            ARGUS_AGENT: str(actor)
        }

        if is_an_agent:
            attributes[GEN_AI_OPERATION_NAME] = GEN_AI_INVOKE_AGENT_OPERATION
            attributes[GEN_AI_AGENT_NAME] = str(actor)

        stepping = tracer if tracer is not None else trace.get_tracer(_SCOPE)
        named = context.attach(baggage.set_baggage(ARGUS_AGENT, str(actor)))

        try:
            with stepping.start_as_current_span(
                name, attributes=attributes, set_status_on_exception=False
            ) as span:
                try:
                    return node(state)
                except Exception as error:
                    span.set_attribute(ERROR_TYPE, type(error).__name__)
                    span.set_status(Status(StatusCode.ERROR, str(error)))
                    raise
        finally:
            context.detach(named)

    return run
