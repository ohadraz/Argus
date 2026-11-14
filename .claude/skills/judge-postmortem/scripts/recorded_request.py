"""A request for api_draws.py from a recording's own `.request.json`, as HEAD
sends it: the recorded body with the submit tool rebuilt from HEAD's code, so
its fields go in Argus's order - a recording stores keys sorted, and the
order changes answers - and the recorded brief beside it.

Refuses unless HEAD's tool says what the recorded one says, field for field:
otherwise the recording is not HEAD's input, and a draw from it measures a
request nobody sends.

usage: recorded_request.py <recording.request.json> <out dir>
"""

import json
import sys
from pathlib import Path

from agent_postmortem.prompting import SUBMIT_POSTMORTEM

# The fields only some incidents are offered, in the order the code adds them.
OFFERED_IN_ORDER = ("lead_effects", "logs_show_serving_as_before")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def main() -> None:
    body = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)

    assert len(body["messages"]) == 1, "not a first call: it carries an earlier turn"
    recorded = next(tool for tool in body["tools"] if tool["name"] == SUBMIT_POSTMORTEM.name)
    properties = recorded["input_schema"]["properties"]
    offered = {name: properties[name] for name in OFFERED_IN_ORDER if name in properties}
    unknown = set(properties) - set(SUBMIT_POSTMORTEM.properties) - set(offered)
    assert not unknown, f"fields this script does not know the place of: {unknown}"

    head = SUBMIT_POSTMORTEM.model_copy(update={
        "properties": {**SUBMIT_POSTMORTEM.properties, **offered},
        "required": [*SUBMIT_POSTMORTEM.required, *offered]})
    wire = {**{key: value for key, value in recorded.items() if key not in head.to_wire()},
            **head.to_wire()}
    assert canonical(wire) == canonical(recorded), "HEAD's tool differs from the recording"

    content = body["messages"][0]["content"]
    assert isinstance(content, str)
    (out / "request.json").write_text(json.dumps({**body, "tools": [wire]}, ensure_ascii=False),
                                      encoding="utf-8")
    (out / "brief.txt").write_text(content, encoding="utf-8", newline="\n")
    print(f"{out}: fields in order {list(wire['input_schema']['properties'])}")


if __name__ == "__main__":
    main()
