from __future__ import annotations

from collections.abc import Callable
from typing import Any

from argus_testkit.assertions import Assertion

type Step = Callable[[], Any] | Any


class Scenario:
    """A given/when/then wrapper that keeps a test's three phases visible.

    A step may be a callable or an already-evaluated value - call sites
    commonly use the walrus operator to bind a result and pass it in one
    expression, which evaluates eagerly, so both forms have to work.

    `then` receives whatever `when` produced. An assertion that needs
    something else (a database connection, say) may bind it with
    `functools.partial` at the call site, rather than the scenario carrying
    per-suite context.
    """

    def __init__(self) -> None:
        self.result: Any = None

    def given(self, *steps: Step) -> Scenario:
        for step in steps:
            _run(step)

        return self

    def when(self, step: Step) -> Scenario:
        self.result = _run(step)

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


def _run(step: Step) -> Any:
    return step() if callable(step) else step
