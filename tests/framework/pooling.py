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

Each row carries what it was taken with, because a pool is only a pool within
one configuration. The commit covers everything that is code - the standing
brief, a tool description, a fixture. It covers nothing that arrives through the
environment, and an eval reads its model, its effort and every retrieval bound
from there: two runs at one commit can measure two different agents. So the
model and the effort are columns of their own, being the two things anybody
tunes deliberately, and the rest is a digest - unreadable, and meant only to
split a pool when something changed that nobody thought to record.

A row that carries none of this is a row from before the columns existed. It is
refused rather than assumed, because the configuration it was taken with is
exactly what nobody can now recover.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
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
COLUMNS = ("taken_at", "commit", "case", "held", "model", "effort", "settings")
HELD = "held"
MISSED = "missed"

# Long enough that two different configurations will not collide in practice,
# short enough to read a row without scrolling. It is an identity, not a
# checksum: nothing here needs to resist anybody trying to forge one.
_DIGEST_LENGTH = 12

# How deep a pool has to be before anything is done with it. Both figures are
# about the width of a binomial interval rather than about taste: at ten samples
# a 95% interval spans some 25 points either side, which catches a regression
# and settles nothing finer; twenty narrows it enough to act on a difference
# between two prompts; fifty is where re-deriving a threshold stops inventing
# precision.
SAMPLES_BEFORE_ACTING_ON_A_DIFFERENCE = 20
SAMPLES_BEFORE_REDERIVING_A_THRESHOLD = 50


@dataclass(frozen=True)
class Configuration:
    """What an eval was run with, as far as a pool is concerned.

    The two named fields are the ones a person tunes and then wants to read back
    out of the file. `settings` stands for everything else the eval reads from
    the environment - built by `a_digest_of`, and compared rather than read.
    """

    model: str
    effort: str
    settings: str


@dataclass(frozen=True)
class Sample:
    """One recorded answer: when, at what commit and configuration, for which
    case, and whether it satisfied that case's claim."""

    taken_at: str
    commit: str
    case: str
    held: bool
    taken_with: Configuration


def a_digest_of(values: Mapping[str, object]) -> str:
    """A short, stable name for one set of settings.

    Sorted before hashing, so the same settings digest the same however the
    caller happened to order them - a digest that moved with dictionary order
    would split a pool that never changed.

    What goes in is the caller's to decide: this knows how to name a
    configuration, not which settings an eval reads.
    """
    rendered = "\n".join(f"{name}={values[name]!r}" for name in sorted(values))

    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


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


def the_samples_taken(eval_name: str,
                      case: str,
                      outcomes: list[bool],
                      taken_with: Configuration) -> None:
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
                rows.write("\t".join([
                    taken_at,
                    commit,
                    case,
                    HELD if held else MISSED,
                    taken_with.model,
                    taken_with.effort,
                    taken_with.settings
                ]) + "\n")
    except OSError as could_not_write:
        print(f"could not record this batch's samples: {could_not_write}")


def _a_sample_from(row: str, results: Path) -> Sample:
    """One row read back, or a refusal naming the file it came from.

    A row of the wrong width predates the configuration columns, and what it was
    taken with cannot be recovered from it. Guessing would be the one mistake
    these columns exist to prevent, so it raises instead - and says where to
    look, since the fix is to drop the stale rows rather than to widen them.
    """
    fields = row.split("\t")

    if len(fields) != len(COLUMNS):
        raise ValueError(
            f"[{results}] has a row with {len(fields)} of {len(COLUMNS)} columns, so it "
            f"predates the configuration a pool is grouped by: [{row}]. Rows taken "
            f"before those columns existed name no configuration and cannot be given "
            f"one after the fact - drop them."
        )

    taken_at, commit, case, held, model, effort, settings = fields

    return Sample(
        taken_at, commit, case, held == HELD, Configuration(model, effort, settings)
    )


def the_samples_of(eval_name: str,
                   case: str,
                   taken_with: Configuration | None = None,
                   since: str | None = None) -> list[Sample]:
    """Every sample recorded for one case, newest last, or none.

    `taken_with` keeps only the rows taken under that configuration. It is what
    stops an effort sweep averaging its two arms: the rows sit in one file, in
    time order, and nothing else tells them apart.

    `since` names a commit and keeps only the rows at or after the first row
    carrying it. That is the other half of pooling a population correctly: a
    change to the prompt starts a new one, and the commit that made the change is
    the boundary. Which commit that was is a human's to name - nothing here can
    tell a change to the brief from a change to a docstring.
    """
    results = _results_file(eval_name)

    if not results.exists():
        return []

    samples = [
        sample for sample in (
            _a_sample_from(line, results) for line in
            results.read_text(encoding="utf-8").splitlines()[1:] if line.strip()
        )
        if sample.case == case
        if taken_with is None or sample.taken_with == taken_with
    ]

    if since is None:
        return samples

    from_here = next(
        (at for at, sample in enumerate(samples) if sample.commit == since), None
    )

    return samples[from_here:] if from_here is not None else []


def the_pooled_rate_of(eval_name: str,
                       case: str,
                       taken_with: Configuration | None = None,
                       since: str | None = None) -> tuple[int, int]:
    """How many of how many samples held, over the whole pool.

    A pair rather than a fraction, because how deep the pool is decides what may
    be done with the rate - see the two depth figures above - and a fraction
    throws that half away.
    """
    samples = the_samples_of(eval_name, case, taken_with, since)

    return sum(1 for sample in samples if sample.held), len(samples)
