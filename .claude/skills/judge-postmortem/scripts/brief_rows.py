"""Print the log-group rows of a captured write-up request, and where the brief
says Argus first acted.

Usage:
  python -I -X utf8 brief_rows.py <write_up_request.json>

Finds every line of the first user turn that carries a log group's label
([G....]), so the rows the model was shown can be read without the rest of the
brief.
"""

import json
import re
import sys
from pathlib import Path

A_GROUP_ROW = re.compile(r"\[G[0-9a-f]{4}\]")


def texts_of(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [block.get("text", "") for block in content or []
            if isinstance(block, dict) and block.get("type") == "text"]


def main(argv: list[str]) -> None:
    request = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    turns = request["transcript"]
    keys = sorted(turns[0]) if isinstance(turns[0], dict) else type(turns[0])
    print(f"{len(turns)} turns; first turn keys: {keys}")
    first = turns[0]
    content = (first.get("content", first.get("text")) if isinstance(first, dict) else first)
    for text in texts_of(content):
        for line in text.splitlines():
            if A_GROUP_ROW.search(line) or "first acted" in line.lower():
                print(line)


if __name__ == "__main__":
    main(sys.argv)
