from __future__ import annotations

from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock, call

Assertion = Callable[[], bool]


def all_of(*assertions: Assertion) -> Assertion:
    def combined_assertion() -> bool:
        failures = []
        for assertion in assertions:
            try:
                assertion()
            except AssertionError as assertion_error:
                failures.append(str(assertion_error))
        if failures:
            raise AssertionError("One or more assertions failed:\n" + "\n".join(failures))
        return True

    return combined_assertion


def assert_that(actual: object) -> _AssertThat:
    return _AssertThat(actual)


class _AssertThat:
    def __init__(self, actual: object) -> None:
        self._actual = actual

    def is_equal_to(self, expected: object) -> Assertion:
        def assertion() -> bool:
            assert self._actual == expected
            return True

        return assertion

    def was_called_with(self, *args: object, **kwargs: object) -> Assertion:
        mock = cast(MagicMock, self._actual)

        def assertion() -> bool:
            assert mock.call_args == call(*args, **kwargs)
            return True

        return assertion
