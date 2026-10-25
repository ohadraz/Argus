"""How the code outside a patch uses what the patch changes, said by the syntax
tree rather than by a model.

Code-Fix said of the code it did not change that every reader of a stored figure
trusts it, and one of those readers compares the figure with the purchases to
catch it being wrong. What each line outside the patch does with what the patch
changes is a fact the tree holds, so the tree says it: the fields the patch's
changed functions now write, every read of them outside the patch, every call of
a function whose definition the patch changes - and every name defined outside
the patch's files, which is how a sentence about code outside it is recognised.
"""

from __future__ import annotations

import pytest
from argus_core.models import CodeOutsideThePatch, CodeUse
from argus_testkit import Scenario, the_answer_was
from read_mcp_server.outside_the_patch import code_outside_the_patch

LEDGER = "src/shop/ledger.py"
SUMMARY = "src/shop/summary.py"
RECONCILIATION = "src/shop/reconciliation.py"
PAGE = "src/shop/page.py"

LEDGER_WRITING_THE_TOTAL = (
    "def record(account, price):\n"
    "    return replace(account, total=account.total + price)\n"
)
LEDGER_WRITING_THE_MONTH_TOO = (
    "def record(account, price):\n"
    "    return replace(account, total=account.total + price, month=account.month + price)\n"
)
SUMMARY_DIVIDING_THE_MONTH = (
    "def average(account, count):\n"
    "    return account.month // count\n"
)
RECONCILIATION_CHECKING_THE_MONTH = (
    "def reconcile(account):\n"
    "    if bought(account) != account.month:\n"
    "        return False\n"
    "    return True\n"
)

THE_SHOP = {
    LEDGER: LEDGER_WRITING_THE_TOTAL,
    SUMMARY: SUMMARY_DIVIDING_THE_MONTH,
    RECONCILIATION: RECONCILIATION_CHECKING_THE_MONTH
}

DONT_CARE_DEFINED = {"average": [SUMMARY], "reconcile": [RECONCILIATION]}


@pytest.mark.unit
def test_every_read_outside_the_patch_of_a_field_it_now_writes_says_what_its_line_does() -> None:
    # The reconciliation reads the figure to check it, which is not what the
    # summary does with it - and the patch's own read of it is the patch's.
    Scenario() \
        .when(
            lambda: code_outside_the_patch(THE_SHOP, {LEDGER: LEDGER_WRITING_THE_MONTH_TOO})
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[
                    CodeUse(name="month", path=RECONCILIATION, line=2, function="reconcile",
                            does="compares it with bought(account)"),
                    CodeUse(name="month", path=SUMMARY, line=2, function="average",
                            does="divides with it: account.month // count")
                ],
                defined=DONT_CARE_DEFINED
            ))
        )


@pytest.mark.unit
def test_a_field_the_patch_now_sets_by_assignment_is_one_it_writes() -> None:
    some_ledger_setting_the_month = (
        "def record(account, price):\n"
        "    account.total = account.total + price\n"
        "    account.month = account.month + price\n"
    )
    some_ledger_setting_the_total = (
        "def record(account, price):\n"
        "    account.total = account.total + price\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch({**THE_SHOP, LEDGER: some_ledger_setting_the_total},
                                           {LEDGER: some_ledger_setting_the_month})
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[
                    CodeUse(name="month", path=RECONCILIATION, line=2, function="reconcile",
                            does="compares it with bought(account)"),
                    CodeUse(name="month", path=SUMMARY, line=2, function="average",
                            does="divides with it: account.month // count")
                ],
                defined=DONT_CARE_DEFINED
            ))
        )


@pytest.mark.unit
def test_a_field_the_patch_writes_as_it_did_before_is_not_one_it_changes() -> None:
    some_ledger_writing_the_total_unchanged_in_a_reworded_function = (
        "def record(account, price):\n"
        "    log(price)\n"
        "    return replace(account, total=account.total + price)\n"
    )
    some_summary_reading_the_total = (
        "def average(account, count):\n"
        "    return account.total // count\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {**THE_SHOP, SUMMARY: some_summary_reading_the_total},
                {LEDGER: some_ledger_writing_the_total_unchanged_in_a_reworded_function}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(uses=[], defined=DONT_CARE_DEFINED))
        )


