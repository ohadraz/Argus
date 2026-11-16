"""The written-columns guard, asked of a schema and a source tree built here.

Two things are under test. The one exemption the guard has: a table a
dependency owns, which the revision declaring it names as that dependency's, is
written by the dependency's code and is not looked for in Argus. The exemption
is the dangerous half of the guard. Matched too widely, it waves through a
column of Argus's own that nothing writes - which is the hole the guard was
written to close - so each case says what it exempts and what it does not.

And a statement composed with psycopg's `sql` module rather than spelled as a
string: its column list is read off the names it is composed from, and a list
composed from names nobody can read is reported rather than passed.
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

# The same write, composed as the repositories compose theirs: the columns
# quoted one by one from a module-level name, the placeholders counted off it.
COMPOSED_FROM_NAMED_COLUMNS = '''
from psycopg import sql

_WRITTEN = ("written",)
WRITE = sql.SQL("INSERT INTO ours ({}) VALUES ({})").format(
    sql.SQL(", ").join(map(sql.Identifier, _WRITTEN)),
    sql.SQL(", ").join(sql.Placeholder() * len(_WRITTEN))
)
'''

# Composed the same way from a list nothing in the file binds.
COMPOSED_FROM_COLUMNS_NOBODY_NAMED = '''
from psycopg import sql

WRITE = sql.SQL("INSERT INTO ours ({}) VALUES (%s)").format(
    sql.SQL(", ").join(map(sql.Identifier, the_columns()))
)
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


@pytest.mark.unit
def test_a_write_composed_from_named_columns_writes_them(tmp_path: Path) -> None:
    # Read for the names it quotes, and not for the template's own `{}` - which,
    # read as it is spelled, is a statement writing a column called "{}".
    Scenario() \
        .given(a_tree := _a_tree(tmp_path, SOME_SCHEMA + NAMED_AS_THE_DEPENDENCYS,
                                 writer=COMPOSED_FROM_NAMED_COLUMNS)) \
        .when(lambda: the_findings_over(*a_tree)) \
        .then(_the_unwritten_columns_are([]))


@pytest.mark.unit
def test_a_write_composed_from_columns_nobody_named_is_reported_unreadable(
    tmp_path: Path
) -> None:
    # There is no construction the guard skips: a write whose columns cannot be
    # read is the hole `action.subject` came through, and passing it builds that
    # hole on purpose.
    Scenario() \
        .given(a_tree := _a_tree(tmp_path, SOME_SCHEMA + NAMED_AS_THE_DEPENDENCYS,
                                 writer=COMPOSED_FROM_COLUMNS_NOBODY_NAMED)) \
        .when(lambda: the_findings_over(*a_tree)) \
        .then(_the_writer_is_reported_unreadable())


def _a_tree(root: Path, revision: str, writer: str = SOME_WRITER) -> tuple[Path, Path]:
    """A migration chain of one revision, and a source tree of one writer -
    laid out as the repository lays them out, so the guard reads them the way
    it reads the real ones."""
    migrations = root / "migrations"
    migrations.mkdir()
    (migrations / "rev_001_some_schema.py").write_text(revision, encoding="utf-8")

    modules = root / "modules"
    source = modules / "some_module" / "src" / "some_module"
    source.mkdir(parents=True)
    (source / "writing.py").write_text(writer, encoding="utf-8")

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


def _the_writer_is_reported_unreadable() -> Assertion[Findings]:
    def assertion(findings: Findings) -> bool:
        if not any("writing.py" in said for said in findings.unreadable):
            raise AssertionError(
                f"Expected the writer reported as unreadable, got "
                f"{findings.unreadable or 'nothing'} reported."
            )

        return True

    return assertion
