"""The deployments the shop's scenarios name, staged into the repository double.

A scenario that ships a revision puts it in the deployment history, and the read
tier answers "what did that deployment change" by asking the repository to
compare it with the revision before. The double holds the fixture and nothing
else, so a pair nobody staged is a 404 - and the walk reads that as a repository
it could not reach, not as the diff that is the diagnosis.

Staged by the case rather than held by the double, because these are the
scenarios' facts and nothing else's. The double depends on nothing in the
workspace, so it cannot derive a real commit of the Target Service - and a
double that named these pairs would be keeping a copy of another repository's
history, right until the next scenario named two other commits and 404'd on the
comparison. Kept here rather than in each case because two of them are seeded by
more than one file.

Each commit is staged with every file the real comparison lists, whole and as
`Argus-Demo-Target-App` holds it at that commit - stored under
`tests/e2e/committed/<sha7>/`, written there by `scripts/snapshot_the_commits.py`.
Whole rather than an excerpt, because a recording is captured against the real
repository: GitHub's patch numbers its hunks from where the change sits in the
file and heads each with the line above it, and an excerpt starts every file at
line one, so the walk a replay reads would not be the walk its recording read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx2
from argus_core import get_settings
from github_double.server import DEFAULT_BASE_URL as GITHUB_DOUBLE_BASE_URL

from tests.e2e.framework.argus import REQUEST_TIMEOUT_SECONDS

# Where each commit's files are kept, one directory per commit named by its
# first seven characters, each file under its path in the repository with a
# suffix that keeps this repository's tools from reading it as code - the
# convention the GitHub double's own fixture keeps.
COMMITTED: Final = Path(__file__).parents[1] / "committed"
STORED_AS: Final = ".txt"


@dataclass(frozen=True)
class DeploymentPair:
    """A revision the shop's history names, and the one before it - its parent.

    `on_main` is whether the shop's `main` holds `after`. Most scenarios ship a
    revision from a branch of its own that was never merged, and Code-Fix reads
    `main` - so whether what ran is there is a fact of the scenario, staged with
    the rest of it, and what Code-Fix is told turns on it.
    """

    before: str
    after: str
    on_main: bool


def as_committed(sha: str) -> dict[str, str]:
    """Every file stored for `sha`, by its path in the repository.

    Each was taken with `git show <sha>:<path>` in `Argus-Demo-Target-App`, by
    `uv run python scripts/snapshot_the_commits.py`. A commit cannot change, so
    a file stored once stays true.
    """
    held = COMMITTED / sha[:7]

    return {
        stored.relative_to(held).as_posix().removesuffix(STORED_AS):
            stored.read_text(encoding="utf-8")
        for stored in sorted(held.rglob(f"*{STORED_AS}"))
    }


def the_deployment_was_staged(pair: DeploymentPair) -> Callable[[], bool]:
    """Puts both commits of a pair into the repository double, the later made
    on the earlier, and says where `main` stands to them.

    Raises rather than answering `False`, for the reason `a_scenario_was_seeded`
    does: `calling` discards what a step returns, so a commit the double refused
    would go unnoticed until the walk read a 404 as the deployment's diff.
    """
    def stage_them() -> bool:
        for sha, parents in ((pair.before, []), (pair.after, [pair.before])):
            httpx2.post(
                f"{GITHUB_DOUBLE_BASE_URL}/double-control/stage-commit",
                json={"sha": sha, "files": as_committed(sha), "parents": parents},
                timeout=REQUEST_TIMEOUT_SECONDS
            ).raise_for_status()

        if pair.on_main:
            httpx2.post(
                f"{GITHUB_DOUBLE_BASE_URL}/double-control/stage-head",
                json={"branch": get_settings().github_base_branch, "parents": [pair.after]},
                timeout=REQUEST_TIMEOUT_SECONDS
            ).raise_for_status()

        return True

    return stage_them


# `monitoring-blind-spot`: the metrics port renamed, and the scrape configuration
# still selecting it by its old name.
THE_METRICS_PORT_RENAMED = DeploymentPair(
    before="e283ba3af732fc4285166a060b827b1305cd30d9",
    after="9f4ad14582c99c497eb6c2d2af87566cd4493020",
    on_main=True
)

# `monitoring-configuration-drift`: every port named for the protocol it
# carries, the platform's convention, and the scrape configuration not following.
THE_PORTS_NAMED_FOR_THEIR_PROTOCOL = DeploymentPair(
    before="2c8f7311966cf37dee314695fe0060867e1ca954",
    after="c3c36da3c66c07707f227b7e70b26813083061f3",
    on_main=False
)

# `cache-misconfigured`: the cache's port moved in the values the shop ships.
THE_CACHE_PORT_MOVED = DeploymentPair(
    before="544cef36a8eaf45c5b030c3d5c21473d8176cef3",
    after="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
    on_main=True
)

# `bad-deployment`: the lifetime average derived from the purchases, once per
# purchase.
THE_AVERAGE_SLOWED = DeploymentPair(
    before="70dbcfde2b549d110a3817d92d60b6dd9786e78b",
    after="5e07d73148d0a704b8fefe5f379bc652bb773655",
    on_main=True
)

# `control-plane-unreachable`: which purchases fall in this month, decided from
# when each was recorded rather than from the flag the writer set - and the
# guard that answered an empty month with zero gone with the old rule.
THE_MONTH_BOUNDARY_MOVED = DeploymentPair(
    before="65279ee05d2cfae49802712847428bc55e794bb3",
    after="383534e9bb182bb778e01fd22ba63f88885362e3",
    on_main=False
)

# `half-finished-rollout`: what the summary cache stores changed shape, with no
# read path kept for the old one.
THE_CACHE_ENTRY_RESHAPED = DeploymentPair(
    before="5470c1a64205bb28f9f2e8a96dc6ffa5eb2e611e",
    after="696c33a68b36aed6456cdc5b3806f33038488515",
    on_main=True
)

# `monthly-totals-falling-behind`: a purchase no longer moves its shopper's
# monthly total.
THE_MONTH_STOPPED_BEING_CARRIED = DeploymentPair(
    before="4c810f22894e612ced87f5ee3f3062dfeb785050",
    after="26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2",
    on_main=False
)

# `categoriser-model-upgraded`: the categoriser moved from model v1 to v2.
THE_CATEGORISER_UPGRADED = DeploymentPair(
    before="d268103129978816ce705c50c14cd42c7c5fe46e",
    after="7c3ca00c7528df68d533f6e87acd4f23a55ab342",
    on_main=False
)

# Every pair above, for the script that stores their files.
EVERY_PAIR: Final = (
    THE_METRICS_PORT_RENAMED,
    THE_PORTS_NAMED_FOR_THEIR_PROTOCOL,
    THE_CACHE_PORT_MOVED,
    THE_AVERAGE_SLOWED,
    THE_MONTH_BOUNDARY_MOVED,
    THE_CACHE_ENTRY_RESHAPED,
    THE_MONTH_STOPPED_BEING_CARRIED,
    THE_CATEGORISER_UPGRADED
)
