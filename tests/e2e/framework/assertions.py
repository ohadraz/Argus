import time
from collections.abc import Callable
from typing import TypeVar

POLL_INTERVAL_SECONDS = 0.5
POLL_TIMEOUT_SECONDS = 30

T = TypeVar("T")

Assertion = Callable[[T], bool]


def all_of[T](*assertions: Assertion[T]) -> Assertion[T]:
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
    def eventually_assertion(result: T) -> bool:
        deadline = time.monotonic() + timeout
        last_error: AssertionError | None = None

        while True:
            try:
                assertion(result)
                return True
            except AssertionError as e:
                last_error = e

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Condition did not become true within {timeout:.1f}s."
                ) from last_error

            time.sleep(interval)

    return eventually_assertion