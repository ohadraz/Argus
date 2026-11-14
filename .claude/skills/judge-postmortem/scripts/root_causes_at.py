"""Prints the root cause of each named case's accepted write-up at a revision.

usage: root_causes_at.py <revision> <case>...
"""

import json
import re
import subprocess
import sys

REPO = r"C:\Users\ohadr\Projects\Argus"
revision, cases = sys.argv[1], set(sys.argv[2:])


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
    if case in cases and (case not in latest or number > latest[case][0]):
        latest[case] = (number, path)

for case, (_, path) in sorted(latest.items()):
    body = json.loads(git("show", f"{revision}:{path}"))
    body = body.get("response", body)
    called = next((block["input"] for block in body["content"]
                   if block.get("type") == "tool_use" and "causal_chain" in block["input"]), None)
    if called is None:
        print(f"== {case}: its latest recording holds no write-up tool call")
        continue
    print(f"== {case}: {called.get('root_cause')}")
