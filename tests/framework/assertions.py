from __future__ import annotations

from argus_core.ids import UuidStr
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_testkit.assertions import Assertion

"""Assertions about a `Hypothesis`, shared by every tier that produces one.

These live here rather than in `argus_testkit` because they know Argus's
domain. The testkit is deliberately generic - `all_of`, `eventually`,
`an_error_was_raised` would read the same in any project - and giving it an
import of `argus_core` would make the test machinery depend on the thing under
test.
"""


def the_cause_was_identified_as(expected_cause: CauseType) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        actual_cause = hypothesis.cause_type

        if actual_cause != expected_cause:
            raise AssertionError(
                f"Expected cause [{expected_cause}], got [{actual_cause}]. "
                f"Model said: {hypothesis.summary}"
            )

        return True

    return assertion


def some_confidence_was_given() -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        if hypothesis.confidence is None:
            raise AssertionError("Expected some confidence, got [None].")

        return True

    return assertion


def no_cause_was_determined() -> Assertion[Hypothesis]:
    """Both halves, because the domain refuses to hold one without the other."""

    def assertion(hypothesis: Hypothesis) -> bool:
        actual_cause = hypothesis.cause_type
        actual_confidence = hypothesis.confidence

        if actual_cause is not None:
            raise AssertionError(
                f"Expected no cause, got [{actual_cause}]. Model said: {hypothesis.summary}"
            )

        if actual_confidence is not None:
            raise AssertionError(f"Expected confidence to be [None], got [{actual_confidence}].")

        return True

    return assertion


def the_hypothesis_belongs_to(incident_id: UuidStr) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        actual_incident_id = hypothesis.incident_id

        if incident_id != actual_incident_id:
            raise AssertionError(f"Expected incident [{incident_id}], got [{actual_incident_id}].")

        return True

    return assertion
