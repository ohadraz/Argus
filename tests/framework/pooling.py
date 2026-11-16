"""What a paid eval scored and spent, kept so that small runs add up to a population.

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

Each row carries whether the sample held and what it cost - its turns and all
four token counts - because a rate and its price are read side by side, and
asked of the same sample so that neither stands for a run the other never saw.

And each row carries what it was taken with, because a pool is only a pool
within one configuration. The commit covers everything that is code. It covers
nothing that arrives through the environment, and an eval reads its model, its
effort and every retrieval bound from there: two runs at one commit can measure
two different agents. So the model and the effort are columns of their own,
being the two things anybody tunes deliberately, and the rest is named by a
digest - which is a key and nothing more. What a digest stands for is written
beside it, once, in `<eval>.settings.tsv`: each short setting as its value, and
each long text - a prompt, a tool list - as the digest of a file under `texts/`
holding it whole. A row reads back to what produced it without checking
anything out.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tests.framework.spending import Spend

# tests/framework/pooling.py -> the repository root.
ARGUS_REPO_ROOT = Path(__file__).resolve().parents[2]

# Beside the evals that write them, one file per eval. One shared file would be
# simpler to read and easier to pool wrongly: two evals' cases share no
# population, and a single file invites a reader to average them.
RESULTS_DIR = ARGUS_REPO_ROOT / "tests" / "eval" / "results"

# One file per text, named by its digest, shared by every eval: a text is the
# same text whichever eval offered it.
TEXTS_DIR = RESULTS_DIR / "texts"

# Tab-separated and committed, so it is read by eye, diffed in review, and needs
# nothing installed to open.
COLUMNS = (
    "taken_at", "commit", "case", "held", "model", "effort", "settings",
    "turns", "input", "output", "cache_read", "cache_write"
)
SETTINGS_COLUMNS = ("settings", "name", "value")
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
    """What a sample was taken with, as far as a pool is concerned.

    The two named fields are the ones a person tunes and then wants to read back
    out of the file. `settings` is the digest of everything else, compared
    rather than read - what it stands for is in the settings file.
    """

    model: str
    effort: str
    settings: str


@dataclass(frozen=True)
class Setup:
    """What an eval runs with, written out in full.

    `values` are the short settings, written as they are. `texts` are the long
    ones, each written once as a file named by its own digest and named in the
    settings by that digest. The configuration a pool is grouped by is derived
    from these rather than stated beside them, so the two cannot disagree.
    """

    model: str
    effort: str
    values: Mapping[str, object]
    texts: Mapping[str, str]


@dataclass(frozen=True)
class Outcome:
    """One sample as an eval scored it: whether it held, and what it cost."""

    held: bool
    spent: Spend


@dataclass(frozen=True)
class Sample:
    """One recorded answer: when, at what commit and configuration, for which
    case, whether it satisfied that case's claim, and what it cost."""

    taken_at: str
    commit: str
    case: str
    held: bool
    taken_with: Configuration
    spent: Spend


def the_settings_of(setup: Setup) -> dict[str, str]:
    """Every setting as the settings file holds it: a value as itself, a text
    as the digest of the file holding it."""
    return {
        **{name: str(value) for name, value in setup.values.items()},
        **{name: _a_digest_of_text(text) for name, text in setup.texts.items()}
    }


def the_configuration_of(setup: Setup) -> Configuration:
    """What a pool groups a setup's samples under."""
    return Configuration(setup.model, setup.effort, _a_digest_of(the_settings_of(setup)))


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


def _a_digest_of(settings: Mapping[str, str]) -> str:
    """A short, stable name for one set of settings.

    Sorted before hashing, so the same settings digest the same however the
    caller happened to order them - a digest that moved with dictionary order
    would split a pool that never changed.
    """
    return _a_digest_of_text("\n".join(f"{name}={settings[name]}" for name in sorted(settings)))


def _a_digest_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


def _results_file(eval_name: str) -> Path:
    return RESULTS_DIR / f"{eval_name}.tsv"


