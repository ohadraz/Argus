from __future__ import annotations

from collections.abc import Callable

import psycopg

Assertion = Callable[[psycopg.Connection], bool]


def all_of(*assertions: Assertion) -> Assertion:
    def combined_assertion(conn: psycopg.Connection) -> bool:
        failures = []

        for assertion in assertions:
            try:
                assertion(conn)
            except AssertionError as assertion_error:
                failures.append(str(assertion_error))

        if failures:
            raise AssertionError("One or more assertions failed:\n" + "\n".join(failures))

        return True

    return combined_assertion
