"""The written-columns guard, asked of a schema and a source tree built here.

What is under test is the one exemption the guard has: a table a dependency
owns, which the revision declaring it names as that dependency's, is written by
the dependency's code and is not looked for in Argus. The exemption is the
dangerous half of the guard. Matched too widely, it waves through a column of
Argus's own that nothing writes - which is the hole the guard was written to
close - so each case says what it exempts and what it does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_testkit import Assertion, Scenario

from scripts.guard_written_columns import Findings, the_findings_over

# One table of Argus's, written by the source tree below, and one of a
# dependency's, written by nothing here.
SOME_SCHEMA = '''
_DDL = """
CREATE TABLE IF NOT EXISTS ours (
    written TEXT NOT NULL
);
"""

_SOME_DEPENDENCYS_DDL = """
CREATE TABLE IF NOT EXISTS theirs (
    written_elsewhere TEXT NOT NULL
);
"""
'''

NAMED_AS_THE_DEPENDENCYS = '''
_OWNED_BY_A_DEPENDENCY = {"some-dependency": _SOME_DEPENDENCYS_DDL}
'''

SOME_WRITER = '''
WRITE = "INSERT INTO ours (written) VALUES (%s)"
'''


@pytest.mark.unit
def test_a_table_the_revision_names_as_a_dependencys_is_not_looked_for(
    tmp_path: Path
) -> None:
    # Its columns are written by the dependency's code, which is not Argus's to
    # have a writer in.
    Scenario() \
        .given(a_tree := _a_tree(tmp_path, SOME_SCHEMA + NAMED_AS_THE_DEPENDENCYS)) \
        .when(lambda: the_findings_over(*a_tree)) \
        .then(_the_unwritten_columns_are([]))


@pytest.mark.unit
def test_the_same_table_not_named_as_a_dependencys_is_reported(tmp_path: Path) -> None:
    # The exemption is what the revision says, and nothing else: a table that
    # merely looks like a dependency's is Argus's, and a column of it nothing
    # writes is always NULL.
    Scenario() \
        .given(a_tree := _a_tree(tmp_path, SOME_SCHEMA)) \
        .when(lambda: the_findings_over(*a_tree)) \
        .then(_the_unwritten_columns_are(["theirs.written_elsewhere"]))


def _a_tree(root: Path, revision: str) -> tuple[Path, Path]:
    """A migration chain of one revision, and a source tree of one writer -
    laid out as the repository lays them out, so the guard reads them the way
    it reads the real ones."""
    migrations = root / "migrations"
    migrations.mkdir()
    (migrations / "rev_001_some_schema.py").write_text(revision, encoding="utf-8")

    modules = root / "modules"
    writer = modules / "some_module" / "src" / "some_module"
    writer.mkdir(parents=True)
    (writer / "writing.py").write_text(SOME_WRITER, encoding="utf-8")

    return migrations, modules


def _the_unwritten_columns_are(expected: list[str]) -> Assertion[Findings]:
    def assertion(findings: Findings) -> bool:
        if findings.unreadable:
            raise AssertionError(
                f"Expected the schema and the writers read, and the guard could not "
                f"read {findings.unreadable}."
            )

        if findings.unwritten != expected:
            raise AssertionError(
                f"Expected {expected} reported as written by nothing, got "
                f"{findings.unwritten}."
            )

        return True

    return assertion
