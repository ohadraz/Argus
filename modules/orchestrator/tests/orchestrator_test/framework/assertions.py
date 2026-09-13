from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, call

from anthropic import BaseModel
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


def the_result_is[R](expected: R) -> Assertion[R]:
    """What `when` produced, whole."""
    def assertion(result: R) -> bool:
        assert result == expected
        return True

    return assertion


def the_result_at(field: str, is_: object) -> Assertion[BaseModel]:
    """One field of what `when` produced.

    A field rather than a key: a node answers with a `StateDelta` now, and the
    mapping this used to index is what the graph is handed rather than what a
    node returns. Typed as the model it reads, so the next thing to change
    shape fails here instead of at run time - subscripting a `Mapping[str, Any]`
    is something mypy will believe of anything.
    """
    def assertion(result: BaseModel) -> bool:
        assert getattr(result, field) == is_
        return True

    return assertion
