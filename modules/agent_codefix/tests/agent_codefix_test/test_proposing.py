"""Asking Code-Fix for a permanent fix, and being told there is none.

The agent is a stub (spec §7.4) - no RAG, no pull request, no `git-mcp` call -
and what is asserted here is the shape of its answer rather than its content.
`None` means looked for and not found, which the walk reports as a fix that was
not found; it is not an absence for a caller to interpret, and it is not an
exception for one to survive.
"""

from __future__ import annotations

import pytest
from agent_codefix import propose_fix
from argus_testkit import Assertion, Scenario

DONT_CARE_HYPOTHESIS = "the flag was reverted and the service did not recover"


@pytest.mark.unit
def test_proposing_a_fix_reports_having_none_rather_than_failing() -> None:
    # `fixing` became reachable the moment Mitigation could return a real
    # `refuted`: a flag was reverted, the service did not recover, and the
    # incident routes here. Code-Fix has nothing to offer yet - but "nothing to
    # offer" has to arrive as an answer rather than as an exception, because the
    # alternative is an incident that was correctly investigated, correctly
    # mitigated and correctly refuted, and then lost to a stack trace on its way
    # to a human.
    Scenario() \
        .given(DONT_CARE_HYPOTHESIS) \
        .when(lambda: propose_fix(DONT_CARE_HYPOTHESIS)) \
        .then(_no_fix_was_proposed())


def _no_fix_was_proposed() -> Assertion[str | None]:
    def assertion(fix: str | None) -> bool:
        if fix is not None:
            raise AssertionError(
                f"Expected Code-Fix to have no fix to propose, it proposed [{fix}]."
            )

        return True

    return assertion
