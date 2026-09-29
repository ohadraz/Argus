#!/usr/bin/env python3
"""Checks a drafted hand-apply message before it is sent, not after.

The rules are already written down once, in the Stop hook
`.claude/hooks/check_handoff_edit_format.py`. That hook reads the message out
of the transcript, which means it can only speak after the message has been
shown - the correction then costs the user a second copy of instructions they
have already started applying.

So this is the same check, aimed at a draft. Nothing here restates a rule: the
hook's `complaints_about` is imported and called, so the two can never drift
into disagreeing about what a usable address is.

That hook is deliberately untracked - `.gitignore` names it - so a checkout
without it is an ordinary checkout rather than a broken one. This says there is
nothing to check with and stops, which is a different answer from "the draft is
fine" and is spelled differently below.

    uv run python scripts/check_edit_message.py draft.md
    uv run python scripts/check_edit_message.py -          # read stdin

Exits 0 when the draft is fit to send, 1 with one complaint per line when it is
not, and 2 when it could not be checked at all. Run it on every message that
directs an edit by hand, and fix the draft rather than the correction.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
THE_HOOK = REPOSITORY_ROOT / ".claude" / "hooks" / "check_handoff_edit_format.py"

READ_FROM_STDIN = "-"


def the_hook_module() -> ModuleType:
    """The Stop hook, imported as a module rather than copied.

    By path, because `.claude/hooks/` is not a package and is not on the path:
    a hook is something the harness runs, not something anything imports. What
    is wanted from it is one function, and the alternative to reaching for it
    like this is a second copy of every rule in it.
    """
    specification = importlib.util.spec_from_file_location(
        "check_handoff_edit_format", THE_HOOK
    )

    if specification is None or specification.loader is None:
        raise RuntimeError(f"the edit-format hook could not be loaded from {THE_HOOK}")

    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)

    return module


def drafted_in(argument: str) -> str:
    """The draft to check, from a file or from stdin."""
    if argument == READ_FROM_STDIN:
        return sys.stdin.read()

    return Path(argument).read_text(encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2

    if not THE_HOOK.is_file():
        # Not the same answer as a clean draft, and it must not be able to read
        # as one: a checkout without the hook can check nothing, and exiting 0
        # here would tell every caller that every message was fine.
        print(
            f"No edit-format hook at {THE_HOOK}, so there is nothing to check "
            f"this draft against. The hook is untracked by design; this is a "
            f"checkout without it rather than a fault.",
            file=sys.stderr
        )

        return 2

    complaints = the_hook_module().complaints_about(drafted_in(sys.argv[1]))

    if not complaints:
        return 0

    print("This draft directs an edit without a usable address:", file=sys.stderr)
    for complaint in complaints:
        print(f"- {complaint}", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
