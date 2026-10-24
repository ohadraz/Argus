"""A sentence of Code-Fix's explanation that speaks of several pieces of code
outside its patch at once.

Every slip of this kind Code-Fix made was one: each reader said right on its
own, then "those readers keep trusting it" over a list holding the one reader
that checks the figure. A piece is a file of the repository the patch does not
touch, a module of one written as code by its bare name, or a function or class
defined only outside the patch's files - and the trigger is one sentence, or
one list with the sentence leading it, naming two or more. One piece outside
the patch is how a fix's cause is said ("the scrape names `metrics`, but
deploy/values-production.yaml names `http-metrics`") and is never a group.
"""

from __future__ import annotations

import pytest
from agent_codefix.grouping import the_group_outside
from argus_testkit import Scenario, the_answer_was

LEDGER = "src/io_shop/purchase_ledger.py"
SUMMARY = "src/io_shop/spend_summary.py"
RECONCILIATION = "src/io_shop/spend_reconciliation.py"
STATEMENT = "src/io_shop/monthly_statement.py"
VALUES = "deploy/values-production.yaml"

SOME_LISTING = [LEDGER, SUMMARY, RECONCILIATION, STATEMENT, VALUES]

SOME_PATCH = {LEDGER: "def record_purchase_deriving_the_month(account, purchase):\n"
                      "    return account\n"}

SOME_DEFINED = {
    "average_spend_per_item_this_month": [SUMMARY],
    "reconcile_monthly_totals": [RECONCILIATION],
    "render_monthly_statement": [STATEMENT],
    "record_purchase_deriving_the_month": [STATEMENT]
}


@pytest.mark.unit
@pytest.mark.parametrize("sentence", [
    f"Both {SUMMARY} and {RECONCILIATION} read the stored figure as the month's total.",
    "`spend_summary` and `spend_reconciliation` keep trusting the stored figure.",
    "`average_spend_per_item_this_month` and `reconcile_monthly_totals` read it as true.",
    "average_spend_per_item_this_month and reconcile_monthly_totals read it as true.",
    f"{SUMMARY} divides it, and `reconcile_monthly_totals` reads it as true."
], ids=["two-paths", "two-modules-as-code", "two-functions-as-code",
        "two-functions-by-their-shape", "a-path-and-a-function"])
def test_a_sentence_naming_two_pieces_outside_the_patch_is_its_paragraph(sentence: str) -> None:
    some_explanation = (
        f"The fix changes {LEDGER}.\n\n"
        f"The month is left unmoved. {sentence}"
    )

    Scenario() \
        .when(
            lambda: the_group_outside(some_explanation, SOME_PATCH, SOME_LISTING, SOME_DEFINED)
        ) \
        .then(
            the_answer_was(f"The month is left unmoved. {sentence}")
        )


@pytest.mark.unit
def test_a_list_naming_two_pieces_outside_the_patch_is_its_paragraph_whole() -> None:
    # The slip's quiet form: no bullet names two pieces, the sentence leading
    # them says what all of them do.
    some_list = (
        "The docstring says the month adds up from the history, but readers use the stored "
        "figure:\n"
        f"- {SUMMARY}: `average_spend_per_item_this_month` divides it.\n"
        f"- {RECONCILIATION} compares it with the purchases."
    )

    Scenario() \
        .when(
            lambda: the_group_outside(f"The fix changes {LEDGER}.\n\n{some_list}",
                                      SOME_PATCH, SOME_LISTING, SOME_DEFINED)
        ) \
        .then(
            the_answer_was(some_list)
        )


@pytest.mark.unit
@pytest.mark.parametrize("explanation", [
    f"The scrape names `metrics`, but {VALUES} names the port `http-metrics`.",
    f"Its callers in {SUMMARY} need no change.",
    f"{LEDGER} writes the month again, and {SUMMARY} divides it.",
    "`record_purchase_deriving_the_month` and `reconcile_monthly_totals` disagree.",
    f"{SUMMARY} divides it.\n\n{RECONCILIATION} compares it."
], ids=["one-file-outside", "one-file-outside-again", "a-patch-file-and-one-outside",
        "a-function-the-patch-defines-and-one-outside", "one-a-sentence"])
def test_an_explanation_naming_at_most_one_piece_outside_the_patch_at_once_has_no_group(
        explanation: str) -> None:
    # The cause of a fix often lives outside it, and saying so names one piece.
    Scenario() \
        .when(
            lambda: the_group_outside(explanation, SOME_PATCH, SOME_LISTING, SOME_DEFINED)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_name_several_files_define_is_one_piece_however_often_it_is_said() -> None:
    some_defined_twice = {"average": [SUMMARY, STATEMENT]}

    Scenario() \
        .when(
            lambda: the_group_outside("`average` is called twice: `average` again.",
                                      SOME_PATCH, SOME_LISTING, some_defined_twice)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_word_joined_to_another_by_a_hyphen_is_not_a_name() -> None:
    # A port called `http-metrics` was read as the function `metrics` the
    # service's endpoints define, and the drift case's one piece became two.
    some_endpoints = "src/io_shop/endpoints.py"

    Scenario() \
        .when(
            lambda: the_group_outside(f"{VALUES} names the port `http-metrics`.",
                                      SOME_PATCH, [*SOME_LISTING, some_endpoints],
                                      {"metrics": [some_endpoints]})
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_word_a_dot_leads_into_another_is_not_a_name() -> None:
    # The values file's key `metrics.portName` was read as the same function.
    # What a dotted name calls is its last part; what comes before it is a
    # module or an object, and a module is a file the file check finds.
    some_endpoints = "src/io_shop/endpoints.py"

    Scenario() \
        .when(
            lambda: the_group_outside(f"The test reads `metrics.portName` from {VALUES}.",
                                      SOME_PATCH, [*SOME_LISTING, some_endpoints],
                                      {"metrics": [some_endpoints]})
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_plain_word_in_backticks_is_not_a_name() -> None:
    # "(`metrics` != `http-metrics`)" is a port's name, and the endpoints define
    # a function called that too. Nothing in a plain word says which it is, for
    # the reason a bare word is never a file.
    some_endpoints = "src/io_shop/endpoints.py"

    Scenario() \
        .when(
            lambda: the_group_outside(f"{VALUES} says otherwise (`metrics` != `http-metrics`).",
                                      SOME_PATCH, [*SOME_LISTING, some_endpoints],
                                      {"metrics": [some_endpoints]})
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_name_several_files_define_adds_no_piece_where_one_of_its_files_already_is_one() -> None:
    # A rewrite naming `reconcile_monthly_totals` and the `anything_disagrees`
    # beside it - one file - was read as two pieces, because another module
    # defines an `anything_disagrees` too.
    some_cache_reconciliation = "src/io_shop/cache_reconciliation.py"

    Scenario() \
        .when(
            lambda: the_group_outside(
                "`reconcile_monthly_totals` checks `anything_disagrees` again.",
                SOME_PATCH, [*SOME_LISTING, some_cache_reconciliation],
                {"reconcile_monthly_totals": [RECONCILIATION],
                 "anything_disagrees": [RECONCILIATION, some_cache_reconciliation]})
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_the_first_group_found_is_the_one_answered() -> None:
    some_first = f"{SUMMARY} and {RECONCILIATION} read it."
    some_second = f"{STATEMENT} and {SUMMARY} read it too."

    Scenario() \
        .when(
            lambda: the_group_outside(f"{some_first}\n\n{some_second}",
                                      SOME_PATCH, SOME_LISTING, SOME_DEFINED)
        ) \
        .then(
            the_answer_was(some_first)
        )
