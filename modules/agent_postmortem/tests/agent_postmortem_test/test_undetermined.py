"""Whether the investigation named no cause, which decides who writes it.

Asked of the candidates as the Investigator left them: a candidate with no
failure mode and no confidence is its honest "nothing identified", whichever
way it got there.
"""

from __future__ import annotations

import pytest
from agent_postmortem import IncidentEvidence
from agent_postmortem.undetermined import named_no_cause
from argus_testkit import Scenario, the_answer_was

from agent_postmortem_test.framework.builders import a_candidate, an_evidence_bundle

NOTHING_IDENTIFIED = a_candidate("no cause determined", confidence=None).model_copy(
    update={"failure_mode": None})


@pytest.mark.unit
def test_an_investigation_whose_every_candidate_names_nothing_named_no_cause() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[NOTHING_IDENTIFIED])
        ) \
        .when(
            lambda: named_no_cause(evidence)
        ) \
        .then(
            the_answer_was(True)
        )


@pytest.mark.unit
@pytest.mark.parametrize("evidence", [
    # A later round that found nothing, after an earlier one named a cause that
    # was tried: there is a cause to write about, refuted or not.
    pytest.param(an_evidence_bundle(candidates=[a_candidate("the flag was switched on"),
                                                NOTHING_IDENTIFIED]),
                 id="one names a cause"),
    # Its candidate is shaped the same, and its cause sentence says why the
    # alarm was false.
    pytest.param(an_evidence_bundle(disproven=True, candidates=[NOTHING_IDENTIFIED]),
                 id="disproven"),
    # Never reached an investigation: nothing was named, and nothing was asked.
    pytest.param(an_evidence_bundle(candidates=[]), id="no candidates")
])
def test_an_investigation_that_named_a_cause_disproved_the_alarm_or_never_ran_did_not(
        evidence: IncidentEvidence) -> None:
    Scenario() \
        .when(
            lambda: named_no_cause(evidence)
        ) \
        .then(
            the_answer_was(False)
        )
