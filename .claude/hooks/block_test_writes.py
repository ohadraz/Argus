#!/usr/bin/env python3
"""
PreToolUse hook: blocks Write/Edit/NotebookEdit against Argus's own tests/
directories, and against the argus_testkit and anthropic_double modules.

argus_testkit is not test cases but the machinery every assertion runs
through — an edit there could neuter every suite in the repo at once
(`all_of` swallowing failures, `eventually` returning True on timeout)
without touching a single test file.

anthropic_double stands in for the model itself. Its recordings are what
the integration and contract suites judge the adapter against; an agent
able to reshape a recording could make its own code pass without the
adapter ever being right. Claude wrote it once, then the door closed.

The tests/ rule is scoped to this repository. It exists to enforce the TDD
policy in AGENTS.md — the human writes the test, the agent writes the code —
and that policy governs Argus's own modules. The demo Target Service is a
fixture held to different standards, and its tests are a regression net
written after the code rather than a specification written before it; a rule
that guards a policy which does not apply there is only friction. The two
module rules stay unscoped, because both modules live here and nowhere else.

Cross-platform by design — runs via `uv run python`, identical on Windows,
macOS, and Linux. No shell-specific syntax.
"""
import json
import re
import sys
from pathlib import Path

# .claude/hooks/block_test_writes.py -> the repository root.
ARGUS_REPO_ROOT = Path(__file__).resolve().parents[2]

TESTS_ANYWHERE = r"(^|[/\\])tests[/\\]"

OFF_LIMITS_EVERYWHERE = (
    r"(^|[/\\])argus_testkit([/\\]|$)",
    r"(^|[/\\])anthropic_double([/\\]|$)",
)


def is_inside_argus(file_path: str) -> bool:
    """Whether this path lands inside Argus's own repository.

    Fails closed: a path that cannot be resolved at all is treated as inside,
    so a malformed or exotic path gets the stricter rule rather than slipping
    past it. A relative path resolves against the current working directory,
    which is what the write itself would do.
    """
    try:
        resolved = Path(file_path).resolve()
    except (OSError, ValueError):
        return True

    return resolved == ARGUS_REPO_ROOT or ARGUS_REPO_ROOT in resolved.parents


def main() -> None:
    payload = json.load(sys.stdin)
    file_path = payload.get("tool_input", {}).get("file_path", "")

    if any(re.search(pattern, file_path) for pattern in OFF_LIMITS_EVERYWHERE):
        print(
            "Blocked: modules/argus_testkit/ and modules/anthropic_double/ are "
            "off-limits for Claude. Propose the change in chat/console instead - "
            "the user applies it by hand.",
            file=sys.stderr,
        )
        sys.exit(2)

    if re.search(TESTS_ANYWHERE, file_path) and is_inside_argus(file_path):
        print(
            "Blocked: tests/ is off-limits for Claude in the Argus repo - the "
            "human writes the test, Claude writes the code (AGENTS.md). Propose "
            "the whole file in chat/console instead.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
