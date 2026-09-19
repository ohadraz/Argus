#!/usr/bin/env python3
"""
Fails if a column the schema declares is written by nothing.

A column only readers know about is a column whose value is always NULL, and
nothing in the system can tell that from a value that happens to be missing.
`action.subject` lived that way for the whole of its existence: declared,
selected by both reads, consumed by two modules, and set by no INSERT or UPDATE
anywhere - so no incident could ever be remembered and every postmortem read
"revert_feature_flag on None". Every test passed, because builders populate what
production does not.

This is the static half of the answer: a column must have a writer. What it
cannot see - a writer nobody calls, or one that always writes NULL - is what the
per-table tests are for.

A column with a DEFAULT has a writer: the database. `created_at` is set by
`now()` on every insert, and asking the application to repeat that would be
asking for the row's own clock to be written by whoever happened to be holding
a connection.

There is no exemption list, and no such thing as a construction this skips. A
statement whose columns cannot be determined fails, naming the file - the hole
`subject` came through was something nobody was looking at, and a guard that
quietly passes what it cannot read builds the same hole on purpose.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_COLUMN_LIST_SEPARATOR = ", "

# A `CREATE TABLE` body holds these as well as columns, and none of them names
# one. Matched on the first word of an entry.
_CONSTRAINT_WORDS = frozenset(
    {"primary", "unique", "foreign", "constraint", "check", "exclude"}
)

_CREATE_TABLE = re.compile(
    r"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*)\)\s*$",
    re.IGNORECASE | re.DOTALL
)
_CREATE_INDEX = re.compile(r"^CREATE\s+(?:UNIQUE\s+)?INDEX\b", re.IGNORECASE)
_ALTER_ADD = re.compile(
    r"^ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\b(.*)$",
    re.IGNORECASE | re.DOTALL
)
_ALTER_DROP = re.compile(
    r"^ALTER\s+TABLE\s+(\w+)\s+DROP\s+COLUMN\s+(?:IF\s+EXISTS\s+)?(\w+)\b",
    re.IGNORECASE | re.DOTALL
)

_INSERT = re.compile(r"INSERT\s+INTO\s+(\w+)\s*\(([^)]*)\)", re.IGNORECASE | re.DOTALL)
_INSERT_WITHOUT_COLUMNS = re.compile(r"INSERT\s+INTO\s+(\w+)\s+VALUES\b", re.IGNORECASE)
_UPDATE = re.compile(
    r"UPDATE\s+(\w+)\s+SET\s+(.*?)(?=\bWHERE\b|\bRETURNING\b|$)",
    re.IGNORECASE | re.DOTALL
)
_DO_UPDATE = re.compile(
    r"DO\s+UPDATE\s+SET\s+(.*?)(?=\bWHERE\b|\bRETURNING\b|$)", re.IGNORECASE | re.DOTALL
)
_ASSIGNED = re.compile(r"(\w+)\s*=")
# A write, and not a sentence about one. `INSERT INTO x (` or `INSERT INTO x
# VALUES` or `UPDATE x SET` - prose says "an update rather than a second row"
# and means it, and a guard that reported docstrings would be read past.
_WRITE_KEYWORD = re.compile(
    r"\bINSERT\s+INTO\s+\w+\s*[(]|\bINSERT\s+INTO\s+\w+\s+VALUES\b"
    r"|\bUPDATE\s+\w+\s+SET\b",
    re.IGNORECASE
)

# What an unresolved `{...}` becomes, so a statement carrying one is still
# recognisable as an INSERT or an UPDATE and can be reported rather than missed.
_UNRESOLVED = "\x00"


@dataclass
class Table:
    """One table as the schema declares it."""

    name: str
    columns: dict[str, bool] = field(default_factory=dict)
    """Each column, and whether the database writes it by DEFAULT."""


def _the_database_writes_it(declaration: str) -> bool:
    """Whether the column comes out of the database's own hand.

    Three spellings of one thing. A `DEFAULT` fills the column in on every
    insert that omits it; `SERIAL` is a `DEFAULT nextval(...)` written shorter;
    an identity column is the standard spelling of the same idea. None of them
    is an exemption - each is a writer, and the row it writes is a real value
    no application code should be repeating.
    """
    said = declaration.upper()

    return "DEFAULT" in said or "SERIAL" in said or "GENERATED" in said


def _statements_of(ddl: str) -> list[str]:
    """The DDL as statements, with comments and blank space taken out."""
    without_comments = "\n".join(
        line.split("--")[0] for line in ddl.splitlines()
    )

    return [statement.strip() for statement in without_comments.split(";")]


def _entries_of(body: str) -> list[str]:
    """One `CREATE TABLE` body split on the commas that separate its entries.

    Depth-aware, because `NUMERIC(12, 2)` and `CHECK (a IN ('x', 'y'))` both
    carry commas that separate nothing.
    """
    entries: list[str] = []
    depth = 0
    current: list[str] = []

    for character in body:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1

        if character == "," and depth == 0:
            entries.append("".join(current))
            current = []
            continue

        current.append(character)

    entries.append("".join(current))

    return [entry.strip() for entry in entries if entry.strip()]


def _read_the_schema(migrations: Path) -> tuple[dict[str, Table], list[str]]:
    """Every table the migration chain leaves behind, and what could not be read."""
    tables: dict[str, Table] = {}
    unreadable: list[str] = []

    for revision in sorted(migrations.glob("rev_*.py")):
        ddl = _the_ddl_in(revision)

        if ddl is None:
            unreadable.append(
                f"{revision.name}: cannot determine the DDL this revision applies - "
                f"it declares no module-level string holding it."
            )
            continue

        unreadable.extend(_apply(ddl, to=tables, named_by=revision.name))

    return tables, unreadable


def _the_ddl_in(revision: Path) -> str | None:
    """The revision's DDL, taken from its module-level string constants.

    Annotated and plain assignments alike. `rev_001` spells it `_DDL = "..."`
    and the house style for a constant is `_DDL: Final = "..."`, so reading
    only one of the two makes the next revision written properly the revision
    this cannot read.
    """
    tree = ast.parse(revision.read_text(encoding="utf-8"), filename=str(revision))
    statements = [
        bound.value
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and isinstance(bound := node.value, ast.Constant)
        and isinstance(bound.value, str)
        and ("CREATE TABLE" in bound.value.upper()
             or "ALTER TABLE" in bound.value.upper())
    ]

    return "\n".join(statements) if statements else None


def _apply(ddl: str, to: dict[str, Table], named_by: str) -> list[str]:
    """Applies one revision's statements to the tables read so far."""
    unreadable: list[str] = []

    for statement in _statements_of(ddl):
        if not statement:
            continue

        created = _CREATE_TABLE.match(statement)
        if created is not None:
            table = Table(name=created.group(1))
            for entry in _entries_of(created.group(2)):
                first, _, rest = entry.partition(" ")
                if first.lower() in _CONSTRAINT_WORDS:
                    continue
                table.columns[first] = _the_database_writes_it(rest)
            to[table.name] = table
            continue

        added = _ALTER_ADD.match(statement)
        if added is not None:
            to[added.group(1)].columns[added.group(2)] = _the_database_writes_it(
                added.group(3)
            )
            continue

        dropped = _ALTER_DROP.match(statement)
        if dropped is not None:
            to[dropped.group(1)].columns.pop(dropped.group(2), None)
            continue

        if _CREATE_INDEX.match(statement):
            continue

        unreadable.append(
            f"{named_by}: cannot classify this statement - "
            f"{' '.join(statement.split())[:80]}"
        )

    return unreadable


