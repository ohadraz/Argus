#!/usr/bin/env python3
"""
Copies the Target Service's source into the fixture the GitHub double serves.

The double stands in for the repository Argus reads and proposes fixes to, so
what it holds decides what Code-Fix can find. It held four files chosen by
hand, and two incidents - the memory leak and the slow canary - are faults in
modules that were not among them. Code-Fix searched for code that was not
there, read until its bounds ran out, and the recordings captured from those
walks are of an agent giving up. The corpus before them was worse: with only
the flag scenario's module in reach, the model proposed a change to *that*,
described as a memory fix, and the suite went green on a fix to nothing.

So the fixture is taken from the shop rather than written about it. A list
chosen by hand is a list that is right until the next scenario, and wrong in a
way nothing reports - the file simply is not there, and an agent that cannot
find code reports that it found no fix.

Run when the shop's source changes:

    uv run python -m scripts.snapshot_the_shop

Both repositories are checked out side by side - here, and on CI - so the shop
is found next door rather than configured. It refuses rather than guesses if it
is not there: a snapshot silently taken of nothing would empty the fixture, and
every code-fix recording would then be of an agent finding an empty repository.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

HERE: Final = Path(__file__).resolve().parent.parent
THE_SHOP: Final = HERE.parent / "Argus-Demo-Target-App"

# What the shop is, as far as Argus is concerned: the module tree and the tests
# over it. Both, because a fix to code whose test still asserts the old
# behaviour is a fix that fails the moment anybody runs it - so the tests are
# not context for the change, they are part of it, and a repository that showed
# Code-Fix the one without the other would be asking for a broken pull request.
#
# `tests/target_app/` is deliberately absent. That tree tests the machinery
# that stages incidents - scenarios, generators, flags - which is the harness
# around the shop rather than the shop, and no incident is ever a fault in it.
# It is also three thousand lines for Code-Fix to read past.
THE_SHOP_IS: Final = ("src/io_shop", "tests/io_shop")

FIXTURE_DIR: Final = (
    HERE / "modules" / "github_double" / "src" / "github_double" / "fixture"
)

# Stored with a suffix rather than as `.py`, so nothing in this repo imports,
# lints or typechecks the shop's source by accident - it is data here, and a
# module that is data in one repository and code in another is a module two
# tools disagree about.
NOT_CODE_HERE: Final = ".txt"


def what_the_shop_holds() -> dict[str, Path]:
    """Every file of the shop, by the path it has in its own repository.

    Keyed by repository path rather than by name, because that is what the
    double serves and what Code-Fix asks for: a fix names
    `src/io_shop/visits.py`, and a fixture that knew the file only as `visits`
    could not answer. It is also the reason the fixture mirrors the tree rather
    than flattening it - two files may share a name across `src` and `tests`,
    and flattened they would be one file with whichever content was copied
    last.
    """
    return {
        f"{tree}/{found.name}": found
        for tree in THE_SHOP_IS
        for found in sorted((THE_SHOP / tree).glob("*.py"))
    }


def what_is_missing() -> list[str]:
    """The halves of the shop that are not where this expects them."""
    return [tree for tree in THE_SHOP_IS if not (THE_SHOP / tree).is_dir()]


def main() -> None:
    missing = what_is_missing()
    if missing:
        print(
            f"The shop is not beside this repository: no "
            f"[{', '.join(missing)}] under [{THE_SHOP}].\n"
            f"Both are expected side by side. Nothing was written: an empty "
            f"fixture is a repository Code-Fix would report as having no code "
            f"in it.",
            file=sys.stderr,
        )
        sys.exit(1)

    held = what_the_shop_holds()

    # Cleared rather than written over. A file deleted from the shop would
    # otherwise stay in the fixture for ever, and Code-Fix would keep finding a
    # module the shop no longer has - a snapshot that only ever grows is not a
    # snapshot.
    for stale in FIXTURE_DIR.rglob(f"*{NOT_CODE_HERE}"):
        stale.unlink()

    # Byte for byte, which is why this is a copy rather than a read and a
    # write. Reading as text and writing it back translates the line endings on
    # Windows, and what would land in the fixture is the shop's source with
    # every line a byte longer than the shop has it - a snapshot that is not
    # one, in the one dimension the large-file case actually measures.
    for path, found in held.items():
        into = FIXTURE_DIR / f"{path}{NOT_CODE_HERE}"
        into.parent.mkdir(parents=True, exist_ok=True)
        into.write_bytes(found.read_bytes())

    print(f"{len(held)} files from [{THE_SHOP}]:")
    for path in held:
        print(f"  {path}")


if __name__ == "__main__":
    main()
