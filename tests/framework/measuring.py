"""Where a measurement's rows go, so that the next one can be compared to it.

A measurement printed to a console answers the question that prompted it and
nothing afterwards. What made this project's model and effort comparisons usable
was not that they were scripted - it was that the eval's samples were rows in a
file carrying when they were taken and under what configuration, which is why
four configurations could be compared across two days and why a pool that had
quietly mixed three of them was catchable at all.

So the convention, and it is one line: a measurement appends rows stamped with
their configuration, and a comparison reads the file rather than somebody's
memory of last time's numbers.

Beside `pooling.py` because it is the same discipline with the same shape, and
what separates the two is only who pays. A pooled sample costs a whole
investigation against the real model and says whether an answer held; a
measurement here is free - tokens counted off a turn, scores read out of the
index - and says what something cost or how far apart two things sit. Neither is
recoverable by re-reading the code, which is what makes both worth a row.

The rows themselves live in `measurements/` at the root rather than under
`tests/`, because the suite does not read them: they are written by scripts a
developer runs mid-change and read by the next developer asking the same
question. One file per measurement, tab-separated and committed, so it is read
by eye and diffed in review.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

# tests/framework/measuring.py -> the repository root, as `pooling.py` counts it.
REPO_ROOT = Path(__file__).resolve().parents[2]
MEASUREMENTS_DIR = REPO_ROOT / "measurements"

# Stamped on every row of every measurement, ahead of whatever the measurement
# itself names. `taken_at` because a figure's age is the first thing a reader
# needs, and `commit` because what was measured is code - though never only
# code, which is why each measurement names its own configuration in the columns
# that follow.
_WHEN_AND_WHAT = ("taken_at", "commit")


def the_commit_measured() -> str:
    """The commit a measurement describes, or `unknown` if it cannot be read.

    Never raises, as the eval's equivalent does not: a row with an unknown commit
    is worth more than a measurement lost to a git invocation, and some rows are
    written for runs whose commit is genuinely no longer recoverable.
    """
    try:
        named = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True
        )
    except Exception:
        return "unknown"

    return named.stdout.strip() or "unknown"


def the_measurement_of(name: str,
                       rows: Sequence[Mapping[str, object]],
                       *,
                       taken_at: str | None = None,
                       commit: str | None = None) -> Path:
    """Appends one row per measured thing to `measurements/<name>.tsv`.

    The columns are the first row's keys, in the order given, behind the two
    stamped ones. Every row must carry the same keys, and a file that already
    exists must already have those columns - a measurement that grew a column is
    a different measurement, and appending it to the old file would leave rows
    whose values belong under headings they do not line up with. It gets a name
    of its own instead.

    `taken_at` and `commit` are arguments rather than always read from the clock
    and from git, because a row is sometimes written for a run that happened
    earlier - and stamping such a row with now and with HEAD is the one lie that
    makes the whole file untrustworthy.

    Append-only. Nothing here rewrites a row: a measurement already taken is
    either still true or is answered by a later row saying otherwise.
    """
    if not rows:
        raise ValueError(f"[{name}] was asked to record no rows at all")

    columns = (*_WHEN_AND_WHAT, *rows[0].keys())
    disagreeing = [row for row in rows if tuple(row.keys()) != tuple(rows[0].keys())]

    if disagreeing:
        raise ValueError(
            f"[{name}] was given rows with different columns: {tuple(rows[0].keys())} "
            f"and {tuple(disagreeing[0].keys())}. One measurement is one shape."
        )

    MEASUREMENTS_DIR.mkdir(parents=True, exist_ok=True)
    recorded = MEASUREMENTS_DIR / f"{name}.tsv"
    stamped = [
        taken_at or datetime.now(UTC).isoformat(timespec="seconds"),
        commit or the_commit_measured()
    ]

    if recorded.exists():
        held = recorded.read_text(encoding="utf-8").splitlines()[0].split("\t")

        if tuple(held) != columns:
            raise ValueError(
                f"[{recorded}] holds columns {tuple(held)}, and this measurement has "
                f"{columns}. Record it under a name of its own rather than appending a "
                f"different shape to this one."
            )

    with recorded.open("a", encoding="utf-8", newline="\n") as writing:
        if recorded.stat().st_size == 0:
            writing.write("\t".join(columns) + "\n")

        for row in rows:
            writing.write("\t".join([*stamped, *(str(row[at]) for at in rows[0])]) + "\n")

    return recorded
