"""Which paths are tests, by the name pytest collects them under.

One rule in one place: Code-Fix asks it of a patch it is sent, to know whether
the patch brought its test, and the read tier asks it of a patch whose fields it
reads, because a test's keywords build fixtures rather than write the service's
fields. Two copies of it are two chances to disagree.

By name rather than by place: where a repository keeps its tests is its own
business, and the name is what the runner itself goes by. This module is named
so that it is not one.
"""

from __future__ import annotations

from typing import Final

_PYTHON_SUFFIX: Final = ".py"

# What pytest collects as a test file when nothing tells it otherwise:
# `test_*.py` or `*_test.py`.
_A_TEST_FILE_PREFIX: Final = "test_"
_A_TEST_FILE_SUFFIX: Final = "_test.py"


def is_a_test_file(path: str) -> bool:
    """Whether `path` names a file pytest collects as a test."""
    name = path.rsplit("/", 1)[-1]

    return ((name.startswith(_A_TEST_FILE_PREFIX) and name.endswith(_PYTHON_SUFFIX))
            or name.endswith(_A_TEST_FILE_SUFFIX))
