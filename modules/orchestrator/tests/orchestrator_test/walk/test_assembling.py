"""What a deployment supplies a walk with, and when it is allowed to reach out.

`against` is the only thing in the Orchestrator that knows a database can be
had, so it is the only place a graph could quietly acquire one. Three properties
keep the walk testable without infrastructure, and none is visible from inside a
node: assembling touches nothing, nothing on the record has a default that a
forgetful test could fall through to, and every collaborator bound here is bound
*whole*.

The third is the one no type checker does for us. A collaborator is bound with
`functools.partial`, and a partial that leaves a required keyword unsupplied is
a perfectly well-typed object that raises `TypeError` the first time a node
calls it - which is in the middle of an incident, after the model has been paid
for. So what is asserted below is not that the field is present but that what is
in it can be called with what its caller actually passes.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import MISSING
from typing import Any

import psycopg
import pytest
from argus_core import Connections, get_settings
from argus_core.mcp_transport import McpClient
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from orchestrator.walk.assembling import (
    Collaborators,
    IncidentMemorySettings,
    against,
    the_store_for,
)

NOTHING_IS_SERVED_HERE = "http://127.0.0.1:1/mcp"

# What the mitigation node passes when it performs an action: the action itself,
# and three arguments that carry their own defaults. Everything else `take_action`
# declares has to have been bound at assembly, so anything still required beyond
# this is a collaborator the walk was never given.
WHAT_THE_MITIGATION_NODE_SUPPLIES = frozenset({"action"})

# What puts one change back: the descriptor recording it, and nothing else. Which
# changes to undo and in what order belong to whoever holds the records.
WHAT_AN_UNDO_IS_GIVEN = frozenset({"undo_descriptor"})

# What reads where the rule that paged stands: the rule, and nothing else. The
# connection to the read tier is the binding's.
WHAT_A_RULE_READ_IS_GIVEN = frozenset({"rule"})

# What the investigation node asks the deploy history: which service, and where
# the window ends. The settings and the connection are the binding's.
WHAT_THE_INVESTIGATION_NODE_ASKS = frozenset({"service", "onset"})

# What the investigation node hands the Investigator positionally: the alert and
# the incident. Every channel it reads is the binding's.
WHAT_AN_INVESTIGATION_IS_GIVEN = frozenset({"alert", "incident_id"})


@pytest.mark.unit
def test_assembling_the_collaborators_opens_no_connection() -> None:
    # Everything derived from the connections is a closure over them rather than
    # an open connection - a walk is what opens one, when a node actually runs.
    # A source that refuses to open is both the fixture and the assertion here.
    # No vector store, for the same reason: what a process opened is handed in,
    # so assembling with none is assembling with nothing to reach.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_client_that_must_not_be_reached(),
                              _a_client_that_must_not_be_reached(),
                              None)) \
        .then(_every_collaborator_was_supplied())


@pytest.mark.unit
def test_no_collaborator_may_be_left_out() -> None:
    # A default would be the real Anthropic-backed investigator quietly reached
    # by a test that forgot to name one, and forgetting is what this record
    # exists to make impossible. Asserted against the whole record, so a
    # collaborator added later with a convenient default is caught the day it
    # lands rather than by the run that spends money.
    Scenario() \
        .given(the_record := Collaborators) \
        .when(lambda: [
            field.name for field in dataclasses.fields(the_record)
            if field.default is not MISSING or field.default_factory is not MISSING
        ]) \
        .then(_nothing_is_defaulted())


@pytest.mark.unit
def test_taking_an_action_is_bound_with_every_tool_it_needs() -> None:
    # The failure this exists for is quiet in every way that matters. A new kind
    # of action arrives, the agent grows a keyword-only collaborator for it, the
    # tier and the client and the agent all get their tests - and nobody adds it
    # here. Every gate stays green, because a `functools.partial` missing a
    # required keyword is well-typed until it is called; the walk then dies at
    # the mitigation node, mid-incident.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_client_that_must_not_be_reached(),
                              _a_client_that_must_not_be_reached(),
                              None)) \
        .then(all_of(
            _taking_an_action_needs_only(WHAT_THE_MITIGATION_NODE_SUPPLIES),
            _putting_a_change_back_needs_only(WHAT_AN_UNDO_IS_GIVEN),
            _reading_the_rule_needs_only(WHAT_A_RULE_READ_IS_GIVEN)
        ))


@pytest.mark.unit
def test_the_deploy_history_is_bound_with_everything_but_the_question() -> None:
    # Bound whole for the reason taking an action is. The investigation node asks
    # it about a service and an onset and nothing else, and a partial short of
    # anything more is well-typed until the first round reads it - which is in
    # the middle of an incident, after the model has been paid for.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_client_that_must_not_be_reached(),
                              _a_client_that_must_not_be_reached(),
                              None)) \
        .then(
            _reading_the_deploy_history_needs_only(WHAT_THE_INVESTIGATION_NODE_ASKS)
        )


@pytest.mark.unit
def test_the_investigation_is_bound_with_every_channel_it_reads() -> None:
    # Bound whole for the reason taking an action is. A channel the Investigator
    # gains and nobody binds here leaves a partial one argument short, well-typed
    # until the first round calls it - after the alert has paged and before
    # anything at all was read.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections,
                              _a_client_that_must_not_be_reached(),
                              _a_client_that_must_not_be_reached(),
                              None)) \
        .then(
            _investigating_needs_only(WHAT_AN_INVESTIGATION_IS_GIVEN)
        )


@pytest.mark.unit
def test_a_process_that_keeps_no_memory_says_so_when_it_starts(
    caplog: pytest.LogCaptureFixture
) -> None:
    # A real configuration rather than a failure, and the one setting that makes
    # two otherwise identical runs walk differently - so the log of a run says
    # which of the two it was.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            settings_keeping_no_memory := IncidentMemorySettings.of(
                get_settings().model_copy(update={"incident_memory_enabled": False})
            )
        ) \
        .when(lambda: _what_is_held_inside(the_store_for(settings_keeping_no_memory))) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.assembling", logging.INFO,
                                  "incident memory disabled")
        )


def _what_is_held_inside(held: AbstractContextManager[Any]) -> Any:
    with held as inside:
        return inside


def _a_client_that_must_not_be_reached() -> McpClient:
    """A client to an address nothing serves.

    The parallel of the connections above, and it holds for the same reason: a
    client connects on its first call, so assembling one reaches nothing, and
    anything that asked it a question would fail here rather than quietly find
    a real server.
    """
    return McpClient(NOTHING_IS_SERVED_HERE)


def _connections_that_must_not_be_opened() -> Connections:
    @contextmanager
    def no_connections() -> Generator[psycopg.Connection]:
        raise AssertionError("Assembling must not open a connection.")
        yield  # unreachable, and what makes this a generator

    return no_connections


def _every_collaborator_was_supplied() -> Assertion[Collaborators]:
    """That the record came back whole.

    A frozen dataclass with no defaults cannot be built short, so this is really
    an assertion that `against` returned at all - which, given the source it was
    handed, is the assertion that it reached for nothing.
    """
    def assertion(collaborators: Collaborators) -> bool:
        missing = [field.name for field in dataclasses.fields(collaborators)
                   if getattr(collaborators, field.name) is None]

        if missing:
            raise AssertionError(f"Assembled without {sorted(missing)}")

        return True

    return assertion


def _nothing_is_defaulted() -> Assertion[list[str]]:
    def assertion(defaulted: list[str]) -> bool:
        if defaulted:
            raise AssertionError(
                "Every collaborator must be named at the point of assembly, "
                f"but these default themselves: {sorted(defaulted)}"
            )

        return True

    return assertion


def _taking_an_action_needs_only(supplied: frozenset[str]) -> Assertion[Collaborators]:
    def assertion(collaborators: Collaborators) -> bool:
        _nothing_beyond(supplied, _still_required_of(collaborators.take), "take an action")

        return True

    return assertion


def _putting_a_change_back_needs_only(supplied: frozenset[str]) -> Assertion[Collaborators]:
    """The undo bound *inside* the action, which the check above cannot see.

    Supplying `undo` satisfies `take_action`'s own signature however short the
    undo itself was bound, so the two are separate questions - and the undo's is
    asked on the path a refuted mitigation takes, which is the path nobody
    watches.
    """
    def assertion(collaborators: Collaborators) -> bool:
        undo = getattr(collaborators.take, "keywords", {}).get("undo")

        if undo is None:
            raise AssertionError(
                "Taking an action was bound without an undo, so a refuted "
                "mitigation has nothing to put itself back with."
            )

        _nothing_beyond(supplied, _still_required_of(undo), "put a change back")

        return True

    return assertion


def _reading_the_rule_needs_only(supplied: frozenset[str]) -> Assertion[Collaborators]:
    """The rule reader, which `take_action` defaults to none.

    So the check on the action cannot see it missing: the action is callable
    without it, and an incident paged by a series alert is then judged by the
    levels rather than by the rule that paged - a wrong verdict, not a
    `TypeError`, and so the quieter of the two.
    """
    def assertion(collaborators: Collaborators) -> bool:
        read_rule = getattr(collaborators.take, "keywords", {}).get("read_rule")

        if read_rule is None:
            raise AssertionError(
                "Taking an action was bound without a way to read the alert "
                "rule, so a mitigation on a series alert is judged by the "
                "levels rather than by the rule that paged."
            )

        _nothing_beyond(supplied, _still_required_of(read_rule), "read the rule that paged")

        return True

    return assertion


def _reading_the_deploy_history_needs_only(
    supplied: frozenset[str]
) -> Assertion[Collaborators]:
    def assertion(collaborators: Collaborators) -> bool:
        _nothing_beyond(
            supplied,
            _still_required_of(collaborators.fetch_deployments),
            "read what was deployed"
        )

        return True

    return assertion


def _investigating_needs_only(supplied: frozenset[str]) -> Assertion[Collaborators]:
    def assertion(collaborators: Collaborators) -> bool:
        _nothing_beyond(
            supplied,
            _still_required_of(collaborators.investigate),
            "investigate"
        )

        return True

    return assertion


def _still_required_of(call: Callable[..., Any]) -> set[str]:
    """Every parameter the call has left, after whatever was bound into it.

    `inspect.signature` resolves a partial's bound keywords into defaults, so
    what comes back here is exactly what a caller would still have to pass -
    which is the question being asked.
    """
    return {
        name for name, parameter in inspect.signature(call).parameters.items()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind not in (
            inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD
        )
    }


def _nothing_beyond(supplied: frozenset[str], required: set[str], what: str) -> None:
    unbound = required - supplied

    if unbound:
        raise AssertionError(
            f"Assembling left {sorted(unbound)} unbound, so the walk would "
            f"raise TypeError the first time it tried to {what} - and every "
            f"gate would pass until it did."
        )
