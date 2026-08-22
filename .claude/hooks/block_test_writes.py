#!/usr/bin/env python3
"""
PreToolUse hook: blocks Write/Edit/NotebookEdit against any tests/ directory,
and against the argus_testkit module.

argus_testkit is not test cases but the machinery every assertion runs
through — an edit there could neuter every suite in the repo at once
(`all_of` swallowing failures, `eventually` returning True on timeout)
without touching a single test file.

Cross-platform by design — runs via `uv run python`, identical on Windows,
macOS, and Linux. No shell-specific syntax.
"""
import json
import re
import sys

OFF_LIMITS = (
    r"(^|[/\\])tests[/\\]",
    r"(^|[/\\])argus_testkit([/\\]|$)",
)


def main() -> None:
    payload = json.load(sys.stdin)
    file_path = payload.get("tool_input", {}).get("file_path", "")

    if any(re.search(pattern, file_path) for pattern in OFF_LIMITS):
        print(
            "Blocked: tests/ and modules/argus_testkit/ are off-limits for Claude. "
            "Propose the test in chat/console instead - the user adds it by hand.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
