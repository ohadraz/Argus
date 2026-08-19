from __future__ import annotations

from typing import Any

import psycopg

from .assertions import Assertion


class Scenario:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn


    def given(self, _result: Any) -> Scenario:
        if callable(_result):
            _result()

        return self

    def when(self, _result: Any) -> Scenario:
        if callable(_result):
            _result()

        return self

    def then(self, assertion: Assertion) -> Scenario:
        if not assertion(self.conn):
            raise AssertionError("Then assertion failed")

        return self
