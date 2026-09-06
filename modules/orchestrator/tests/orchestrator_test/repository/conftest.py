from __future__ import annotations

import pytest

"""Every test here reaches the database, so every test here asks for one.

The fixtures themselves live a level up, where the module's other database-
backed tests can see them too. What is left is the one thing true of this
directory and not of that one: there is no repository test that does not want a
database, so none of them should have to say so.
"""


@pytest.fixture(autouse=True)
def a_database_for_every_test(a_clean_database: None) -> None:
    """Hands this directory's tests the database and the emptying, unasked."""
