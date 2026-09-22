"""Assertion messages that do not read as sentences.

A failing test's message is read once, in a hurry, next to fifty others. What
makes a wall of them scannable is that they all start and end the same way, and
the majority here already do: a capital, and a full stop. The ones that do not
are not wrong so much as inconsistent, which is the thing that costs a reader.

Reports rather than fails, for the same reason `find_duplicate_helpers.py` does -
this is a convention with real exceptions, not a contract. A message that opens
with an interpolated value has nothing to capitalise, and one that ends in a
rendered mapping reads worse with a stop after the brace.

Run it with `uv run python scripts/check_assertion_style.py`.
"""

from __future__ import annotations

import ast
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent

# A message may end on any of these and still be a finished sentence.
CLOSERS = (".", "?", ":", "!")


def message_of(node: ast.expr) -> str | None:
    """The literal text of a message, with interpolations shown as `{}`.

    Implicit concatenation and f-strings both arrive as one string, so a message
    split across three source lines is judged as the sentence it renders as
    rather than as its first fragment.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None

    if isinstance(node, ast.JoinedStr):
        rendered = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                rendered.append(part.value)
            else:
                rendered.append("{}")
        return "".join(rendered)

    return None


def opens_badly(message: str) -> bool:
    """Starts lowercase, having something it could have capitalised."""
    head = message.lstrip()

    return bool(head) and head[0].isalpha() and not head[0].isupper()


def closes_badly(message: str) -> bool:
    """Ends without a stop, on something a stop would sit well after.

    A message ending in an interpolated value is excluded: those render as a
    list, a mapping or a repr, and a full stop after a closing brace reads as
    part of the value rather than as punctuation.
    """
    tail = message.rstrip()

    return bool(tail) and not tail.endswith(CLOSERS) and not tail.endswith("}")


def main() -> int:
    opens: dict[str, list[tuple[int, str]]] = defaultdict(list)
    closes: dict[str, list[tuple[int, str]]] = defaultdict(list)
    total = 0

    for base in (ROOT / "modules", ROOT / "tests"):
        for path in base.rglob("*.py"):
            if "recordings" in path.parts:
                continue

            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            where = str(path.relative_to(ROOT)).replace("\\", "/")

            for node in ast.walk(tree):
                if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                    continue
                if getattr(node.exc.func, "id", None) != "AssertionError":
                    continue
                if not node.exc.args:
                    continue

                message = message_of(node.exc.args[0])
                if message is None:
                    continue

                total += 1
                if opens_badly(message):
                    opens[where].append((node.lineno, message[:66]))
                if closes_badly(message):
                    closes[where].append((node.lineno, message[-66:]))

    for heading, found in (
        ("Not starting with a capital", opens),
        ("Not ending in a full stop", closes)
    ):
        count = sum(len(rows) for rows in found.values())
        print(f"\n{'=' * 72}\n{heading}  ({count})\n{'=' * 72}")

        for where in sorted(found):
            print(f"  {where}")
            for line, text in sorted(found[where]):
                print(f"      {line}: {text}")

    print(f"\n{total} assertion messages checked.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
