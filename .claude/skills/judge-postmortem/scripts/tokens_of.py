"""Sum the tokens of every model call in a capture's replay log.

Usage:
  python -I -X utf8 tokens_of.py <capture case dir>

Reads db/replay_log.json; a model call is any row whose call_type is not "mcp".
Prints each call's usage and the total of input, output and cache tokens.
"""

import json
import sys
from pathlib import Path

COUNTED = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")


def usage_in(value: object) -> dict | None:
    if isinstance(value, dict):
        if "usage" in value and isinstance(value["usage"], dict):
            return value["usage"]
        for inner in value.values():
            found = usage_in(inner)
            if found is not None:
                return found
    return None


def main(argv: list[str]) -> None:
    rows = json.loads((Path(argv[1]) / "db" / "replay_log.json").read_text(encoding="utf-8"))
    total = 0
    calls = 0
    for row in rows:
        if row.get("call_type") == "mcp":
            continue
        usage = row.get("response") if isinstance(row.get("response"), dict) else {}
        counted = sum(int(usage.get(key) or 0) for key in COUNTED)
        calls += 1
        total += counted
        print(row.get("seq"), row.get("call_type"), row.get("target"),
              {key: usage.get(key) for key in COUNTED}, counted)
    print(f"{calls} model calls, {total} tokens")


if __name__ == "__main__":
    main(sys.argv)
