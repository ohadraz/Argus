"""Every step of the walk as a span, and an agent's step naming its agent.

The wrapper every node is registered through, for the reason `with_status` is
one: a property all of them must have is one none of them can be trusted to
remember. What it gives a trace is the walk's shape - one span per step, in the
walk's own trace - and what it gives everything beneath a step is the agent's
name, in the baggage, where a model client that was never told whose it is can
read it.

The nodes here are stand-ins that report what they could see while they ran:
the span current inside them and the baggage around them. That is the whole of
what the wrapper promises a node.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_core.models import Actor, Alert, IncidentStatus
from argus_core.telemetry import (
    ARGUS_AGENT,
    ARGUS_INCIDENT_ID,
    ARGUS_WALK_STEP,
    ERROR_TYPE,
    GEN_AI_AGENT_NAME,
)
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    attempting,
    the_answer_was,
    the_same_error_reached_the_caller,
)
from opentelemetry import baggage, trace
from opentelemetry.trace import StatusCode
from orchestrator.walk.state import IncidentState
from orchestrator.walk.tracing import traced

from orchestrator_test.framework.builders import an_incident_state
from orchestrator_test.framework.observing import Observed, observing

DONT_CARE_ALERT = Alert(service="kuki", alert_name="HighErrorRate")
SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"


@pytest.mark.unit
def test_an_agents_step_is_a_span_named_for_the_agent() -> None:
    # The GenAI conventions' agent span, `invoke_agent {agent}`, carrying the
    # incident it worked on and the step of the walk it was.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: traced("investigator", Actor.INVESTIGATOR, _a_node_that_does_nothing,
                           tracer=observed.tracer)(_a_state())
        ) \
        .then(
            _the_step_span_is(observed, named="invoke_agent investigator", carrying={
                ARGUS_INCIDENT_ID: SOME_INCIDENT_ID,
                ARGUS_WALK_STEP: "investigator",
                ARGUS_AGENT: "investigator",
                GEN_AI_AGENT_NAME: "investigator"
            })
        )


@pytest.mark.unit
def test_an_orchestrator_step_is_a_span_named_for_the_step() -> None:
    # Proposing, gating, choosing the next candidate are the walk's own steps,
    # not an agent's - named for what they are, since four spans all called
    # "the orchestrator" would tell a reader of the trace nothing.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: traced("tier_gate", Actor.ORCHESTRATOR, _a_node_that_does_nothing,
                           tracer=observed.tracer)(_a_state())
        ) \
        .then(
            _the_step_span_is(observed, named="tier_gate", carrying={
                ARGUS_WALK_STEP: "tier_gate",
                ARGUS_AGENT: "orchestrator"
            })
        )


@pytest.mark.unit
def test_an_agents_step_names_its_agent_to_everything_it_calls() -> None:
    # A model client is built once and handed around. What it reads to say
    # whose call it made is the baggage, so the agent's name has to be there
    # while the step runs.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: traced("investigator", Actor.INVESTIGATOR, _a_node_reading_the_agent,
                           tracer=observed.tracer)(_a_state())
        ) \
        .then(
            the_answer_was("investigator")
        )


@pytest.mark.unit
def test_a_steps_work_runs_inside_its_span() -> None:
    # What makes a model call or a tool call made by the step a child of it,
    # rather than a sibling of the whole walk.
    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            lambda: traced("investigator", Actor.INVESTIGATOR, _a_node_reading_its_span,
                           tracer=observed.tracer)(_a_state())
        ) \
        .then(
            _the_work_ran_inside_the_step(observed)
        )


@pytest.mark.unit
def test_a_step_that_failed_is_an_error_span_and_fails_as_it_did() -> None:
    some_failure = RuntimeError("the read tier did not answer")

    Scenario() \
        .given(
            observed := observing()
        ) \
        .when(
            attempting(
                lambda: traced("mitigation", Actor.MITIGATION, _a_node_raising(some_failure),
                               tracer=observed.tracer)(_a_state())
            )
        ) \
        .then(
            all_of(
                the_same_error_reached_the_caller(some_failure),
                _the_step_failed_with(observed, "RuntimeError")
            )
        )


def _a_state() -> IncidentState:
    return an_incident_state(DONT_CARE_ALERT, IncidentStatus.INVESTIGATING,
                             incident_id=SOME_INCIDENT_ID)


def _a_node_that_does_nothing(_state: IncidentState) -> None:
    return None


def _a_node_reading_the_agent(_state: IncidentState) -> object:
    return baggage.get_baggage(ARGUS_AGENT)


def _a_node_reading_its_span(_state: IncidentState) -> int:
    return trace.get_current_span().get_span_context().span_id


def _a_node_raising(failure: Exception) -> Any:
    def node(_state: IncidentState) -> None:
        raise failure

    return node


def _the_step_span_is(observed: Observed,
                      named: str,
                      carrying: dict[str, str]) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        span = observed.only_span()
        carried = dict(span.attributes or {})
        wrong = {key: (wanted, carried.get(key))
                 for key, wanted in carrying.items() if carried.get(key) != wanted}

        if span.name != named or wrong:
            raise AssertionError(
                f"Expected a span named [{named}] carrying {carrying}, got [{span.name}] "
                f"where {wrong} differed (expected, got)."
            )

        return True

    return assertion


def _the_work_ran_inside_the_step(observed: Observed) -> Assertion[int]:
    def assertion(span_id_seen_by_the_work: int) -> bool:
        step = observed.only_span().get_span_context()

        if step is None or span_id_seen_by_the_work != step.span_id:
            raise AssertionError(
                f"Expected the step's work to run inside the step's span "
                f"[{step.span_id if step is not None else None}], and it ran inside "
                f"[{span_id_seen_by_the_work}]."
            )

        return True

    return assertion


def _the_step_failed_with(observed: Observed, error_type: str) -> Assertion[Exception | None]:
    def assertion(_raised: Exception | None) -> bool:
        span = observed.only_span()
        said = (span.status.status_code, (span.attributes or {}).get(ERROR_TYPE))

        if said != (StatusCode.ERROR, error_type):
            raise AssertionError(
                f"Expected the step's span to have failed with [{error_type}], and it said {said}."
            )

        return True

    return assertion
