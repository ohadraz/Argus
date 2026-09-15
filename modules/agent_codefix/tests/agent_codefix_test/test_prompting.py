"""What Code-Fix is asked, and the one shape its answer may take.

The answer is a patch - whole files, not a diff - so the reading of it is where
this agent is most easily fooled. A diff that half-applies produces a file that
is subtly not what anyone wrote; a file entry missing its content produces one
that is empty and valid. Both reach a branch looking like work.

So the leniency here is deliberate, the way the postmortem's is: a malformed
entry costs that entry and nothing else. Refusing the whole submission would
throw away three correct files over a fourth, and an agent that proposed nothing
is indistinguishable, downstream, from one that was never asked.
"""

from __future__ import annotations

import pytest
from agent_codefix.prompting import SubmittedFix
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario

SOME_PATH = "src/io_shop/spend_summary.py"
SOME_CONTENT = "def average_spend_per_item_this_month(account):\n    return 0\n"


@pytest.mark.unit
def test_a_submitted_fix_is_read_by_attribute() -> None:
    some_summary = "guard the monthly divisor"
    some_explanation = "The month's purchase list is empty for most shoppers."

    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": some_summary,
                "explanation": some_explanation,
                "files": [{"path": SOME_PATH, "content": SOME_CONTENT}]
            })
        ) \
        .then(
            all_of(
                _the_summary_is(some_summary),
                _the_explanation_is(some_explanation),
                _the_patch_is({SOME_PATH: SOME_CONTENT})
            )
        )


@pytest.mark.unit
def test_a_fix_may_touch_more_than_one_file() -> None:
    # A real fix brings its regression test with it (spec §7.4), which is a
    # second file at minimum. A reader that took only the first would propose
    # the fix without the thing proving it works.
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "files": [
                    {"path": SOME_PATH, "content": SOME_CONTENT},
                    {"path": "tests/io_shop/test_new.py", "content": "assert True"}
                ]
            })
        ) \
        .then(
            all_of(
                _the_patch_is({
                    SOME_PATH: SOME_CONTENT,
                    "tests/io_shop/test_new.py": "assert True"
                })
            )
        )


@pytest.mark.unit
def test_a_prose_field_that_arrived_as_a_number_is_written_out() -> None:
    # A figure where a sentence was asked for is still an answer. Dropping it
    # would record as unwritten something the model wrote.
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": 41, "files": []
            })
        ) \
        .then(
            all_of(
                _the_summary_is("41")
            )
        )


@pytest.mark.unit
def test_a_prose_field_that_arrived_structural_is_read_as_unanswered() -> None:
    # A dict stringified into a summary reaches a human as the words
    # "{'a': 1}", which reads as an answer and is not one.
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": {"unexpected": "shape"}, "files": []
            })
        ) \
        .then(
            all_of(
                _the_summary_is(None)
            )
        )


@pytest.mark.unit
def test_a_file_with_no_path_is_dropped_and_the_rest_survive() -> None:
    # THE ONE THAT COSTS ONLY ITSELF. Refusing the whole submission over one
    # malformed entry would throw away a correct patch, and the incident would
    # record that no fix was found when one very nearly was.
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "files": [
                    {"content": "content with nowhere to go"},
                    {"path": SOME_PATH, "content": SOME_CONTENT}
                ]
            })
        ) \
        .then(
            all_of(
                _the_patch_is({SOME_PATH: SOME_CONTENT})
            )
        )


@pytest.mark.unit
def test_a_file_whose_content_is_not_text_is_dropped() -> None:
    # An entry with a path and no readable content would write an empty file
    # over a working module - a patch that deletes the thing it was fixing.
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "files": [
                    {"path": "src/io_shop/accounts.py", "content": {"not": "text"}},
                    {"path": SOME_PATH, "content": SOME_CONTENT}
                ]
            })
        ) \
        .then(
            all_of(
                _the_patch_is({SOME_PATH: SOME_CONTENT})
            )
        )


@pytest.mark.unit
def test_files_that_did_not_arrive_as_a_list_are_read_as_no_patch() -> None:
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care", "files": "src/io_shop/spend_summary.py"
            })
        ) \
        .then(
            all_of(
                _the_patch_is({})
            )
        )


@pytest.mark.unit
def test_a_fix_that_proposed_no_files_is_read_rather_than_refused() -> None:
    # "I looked and found nothing to change" is a real answer and a different
    # one from "the submission was malformed". Whoever reads this has to be able
    # to tell them apart, so an empty patch parses.
    some_summary = "the fault is in the flag's rollout, not in the code"

    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": some_summary, "files": []
            })
        ) \
        .then(
            all_of(
                _the_summary_is(some_summary),
                _the_patch_is({})
            )
        )


@pytest.mark.unit
def test_a_submission_naming_the_same_file_twice_keeps_the_later_one() -> None:
    # A model that revised itself mid-answer. Keeping the first would write the
    # version it changed its mind about; refusing both would lose a fix over a
    # duplication that has an obvious reading.
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "files": [
                    {"path": SOME_PATH, "content": "the first attempt"},
                    {"path": SOME_PATH, "content": SOME_CONTENT}
                ]
            })
        ) \
        .then(
            all_of(
                _the_patch_is({SOME_PATH: SOME_CONTENT})
            )
        )


def _the_summary_is(summary: str | None) -> Assertion[SubmittedFix]:
    def assertion(submitted: SubmittedFix) -> bool:
        if submitted.summary != summary:
            raise AssertionError(
                f"Expected the summary [{summary!r}], got [{submitted.summary!r}]."
            )

        return True

    return assertion


def _the_explanation_is(explanation: str | None) -> Assertion[SubmittedFix]:
    def assertion(submitted: SubmittedFix) -> bool:
        if submitted.explanation != explanation:
            raise AssertionError(
                f"Expected the explanation [{explanation!r}], "
                f"got [{submitted.explanation!r}]."
            )

        return True

    return assertion


def _the_patch_is(patch: dict[str, str]) -> Assertion[SubmittedFix]:
    """The patch as the mapping the write tier takes - path to whole content.

    Asserted as one value rather than field by field: what matters is the whole
    of what would be written, and a per-file assertion passes happily while a
    fourth file nobody expected rides along.
    """
    def assertion(submitted: SubmittedFix) -> bool:
        proposed = submitted.patch()

        if proposed != patch:
            raise AssertionError(f"Expected the patch {patch}, got {proposed}.")

        return True

    return assertion
