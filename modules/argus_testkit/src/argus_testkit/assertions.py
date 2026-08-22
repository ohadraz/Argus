from __future__ import annotations

import time
from collections.abc import Callable

POLL_INTERVAL_SECONDS = 0.5
POLL_TIMEOUT_SECONDS = 30

type Assertion[T] = Callable[[T], bool]


def all_of[T](*assertions: Assertion[T]) -> Assertion[T]:
    """Combines assertions so a failing one doesn't hide the ones after it.

    Every assertion runs even once one has failed, and all their messages are
    reported together - a test that checks four things about a result should
    tell you which three passed, not stop at the first.
    """

    def combined_assertion(result: T) -> bool:
        failures = []

        for assertion in assertions:
            try:
                assertion(result)
            except AssertionError as assertion_error:
                failures.append(str(assertion_error))

        if failures:
            raise AssertionError("One or more assertions failed:\n" + "\n".join(failures))

        return True

    return combined_assertion


def eventually[T](assertion: Assertion[T],
                  timeout: float = POLL_TIMEOUT_SECONDS,
                  interval: float = POLL_INTERVAL_SECONDS) -> Assertion[T]:
    """Retries an assertion until it passes or the timeout expires.

    For asserting on a system that reaches the expected state a moment after
    the action that triggers it - an async pipeline, a background worker - so
    a test doesn't have to guess at a sleep long enough to be reliable and
    short enough not to hurt. Raises `TimeoutError` chained to the last
    `AssertionError`, so the failure message says what was still wrong when
    time ran out, not merely that time ran out.
    """

    def eventually_assertion(result: T) -> bool:
        deadline = time.monotonic() + timeout
        last_error: AssertionError | None = None

        while True:
            try:
                assertion(result)
                return True
            except AssertionError as assertion_error:
                last_error = assertion_error

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Condition did not become true within {timeout:.1f}s."
                ) from last_error

            time.sleep(interval)

    return eventually_assertion
