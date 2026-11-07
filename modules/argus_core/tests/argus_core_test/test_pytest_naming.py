"""Which paths are tests, by the name pytest collects them under.

One rule in one place, because Code-Fix asks it of a patch it is sent and the
read tier asks it of a patch whose fields it reads, and two copies of it are two
chances to disagree.
"""

from __future__ import annotations

import pytest
from argus_core import is_a_test_file
from argus_testkit import Scenario, the_answer_was


@pytest.mark.unit
@pytest.mark.parametrize(("path", "is_a_test"), [
    ("tests/io_shop/test_spend_summary.py", True),
    ("tests/io_shop/spend_summary_test.py", True),
    ("test_spend_summary.py", True),
    ("tests/io_shop/conftest.py", False),
    ("src/io_shop/spend_summary.py", False),
    ("tests/io_shop/test_data.json", False)
], ids=["test-prefix", "test-suffix", "at-the-root", "conftest", "source", "not-python"])
def test_a_test_is_known_by_the_name_pytest_collects_it_under(path: str, is_a_test: bool) -> None:
    Scenario() \
        .when(
            lambda: is_a_test_file(path)
        ) \
        .then(
            the_answer_was(is_a_test)
        )