@pytest.mark.unit
def test_a_field_written_through_a_local_is_written_as_the_locals_value() -> None:
    # The shop's fix moved the purchases into a local to sum them, and every
    # read of the purchases in the shop came back as a use of a field it
    # changed.
    some_ledger_writing_the_total_through_a_local = (
        "def record(account, price):\n"
        "    total = account.total + price\n"
        "    return replace(account, total=total, month=account.month + price)\n"
    )
    some_summary_reading_the_total = (
        "def average(account, count):\n"
        "    return account.total // count\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {**THE_SHOP, SUMMARY: some_summary_reading_the_total},
                {LEDGER: some_ledger_writing_the_total_through_a_local}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[
                    CodeUse(name="month", path=RECONCILIATION, line=2, function="reconcile",
                            does="compares it with bought(account)")
                ],
                defined=DONT_CARE_DEFINED
            ))
        )


@pytest.mark.unit
def test_a_function_the_patch_adds_changes_nothing_the_code_outside_it_uses() -> None:
    # Nothing outside the patch was written against a function that did not
    # exist. A test builds its fixtures by keyword, and every one of those read
    # as a field the patch writes buried the rows that mattered on the shop.
    some_ledger_with_a_function_added = LEDGER_WRITING_THE_TOTAL + (
        "\n\ndef reset(account):\n"
        "    return replace(account, month=0)\n"
    )
    some_test_the_patch_adds = (
        "def test_record():\n"
        "    record(Account(month=3), 1)\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                THE_SHOP,
                {LEDGER: some_ledger_with_a_function_added,
                 "tests/shop/test_ledger.py": some_test_the_patch_adds}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(uses=[], defined=DONT_CARE_DEFINED))
        )


@pytest.mark.unit
def test_every_call_outside_the_patch_of_a_function_whose_definition_it_changes_is_listed() -> None:
    some_guarded_summary = (
        "def average(account, count):\n"
        "    return account.month // count if count else 0\n"
    )
    some_page_calling_the_summary = (
        "def render(account):\n"
        "    figure = average(account, 3)\n"
        "    return figure\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch({**THE_SHOP, PAGE: some_page_calling_the_summary},
                                           {SUMMARY: some_guarded_summary})
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[
                    CodeUse(name="average", path=PAGE, line=2, function="render",
                            does="calls it: figure = average(account, 3)")
                ],
                defined={"record": [LEDGER], "reconcile": [RECONCILIATION],
                         "render": [PAGE]}
            ))
        )


@pytest.mark.unit
def test_a_changed_function_writes_what_the_functions_of_its_file_it_calls_write() -> None:
    # Two of six rewrites made the changed function hand the sale to another in
    # its file, and with nothing written by the changed function itself the
    # rows came out at none.
    some_ledger_writing_both = (
        "def record_both(account, price):\n"
        "    return replace(account, total=account.total + price, month=account.month + price)\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {**THE_SHOP, LEDGER: some_ledger_writing_both + "\n\n" + LEDGER_WRITING_THE_TOTAL},
                {LEDGER: some_ledger_writing_both + (
                    "\n\ndef record(account, price):\n"
                    "    return record_both(account, price)\n"
                )}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[
                    CodeUse(name="month", path=RECONCILIATION, line=2, function="reconcile",
                            does="compares it with bought(account)"),
                    CodeUse(name="month", path=SUMMARY, line=2, function="average",
                            does="divides with it: account.month // count")
                ],
                defined=DONT_CARE_DEFINED
            ))
        )


@pytest.mark.unit
def test_a_changed_function_writes_what_a_chain_of_functions_of_its_file_writes() -> None:
    # Handed on twice is handed on all the same: the field is written two calls
    # down rather than one.
    some_ledger_handing_the_sale_on_twice = (
        "def record_both(account, price):\n"
        "    return replace(account, total=account.total + price, month=account.month + price)\n"
        "\n\n"
        "def apply(account, price):\n"
        "    return record_both(account, price)\n"
        "\n\n"
        "def record(account, price):\n"
        "    return apply(account, price)\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch(THE_SHOP,
                                           {LEDGER: some_ledger_handing_the_sale_on_twice})
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[
                    CodeUse(name="month", path=RECONCILIATION, line=2, function="reconcile",
                            does="compares it with bought(account)"),
                    CodeUse(name="month", path=SUMMARY, line=2, function="average",
                            does="divides with it: account.month // count")
                ],
                defined=DONT_CARE_DEFINED
            ))
        )


