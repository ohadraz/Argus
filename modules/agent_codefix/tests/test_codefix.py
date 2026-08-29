from __future__ import annotations

import pytest
from agent_codefix import propose_fix


@pytest.mark.unit
def test_proposing_a_fix_reports_having_none_rather_than_failing() -> None:
    # `fixing` became reachable the moment Mitigation could return a real
    # `refuted`: a flag was reverted, the service did not recover, and the
    # incident routes here. Code-Fix has nothing to offer yet - no RAG, no
    # pull request - but "nothing to offer" has to arrive as an answer rather
    # than as an exception, because the alternative is an incident that was
    # correctly investigated, correctly mitigated and correctly refuted, and
    # then lost to a stack trace on its way to a human.
    dont_care_hypothesis = "the flag was reverted and the service did not recover"

    assert propose_fix(dont_care_hypothesis) is None
