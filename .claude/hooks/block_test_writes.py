#!/usr/bin/env python3
"""
PreToolUse hook: blocks Write/Edit/NotebookEdit against any tests/ directory.

Cross-platform by design — runs via `uv run python`, identical on Windows,
macOS, and Linux. No shell-specific syntax.
"""
import json
import re
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    file_path = payload.get("tool_input", {}).get("file_path", "")

    if re.search(r"(^|[/\\])tests[/\\]", file_path):
        print(
            "Blocked: tests/ is off-limits for Claude. "
            "Propose the test in chat/console instead - the user adds it by hand.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
