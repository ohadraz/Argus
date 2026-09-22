"""Test helpers defined identically in more than one file, and where each could live.

Reports rather than fails. A duplicated builder is not a defect the way a broken
layering contract is - two suites that happen to need the same two-line fixture
are not coupled by it - so this prints what it found and exits zero. What makes
it worth running is the classification: the same duplicate has a different right
answer depending on who shares it, and that answer is not obvious from the
duplicate itself.

Bodies are compared with their docstrings removed, so two copies that differ
only in whitespace, quoting or prose still count as one. That last part is not a
nicety: a helper copied into a second file and then given a fuller explanation
there is exactly the copy nobody remembers, and comparing the prose along with
the code hides it. Names are ignored entirely - a helper renamed on its way into
a second file is the same duplication, and matching on names would miss it while
flagging every `_an_alert` that happens to build a different alert.

Run it with `uv run python scripts/find_duplicate_helpers.py`.
"""

from __future__ import annotations

import ast
import hashlib
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Imports that do not stop a helper moving into `argus_testkit`. Anything else
# it reaches for is a package, and the testkit declares `dependencies = []` -
# depending back on the code under test would close a cycle, which is a worse
# thing to own than a duplicated builder.
CARRIED_ANYWHERE = frozenset({
    "__future__", "abc", "collections", "contextlib", "dataclasses", "datetime",
    "decimal", "email", "enum", "functools", "hashlib", "itertools", "json",
    "math", "os", "pathlib", "random", "re", "string", "textwrap", "time",
    "typing", "unittest", "uuid", "argus_testkit"
})


def owning_module(path: str) -> str:
    """Which module's suite a test file belongs to, or the root suite."""
    parts = path.split("/")

    if parts[0] == "tests":
        return "<root tests>"

    return parts[1] if parts[0] == "modules" else "<unknown>"


def names_brought_in(tree: ast.Module) -> dict[str, str]:
    """Every imported name, mapped to the top-level package it came from."""
    brought: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                brought[alias.asname or alias.name] = node.module.split(".")[0]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                brought[alias.asname or alias.name.split(".")[0]] = alias.name.split(".")[0]

    return brought


def packages_needed(node: ast.FunctionDef, brought: dict[str, str]) -> set[str]:
    """Which real packages a helper would drag along if it were moved."""
    used = {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}
    used |= {inner.attr for inner in ast.walk(node) if isinstance(inner, ast.Attribute)}

    return {
        brought[name] for name in used
        if name in brought and brought[name] not in CARRIED_ANYWHERE
    }


def without_annotations(node: ast.AST) -> ast.AST:
    """The same tree with every type annotation dropped.

    Two helpers that differ only in how tightly they type an argument are one
    helper - `(double: Any)` and `(double: Mock)` set the same attribute on the
    same object. Six copies of one mock-arranging step hid behind exactly that,
    and the looser annotation is usually the later copy.
    """
    for inner in ast.walk(node):
        if isinstance(inner, ast.arg):
            inner.annotation = None
        elif isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef):
            inner.returns = None
        elif isinstance(inner, ast.AnnAssign):
            inner.annotation = ast.Constant(value=None)

    return node


def without_docstrings(node: ast.AST) -> ast.AST:
    """The same tree with every docstring dropped, nested functions included.

    What is being compared is what a helper *does*. Prose that drifted while the
    code did not is still one helper in two places - and it is the likelier
    shape, since whoever copied it is the one who then explained it better.
    """
    for inner in ast.walk(node):
        if not isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue

        first = inner.body[0] if inner.body else None
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            inner.body = inner.body[1:] or [ast.Pass()]

    return node


def is_a_fixture(node: ast.FunctionDef) -> bool:
    """Whether pytest hands this out rather than a caller calling it.

    Matters for where it can go: a fixture shared between two files in one
    module belongs in that module's `conftest.py`, which is the only place
    pytest looks - moving it to a framework module makes it an ordinary
    function every test then has to call and remember to make fresh.
    """
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True

    return False


