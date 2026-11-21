"""Everything a walk is supplied with, and that none of it supplies itself.

The record is the walk's whole contract with the process running it, so what it
must never do is fill a gap on its own: a collaborator a test forgot to name
would be one the record quietly reached for, and the real one is the
Anthropic-backed investigator.
"""

from __future__ import annotations

import dataclasses
from dataclasses import MISSING

import pytest
from argus_testkit import Assertion, Scenario
from orchestrator.walk.collaborators import Collaborators


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


def _nothing_is_defaulted() -> Assertion[list[str]]:
    def assertion(defaulted: list[str]) -> bool:
        if defaulted:
            raise AssertionError(
                "Every collaborator must be named at the point of assembly, "
                f"but these default themselves: {sorted(defaulted)}"
            )

        return True

    return assertion
