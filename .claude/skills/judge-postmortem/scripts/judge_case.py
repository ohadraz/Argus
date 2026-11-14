"""Render one captured case and set it against the baseline capture.

usage: judge_case.py <case capture dir> <out dir> <baseline text dir>

Writes the pages and PDF as text into <out dir> (through the skill's scripts),
prints Slack's posts, each event kind in the incident's account, and a diff of
each page against the baseline's with ids, clock times and digits masked, so
what is left is what the case changed in words.
"""

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\Users\ohadr\Projects\Argus")
SCRIPTS = REPO / ".claude" / "skills" / "judge-postmortem" / "scripts"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DIGITS = re.compile(r"\d[\d,.:]*")


def masked(text: str) -> list[str]:
    return [DIGITS.sub("#", UUID.sub("<id>", line)) for line in text.splitlines()]


def main() -> None:
    case, out, baseline = (Path(arg) for arg in sys.argv[1:4])
    out.mkdir(parents=True, exist_ok=True)

    for script in ("check_pages.py", "check_pdf.py"):
        subprocess.run([str(PYTHON), "-X", "utf8", str(SCRIPTS / script), str(case), str(out)],
                       check=False)

    slack = case / "slack_posted.json"
    if slack.exists():
        posted = json.loads(slack.read_text(encoding="utf-8"))["posted"]
        starts = [i for i, m in enumerate(posted) if m["text"].startswith("Argus: Received")]
        mine = posted[starts[-1]:] if starts else posted
        print(f"== slack: {len(posted)} posted in all, {len(mine)} from the last opening")
        for message in mine:
            where = "thread " if message.get("thread_ts") else "CHANNEL"
            updated = " (updated)" if message.get("updated") else ""
            print(f"  {where}{updated} {message['text'][:220]}")

    events = case / "db" / "incident_event.json"
    if events.exists():
        rows = json.loads(events.read_text(encoding="utf-8"))
        kinds = [row.get("kind") or row.get("event_type") or row.get("type") for row in rows]
        print(f"== events: {len(rows)}")
        print("  " + ", ".join(str(kind) for kind in kinds))

    for name in ("postmortem_page", "postmortem_pdf", "walk_page"):
        mine, theirs = out / f"{name}.txt", baseline / f"{name}.txt"
        if not mine.exists():
            print(f"== {name}: not captured")
            continue
        diff = list(difflib.unified_diff(masked(theirs.read_text(encoding="utf-8")),
                                         masked(mine.read_text(encoding="utf-8")),
                                         "baseline", "case", n=0, lineterm=""))
        print(f"== {name} vs baseline: {len(diff)} diff lines")
        for line in diff[:120]:
            print("  " + line[:240])


if __name__ == "__main__":
    main()
