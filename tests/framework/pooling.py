"""What a paid eval scored, kept so that small runs add up to a population.

An eval sample costs a whole investigation against the real model, so a run
large enough to derive a threshold from is a bill nobody wants to pay in one
afternoon. Samples are independent, though, so the population is simply the union
of the batches - provided the batches are written down. That is all this is: one
row per sample, appended, never rewritten.

Only what cannot be recomputed is kept. A deterministic grader over committed
inputs writes nothing here and should not: its verdict is recovered by checking
out the commit and running it again. These rows are the other kind - the model
answered as it answered on the day, and re-running costs money and may answer
differently.

Each row carries the commit it was taken at, because a pool is only a pool
within one prompt. Samples from before a change to the standing brief, a tool
description or a budget describe an agent that no longer exists, and averaging
them with what came after is how a pass rate outlives the thing it measured.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# tests/framework/pooling.py -> the repository root.
ARGUS_REPO_ROOT = Path(__file__).resolve().parents[2]

# Beside the evals that write them, one file per eval. One shared file would be
# simpler to read and easier to pool wrongly: two evals' cases share no
# population, and a single file invites a reader to average them.
RESULTS_DIR = ARGUS_REPO_ROOT / "tests" / "eval" / "results"

# Tab-separated and committed, so it is read by eye, diffed in review, and needs
# nothing installed to open.
COLUMNS = ("taken_at", "commit", "case", "held")
HELD = "held"
MISSED = "missed"

# How deep a pool has to be before anything is done with it. Both figures are
# about the width of a binomial interval rather than about taste: at ten samples
# a 95% interval spans some 25 points either side, which catches a regression
# and settles nothing finer; twenty narrows it enough to act on a difference
# between two prompts; fifty is where re-deriving a threshold stops inventing
# precision.
SAMPLES_BEFORE_ACTING_ON_A_DIFFERENCE = 20
SAMPLES_BEFORE_REDERIVING_A_THRESHOLD = 50


@dataclass(frozen=True)
class Sample:
    """One recorded answer: when, at what commit, for which case, and whether it
    satisfied that case's claim."""

    taken_at: str
    commit: str
    case: str
    held: bool


def the_commit_under_test() -> str:
    """The commit these samples describe, or `unknown` if it cannot be read.

    Never raises. A results file is worth more with an unknown commit in one row
    than a paid run is worth losing to a git invocation - the samples have
    already been paid for by the time anything is written.
    """
    try:
        named = subprocess.run(
            ["git", "-C", str(ARGUS_REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True
        )
    except Exception:
        return "unknown"

    return named.stdout.strip() or "unknown"


def _results_file(eval_name: str) -> Path:
    return RESULTS_DIR / f"{eval_name}.tsv"


def the_samples_taken(eval_name: str, case: str, outcomes: list[bool]) -> None:
    """Appends one row per sample, creating the file with its header if new.

    Append-only, and deliberately so: a sample already taken is a sample already
    paid for, and a run that rewrote the file would charge for it twice.

    Failing to write is not allowed to fail the eval. The assertion that follows
    is about the model, and losing a batch's record is worse news reported in a
    worse place - so it goes to stderr and the scoring carries on.
    """
    taken_at = datetime.now(UTC).isoformat(timespec="seconds")
    commit = the_commit_under_test()

    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        results = _results_file(eval_name)
        new = not results.exists()

        with results.open("a", encoding="utf-8", newline="\n") as rows:
            if new:
                rows.write("\t".join(COLUMNS) + "\n")

            for held in outcomes:
                rows.write(
                    "\t".join([taken_at, commit, case, HELD if held else MISSED]) + "\n"
                )
    except OSError as could_not_write:
        print(f"could not record this batch's samples: {could_not_write}")


def the_samples_of(eval_name: str, case: str, since: str | None = None) -> list[Sample]:
    """Every sample recorded for one case, newest last, or none.

    `since` names a commit and keeps only the rows at or after the first row
    carrying it. That is what pools a population correctly: a change to the
    prompt starts a new one, and the commit that made the change is the boundary.
    Which commit that was is a human's to name - nothing here can tell a change
    to the brief from a change to a docstring.
    """
    results = _results_file(eval_name)

    if not results.exists():
        return []

    samples = [
        Sample(taken_at, commit, sampled_case, held == HELD)
        for taken_at, commit, sampled_case, held in (
            line.split("\t") for line in
            results.read_text(encoding="utf-8").splitlines()[1:] if line.strip()
        )
        if sampled_case == case
    ]

    if since is None:
        return samples

    from_here = next(
        (at for at, sample in enumerate(samples) if sample.commit == since), None
    )

    return samples[from_here:] if from_here is not None else []


def the_pooled_rate_of(eval_name: str,
                       case: str,
                       since: str | None = None) -> tuple[int, int]:
    """How many of how many samples held, over the whole pool.

    A pair rather than a fraction, because how deep the pool is decides what may
    be done with the rate - see the two depth figures above - and a fraction
    throws that half away.
    """
    samples = the_samples_of(eval_name, case, since)

    return sum(1 for sample in samples if sample.held), len(samples)
