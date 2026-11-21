"""The vector store's ports, and the one rule their values hold themselves to.

Everything else here is a Protocol, answered by an adapter and asserted against a
real store in the adapter's own suite. What belongs here is the one thing a value
decides for itself: a scope of no prefixes is not a condition anybody meant.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, an_error_was_raised, attempting
from core.vector_store import StartsWithAnyOf

DONT_CARE_FIELD = "path"


@pytest.mark.unit
def test_a_scope_of_no_prefixes_is_refused() -> None:
    # "Starts with any of none" matches nothing, where a deployment that scoped
    # nothing means everything. A caller with no prefixes states no condition,
    # and one that built this anyway has read its setting wrong - which is
    # said here rather than answered as a search that finds nothing.
    Scenario() \
        .given(no_prefixes := tuple[str, ...]()) \
        .when(attempting(lambda: StartsWithAnyOf(field=DONT_CARE_FIELD, prefixes=no_prefixes))) \
        .then(an_error_was_raised(ValueError))
