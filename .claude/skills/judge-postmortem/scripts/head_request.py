"""A write-up request as HEAD sends it, from a recording too stale for
recorded_request.py: the recorded body (model, system, thinking, effort),
HEAD's submit tool built by HEAD's own submit_postmortem_for - so its fields go
in Argus's order - and the brief you give it (edit a stale brief by hand to say
what a fresh run would, and say what you changed).

Prints which fields differ from the recording, as sent, so a draw is known to
measure exactly the changes it is meant to. Offers only the logs-in-the-gap
field, and refuses a recording offered anything else (lead_effects needs leads
built here first).

Written for drift's regression check on 0ffd4877 (2026-10-22).

usage: head_request.py <recording.request.json> <brief.txt> <out dir>
"""

import json
import sys
from pathlib import Path

from agent_postmortem.briefing import STANDING_BRIEF
from agent_postmortem.prompting import SUBMIT_POSTMORTEM, submit_postmortem_for
from argus_core.models import LogsInTheGap


def dumped(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def system_text(system: object) -> str:
    if isinstance(system, str):
        return system
    return "".join(block["text"] for block in system if block.get("type") == "text")


def main() -> None:
    body = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    brief = Path(sys.argv[2]).read_text(encoding="utf-8")
    out = Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)

    assert len(body["messages"]) == 1, "not a first call: it carries an earlier turn"
    assert len(body["tools"]) == 1, [tool["name"] for tool in body["tools"]]
    assert system_text(body["system"]) == STANDING_BRIEF, "the recorded system is not HEAD's"

    recorded = body["tools"][0]
    recorded_properties = recorded["input_schema"]["properties"]
    recorded_extra = [name for name in recorded_properties
                      if name not in SUBMIT_POSTMORTEM.properties]
    gap = LogsInTheGap(read=True, labels=["G1"], reach_until=None, read_until=None,
                       read_until_the_alert=True)
    head = submit_postmortem_for([], gap) if recorded_extra else SUBMIT_POSTMORTEM
    offered = [name for name in head.properties if name not in SUBMIT_POSTMORTEM.properties]
    assert offered == recorded_extra, f"offered {offered}, recorded beyond HEAD's {recorded_extra}"

    wire = {**{key: value for key, value in recorded.items() if key not in head.to_wire()},
            **head.to_wire()}
    sent = wire["input_schema"]["properties"]
    differs = sorted(name for name in {*sent, *recorded_properties}
                     if dumped(sent.get(name)) != dumped(recorded_properties.get(name)))
    print(f"offered: {offered}")
    print(f"fields that differ from the recording, as sent: {differs}")
    required_as_recorded = set(recorded["input_schema"]["required"])
    print(f"required added: {sorted(set(head.required) - required_as_recorded)}")
    print(f"required dropped: {sorted(required_as_recorded - set(head.required))}")
    print(f"rest of the tool as recorded: "
          f"{dumped({**wire, 'input_schema': None}) == dumped({**recorded, 'input_schema': None})}")

    (out / "request.json").write_text(
        json.dumps({**body, "tools": [wire], "messages": [{"role": "user", "content": brief}]},
                   ensure_ascii=False), encoding="utf-8")
    (out / "brief.txt").write_text(brief, encoding="utf-8", newline="\n")
    print(f"fields in order: {list(wire['input_schema']['properties'])}")


if __name__ == "__main__":
    main()
