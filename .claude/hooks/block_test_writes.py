#!/usr/bin/env python3
"""
PreToolUse hook: blocks Write/Edit/NotebookEdit against any tests/ directory,
and against the argus_testkit and anthropic_double modules.

argus_testkit is not test cases but the machinery every assertion runs
through — an edit there could neuter every suite in the repo at once
(`all_of` swallowing failures, `eventually` returning True on timeout)
without touching a single test file.

anthropic_double stands in for the model itself. Its recordings are what
the integration and contract suites judge the adapter against; an agent
able to reshape a recording could make its own code pass without the
adapter ever being right. Claude wrote it once, then the door closed.

Cross-platform by design — runs via `uv run python`, identical on Windows,
macOS, and Linux. No shell-specific syntax.
"""
import json
import re
import sys

OFF_LIMITS = (
    r"(^|[/\\])tests[/\\]",
    r"(^|[/\\])argus_testkit([/\\]|$)",
    r"(^|[/\\])anthropic_double([/\\]|$)",
)


def main() -> None:
    payload = json.load(sys.stdin)
    file_path = payload.get("tool_input", {}).get("file_path", "")

    if any(re.search(pattern, file_path) for pattern in OFF_LIMITS):
        print(
            "Blocked: tests/, modules/argus_testkit/ and modules/anthropic_double/ "
            "are off-limits for Claude. Propose the change in chat/console instead - "
            "the user applies it by hand.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
