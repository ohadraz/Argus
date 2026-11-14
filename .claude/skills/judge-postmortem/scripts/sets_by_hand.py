"""Each log group's minutes after Argus first acted, worked from the captured
record without Argus's code, against what the captured brief said.

Usage:
  python -I -X utf8 sets_by_hand.py <capture case dir> [<capture case dir> ...]

From db/: the act is the earliest performed action, dated by its last
action-taken announcement (its row's taken_at where none was made), as
argus_incidents.dating says it. The lines are every logs-retrieved read's. A
group is keyed by its message with every number taken out, and labelled G plus
the first four hex characters of the key's sha1, as log_groups documents. A
group's set is the distinct minutes of the lines whose stamp names an instant
later than the act - none where any line of it is undated - in runs of
consecutive minutes, split where a minute is a day or more after the one before.

From write_up_request.json: each row's text after "After Argus first acted,
logged in", with the figure names taken out. Prints MATCH or DIFFERS per group.
"""

import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PHRASE = "After Argus first acted, logged in "
STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)?)\s+")
NUMBER = re.compile(r"(\d+(?:\.\d+)?)")
ROW = re.compile(r"\[(G[0-9a-f]{4})\]")
NAME = re.compile(r" \{G[0-9a-f]{4}\.\d+\}")
A_DAY_BEFORE = re.compile(r"^[A-Z][a-z]{2} \d{1,2} ")
MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)


def instant(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace(" ", "T"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def the_act(db: Path) -> datetime | None:
    actions = json.loads((db / "action.json").read_text(encoding="utf-8"))
    events = json.loads((db / "incident_event.json").read_text(encoding="utf-8"))
    taken = []
    for action in actions:
        if action.get("progress") != "performed":
            continue
        announced = [instant(event["payload"]["at"]) for event in events
                     if event.get("kind") == "action-taken"
                     and event["payload"].get("hypothesis_id") == action.get("hypothesis_id")
                     and action.get("hypothesis_id") is not None]
        taken.append(announced[-1] if announced else instant(action["taken_at"]))
    return min(taken, default=None)


def the_lines(db: Path) -> list[str]:
    events = json.loads((db / "incident_event.json").read_text(encoding="utf-8"))
    return [line for event in sorted(events, key=lambda row: row["seq"])
            if event.get("kind") == "logs-retrieved"
            for line in event["payload"].get("lines", [])]


def label_of(message: str) -> str:
    key = "#".join(NUMBER.split(message)[0::2])
    return "G" + hashlib.sha1(key.encode()).hexdigest()[:4]


def said_as_sets(minutes: list[datetime]) -> list[str]:
    sets: list[list[datetime]] = []
    for minute in minutes:
        if sets and minute - sets[-1][-1] < DAY:
            sets[-1].append(minute)
        else:
            sets.append([minute])

    said = []
    for each in sets:
        runs: list[list[datetime]] = []
        for minute in each:
            if runs and minute - runs[-1][-1] == MINUTE:
                runs[-1].append(minute)
            else:
                runs.append([minute])
        said.append(",".join(f"{run[0]:%H:%M}" if len(run) == 1
                             else f"{run[0]:%H:%M}–{run[-1]:%H:%M}" for run in runs)
                    + f"   (first on {each[0]:%Y-%m-%d})")
    return said


def by_hand(case: Path) -> dict[str, list[str]]:
    db = case / "db"
    act = the_act(db)
    print(f"   act (last announcement of the earliest performed action): {act}")
    groups: dict[str, list[datetime | None]] = {}
    for line in the_lines(db):
        found = STAMP.match(line)
        message = line[found.end():] if found else line
        groups.setdefault(label_of(message), []).append(instant(found.group(1)) if found else None)

    sets = {}
    for label, stamps in groups.items():
        if act is None or any(stamp is None for stamp in stamps):
            sets[label] = []
            continue
        after = sorted({stamp.replace(second=0, microsecond=0) for stamp in stamps if stamp > act})
        sets[label] = said_as_sets(after) if after else []
    return sets


def in_the_brief(case: Path) -> dict[str, list[str]]:
    request = json.loads((case / "write_up_request.json").read_text(encoding="utf-8"))
    first = request["transcript"][0]
    text = first.get("text") or first.get("content") or ""
    said: dict[str, list[str]] = {}
    for line in str(text).splitlines():
        row = ROW.search(line)
        if row is None:
            continue
        at = line.find(PHRASE)
        said[row.group(1)] = (NAME.sub("", line[at + len(PHRASE):]).strip().split(" and ")
                              if at >= 0 else [])
    return said


def main(argv: list[str]) -> None:
    for case in map(Path, argv[1:]):
        print(f"== {case.name}")
        mine, brief = by_hand(case), in_the_brief(case)
        for label in sorted(set(mine) | set(brief)):
            ours = [each.split("   ")[0] for each in mine.get(label, [])]
            theirs = [A_DAY_BEFORE.sub("", each) for each in brief.get(label, [])]
            verdict = "MATCH" if ours == theirs else "DIFFERS"
            print(f"   {label}: {verdict}  by hand {mine.get(label, 'no group')}  "
                  f"brief {brief.get(label, 'no row')}")


if __name__ == "__main__":
    main(sys.argv)