@pytest.mark.unit
def test_a_field_a_function_wrote_through_another_before_is_written_as_it_was() -> None:
    # What the function wrote before is read the way what it writes now is. A
    # fix that stopped handing the sale on and wrote the same fields itself
    # changed nothing about them.
    some_ledger_writing_both = (
        "def record_both(account, price):\n"
        "    return replace(account, total=account.total + price, month=account.month + price)\n"
    )
    some_ledger_handing_the_sale_on = some_ledger_writing_both + (
        "\n\ndef record(account, price):\n"
        "    return record_both(account, price)\n"
    )
    some_ledger_writing_both_itself = some_ledger_writing_both + (
        "\n\ndef record(account, price):\n"
        "    log(price)\n"
        "    return replace(account, total=account.total + price, month=account.month + price)\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch({**THE_SHOP, LEDGER: some_ledger_handing_the_sale_on},
                                           {LEDGER: some_ledger_writing_both_itself})
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(uses=[], defined=DONT_CARE_DEFINED))
        )


@pytest.mark.unit
def test_a_keyword_passed_to_a_call_that_builds_nothing_is_no_field() -> None:
    # `key=` to `sorted` is not a field of anything, and read as one every
    # `.key` in the service would be a row.
    some_reader = "src/shop/reader.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {**THE_SHOP, some_reader: "def first(entry):\n    return entry.key\n"},
                {LEDGER: "def record(account, price):\n"
                         "    ordered = sorted(account.items, key=len)\n"
                         "    return replace(account, total=account.total + price)\n"}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[], defined={**DONT_CARE_DEFINED, "first": [some_reader]}
            ))
        )


@pytest.mark.unit
def test_a_keyword_passed_to_a_class_the_source_defines_is_a_field() -> None:
    some_accounts = "src/shop/accounts.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {**THE_SHOP,
                 LEDGER: "def open_account(owner):\n    return Account(owner=owner)\n",
                 some_accounts: "class Account:\n    pass\n"},
                {LEDGER: "def open_account(owner):\n    return Account(owner=owner, month=0)\n"}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[
                    CodeUse(name="month", path=RECONCILIATION, line=2, function="reconcile",
                            does="compares it with bought(account)"),
                    CodeUse(name="month", path=SUMMARY, line=2, function="average",
                            does="divides with it: account.month // count")
                ],
                defined={**DONT_CARE_DEFINED, "Account": [some_accounts]}
            ))
        )


@pytest.mark.unit
def test_a_method_of_a_changed_functions_name_is_not_that_function() -> None:
    # `cache.average(...)` calls whatever the cache's `average` is; the changed
    # one is a function of a module, called by its name or through its module.
    some_guarded_summary = (
        "def average(account, count):\n"
        "    return account.month // count if count else 0\n"
    )
    some_page_calling_a_cache = (
        "def render(account, cache):\n"
        "    return cache.average(account)\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch({**THE_SHOP, PAGE: some_page_calling_a_cache},
                                           {SUMMARY: some_guarded_summary})
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[],
                defined={"record": [LEDGER], "reconcile": [RECONCILIATION],
                         "render": [PAGE]}
            ))
        )


@pytest.mark.unit
def test_a_changed_function_called_through_its_module_is_called() -> None:
    some_guarded_summary = (
        "def average(account, count):\n"
        "    return account.month // count if count else 0\n"
    )
    some_page_calling_through_the_module = (
        "from shop import summary\n"
        "\n"
        "\n"
        "def render(account):\n"
        "    return summary.average(account, 3)\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {**THE_SHOP, PAGE: some_page_calling_through_the_module},
                {SUMMARY: some_guarded_summary}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="average", path=PAGE, line=5, function="render",
                              does="calls it: return summary.average(account, 3)")],
                defined={"record": [LEDGER], "reconcile": [RECONCILIATION],
                         "render": [PAGE]}
            ))
        )


