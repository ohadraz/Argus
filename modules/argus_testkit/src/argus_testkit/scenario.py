from __future__ import annotations

from collections.abc import Callable
from typing import Any

from argus_testkit.assertions import Assertion


class Scenario:
    """A given/when/then wrapper that keeps a test's three phases visible.

    The two phases take different things, and the difference is the point.
    `given` takes values - the world the test starts in, already built, since a
    call site binds each one with the walrus operator and that evaluates before
    the scenario ever sees it. `when` takes the callable that does the thing
    under test, because deferring it is what lets the three phases be written in
    order.

    A `given` step is a value unless it is wrapped in `calling(...)`, which is
    the caller saying it is setup to run. Inferring it was the old behaviour and
    the reason for this one: a mock, a bound method or the function under test
    is callable and is an ordinary thing to state as `given`, and each was
    silently invoked with no arguments as the test began. The failure landed in
    the scenario rather than in the test, and said nothing about either.

    `then` receives whatever `when` produced. An assertion that needs
    something else (a database connection, say) may bind it with
    `functools.partial` at the call site, rather than the scenario carrying
    per-suite context.
    """

    def __init__(self) -> None:
        self.result: Any = None

    def given(self, *world: Any) -> Scenario:
        """The state the test starts in.

        Values are taken and left alone - they were built by the expressions
        that produced them, and naming them here is what makes the phase
        visible. A `calling(...)` step is run, for setup that is a call with
        no result to bind.
        """
        for step in world:
            if isinstance(step, _Calling):
                step.run()

        return self

    def when(self, action: Callable[[], Any]) -> Scenario:
        self.result = action()

        return self

    def then(self, *assertions: Assertion[Any]) -> Scenario:
        """Runs each assertion against what `when` produced.

        An assertion is expected to raise `AssertionError` with its own
        message; one that merely returns False has none to report, so the
        failure is identified by position and by the closure's `repr`, which
        carries the defining module and line.
        """
        for position, assertion in enumerate(assertions, start=1):
            if not assertion(self.result):
                raise AssertionError(
                    f"'THEN' assertion #{position} of {len(assertions)} "
                    f"returned False: {assertion!r}"
                )

        return self


def calling(step: Callable[[], Any]) -> _Calling:
    """Marks a `given` step as setup to run, rather than a value to state.

    `given` takes values, because a call site binds each one with the walrus
    operator and that has already evaluated. Some setup is a call with nothing
    to bind, though - a counter advanced, a row written - and this is how a
    caller says so.

    Explicit rather than inferred. `given` used to run whatever was callable,
    which silently invoked any mock, bound method or function the test had set
    up, with no arguments, before the test began. Nothing in a value says
    whether it is meant to be called; only the caller knows.
    """
    return _Calling(step)


def attempting(step: Callable[[], Any]) -> Callable[[], Exception | None]:
    """Turns a step expected to fail into one that yields its failure.

    `when` hands its result to `then`, so an exception escaping `when` never
    reaches an assertion. Catching here rather than inside `Scenario` keeps it
    opt-in: a scenario whose `when` was not supposed to fail still reports the
    real traceback, not an assertion message three lines later.

    Returns `None` when the step unexpectedly succeeded, which
    `an_error_was_raised` reports as the failure it is.
    """
    def attempt() -> Exception | None:
        try:
            step()
        except Exception as error:
            return error

        return None

    return attempt


class _Calling:
    """A `given` step that is a call to make, not a value to state."""

    def __init__(self, step: Callable[[], Any]) -> None:
        self.step = step

    def run(self) -> None:
        self.step()
