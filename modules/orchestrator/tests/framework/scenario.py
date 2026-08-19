from __future__ import annotations

from typing import Any

from .assertions import Assertion


class Scenario:
    def given(self, _result: Any) -> Scenario:
        if callable(_result):
            _result()
        return self

    def when(self, _result: Any) -> Scenario:
        if callable(_result):
            _result()
        return self

    def then(self, assertion: Assertion) -> Scenario:
        if not assertion():
            raise AssertionError("Then assertion failed")
        return self