def collect() -> dict[str, list[tuple[str, str, bool, set[str]]]]:
    """Every top-level test helper, grouped by the body it shares."""
    groups: dict[str, list[tuple[str, str, bool, set[str]]]] = defaultdict(list)

    for base in (ROOT / "modules", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if "recordings" in path.parts or "tests" not in path.parts:
                continue

            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            brought = names_brought_in(tree)
            where = str(path.relative_to(ROOT)).replace("\\", "/")

            for node in tree.body:
                if not isinstance(node, ast.FunctionDef) or node.name.startswith("test_"):
                    continue

                normalised = ast.dump(
                    without_annotations(
                        without_docstrings(ast.parse(ast.unparse(node)).body[0])
                    )
                )
                digest = hashlib.sha256(normalised.encode()).hexdigest()[:12]
                groups[digest].append(
                    (node.name, where, is_a_fixture(node), packages_needed(node, brought))
                )

    return groups


def duplicated_constants() -> dict[tuple[str, str], list[str]]:
    """Module-level constants declared under the same name and value twice.

    Same name *and* same value, because either alone says nothing: two suites
    that both call a service `"checkout"` have not shared anything, and two
    that spell one format differently under different names are two bugs rather
    than one duplicate. Together they are a value somebody copied.

    Reported apart from the helpers, since a constant beside a duplicated
    builder is easy to lift with it and easy to leave behind - `TIMESTAMP_FORMAT`
    sat next to `_an_iso_minute` through a pass that moved only the function.
    """
    seen: dict[tuple[str, str], list[str]] = defaultdict(list)

    for base in (ROOT / "modules", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if "recordings" in path.parts or "tests" not in path.parts:
                continue

            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            where = str(path.relative_to(ROOT)).replace("\\", "/")

            for node in tree.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    target, value = node.targets[0], node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    target, value = node.target, node.value
                else:
                    continue

                if not isinstance(target, ast.Name) or not target.id.isupper():
                    continue

                seen[(target.id, ast.unparse(value))].append(where)

    return {what: files for what, files in seen.items() if len({*files}) > 1}


def classify(files: list[str], fixture: bool, needs: set[str]) -> tuple[str, str]:
    """Where a shared copy could live, and the one-line reason."""
    owners = {owning_module(f) for f in files}

    if owners == {"<root tests>"}:
        return "B", "tests/framework/"

    if len(owners) == 1:
        module = next(iter(owners))
        if fixture:
            return "A", f"modules/{module}/tests/{module}_test/conftest.py"

        return "A", f"modules/{module}/tests/{module}_test/framework/"

    if needs:
        return "D", f"nowhere - would need {', '.join(sorted(needs))}"

    return "C", "argus_testkit"


def main() -> int:
    buckets: dict[str, list[tuple[str, list[str], str]]] = defaultdict(list)

    for entries in collect().values():
        files = sorted({where for _, where, _, _ in entries})
        if len(files) < 2:
            continue

        name = entries[0][0]
        fixture = any(is_fixture for _, _, is_fixture, _ in entries)
        needs: set[str] = set()
        for _, _, _, package in entries:
            needs |= package

        bucket, destination = classify(files, fixture, needs)
        buckets[bucket].append((name, files, destination))

    headings = {
        "A": "One module's own suites - lift into that module",
        "B": "The root suites - lift into tests/framework/",
        "C": "Several modules, carrying nothing - argus_testkit can hold it",
        "D": "Several modules, but it would drag a package along - leave it"
    }

    total = 0
    for bucket in "ABCD":
        rows = sorted(buckets[bucket])
        total += len(rows)
        print(f"\n{'=' * 72}")
        print(f"{bucket}. {headings[bucket]}  ({len(rows)})")
        print("=" * 72)

        for name, files, destination in rows:
            print(f"  {name}  ->  {destination}")
            for where in files:
                print(f"      {where}")

    constants = duplicated_constants()
    print(f"\n{'=' * 72}")
    print(f"Constants declared identically in more than one file  ({len(constants)})")
    print("=" * 72)
    print("  Mostly data, and mostly fine. Two suites naming a flag the same thing")
    print("  share nothing; read this list for the few that are infrastructure - a")
    print("  format, a timeout, a window - and leave the DONT_CARE_ and SOME_ ones.\n")

    for (name, value), files in sorted(constants.items()):
        print(f"  {name} = {value}")
        for where in sorted({*files}):
            print(f"      {where}")

    print(f"\n{total} duplicated helpers, {len(constants)} duplicated constants.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
