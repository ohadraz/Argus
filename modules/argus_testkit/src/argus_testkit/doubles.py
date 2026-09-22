"""Stand-ins that do nothing, and stand-ins that refuse to be called.

The third kind of test support here, beside `assertions` and `collecting`: a
collaborator a test has to supply but does not want to happen. A wait nobody
spends, a factory that must never be reached.

Domain-free like the rest of this package. What is being stood in for is a
shape - something callable that returns nothing, something callable at all -
and none of that is any particular system's business.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

from argus_testkit.collecting import Kept


def dont_care_sleep(seconds: float) -> None:
    """A wait that returns at once, for a loop whose timing is not under test.

    Injected where production would sleep, so a test of what a poll *does* does
    not also pay for how long it waits between looks. A test that is about the
    waiting passes something that records instead.
    """
    return None


def a_factory_that_must_not_be_called(kept: Kept[bool]) -> Any:
    """A factory that records having been reached, then refuses.

    Both halves matter. Raising alone would fail the test at the call site with
    a stack trace about the double; recording alone would let the run continue
    into whatever the factory was supposed to produce. Together the test can
    assert `nothing_was_collected(kept)` and report the thing it actually cares
    about - that nobody asked - rather than the crash.
    """
    def factory(*dont_care_args: Any, **dont_care_kwargs: Any) -> Any:
        kept.take(True)

        raise AssertionError("A factory that must not be called was called.")

    return factory


def returning(double: Mock, value: object) -> Callable[[], None]:
    """A `given` step that fixes what a stand-in answers with.

    A step rather than the assignment itself, so that arranging a double reads
    the same way as every other `given` in a scenario. Written six times across
    two modules before it was written once here.
    """
    def step() -> None:
        double.return_value = value

    return step


def raising(double: Mock, error: Exception) -> Callable[[], None]:
    """A `given` step that fixes what a stand-in fails with.

    The other half of `returning`, and the one worth having beside it: a test
    that arranges an answer and a test that arranges a failure are the same
    scenario with one line different, and they should look it.
    """
    def step() -> None:
        double.side_effect = error

    return step
