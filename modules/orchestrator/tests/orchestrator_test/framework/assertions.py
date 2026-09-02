from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, call

from argus_testkit import Assertion


def assert_that[A](actual: A) -> _AssertThat[A]:
    return _AssertThat(actual)


class _AssertThat[A]:
    def __init__(self, actual: A) -> None:
        self._actual = actual

    def is_equal_to[R](self, expected: A) -> Assertion[R]:
        def assertion(_result: R) -> bool:
            assert self._actual == expected
            return True

        return assertion

    def was_called_with[R](self, *args: object, **kwargs: object) -> Assertion[R]:
        mock = cast(MagicMock, self._actual)

        def assertion(_result: R) -> bool:
            assert mock.call_args == call(*args, **kwargs)
            return True

        return assertion
