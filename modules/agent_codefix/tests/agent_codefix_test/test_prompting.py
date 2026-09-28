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

import json
from typing import Any

import pytest
from agent_codefix.prompting import (
    EXPLANATION_FIELD,
    FILES_FIELD,
    REPORT_NOTHING_TO_CHANGE,
    REPORT_TOOL_NAME,
    SUBMIT_FIX,
    SubmittedFix,
)
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
def test_files_that_arrived_as_json_text_are_read_as_the_patch_they_are() -> None:
    # Measured on a real walk rather than imagined. Asked to rewrite one large
    # file, the model sent `files` as a *string* holding the array's JSON - 72KB
    # of it - where the schema asks for the array itself. Dropped as "not a
    # list", that fix reached a human as "there is nothing here to change", and
    # the incident recorded the verdict with nothing anywhere to say it was the
    # shape of the answer rather than the state of the code.
    #
    # Read rather than dropped, for the reason a number where a sentence was
    # asked for is written out: the answer arrived and is recoverable, and only
    # its wrapping is wrong. A string that is not JSON at all is still no patch -
    # the test above says so, and must keep saying it.
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "files": json.dumps([{"path": SOME_PATH, "content": SOME_CONTENT}])
            })
        ) \
        .then(
            all_of(
                _the_patch_is({SOME_PATH: SOME_CONTENT})
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


@pytest.mark.unit
def test_the_submit_tool_will_not_accept_a_patch_with_no_files() -> None:
    # The schema refuses it rather than the loop reading it back: strict mode
    # constrains sampling, so a patch with nothing in it cannot be sent at all.
    # `minItems` is one of the few numeric constraints strict mode honours, and
    # only for 0 and 1 - which is exactly the bound wanted here.
    Scenario() \
        .when(lambda: SUBMIT_FIX.to_wire()) \
        .then(
            all_of(
                _the_schema_requires(FILES_FIELD),
                _the_schema_asks_for_at_least_one(FILES_FIELD)
            )
        )


@pytest.mark.unit
def test_nothing_to_change_is_its_own_tool_and_carries_its_reasoning() -> None:
    # A verdict and a proposal are two answers, so they are two calls. One tool
    # answering both made an empty patch ambiguous between them, and no reading
    # of the prose separates the two - an explanation accompanies either.
    #
    # The explanation is required though nothing downstream reads it: being
    # asked for one is what makes submitting this a conclusion rather than a way
    # out of a hard read.
    Scenario() \
        .when(lambda: REPORT_NOTHING_TO_CHANGE.to_wire()) \
        .then(
            all_of(
                _the_tool_is_called(REPORT_TOOL_NAME),
                _the_schema_requires(EXPLANATION_FIELD)
            )
        )


@pytest.mark.unit
def test_a_file_wrapped_in_a_stray_closing_tag_is_read_without_it() -> None:
    # A real answer, on a whole recorded walk: every file in the patch ended
    # with a literal `</content>`, so each one was syntactically invalid Python
    # that would have been written to the branch and reviewed by somebody. The
    # field is named `content`, and the model closed a tag it never opened.
    #
    # Repaired rather than refused, for the reason `_the_array_inside` is: the
    # wrapping was wrong and the answer was not, and a patch dropped here
    # reaches a human as "there was nothing to change".
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "files": [{"path": SOME_PATH, "content": SOME_CONTENT + "</content>"}]
            })
        ) \
        .then(_the_patch_is({SOME_PATH: SOME_CONTENT}))


@pytest.mark.unit
def test_the_patch_field_says_a_test_for_slowness_has_to_bound_something() -> None:
    # A whole recorded walk turned on this. The fix was a real one - a quadratic
    # repeated-minimum scan replaced by one ordering - and the test it brought
    # asserted the figure the function returns. That assertion is just as true of
    # the slow implementation; it only takes longer. So the test passed against
    # the unfixed service and demonstrated nothing about the fault.
    #
    # It is the one class of fault a correctness assertion cannot show, and the
    # model cannot be expected to notice on its own: it is asked for a test that
    # fails first, and its test does fail to *prove* anything while passing.
    Scenario() \
        .when(lambda: SUBMIT_FIX.to_wire()) \
        .then(
            all_of(
                _the_description_of(FILES_FIELD, mentions="bound"),
                _the_description_of(FILES_FIELD, mentions="how long")
            )
        )


