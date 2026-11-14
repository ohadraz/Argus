"""Prints every field of each answer given - draws (W*.json, the tool input)
or a recording (its tool_use input) - one after another, for reading side by
side. A recorded answer that called no tool says what it stopped on instead.

usage: fields.py <answer.json or draw dir>...
"""

import json
import sys
from pathlib import Path


def answers(path: Path) -> list[tuple[str, dict | str]]:
    if path.is_dir():
        return [(f"{path.name}/{draw.stem}", json.loads(draw.read_text(encoding="utf-8")))
                for draw in sorted(path.glob("W*.json"))]
    recorded = json.loads(path.read_text(encoding="utf-8"))
    body = recorded.get("response", recorded)
    called = next((block["input"] for block in body["content"] if block["type"] == "tool_use"),
                  f"no tool called; stopped on {body.get('stop_reason')}")
    return [(path.stem, called)]


for argument in sys.argv[1:]:
    for name, answer in answers(Path(argument)):
        print(f"\n######## {name}")
        if isinstance(answer, str):
            print(answer)
            continue
        for key in ("symptom", "cause_in_plain_words", "root_cause", "still_at_risk",
                    "logs_show_serving_as_before", "reaches_a_cause",
                    "cause_rests_on_an_unrun_reading"):
            print(f"{key}: {answer.get(key)}")
        for number, step in enumerate(answer.get("causal_chain") or [], 1):
            print(f"step {number} {step.get('cites')}: {step.get('step')}")
            for ruled in step.get("ruled_out") or []:
                print(f"   ruled out {ruled.get('cites')}: {ruled.get('what')}")
        for factor in answer.get("contributing_factors") or []:
            print(f"factor {factor.get('addressed_by')}: {factor.get('factor')}")
            print(f"   otherwise: {factor.get('had_it_been_otherwise')}")
        for item in answer.get("action_items") or []:
            print(f"item ({item.get('type')}): {item.get('item')}")
        lessons = answer.get("lessons") or {}
        for kind in ("went_well", "went_wrong", "got_lucky"):
            for lesson in lessons.get(kind) or []:
                print(f"{kind}: {lesson}")
        for assumption in answer.get("assumptions") or []:
            print(f"assumption: {assumption}")