def _settings_file(eval_name: str) -> Path:
    return RESULTS_DIR / f"{eval_name}.settings.tsv"


def the_samples_taken(eval_name: str,
                      case: str,
                      outcomes: list[Outcome],
                      taken_with: Setup) -> None:
    """Appends one row per sample, and what its digest stands for if that is
    not written down yet, creating each file with its header if new.

    Append-only, and deliberately so: a sample already taken is a sample already
    paid for, and a run that rewrote the file would charge for it twice.

    Failing to write is not allowed to fail the eval. The assertion that follows
    is about the model, and losing a batch's record is worse news reported in a
    worse place - so it goes to stderr and the scoring carries on.
    """
    taken_at = datetime.now(UTC).isoformat(timespec="seconds")
    commit = the_commit_under_test()
    configuration = the_configuration_of(taken_with)

    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        _the_setup_written(eval_name, taken_with, configuration)
        results = _results_file(eval_name)
        new = not results.exists()

        with results.open("a", encoding="utf-8", newline="\n") as rows:
            if new:
                rows.write("\t".join(COLUMNS) + "\n")

            for outcome in outcomes:
                rows.write("\t".join([
                    taken_at,
                    commit,
                    case,
                    HELD if outcome.held else MISSED,
                    configuration.model,
                    configuration.effort,
                    configuration.settings,
                    str(outcome.spent.turns),
                    str(outcome.spent.input_tokens),
                    str(outcome.spent.output_tokens),
                    str(outcome.spent.cache_read_tokens),
                    str(outcome.spent.cache_write_tokens)
                ]) + "\n")
    except OSError as could_not_write:
        print(f"could not record this batch's samples: {could_not_write}")


def _the_setup_written(eval_name: str, setup: Setup, configuration: Configuration) -> None:
    """Writes what a digest stands for, the first time it is used.

    Once per digest rather than once per batch: every batch under one setup
    would otherwise repeat the same lines, and a reader looking a digest up
    wants one answer. A text's file is written only where none holds it yet,
    since its name is its content's digest.
    """
    written = _settings_file(eval_name)
    known = {
        line.split("\t", 1)[0]
        for line in written.read_text(encoding="utf-8").splitlines()[1:]
    } if written.exists() else set()

    if configuration.settings in known:
        return

    TEXTS_DIR.mkdir(parents=True, exist_ok=True)

    for text in setup.texts.values():
        holding = TEXTS_DIR / f"{_a_digest_of_text(text)}.txt"

        if not holding.exists():
            holding.write_text(text, encoding="utf-8", newline="\n")

    new = not written.exists()

    with written.open("a", encoding="utf-8", newline="\n") as rows:
        if new:
            rows.write("\t".join(SETTINGS_COLUMNS) + "\n")

        for name, value in sorted(the_settings_of(setup).items()):
            rows.write("\t".join([configuration.settings, name, value]) + "\n")


def _a_sample_from(row: str, results: Path) -> Sample:
    """One row read back, or a refusal naming the file it came from.

    A row of the wrong width was written to some other shape of this file, and
    what it was taken with or what it cost cannot be recovered from it. Guessing
    would be the one mistake these columns exist to prevent, so it raises
    instead - and says where to look, since the fix is to drop the stale rows
    rather than to widen them.
    """
    fields = row.split("\t")

    if len(fields) != len(COLUMNS):
        raise ValueError(
            f"[{results}] has a row with {len(fields)} of {len(COLUMNS)} columns, so it "
            f"was written to another shape of this file: [{row}]. What it was taken "
            f"with or what it cost cannot be given to it after the fact - drop it."
        )

    (taken_at, commit, case, held, model, effort, settings,
     turns, input_tokens, output_tokens, cache_read, cache_write) = fields

    return Sample(
        taken_at,
        commit,
        case,
        held == HELD,
        Configuration(model, effort, settings),
        Spend(int(turns), int(input_tokens), int(output_tokens), int(cache_read),
              int(cache_write))
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