@pytest.mark.unit
def test_a_changed_method_called_through_an_object_is_called() -> None:
    some_summary_before = (
        "class Summary:\n"
        "    def average(self, account):\n"
        "        return 0\n"
    )
    some_summary_after = (
        "class Summary:\n"
        "    def average(self, account):\n"
        "        return account.month\n"
    )
    some_page_calling_the_method = (
        "def render(account, summary):\n"
        "    return summary.average(account)\n"
    )

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {**THE_SHOP, SUMMARY: some_summary_before, PAGE: some_page_calling_the_method},
                {SUMMARY: some_summary_after}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="average", path=PAGE, line=2, function="render",
                              does="calls it: return summary.average(account)")],
                defined={"record": [LEDGER], "reconcile": [RECONCILIATION],
                         "render": [PAGE]}
            ))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("statement", "does"), [
    ("return account.month // 3", "divides with it: account.month // 3"),
    ("return account.month + 3", "adds with it: account.month + 3"),
    ("return account.month - 3", "subtracts with it: account.month - 3"),
    ("return account.month * 3", "multiplies with it: account.month * 3"),
    ("return account.month", "returns it"),
    ("if bought(account) != account.month: pass", "compares it with bought(account)"),
    ("if account.month > limit: pass", "compares it with limit"),
    ("show(account.month)", "passes it to show"),
    ("show(figure=account.month)", "passes it to show as figure"),
    ("account.month = 0", "sets it: account.month = 0"),
    ("figure = account.month", "reads it: figure = account.month")
], ids=["divides", "adds", "subtracts", "multiplies", "returns", "compares",
        "compares-on-the-left", "passes", "passes-by-keyword", "sets", "reads"])
def test_what_a_line_does_with_a_field_is_said_by_the_kind_of_expression_it_sits_in(
        statement: str, does: str) -> None:
    some_reader = "src/shop/reader.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {LEDGER: LEDGER_WRITING_THE_TOTAL,
                 some_reader: f"def reader(account, limit):\n    {statement}\n"},
                {LEDGER: LEDGER_WRITING_THE_MONTH_TOO}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="month", path=some_reader, line=2, function="reader",
                              does=does)],
                defined={"reader": [some_reader]}
            ))
        )


@pytest.mark.unit
@pytest.mark.parametrize(("statement", "does"), [
    ("if bought(account) != account.month: pass",
     "compares it with bought(account), where bought(account) returns sum(account.purchases)"),
    ("return bought(account) - account.month",
     "subtracts with it: bought(account) - account.month, where bought(account) returns "
     "sum(account.purchases)")
], ids=["compares", "subtracts"])
def test_a_field_set_against_a_one_line_function_of_its_file_says_what_that_returns(
        statement: str, does: str) -> None:
    # The write-up counted the reconciliation among the readers that take the
    # stored figure as the month's, from a row that said only that it compares
    # the figure with a call. What the call returns is the purchases added up
    # again, and a function that is one return says that in the tree.
    some_reader = "src/shop/reader.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {LEDGER: LEDGER_WRITING_THE_TOTAL,
                 some_reader: "def bought(account):\n"
                              "    return sum(account.purchases)\n"
                              "\n\n"
                              f"def reader(account):\n    {statement}\n"},
                {LEDGER: LEDGER_WRITING_THE_MONTH_TOO}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="month", path=some_reader, line=6, function="reader",
                              does=does, set_against_a_call=True)],
                defined={"bought": [some_reader], "reader": [some_reader]}
            ))
        )


@pytest.mark.unit
def test_what_a_function_returns_is_quoted_as_its_source_spells_it_on_one_line() -> None:
    # A lone generator argument came back from the tree in two pairs of
    # brackets where the source has one.
    some_reader = "src/shop/reader.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {LEDGER: LEDGER_WRITING_THE_TOTAL,
                 some_reader: "def bought(account):\n"
                              "    return sum(\n"
                              "        purchase.price\n"
                              "        for purchase in account.purchases\n"
                              "    )\n"
                              "\n\n"
                              "def reader(account):\n"
                              "    if bought(account) != account.month: pass\n"},
                {LEDGER: LEDGER_WRITING_THE_MONTH_TOO}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="month", path=some_reader, line=9, function="reader",
                              does="compares it with bought(account), where bought(account) "
                                   "returns sum(purchase.price for purchase in "
                                   "account.purchases)", set_against_a_call=True)],
                defined={"bought": [some_reader], "reader": [some_reader]}
            ))
        )


