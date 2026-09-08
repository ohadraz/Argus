from __future__ import annotations

import pytest

"""Postgres for the one suite in this module that has a queue to read.

The database itself and the emptying between tests belong to the module's own
conftest, which several of its directories reach. What is different here is
only who asks: every test in this directory needs the database, so none of them
should have to say so, while the unit suites beside it must not start one.

That difference is the whole of this file. A second `postgres` fixture would be
a second session-scoped database in the same pytest process - sequential, so it
worked, but it meant every rule about starting, adopting or wiping a database
had to hold for two of them at once and stay safe in either order.
"""


@pytest.fixture(autouse=True)
def a_database_for_every_test_here(a_clean_database: None) -> None:
    """Asks for the module's database on behalf of every test in this
    directory, which is what `autouse` is for and what the module's own
    fixture deliberately is not."""
