"""Prints the symptom and the first causal-chain step of every write-up
recording committed at a revision - the highest-numbered answer per case, the
accepted one - so the shape of step 1 can be compared across revisions.

usage: steps_at.py <revision>
"""

import json
import re
import subprocess
import sys

REPO = r"C:\Users\ohadr\Projects\Argus"
revision = sys.argv[1]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


listed = git("grep", "-l", "causal_chain", revision, "--",
             "modules/anthropic_double/recordings/both-*.json", ":!*.request.json")
paths = [line.split(":", 1)[1] for line in listed.splitlines() if line]

latest: dict[str, tuple[int, str]] = {}
for path in paths:
    stem = path.rsplit("/", 1)[1][:-len(".json")]
    found = re.match(r"(.*?)(?:-(\d+))?$", stem)
    case, number = found.group(1), int(found.group(2) or 1)
    if case not in latest or number > latest[case][0]:
        latest[case] = (number, path)

for case, (number, path) in sorted(latest.items()):
    answer = json.loads(git("show", f"{revision}:{path}"))
    body = answer.get("response", answer)
    called = next((block["input"] for block in body.get("content", [])
                   if block.get("type") == "tool_use"
                   and "causal_chain" in block.get("input", {})), None)
    if called is None:
        continue
    chain = called.get("causal_chain") or [{}]
    print(f"== {case} (answer {number})")
    print("   SYMPTOM:", called.get("symptom"))
    print("   STEP 1: ", chain[0].get("step"))
