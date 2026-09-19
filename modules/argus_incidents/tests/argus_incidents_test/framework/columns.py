"""Whether a write left any column of the row it wrote empty.

The other half of `nox -s guard_written_columns`, and the half a static reading
cannot do. The guard says a writer exists somewhere in `src/`; it cannot say
that the writer is ever called, or that what it puts in the column is a value
rather than NULL. This says both, because the row it looks at is one a real
writer has just written.

The column names come from `information_schema`, which is the schema as the
database holds it rather than a list somebody has to remember to extend. A
column declared next year is in every one of these tests the day it is declared,
and fails them until something writes it - which is the whole of what
`action.subject` needed and did not have.
"""

from __future__ import annotations

from collections.abc import Iterable

import psycopg
from argus_testkit import Assertion


def no_column_is_empty(conn: psycopg.Connection,
                       table: str,
                       found_by: str,
                       value: object,
                       except_for: Iterable[str] = ()) -> Assertion[object]:
    """Asserts that every column of the rows just written carries a value.

    `except_for` names the columns this particular write cannot fill, and is
    the exception rather than the rule: `incident_run` has no single row that
    carries everything, because the update recording a failure is the update
    that clears the lease it failed under. Naming them here keeps the property
    that matters - a column nobody thought about is in no exception list, so it
    fails until somebody writes it.
    """
    excepted = set(except_for)

    def assertion(_result: object) -> bool:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_name = %s "
                "ORDER BY ordinal_position",
                (table,)
            )
            columns = [str(row[0]) for row in cursor.fetchall()]

            if not columns:
                raise AssertionError(
                    f"Expected the table [{table}] to exist, and the database "
                    f"knows no table by that name."
                )

            cursor.execute(
                f"SELECT {', '.join(columns)} FROM {table} WHERE {found_by} = %s",
                (value,)
            )
            rows = cursor.fetchall()

        if not rows:
            raise AssertionError(
                f"Expected at least one row in [{table}] where {found_by} is "
                f"[{value}], and there were none - so nothing was written at all."
            )

        empty = sorted({
            column
            for row in rows
            for column, held in zip(columns, row, strict=True)
            if held is None and column not in excepted
        })

        if empty:
            raise AssertionError(
                f"Expected this write to fill every column of [{table}], and "
                f"{empty} came back empty. A column nothing writes reads as absent "
                f"to every consumer downstream, and no test that does not ask for "
                f"it by name can tell that from a value that happens to be missing."
            )

        return True

    return assertion
