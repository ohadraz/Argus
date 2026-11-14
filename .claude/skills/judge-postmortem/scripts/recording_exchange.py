"""A recorded answer and the request it answered, as text: every message of
the request (the brief, earlier answers, refusals), then the answer with its
thinking and tool calls, then its usage.

usage: recording_exchange.py <out dir> <recording.json>...
       (each recording's <name>.request.json is read beside it)
"""

import json
import sys
from pathlib import Path
from typing import Any


def texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]

    out: list[str] = []
    for block in content or []:
        kind = block.get("type")
        if kind == "text":
            out.append(block["text"])
        elif kind == "thinking":
            out.append("[THINKING]\n" + block.get("thinking", ""))
        elif kind == "tool_use":
            out.append("[TOOL_USE]\n" + json.dumps(block["input"], indent=1, ensure_ascii=False))
        elif kind == "tool_result":
            out.append("[TOOL_RESULT]\n" + "\n".join(texts(block.get("content"))))
    return out


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    for name in sys.argv[2:]:
        recording = Path(name)
        request = json.loads(recording.with_suffix(".request.json").read_text(encoding="utf-8"))
        answer = json.loads(recording.read_text(encoding="utf-8"))
        body = answer.get("response", answer)

        lines: list[str] = []
        for message in request.get("messages", []):
            lines.append(f"===== {message['role']}")
            lines.extend(texts(message["content"]))
        lines.append("===== ANSWER")
        lines.extend(texts(body.get("content")))
        lines.append(f"usage: {body.get('usage')}")

        written = out / f"{recording.stem}.txt"
        written.write_text("\n".join(lines), encoding="utf-8")
        print(f"{written}: {len(request.get('messages', []))} messages in the request")


if __name__ == "__main__":
    main()
