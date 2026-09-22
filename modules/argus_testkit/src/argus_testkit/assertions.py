from __future__ import annotations

import time
from collections.abc import Callable

from argus_testkit.collecting import Kept

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


def an_error_was_raised(expected_type: type[Exception]) -> Assertion[Exception | None]:
    """Subclasses count. An error taxonomy exists so a caller can catch a 
    family, and a test naming the base should accept any member of it.
    """
    def assertion(error: Exception | None) -> bool:
        if error is None:
            raise AssertionError(
                f"Expected [{expected_type.__name__}] to be raised, but nothing was."
            )

        if not isinstance(error, expected_type):
            raise AssertionError(
                f"Expected [{expected_type.__name__}], got [{type(error).__name__}]: [{error}]."
            )

        return True

    return assertion


def the_error_mentioned(wanted: str) -> Assertion[Exception | None]:
    """Asserts that the error raised named `wanted` somewhere in its message.

    Paired with `an_error_was_raised` rather than replacing it. A type on its
    own cannot tell one rule from another wherever a family of rules raises
    the same exception - a validation library raises one class for every field
    it refuses - so a test naming only the type goes on passing through the
    change that made it meaningless.

    A substring rather than an equality, because the wording around the name
    belongs to whoever raised it and may be reworded tomorrow. What a test is
    entitled to rely on is that the subject was named at all.
    """
    def assertion(error: Exception | None) -> bool:
        if error is None:
            raise AssertionError(
                f"Expected an error mentioning [{wanted}], but nothing was raised."
            )

        if wanted not in str(error):
            raise AssertionError(f"Expected the error to mention [{wanted}], got [{error}].")

        return True

    return assertion


def the_answer_was[T](expected: T) -> Assertion[T]:
    """Asserts that what came back equals `expected`.

    The plainest assertion there is, and worth naming once rather than
    rewriting per file: a suite that spells equality afresh each time ends up
    with a dozen near-identical helpers whose failure messages all differ, so
    the same failure reads differently depending on which file found it.

    Equality rather than identity, because most results are values. Where a
    test means "the very object I passed in", it means `is`, and that is a
    different claim with a different message - see
    `the_same_error_reached_the_caller` for the case that comes up most.
    """
    def assertion(answered: T) -> bool:
        if answered != expected:
            raise AssertionError(f"Expected [{expected!r}], got [{answered!r}].")

        return True

    return assertion


def the_same_error_reached_the_caller(failure: Exception) -> Assertion[Exception | None]:
    """Asserts that the very exception raised below arrived above untouched.

    Identity, not equality, and not merely type: two exceptions of one class
    carrying different messages compare equal on neither, but a decorator that
    caught one and raised a fresh one of the same class would pass a check
    written with `an_error_was_raised`. What is being claimed here is that
    nothing in between reshaped it - which is what lets the caller above
    distinguish the failures it has to act on differently.
    """
    def assertion(raised: Exception | None) -> bool:
        if raised is not failure:
            raise AssertionError(
                f"Expected [{failure!r}] to reach the caller, got [{raised!r}]."
            )

        return True

    return assertion


def nothing_was_collected[T](kept: Kept[T]) -> Assertion[object]:
    """Asserts that a collaborator standing by was never called.

    The negative half of what `Kept` is for. It takes the collector rather than
    the result, because the claim is about what did *not* happen on the way to
    the result - a credential-less deployment that built no client, a publisher
    nobody told. Those read off the collector, and the returned value is beside
    the point.
    """
    def assertion(dont_care_result: object) -> bool:
        if kept.taken:
            raise AssertionError(f"Expected nothing to be collected, got {kept.taken}.")

        return True

    return assertion


def at_least[T](passing: int, satisfy: Assertion[T]) -> Assertion[list[T]]:
    """Asserts that at least `passing` of many results satisfy an assertion.

    For asserting on something that answers differently each time it is asked.
    A single sample from a distribution is not a verdict on it: a case the
    model gets right nine times in ten still fails one run in ten, and that
    failure is indistinguishable from a real regression.

    The failure message carries the score and every distinct reason a run
    missed, because "7 of 10, and all three misses named no cause" says what
    to fix, where "expected X, got None" does not.
    """

    def assertion(results: list[T]) -> bool:
        failures = []

        for result in results:
            try:
                satisfy(result)
            except AssertionError as assertion_error:
                failures.append(str(assertion_error))

        passed = len(results) - len(failures)
        if passed < passing:
            reasons = "\n".join(f"  - {reason}" for reason in sorted(set(failures)))
            raise AssertionError(
                f"Expected at least {passing} of {len(results)} to pass, got {passed}.\n"
                f"Distinct reasons for the {len(failures)} that did not:\n{reasons}"
            )

        return True

    return assertion
