"""A request for api_draws.py from a held replay's capture, as HEAD sends it:
the write-up call's settings from any recorded request of this agent, HEAD's
standing brief, HEAD's submit tool for this incident - in Argus's own order,
which a recording does not keep (it stores keys sorted, and the order changes
answers) - and the captured brief.

The tool is built by HEAD's own `submit_postmortem_for`, never recomposed
here: every variant it can send this incident - the cause fields asked or left
out, what went well asked who formed a confirmed cause or not, with the leads'
field where the capture has one, the logs' field where it has that, and the
field for what stops the harm where it has that (stand-ins only switch those on:
the schemas are HEAD's constants). The capture is
accepted only if it equals one of them field for field and in what it requires,
and the request is built from the one it matched. A capture whose tool HEAD
cannot send is refused. The brief is not checked - which is why the captures
come from a held replay on HEAD.

usage: draw_request.py <write_up_request.json> <any write-up .request.json> <out dir>
"""

import json
import sys
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

from agent_postmortem.briefing import STANDING_BRIEF
from agent_postmortem.prompting import (
    LEAD_EFFECTS_FIELD,
    LOGS_SHOW_SERVING_AS_BEFORE_FIELD,
    STOPS_THE_HARM_FIELD,
    submit_postmortem_for,
)
from argus_core.models import LogsInTheGap, Reference, ThreadMessage, ToolDefinition

# What switches HEAD's optional fields on; their schemas are HEAD's constants.
A_STAND_IN_LEAD = ThreadMessage(incident_id="00000000-0000-0000-0000-000000000000",
                                message=Reference(source="stand-in", kind="stand-in",
                                                  value="stand-in"),
                                person_id="stand-in", text="stand-in",
                                written_at=datetime(2026, 1, 1, tzinfo=UTC))
A_STAND_IN_GAP = LogsInTheGap(read=True, labels=["G1"],
                              reach_until=datetime(2026, 1, 1, tzinfo=UTC),
                              read_until=None, read_until_the_alert=False)


def system_text(system: object) -> str:
    if isinstance(system, str):
        return system
    return "".join(block["text"] for block in system if block.get("type") == "text")


def the_same(head: ToolDefinition, tool: dict[str, Any]) -> bool:
    """Whether HEAD's tool is the capture's, field for field and in what it
    requires - whatever order either lists them in."""
    fields = {*head.properties, *tool["properties"]}
    return (all(json.dumps(head.properties.get(name), sort_keys=True)
                == json.dumps(tool["properties"].get(name), sort_keys=True)
                for name in fields)
            and sorted(head.required) == sorted(tool["required"]))


def main() -> None:
    captured = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    template = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    out = Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)

    tool = captured["tools"][0]
    leads = [A_STAND_IN_LEAD] if LEAD_EFFECTS_FIELD in tool["properties"] else []
    gap = A_STAND_IN_GAP if LOGS_SHOW_SERVING_AS_BEFORE_FIELD in tool["properties"] else None
    harm = STOPS_THE_HARM_FIELD in tool["properties"]
    variants = {(asked, confirmed): submit_postmortem_for(leads, gap, cause_asked=asked,
                                                          cause_confirmed=confirmed,
                                                          harm_left_standing=harm)
                for asked, confirmed in product((True, False), repeat=2)}
    matched = [(which, head) for which, head in variants.items() if the_same(head, tool)]
    assert matched, "the capture's tool is none HEAD can send this incident"
    (asked, confirmed), head = matched[0]
    assert system_text(template["system"]) == STANDING_BRIEF, "template's system is not HEAD's"

    recorded_tool = template["tools"][0]
    wire = {**{key: value for key, value in recorded_tool.items()
               if key not in head.to_wire()}, **head.to_wire()}
    body = {**template, "tools": [wire],
            "messages": [{"role": "user", "content": captured["transcript"][0]["text"]}]}

    (out / "request.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    (out / "brief.txt").write_text(captured["transcript"][0]["text"], encoding="utf-8",
                                   newline="\n")
    print(f"{out}: cause asked {asked}, cause confirmed {confirmed}, "
          f"fields in order {list(wire['input_schema']['properties'])}")


if __name__ == "__main__":
    main()
