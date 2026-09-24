"""Files the two spend measurements taken before there was anywhere to file them.

Both runs happened, printed their figures to a console and were read once. The
numbers are still on disk in the logs they were written to, and the commit each
belongs to is recoverable from when the log was written against when each commit
landed - so these rows are transcribed measurements rather than remembered ones.

Stamped with the commit and the hour the run actually happened, never with HEAD
and now: a row claiming to describe the current tree when it describes an older
one is the single thing that would make the whole file untrustworthy.

Run once. `the_measurement_of` appends, so a second run files the same rows
twice - which is why this names the logs it has read rather than scanning a
directory that will grow.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.framework.measuring import the_measurement_of  # noqa: E402

SCRATCHPAD = Path(
    r"C:\Users\ohadr\AppData\Local\Temp\claude"
    r"\c--Users-ohadr-Projects-Argus\85641462-a8a2-47f8-af06-1aeb3db755f4\scratchpad"
)

# Each run's log, the moment it finished, and the commit that was HEAD then. The
# first ran between `8287c64` at 21:03 and `3fbe0de` at 22:22; the second between
# `3fbe0de` and `6d33a38` at 00:22 the next day. Both are local time, as the
# commits are.
THE_RUNS: tuple[tuple[str, str, str], ...] = (
    ("effort_spend.log", "2026-09-24T19:12:37+00:00", "8287c64"),
    ("arm_spend.log", "2026-09-24T19:54:46+00:00", "3fbe0de")
)

# `  claude-opus-5/high  unrelated-change  turns   4  in    8  out 2179  read ...`
# The first log predates the model column and names only the effort, so the model
# is optional here and defaults to what that run used throughout.
A_ROW = re.compile(
    r"^\s*(?:(?P<model>[\w.-]+)/)?(?P<effort>low|medium|high|xhigh|max)\s+"
    r"(?P<incident>[\w-]+)\s+turns\s+(?P<turns>\d+)\s+in\s+(?P<input>\d+)\s+"
    r"out\s+(?P<output>\d+)\s+read\s+(?P<cache_read>\d+)\s+write\s+(?P<cache_write>\d+)"
)

# What the run that named no model was using. Both efforts in that log were
# measured against it, which is the whole reason the column was added afterwards.
THE_MODEL_BEFORE_THE_COLUMN = "claude-opus-5"

WHAT_THIS_MEASURES = "what_an_investigation_bills"


def _rows_in(log: Path) -> list[dict[str, object]]:
    """Every per-incident line in one log, as rows of the shape the file holds.

    `TOTAL` lines are skipped rather than parsed: a total is the sum of the rows
    beside it, and a file holding both invites a reader to add the total in.
    """
    rows: list[dict[str, object]] = []

    # `utf-8-sig`, because PowerShell wrote these and its redirect opens with a
    # byte-order mark - which sits in front of the first measured line and is
    # exactly enough to stop it matching, losing one incident per run silently.
    for line in log.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if "TOTAL" in line:
            continue

        found = A_ROW.match(line)

        if found is None:
            continue

        rows.append({
            "model": found["model"] or THE_MODEL_BEFORE_THE_COLUMN,
            "effort": found["effort"],
            "incident": found["incident"],
            "turns": int(found["turns"]),
            "input": int(found["input"]),
            "output": int(found["output"]),
            "cache_read": int(found["cache_read"]),
            "cache_write": int(found["cache_write"])
        })

    return rows


def main() -> None:
    """Files both runs, or says which log could not be found."""
    for name, taken_at, commit in THE_RUNS:
        log = SCRATCHPAD / name

        if not log.exists():
            print(f"{name}: gone - nothing to file")
            continue

        rows = _rows_in(log)

        if not rows:
            print(f"{name}: no measured lines found")
            continue

        recorded = the_measurement_of(
            WHAT_THIS_MEASURES, rows, taken_at=taken_at, commit=commit
        )
        arms = sorted({f"{row['model']}/{row['effort']}" for row in rows})
        print(f"{name}: {len(rows)} rows at {commit}, arms {arms} -> {recorded}")


if __name__ == "__main__":
    main()
