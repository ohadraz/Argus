"""Drops eval samples taken before the configuration columns, and names the rest.

`tests/framework/pooling.py` is append-only on purpose, and this rewrites the
file it appends to - so it is a script somebody runs deliberately once, not
something the suite does. What makes the rewrite honest is that it removes rows
rather than inventing values for them: a sample taken before the columns existed
names no model, no effort and no settings, and nothing can recover them now.

What survives is the window in which one configuration demonstrably held. Every
other row in the file was taken against a fixture or a brief that has since
changed, so pooling them was already wrong - the columns only made it visible.

Run it with no arguments to see what it would do; `--apply` to do it.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tests.eval.test_investigator_eval import (  # noqa: E402
    the_configuration_under_test,
)
from tests.framework.pooling import COLUMNS  # noqa: E402

RESULTS = REPO_ROOT / "tests" / "eval" / "results" / "investigator.tsv"

# The window in which the current fixture and the current brief both held: the
# first batch after the metrics span was widened, through the last batch before
# the falsification paragraph was tried. Both ends are inclusive of whole
# batches - a batch writes one timestamp for all ten of its samples.
FIRST_KEPT = "2026-09-24T15:48"
LAST_KEPT = "2026-09-24T16:12"


def _kept(taken_at: str) -> bool:
    return FIRST_KEPT <= taken_at < LAST_KEPT


def main() -> None:
    """Reports what would be dropped and kept, and rewrites the file on `--apply`."""
    lines = RESULTS.read_text(encoding="utf-8").splitlines()

    # Run once, and say so rather than running again. A second pass would split
    # each row and append the three values to what already carries them, leaving
    # ten columns where seven belong - and a results file nobody can read is a
    # worse outcome than a script that refuses.
    if lines and lines[0].split("\t") == list(COLUMNS):
        print(f"{RESULTS} already names a configuration - nothing to do")
        return

    rows = [line for line in lines[1:] if line.strip()]

    kept = [row for row in rows if _kept(row.split("\t")[0])]
    named = the_configuration_under_test()

    print(f"{len(rows)} rows, keeping {len(kept)}, dropping {len(rows) - len(kept)}")
    print(f"naming them: {named.model} / {named.effort} / {named.settings}")

    if "--apply" not in sys.argv:
        print("nothing written - pass --apply to rewrite the file")
        return

    RESULTS.write_text(
        "\n".join([
            "\t".join(COLUMNS),
            *(
                "\t".join([*row.split("\t"), named.model, named.effort, named.settings])
                for row in kept
            )
        ]) + "\n",
        encoding="utf-8",
        newline="\n"
    )
    print(f"rewrote {RESULTS}")


if __name__ == "__main__":
    main()
