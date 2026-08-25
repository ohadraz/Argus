#!/usr/bin/env python3
"""
Fails if any test under modules/*/tests/ carries the `e2e` pytest marker.

e2e tests need the full docker-compose stack, which only `uv run python -m nox -s e2e` brings
up - and only for the root `tests/e2e/` directory. See CLAUDE.md's pytest
markers convention.
"""
import ast
import sys
from pathlib import Path


def _mark_name(expr: ast.expr) -> str | None:
    """If `expr` is `pytest.mark.<name>` or `mark.<name>` (bare or called), return `<name>`."""
    target = expr.func if isinstance(expr, ast.Call) else expr
    if not isinstance(target, ast.Attribute):
        return None
    base = target.value
    is_pytest_mark = isinstance(base, ast.Attribute) and base.attr == "mark"
    is_bare_mark = isinstance(base, ast.Name) and base.id == "mark"
    return target.attr if (is_pytest_mark or is_bare_mark) else None


def find_e2e_lines(test_file: Path) -> list[int]:
    """Returns line numbers in `test_file` where an `e2e` pytest mark is applied."""
    tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
    lines: list[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            marks = node.value
            mark_list = marks.elts if isinstance(marks, ast.List | ast.Tuple) else [marks]
            if any(_mark_name(m) == "e2e" for m in mark_list):
                lines.append(node.lineno)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if any(_mark_name(d) == "e2e" for d in node.decorator_list):
                lines.append(node.lineno)

    return lines


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    modules_dir = repo_root / "modules"
    if not modules_dir.exists():
        return

    violations = [
        f"{test_file.relative_to(repo_root)}:{lineno}"
        for test_file in modules_dir.glob("*/tests/**/*.py")
        for lineno in find_e2e_lines(test_file)
    ]

    if violations:
        print(
            "e2e-marked tests found inside a module's tests/ - not allowed.\n"
            "Only `uv run python -m nox -s e2e` brings up docker-compose, "
            "and only for root tests/e2e/.\n"
            "Move these to tests/e2e/ instead:\n" + "\n".join(f"  {v}" for v in violations),
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