@pytest.mark.unit
def test_a_field_divided_by_a_one_line_function_of_its_file_is_not_set_against_it() -> None:
    # Dividing by what a function returns uses the figure: only comparing it
    # with what the function returns, or subtracting one from the other,
    # checks it.
    some_reader = "src/shop/reader.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {LEDGER: LEDGER_WRITING_THE_TOTAL,
                 some_reader: "def bought(account):\n"
                              "    return len(account.purchases)\n"
                              "\n\n"
                              "def reader(account):\n"
                              "    return account.month // bought(account)\n"},
                {LEDGER: LEDGER_WRITING_THE_MONTH_TOO}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="month", path=some_reader, line=6, function="reader",
                              does="divides with it: account.month // bought(account), where "
                                   "bought(account) returns len(account.purchases)")],
                defined={"bought": [some_reader], "reader": [some_reader]}
            ))
        )


@pytest.mark.unit
def test_a_field_set_against_a_function_of_more_than_a_return_says_only_the_call() -> None:
    # A body of several statements is no one expression the row could quote.
    some_reader = "src/shop/reader.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {LEDGER: LEDGER_WRITING_THE_TOTAL,
                 some_reader: "def bought(account):\n"
                              "    log(account)\n"
                              "    return sum(account.purchases)\n"
                              "\n\n"
                              "def reader(account):\n"
                              "    if bought(account) != account.month: pass\n"},
                {LEDGER: LEDGER_WRITING_THE_MONTH_TOO}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="month", path=some_reader, line=7, function="reader",
                              does="compares it with bought(account)")],
                defined={"bought": [some_reader], "reader": [some_reader]}
            ))
        )


@pytest.mark.unit
def test_a_read_outside_any_function_has_no_function_to_name() -> None:
    some_module = "src/shop/constants.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {LEDGER: LEDGER_WRITING_THE_TOTAL, some_module: "FIGURE = ACCOUNT.month\n"},
                {LEDGER: LEDGER_WRITING_THE_MONTH_TOO}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="month", path=some_module, line=1, function=None,
                              does="reads it: FIGURE = ACCOUNT.month")],
                defined={}
            ))
        )


@pytest.mark.unit
def test_every_name_defined_outside_the_patch_is_listed_with_every_file_defining_it() -> None:
    # A name two files define is two pieces of code, and a sentence naming it
    # speaks of both.
    some_admin_summary = "src/admin/summary.py"

    Scenario() \
        .when(
            lambda: code_outside_the_patch(
                {**THE_SHOP, some_admin_summary: "class Summary:\n    def average(self):\n"
                                                 "        return 0\n"},
                {LEDGER: LEDGER_WRITING_THE_TOTAL}
            )
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[],
                defined={"Summary": [some_admin_summary],
                         "average": [some_admin_summary, SUMMARY],
                         "reconcile": [RECONCILIATION]}
            ))
        )


@pytest.mark.unit
def test_a_file_that_does_not_parse_is_passed_over() -> None:
    # A file the tree cannot read says nothing it could be wrong about.
    Scenario() \
        .when(
            lambda: code_outside_the_patch({**THE_SHOP, "src/shop/broken.py": "def (account:\n"},
                                           {LEDGER: LEDGER_WRITING_THE_MONTH_TOO})
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[
                    CodeUse(name="month", path=RECONCILIATION, line=2, function="reconcile",
                            does="compares it with bought(account)"),
                    CodeUse(name="month", path=SUMMARY, line=2, function="average",
                            does="divides with it: account.month // count")
                ],
                defined=DONT_CARE_DEFINED
            ))
        )


@pytest.mark.unit
def test_a_patch_to_files_that_are_not_python_changes_nothing_the_tree_can_follow() -> None:
    Scenario() \
        .when(
            lambda: code_outside_the_patch(THE_SHOP, {"deploy/scrape.yaml": "port: metrics\n"})
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[],
                defined={"record": [LEDGER], **DONT_CARE_DEFINED}
            ))
        )
