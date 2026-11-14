"""For every write-up recording committed at a revision (the accepted answer per
case), lists the causal-chain steps that cite a reading of the source (an F
row) and says what else each cites: F rows alone, F beside an S or D row (read
at the running revision), or F beside only other rows (logs, the walk, ...).

usage: f_steps_at.py <revision>
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
latest: dict[str, tuple[int, str]] = {}
for path in (line.split(":", 1)[1] for line in listed.splitlines() if line):
    stem = path.rsplit("/", 1)[1][:-len(".json")]
    found = re.match(r"(.*?)(?:-(\d+))?$", stem)
    case, number = found.group(1), int(found.group(2) or 1)
    if case not in latest or number > latest[case][0]:
        latest[case] = (number, path)

reading = re.compile(r"^F\d+$")
read_at_revision = re.compile(r"^[SD]\d+$")
for case, (_, path) in sorted(latest.items()):
    body = json.loads(git("show", f"{revision}:{path}"))
    body = body.get("response", body)
    called = next((block["input"] for block in body.get("content", [])
                   if block.get("type") == "tool_use"
                   and "causal_chain" in block.get("input", {})), None)
    if called is None:
        continue
    for index, step in enumerate(called.get("causal_chain") or [], 1):
        cites = step.get("cites") or []
        if not any(reading.match(label) for label in cites):
            continue
        if all(reading.match(label) for label in cites):
            kind = "F ALONE (box left for a person today)"
        elif any(read_at_revision.match(label) for label in cites):
            kind = "F beside S/D (ticked today)"
        else:
            kind = "F beside only other rows (ticked today)"
        print(f"{case} step {index} {cites}: {kind}")
