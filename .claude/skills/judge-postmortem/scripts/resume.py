"""What happened after the judge's handover was written, read back on resume.

usage, through the judge's one allowlisted command, from the repository root:
  uv run python .claude/skills/judge-postmortem/scripts/judge_capture.py resume <jsonl> [<since>]

<jsonl> is the judge's last session transcript, under ~/.claude/projects/<project>/.
<since> is a UTC instant such as 2026-11-14T12:45:00; left out, it is
.claude/HANDOVER-1f.md's own modified time, so nothing is worked out by hand.

Writes two files under .claude/local/resume/: tail.md, the transcript's user
text, assistant text, tool calls and tool results (the last two cut short) in
order; and peer-messages.md, every cross-session message from then on, whole and
once each - one absorbed mid-turn arrives as an attachment the text blocks miss.
Prints the instant used and how many of each.
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]
HANDOVER = REPO / ".claude" / "HANDOVER-1f.md"
OUT = REPO / ".claude" / "local" / "resume"
PEER_MESSAGE = re.compile(r"<cross-session-message\b.*?</cross-session-message>", re.DOTALL)
TOOL_INPUT_CHARACTERS = 3000
TOOL_RESULT_CHARACTERS = 1500


def handover_written() -> str:
    """The handover file's modified time, in UTC, spelled as the transcript stamps it."""
    written = datetime.fromtimestamp(HANDOVER.stat().st_mtime, tz=UTC)
    return written.strftime("%Y-%m-%dT%H:%M:%S")


def texts_of(record: dict[str, Any]) -> list[str]:
    """A record's user or assistant text, each tool call's input and each tool
    result, the last two cut short."""
    message = record.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    parts = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind == "tool_use":
            given = json.dumps(block.get("input"), ensure_ascii=False)
            parts.append("TOOL_USE " + given[:TOOL_INPUT_CHARACTERS])
        elif kind == "tool_result":
            inner = block.get("content")
            if isinstance(inner, list):
                inner = " ".join(item.get("text", "") for item in inner if isinstance(item, dict))
            parts.append("TOOL_RESULT " + str(inner)[:TOOL_RESULT_CHARACTERS])
    return parts


def strings_in(value: Any) -> list[str]:
    """Every string anywhere in a parsed record, decoded, so a message reads with
    its own line breaks wherever in the record it was carried."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [found for item in value.values() for found in strings_in(item)]
    if isinstance(value, list):
        return [found for item in value for found in strings_in(item)]
    return []


def main(argv: list[str]) -> None:
    if not 2 <= len(argv) <= 3:
        print(__doc__)
        sys.exit(2)
    transcript = Path(argv[1])
    since = argv[2] if len(argv) == 3 else handover_written()
    tail: list[str] = []
    messages: list[str] = []
    seen: set[str] = set()
    for raw in transcript.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stamp = record.get("timestamp", "")
        if stamp < since:
            continue
        role = record.get("type", "?")
        tail += [f"=== {role} {stamp}\n{text}\n" for text in texts_of(record)]
        for text in strings_in(record):
            for found in PEER_MESSAGE.findall(text):
                if found not in seen:
                    seen.add(found)
                    messages.append(f"=== {stamp}\n{found}\n")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tail.md").write_text("\n".join(tail), encoding="utf-8")
    (OUT / "peer-messages.md").write_text("\n".join(messages), encoding="utf-8")
    print(f"since {since} UTC")
    print(f"{len(tail)} entries in {OUT / 'tail.md'}")
    print(f"{len(messages)} peer messages in {OUT / 'peer-messages.md'}")


if __name__ == "__main__":
    main(sys.argv)
