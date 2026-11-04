"""Assertions the repository-writing suites share."""

from __future__ import annotations

from argus_testkit.assertions import Assertion


def the_error_did_not_mention(unwanted: str) -> Assertion[Exception | None]:
    """Asserts that the error raised left `unwanted` out of its message - the
    other half of `the_error_mentioned`, for a failure whose words are part of
    what is being tested."""
    def assertion(error: Exception | None) -> bool:
        if error is not None and unwanted in str(error):
            raise AssertionError(f"Expected the error not to mention [{unwanted}], got [{error}].")

        return True

    return assertion
