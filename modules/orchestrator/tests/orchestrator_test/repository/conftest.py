from __future__ import annotations

import pytest

"""Both tests here reach the database, so both ask for one without saying so.

The fixtures themselves live a level up, where the module's other database-
backed tests can see them too. What is left is the one thing true of this
directory and not of that one: nothing in it runs without a database.

The directory outlived its name. The repository moved to `argus_incidents` and
took its suites with it; what stayed reads rows to test `orchestrator.rates`
and `orchestrator.postmortem`, which is a different subject wearing the old
folder.
"""


@pytest.fixture(autouse=True)
def a_database_for_every_test(a_clean_database: None) -> None:
    """Hands this directory's tests the database and the emptying, unasked."""