class _Constants:
    """The module-level names one file binds to a list of column names.

    Two ways, because the repository writes them two ways and both are good.
    A tuple of literals is read out of the syntax. A tuple built from a model's
    fields is read out of the model itself - the same source of truth the
    statement uses, which makes this guard schema-against-model drift detection
    for those tables rather than a reading of what somebody typed.
    """

    def __init__(self, tree: ast.Module) -> None:
        self._imported = _imports_of(tree)
        self._bound: dict[str, list[str] | None] = {}

        for node in tree.body:
            # `_WRITTEN: Final = (...)` is an annotated assignment and a plain
            # one is not, and this repository spells its constants the first
            # way - so reading only `Assign` reads none of them.
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.value is not None:
                    self._bound[node.target.id] = self._resolve(node.value)
                continue

            if not isinstance(node, ast.Assign):
                continue

            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._bound[target.id] = self._resolve(node.value)

    def of(self, name: str) -> list[str] | None:
        return self._bound.get(name)

    def _resolve(self, value: ast.expr) -> list[str] | None:
        if isinstance(value, ast.Tuple | ast.List):
            return self._resolve_elements(value.elts)

        if (isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in {"tuple", "list"}
                and len(value.args) == 1):
            return self._resolve(value.args[0])

        if isinstance(value, ast.Attribute) and value.attr == "model_fields":
            return self._fields_of(value.value)

        if isinstance(value, ast.Name):
            return self._bound.get(value.id)

        return None

    def _resolve_elements(self, elements: list[ast.expr]) -> list[str] | None:
        names: list[str] = []

        for element in elements:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                names.append(element.value)
                continue

            spread = (
                self._resolve(element.value)
                if isinstance(element, ast.Starred) else self._resolve(element)
            )

            if spread is None:
                return None

            names.extend(spread)

        return names

    def _fields_of(self, model: ast.expr) -> list[str] | None:
        """The field names of a model this file imports, from the model itself."""
        if not isinstance(model, ast.Name):
            return None

        module = self._imported.get(model.id)

        if module is None:
            return None

        try:
            imported = getattr(importlib.import_module(module), model.id)
            return list(imported.model_fields)
        except (ImportError, AttributeError):
            return None


