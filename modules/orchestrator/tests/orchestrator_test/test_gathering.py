"""What a write-up reads its incident at, unless told otherwise.

What is gathered, and from where, is `component/test_gathering.py`'s - where
each case hands in a moment of its own to see that it was used. This holds the
one thing those cases cannot: that a caller who hands in nothing reads at one
moment.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario
from orchestrator.gathering import write_postmortem_for, write_synopsis_for
from postgres import at_one_moment

# The parameter a write-up is handed its moment by.
READING_AT = "reading_at"


@pytest.mark.unit
@pytest.mark.parametrize("write_up", [write_postmortem_for, write_synopsis_for])
def test_a_write_up_reads_at_one_moment_unless_handed_another(
    write_up: Callable[..., Any]
) -> None:
    Scenario() \
        .when(
            lambda: inspect.signature(write_up).parameters[READING_AT].default
        ) \
        .then(
            _it_is(at_one_moment)
        )


def _it_is(expected: object) -> Assertion[object]:
    def assertion(found: object) -> bool:
        if found is not expected:
            raise AssertionError(
                f"Expected a write-up to read at {expected} unless handed another, and "
                f"it reads at {found}."
            )

        return True

    return assertion
