"""Whether the shop's stand-in still draws the world the shop drew.

A replay serves the shop through `target_service_double`, which seeds a
recording's world at a later instant by moving the minutes the shop draws its
figures from. What no replay can say is whether that world is the one the shop
itself drew at the recording's anchor. A shop that came to draw from something
the stand-in does not move would still serve, every replay would still pass, and
every write-up recorded against it would cite a world nobody recorded - which is
the failure the stand-in exists to end, back and silent.

So it is checked here against the shop itself: every generated scenario seeded
at an anchor by the shop and later by the stand-in from that anchor, and the
stand-in's windows required to be the shop's minute for minute once their
instants are moved back. With nothing staged, the stand-in is required to be the
shop unchanged.

The shop is a party that changes out from under Argus - its own repository, its
own commits. This runs in its environment, with its own interpreter, the way
`grade_fixes` does: the stand-in is loaded into the shop's process, and that
process is the only place both are installed. So it needs the shop checked out
beside this repository.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, all_of

# tests/contract/target_service/<this file> -> the repository root.
ARGUS_REPO_ROOT = Path(__file__).resolve().parents[3]

THE_SHOP = ARGUS_REPO_ROOT.parent / "Argus-Demo-Target-App"
THE_STAND_IN = ARGUS_REPO_ROOT / "modules" / "target_service_double" / "src"
BOTH_WORLDS = Path(__file__).with_name("drawing_both_worlds.py")

# Every generated scenario, three times each, three readings a time - and every
# seed the shop makes tries a cache that is not running here, which on some
# machines is a refusal that takes seconds to arrive.
A_WHOLE_COMPARISON_SECONDS = 1200


@pytest.mark.contract
def test_the_stand_in_draws_the_world_the_shop_drew_at_the_anchor() -> None:
    Scenario() \
        .given(THE_SHOP) \
        .when(_both_worlds_drawn) \
        .then(all_of(
            _something_was_compared(),
            _the_stand_in_drew_the_shops_world_every_time()
        ))


def _both_worlds_drawn() -> dict[str, Any]:
    """What `drawing_both_worlds.py` found, run as the shop runs."""
    if not THE_SHOP.is_dir():
        raise AssertionError(
            f"Expected the shop checked out at [{THE_SHOP}], and nothing is there."
        )

    run = subprocess.run(
        ["uv", "run", "python", str(BOTH_WORLDS)],
        cwd=THE_SHOP, capture_output=True, text=True, timeout=A_WHOLE_COMPARISON_SECONDS,
        env={**os.environ, "PYTHONPATH": str(THE_STAND_IN)}
    )
    said = run.stdout.strip().splitlines()

    if not said:
        raise AssertionError(
            f"Expected the comparison to say what it found, it said nothing and "
            f"exited [{run.returncode}]: {run.stderr}"
        )

    found: dict[str, Any] = json.loads(said[-1])

    if "lacking" in found:
        raise AssertionError(
            f"Expected the stand-in to reach the shop where it moves it, and it "
            f"cannot: {found['lacking']}."
        )

    return found


def _something_was_compared() -> Assertion[dict[str, Any]]:
    """At least one scenario drawn both ways - a shop whose every scenario was
    excluded would pass the next assertion by comparing nothing."""
    def assertion(found: dict[str, Any]) -> bool:
        if not found["compared"]:
            raise AssertionError(
                f"Expected at least one scenario compared, every one was excluded: "
                f"{found['excluded']}."
            )

        return True

    return assertion


def _the_stand_in_drew_the_shops_world_every_time() -> Assertion[dict[str, Any]]:
    """Every comparison found nothing, and each one that did not is named with
    the first of what it found."""
    def assertion(found: dict[str, Any]) -> bool:
        differing = {label: said for label, said in found["compared"].items() if said}

        if differing:
            raise AssertionError(
                f"Expected the stand-in to draw the shop's world in every one of "
                f"[{len(found['compared'])}] comparisons, it drew another in "
                f"[{len(differing)}]:\n"
                + "\n".join(f"{label}:\n  " + "\n  ".join(said)
                            for label, said in differing.items())
            )

        return True

    return assertion