def _imports_of(tree: ast.Module) -> dict[str, str]:
    """Each name this file imports, and the module it came from."""
    return {
        alias.asname or alias.name: node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
        for alias in node.names
    }


def _sql_strings_of(tree: ast.Module, constants: _Constants) -> list[str]:
    """Every string in the file that might be a statement, resolved where it can be.

    Implicitly concatenated literals arrive already joined - the parser does
    that - so a statement spread over five lines is one constant here. An
    f-string is not, and is rebuilt from its parts: a `", ".join(NAME)` becomes
    the columns `NAME` holds, and anything else becomes a mark that keeps the
    statement recognisable while saying its columns could not be read.
    """
    strings: list[str] = []
    # An f-string's own literal parts are `Constant` nodes too, and `ast.walk`
    # reaches them. Taken on their own they are half a statement - `INSERT INTO
    # postmortem (` - which names a write and has no columns anybody could
    # read, so they would be reported as unreadable while the whole string
    # beside them resolved perfectly.
    fragments = {
        id(part)
        for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
        for part in ast.walk(node) if isinstance(part, ast.Constant)
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in fragments:
                strings.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            strings.append(_rebuild(node, constants))

    return strings


def _rebuild(node: ast.JoinedStr, constants: _Constants) -> str:
    parts: list[str] = []

    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
            continue

        if isinstance(value, ast.FormattedValue):
            parts.append(_joined(value.value, constants) or _UNRESOLVED)

    return "".join(parts)


def _joined(expression: ast.expr, constants: _Constants) -> str | None:
    """`", ".join(NAME)` as the column list it produces, where NAME is known."""
    if not isinstance(expression, ast.Call):
        return None

    method = expression.func

    if not (isinstance(method, ast.Attribute) and method.attr == "join"):
        return None

    if not (isinstance(method.value, ast.Constant)
            and isinstance(method.value.value, str)):
        return None

    if len(expression.args) != 1 or not isinstance(expression.args[0], ast.Name):
        return None

    columns = constants.of(expression.args[0].id)

    return method.value.value.join(columns) if columns is not None else None


def _written_by(statement: str) -> dict[str, set[str]]:
    """The columns this statement sets, by table."""
    written: dict[str, set[str]] = {}

    for table, columns in _INSERT.findall(statement):
        written.setdefault(table, set()).update(
            column.strip() for column in columns.split(",")
        )

    for table, assignments in _UPDATE.findall(statement):
        written.setdefault(table, set()).update(_ASSIGNED.findall(assignments))

    # `ON CONFLICT ... DO UPDATE SET` belongs to the INSERT above it, which is
    # the only table named anywhere in the statement.
    conflicted = _DO_UPDATE.findall(statement)

    if conflicted:
        inserted = _INSERT.findall(statement) or _INSERT_WITHOUT_COLUMNS.findall(
            statement
        )
        if inserted:
            table = inserted[0][0] if isinstance(inserted[0], tuple) else inserted[0]
            for assignments in conflicted:
                written.setdefault(table, set()).update(_ASSIGNED.findall(assignments))

    return written


def _unreadable_in(statement: str, source: Path) -> str | None:
    """Whether this statement writes columns nobody can read off it.

    Asked of the column list and the assignments alone, not of the whole
    statement. `VALUES ({', '.join(['%s'] * len(_WRITTEN))})` is an expression
    this cannot resolve and does not need to: it is placeholders, and the
    columns they stand for were named two clauses earlier.
    """
    regions = [written.group(2) for written in _INSERT.finditer(statement)]
    regions += [assigned.group(2) for assigned in _UPDATE.finditer(statement)]
    regions += _DO_UPDATE.findall(statement)

    names_a_write = (_WRITE_KEYWORD.search(statement) is not None)

    if not names_a_write:
        return None

    if regions and not any(_UNRESOLVED in region for region in regions):
        return None

    if not regions and _INSERT_WITHOUT_COLUMNS.search(statement):
        return None

    return (
        f"{source}: cannot determine the columns written here - the statement is "
        f"built from an expression this guard cannot resolve. Bind the column list "
        f"to a module-level name, or build it from a model's fields."
    )


def _read_the_writers(modules: Path) -> tuple[dict[str, set[str]], list[str]]:
    """Every column any statement in `src/` sets, and what could not be read."""
    written: dict[str, set[str]] = {}
    unreadable: list[str] = []

    for source in sorted(modules.glob("*/src/**/*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        constants = _Constants(tree)

        for statement in _sql_strings_of(tree, constants):
            complaint = _unreadable_in(statement, source)

            if complaint is not None:
                unreadable.append(complaint)
                continue

            for table, columns in _written_by(statement).items():
                written.setdefault(table, set()).update(columns)

    return written, unreadable


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    migrations = (
        repo_root / "modules" / "argus_core" / "src" / "argus_core"
        / "migrations" / "versions"
    )

    tables, unreadable_schema = _read_the_schema(migrations)
    written, unreadable_writers = _read_the_writers(repo_root / "modules")

    unwritten = [
        f"  {table.name}.{column}"
        for table in tables.values()
        for column, defaulted in table.columns.items()
        if not defaulted and column not in written.get(table.name, set())
    ]

    complaints = unreadable_schema + unreadable_writers

    if complaints:
        print(
            "The schema or a statement could not be read, so this guard cannot "
            "say whether every column has a writer:\n"
            + "\n".join(f"  {complaint}" for complaint in complaints),
            file=sys.stderr
        )
        sys.exit(1)

    if unwritten:
        print(
            "These columns are declared and written by nothing - no INSERT names "
            "them, no UPDATE sets them, and no DEFAULT fills them in:\n"
            + "\n".join(unwritten)
            + "\n\nA column only readers know about is always NULL, and nothing can "
              "tell that from a value that happens to be missing. Either write it "
              "where the row is written, or drop it from the schema.",
            file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
