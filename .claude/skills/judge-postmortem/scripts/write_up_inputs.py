"""The CLI inputs for the write-up call, from a held replay's request: the
brief, the tool in the API's shape, and HEAD's standing brief as the system
prompt. Run with the workspace interpreter, which has `agent_postmortem`.

A replay of a stale recording can mix revisions - edit brief.txt by hand
afterwards so it says what a fresh run would.

usage: write_up_inputs.py <write_up_request.json> <input dir>
"""

import json
import sys
from pathlib import Path

from agent_postmortem.briefing import STANDING_BRIEF


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)

    raw = request["tools"][0]
    tool = {"name": raw["name"], "description": raw["description"],
            "input_schema": {"type": "object", "properties": raw["properties"],
                             "required": raw["required"], "additionalProperties": False}}

    (out / "brief.txt").write_text(request["transcript"][0]["text"], encoding="utf-8")
    (out / "tool.json").write_text(json.dumps(tool, indent=1), encoding="utf-8")
    (out / "system.txt").write_text(STANDING_BRIEF, encoding="utf-8")
    print(f"{out}: brief, tool {tool['name']}, system prompt")


if __name__ == "__main__":
    main()
