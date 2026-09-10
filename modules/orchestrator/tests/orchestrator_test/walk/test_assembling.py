from __future__ import annotations

import dataclasses
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import MISSING

import psycopg
import pytest
from argus_core.db import Connections
from argus_testkit import Assertion, Scenario
from orchestrator.walk.assembling import Collaborators, against

"""What a deployment supplies a walk with, and when it is allowed to reach out.

`against` is the only thing in the Orchestrator that knows a database can be
had, so it is the only place a graph could quietly acquire one. Two properties
keep the walk testable without infrastructure, and neither is visible from
inside a node: assembling touches nothing, and nothing on the record has a
default that a forgetful test could fall through to.
"""


@pytest.mark.unit
def test_assembling_the_collaborators_opens_no_connection() -> None:
    # Everything derived from the connections is a closure over them rather than
    # an open connection - a walk is what opens one, when a node actually runs.
    # A source that refuses to open is both the fixture and the assertion here.
    Scenario() \
        .given(no_connections := _connections_that_must_not_be_opened()) \
        .when(lambda: against(no_connections)) \
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


def _connections_that_must_not_be_opened() -> Connections:
    @contextmanager
    def no_connections() -> Generator[psycopg.Connection]:
        raise AssertionError("assembling must not open a connection")
        yield  # pragma: no cover - unreachable, and what makes this a generator

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
            raise AssertionError(f"assembled without {sorted(missing)}")

        return True

    return assertion


def _nothing_is_defaulted() -> Assertion[list[str]]:
    def assertion(defaulted: list[str]) -> bool:
        if defaulted:
            raise AssertionError(
                "every collaborator must be named at the point of assembly, "
                f"but these default themselves: {sorted(defaulted)}"
            )

        return True

    return assertion
