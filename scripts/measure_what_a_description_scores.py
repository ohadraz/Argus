"""What the retrieval threshold actually separates, measured against the index.

`NEAR_ENOUGH_TO_ANSWER` is 0.5 because a small hand sample put a fault's own
code around 0.65 and unrelated code between 0.41 and 0.50. That was one
embedder's numbers on a handful of descriptions, and the constant says so. This
asks the live index the same question at scale: every hit and its score, with no
threshold applied, so the gap the figure sits in is visible rather than assumed.

The descriptions are not invented for the occasion. They are the ones Code-Fix
actually searched with, lifted from the committed recordings - which is the only
sample that is representative of what this threshold filters in production,
since a description written to test retrieval is a description written by
somebody who already knows the answer.

Free: the embedder runs in this process and Qdrant is local. Needs the index
built - `nox -s index -- --once`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from argus_core import get_settings  # noqa: E402
from code_index.embedding import an_embedder  # noqa: E402
from code_index.indexing import Embedder  # noqa: E402
from read_mcp_server.meaning import (  # noqa: E402
    MOST_PASSAGES_WORTH_ANSWERING,
    NEAR_ENOUGH_TO_ANSWER,
    IndexReadSettings,
    NearestPassages,
    the_index_at,
)

# What Code-Fix asked the index, verbatim, with the scenario each came from. Nine
# calls across the committed corpus - every `search_repository_by_meaning` in it.
THE_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    ("slow-canary-rollout",
     "a loop that repeatedly scans the whole purchase history, making the cost grow "
     "with the square of the number of purchases and making the page slow for shoppers "
     "with long histories"),
    ("bad-deployment",
     "request handler that performs a blocking or synchronous call per request causing "
     "latency to climb and timeouts"),
    ("bad-deployment",
     "iterating over purchases repeatedly, recomputing totals inside a loop, N+1 lookups "
     "per account"),
    ("bad-deployment",
     "average spend per item divides total by number of purchases, crashes when list is "
     "empty"),
    ("fallback-disabled",
     "computes average spend per order by dividing total spend by order count, raising "
     "ZeroDivisionError when the customer has no orders"),
    ("feature-flag-toggle",
     "computes average monthly spend by dividing total spend by number of months, raising "
     "ZeroDivisionError when there are zero months or zero orders"),
    ("feature-flag-toggle",
     "feature flag monthly-spend-feature checked to decide whether to render new spend "
     "summary on account page"),
    ("flag-toggle-uncorroborated",
     "computes average spend per order by dividing total spend by the number of orders, "
     "which divides by zero when a customer has no orders"),
    ("flag-toggle-uncorroborated",
     "spend summary for account page, aggregates transactions and computes averages")
)

# The case the floor exists for, and the only one that can tell a threshold that
# is inert from one that has never had to fire. Every description above names
# something the shop really contains, so all of them *should* be admitted; a
# store answers its k nearest whatever the question, so what decides whether 0.5
# separates anything is where these land - questions this repository has no code
# for at all. If they score like the real ones, the embedder cannot discriminate
# on this domain and the constant should say so; if they fall, the number wants
# recalibrating to the gap rather than removing.
THE_DESCRIPTIONS_NOTHING_ANSWERS: tuple[tuple[str, str], ...] = (
    ("absent", "kernel thread scheduling and CPU affinity for real-time priority tasks"),
    ("absent", "parsing X.509 certificate chains and validating TLS handshake signatures"),
    ("absent", "video transcoding pipeline choosing bitrate ladders for adaptive streaming"),
    ("absent", "B-tree page splits and write-ahead log replay after an unclean shutdown"),
    ("absent", "evicting pods from a node under memory pressure and rescheduling them"),
    ("absent", "tokenizing source code into an abstract syntax tree for a compiler front end")
)


def _scored(kind: str,
            descriptions: tuple[tuple[str, str], ...],
            embed: Embedder,
            find: NearestPassages,
            *,
            every_hit: bool) -> None:
    """Scores one group of descriptions and says where its scores landed.

    The two groups are read against each other rather than against the constant.
    What decides whether a floor can separate anything is not whether either
    group clears it, but whether the two land in different places at all.
    """
    tops: list[float] = []
    every: list[float] = []

    for scenario, description in descriptions:
        # The embedder takes and returns a batch, as indexing wants it; one
        # description is a batch of one and its vector the only one back.
        vector, = embed([description])
        found = find(vector, MOST_PASSAGES_WORTH_ANSWERING)

        if every_hit:
            print(f"\n{scenario}: {description[:78]}")

            for rank, hit in enumerate(found, start=1):
                kept = "keep" if hit.score >= NEAR_ENOUGH_TO_ANSWER else "drop"
                print(f"  {rank}. {hit.score:.3f} {kept}  {hit.chunk.path}")
        else:
            best = f"{found[0].score:.3f} {found[0].chunk.path}" if found else "nothing"
            print(f"  {description[:66]:<68} {best}")

        every.extend(hit.score for hit in found)

        if found:
            tops.append(found[0].score)

    admitted = sum(1 for score in every if score >= NEAR_ENOUGH_TO_ANSWER)
    print(
        f"\n{kind}: {len(descriptions)} descriptions, {len(every)} hits, "
        f"{admitted} above {NEAR_ENOUGH_TO_ANSWER}. Best hits "
        f"{min(tops):.3f}-{max(tops):.3f}, every hit {min(every):.3f}-{max(every):.3f}"
    )


def _every_score(descriptions: tuple[tuple[str, str], ...],
                 embed: Embedder,
                 find: NearestPassages) -> list[float]:
    """Every hit's score across a group, for sweeping a candidate threshold over."""
    scores: list[float] = []

    for _, description in descriptions:
        vector, = embed([description])
        scores.extend(hit.score for hit in find(vector, MOST_PASSAGES_WORTH_ANSWERING))

    return scores


def _swept(answered: list[float], unanswered: list[float]) -> None:
    """What each candidate threshold would keep and what it would refuse.

    The two columns are the two mistakes a floor can make, and they are not
    equal: a passage admitted too many costs a few hundred tokens of a model's
    turn, where a passage refused may have been the fix. So the figure wanted is
    the highest one that still keeps everything real, not the one that refuses
    the most noise.
    """
    print("\ncandidate  keeps of real  refuses of noise")

    for candidate in (0.50, 0.55, 0.60, 0.62, 0.64, 0.65, 0.66, 0.70):
        kept = sum(1 for score in answered if score >= candidate)
        refused = sum(1 for score in unanswered if score < candidate)
        print(
            f"   {candidate:.2f}     {kept:>3} of {len(answered)}      "
            f"{refused:>3} of {len(unanswered)}"
        )


def main() -> None:
    """Scores what the shop answers and what nothing answers, and compares them."""
    settings = IndexReadSettings.of(get_settings())
    embed = an_embedder()
    find = the_index_at(settings)

    _scored("IN THE REPOSITORY", THE_DESCRIPTIONS, embed, find, every_hit=True)
    print("\n" + "=" * 78)
    print("Descriptions this repository has no code for at all:\n")
    _scored(
        "ABSENT FROM IT", THE_DESCRIPTIONS_NOTHING_ANSWERS, embed, find, every_hit=False
    )
    _swept(
        _every_score(THE_DESCRIPTIONS, embed, find),
        _every_score(THE_DESCRIPTIONS_NOTHING_ANSWERS, embed, find)
    )


if __name__ == "__main__":
    main()