def _the_description_of(field: str, mentions: str) -> Assertion[dict[str, Any]]:
    def assertion(offered: dict[str, Any]) -> bool:
        said = offered["input_schema"]["properties"][field]["description"]

        if mentions not in said:
            raise AssertionError(
                f"Expected [{field!r}]'s description to mention [{mentions!r}], "
                f"got [{said!r}]."
            )

        return True

    return assertion


@pytest.mark.unit
def test_a_file_that_is_only_a_placeholder_word_is_dropped() -> None:
    # A real answer: `PLACEHOLDER`, eleven characters, offered as the whole new
    # contents of an 11KB module - beside an explanation that correctly named the
    # fault and the fix. Written out, it replaces the module with one word.
    #
    # Nothing caught it. The content was a string, it was not empty, and it is
    # valid Python - a bare name is an expression statement - so parsing it
    # proves nothing either. What gives it away is that a module the model claims
    # to have rewritten in full always contains something: an import, a
    # definition, an assignment. A file that is only a bare word is the model
    # eliding the work, and the one thing worse than losing the patch is writing
    # it.
    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "files": [
                    {"path": "src/io_shop/pricing_service.py", "content": "PLACEHOLDER"},
                    {"path": SOME_PATH, "content": SOME_CONTENT}
                ]
            })
        ) \
        .then(_the_patch_is({SOME_PATH: SOME_CONTENT}))


@pytest.mark.unit
def test_a_module_that_is_only_its_docstring_is_kept() -> None:
    # The rule above has to let this through: a package's `__init__.py` is often
    # a docstring and nothing else, and it is a real file somebody wrote. A
    # docstring is a string constant, where a placeholder is a bare name, and
    # that is the line between them.
    an_init = '"""The shop\'s pricing, as the account page asks for it."""\n'

    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "files": [{"path": "src/io_shop/__init__.py", "content": an_init}]
            })
        ) \
        .then(_the_patch_is({"src/io_shop/__init__.py": an_init}))


@pytest.mark.unit
def test_a_patch_written_as_parameter_tags_inside_the_explanation_is_read() -> None:
    # Measured on two paid runs, five submissions, every one the same. The model
    # closes the prose with `</explanation>`, opens `<parameter name="files">`,
    # and writes the whole patch as JSON inside the explanation string - while
    # the `files` argument that arrives properly holds a phrase pointing at it.
    #
    # Nothing was lost and nothing was wrong with the fix: the patches recovered
    # this way are 67-68KB of `monthly_statement.py` plus its tests, which is the
    # shape of every recording that ever worked. What it cost was the run - four
    # rejections, a whole wall clock spent resubmitting, and a walk reported as
    # having read until it ran out.
    #
    # Repaired rather than refused, for the reason the stray closing tag above is
    # and the array inside a string before it: the wrapping was wrong and the
    # answer was not.
    prose = "The month with no purchases raises from `max`."
    patch = json.dumps([{"path": SOME_PATH, "content": SOME_CONTENT}])

    Scenario() \
        .when(
            lambda: SubmittedFix.model_validate({
                "summary": "dont care",
                "explanation": (
                    f"{prose}</explanation>\n<parameter name=\"files\">{patch}"
                ),
                "files": [{"path": SOME_PATH, "content": "(see explanation)"}]
            })
        ) \
        .then(
            all_of(
                _the_patch_is({SOME_PATH: SOME_CONTENT}),
                _the_explanation_is(prose)
            )
        )


def _the_tool_is_called(name: str) -> Assertion[dict[str, Any]]:
    def assertion(offered: dict[str, Any]) -> bool:
        if offered["name"] != name:
            raise AssertionError(
                f"Expected the tool to be called [{name!r}], got "
                f"[{offered['name']!r}]."
            )

        return True

    return assertion


def _the_schema_requires(field: str) -> Assertion[dict[str, Any]]:
    def assertion(offered: dict[str, Any]) -> bool:
        required = offered["input_schema"]["required"]

        if field not in required:
            raise AssertionError(
                f"Expected [{field!r}] to be required, got [{required!r}]."
            )

        return True

    return assertion


def _the_schema_asks_for_at_least_one(field: str) -> Assertion[dict[str, Any]]:
    def assertion(offered: dict[str, Any]) -> bool:
        asked = offered["input_schema"]["properties"][field].get("minItems")

        if asked != 1:
            raise AssertionError(
                f"Expected [{field!r}] to ask for at least one item, got "
                f"minItems [{asked!r}]."
            )

        return True

    return assertion


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
