"""What the retrieval threshold actually separates, measured against the index.

`NEAR_ENOUGH_TO_ANSWER` decides which passages a model is shown, and the figure
is only as good as the sample it was read off. This asks the live index at scale
and with no threshold applied: every hit and its score, for questions the
repository answers and for questions it does not, so what each candidate floor
would keep and refuse is visible rather than argued.

Two halves, and they are sourced differently on purpose. The questions with
answers are the ones Code-Fix actually searched with, read out of the committed
recordings - the only sample representative of what this threshold filters in
production, since a description written to test retrieval is written by somebody
who already knows which file answers it. The questions with no answers are
authored here, because a corpus of searches against this repository cannot supply
a question this repository has no code for.

Free: the embedder runs in this process and Qdrant is local. Needs Qdrant up and
the index built - `nox -s index -- --once`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from argus_core import get_settings  # noqa: E402
from code_index.embedding import an_embedder  # noqa: E402
from code_index.indexing import Embedder  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from read_mcp_server.meaning import (  # noqa: E402
    MOST_PASSAGES_WORTH_ANSWERING,
    NEAR_ENOUGH_TO_ANSWER,
    IndexReadSettings,
    NearestPassages,
    the_index_at,
)

from tests.framework.measuring import the_measurement_of  # noqa: E402

# The file these rows go to, named for the question rather than the run.
WHAT_THIS_MEASURES = "what_a_description_scores"

# Recorded beside each candidate so a row says whether it is the figure the code
# was using when the row was written. The sweep is only readable against that:
# which candidate won is a judgement, and which one was in force is a fact.
THE_FLOOR_IN_USE = NEAR_ENOUGH_TO_ANSWER

RECORDINGS_DIR = REPO_ROOT / "modules" / "anthropic_double" / "recordings"

# The tool whose calls are the sample. Named from the wire rather than the module
# that defines it: what is being read here is a recorded request body.
THE_MEANING_TOOL = "search_repository_by_meaning"


def the_descriptions_code_fix_searched_with() -> tuple[tuple[str, str], ...]:
    """Every meaning search in the committed corpus, with the scenario it came from.

    Read out of the recordings rather than copied into this file, so the sample
    is whatever the agent last actually asked - a corpus re-recorded against a
    new prompt or a new model brings its own descriptions, and this measurement
    follows without anybody remembering to re-paste them.

    That matters more than convenience: a description written to test retrieval
    is written by somebody who already knows which file answers it, and scores
    accordingly. These were written by an agent that did not.
    """
    asked: list[tuple[str, str]] = []

    for recording in sorted(RECORDINGS_DIR.glob("*.json")):
        held = recording.read_text(encoding="utf-8")

        if THE_MEANING_TOOL not in held:
            continue

        # `both-feature-flag-toggle-3.json` -> `feature-flag-toggle`: the mode in
        # front and the answer's number behind it say which run this was, not
        # which incident, and the incident is what a reader of a score wants.
        scenario = re.sub(r"^(grep|meaning|both)-|-\d+$", "", recording.stem)

        for block in json.loads(held).get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == THE_MEANING_TOOL:
                asked.append((scenario, block["input"]["description"]))

    return tuple(asked)

# The case the floor exists for, and the only one that can tell a threshold that
# is inert from one that has never had to fire. Every description read above
# names something the shop really contains, so all of them *should* be admitted;
# a store answers its k nearest whatever the question, so what decides whether
# the floor separates anything is where these land - questions this repository
# has no code for at all. If they score like the real ones, the embedder cannot
# discriminate on this domain and the constant should say so; if they fall, the
# number wants recalibrating to the gap rather than removing.
#
# Written here rather than read from the corpus, and that is the arrangement
# rather than the half of it that nobody finished. The recordings hold what
# Code-Fix asked *about this repository*, so every description in them has an
# answer somewhere in the index - a corpus cannot supply a question it contains
# no answer to, and one that could would mean the agent had searched for
# something absent and the search had been kept. The absent half has to be
# authored, and stays as fixed as the corpus half is live: change a question here
# and the sweep either side of it is no longer comparable with the rows already
# recorded.
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


def _swept(answered: list[float], unanswered: list[float], passages: int) -> None:
    """What each candidate threshold would keep and what it would refuse.

    The two columns are the two mistakes a floor can make, and they are not
    equal: a passage admitted too many costs a few hundred tokens of a model's
    turn, where a passage refused may have been the fix. So the figure wanted is
    the highest one that still keeps everything real, not the one that refuses
    the most noise.
    """
    print("\ncandidate  keeps of real  refuses of noise")
    rows: list[dict[str, object]] = []

    for candidate in (0.50, 0.55, 0.60, 0.62, 0.64, 0.65, 0.66, 0.70):
        kept = sum(1 for score in answered if score >= candidate)
        refused = sum(1 for score in unanswered if score < candidate)
        rows.append({
            "candidate": f"{candidate:.2f}",
            "in_use": candidate == THE_FLOOR_IN_USE,
            "passages": passages,
            "kept_of_real": kept,
            "real_hits": len(answered),
            "refused_of_absent": refused,
            "absent_hits": len(unanswered)
        })
        print(
            f"   {candidate:.2f}     {kept:>3} of {len(answered)}      "
            f"{refused:>3} of {len(unanswered)}"
        )

    print(f"\nrecorded to {the_measurement_of(WHAT_THIS_MEASURES, rows)}")


def main() -> None:
    """Scores what the shop answers and what nothing answers, and compares them."""
    settings = IndexReadSettings.of(get_settings())
    embed = an_embedder()
    find = the_index_at(settings)
    answered = the_descriptions_code_fix_searched_with()

    if not answered:
        print(f"no {THE_MEANING_TOOL} calls recorded under {RECORDINGS_DIR}")
        return

    _scored("IN THE REPOSITORY", answered, embed, find, every_hit=True)
    print("\n" + "=" * 78)
    print("Descriptions this repository has no code for at all:\n")
    _scored(
        "ABSENT FROM IT", THE_DESCRIPTIONS_NOTHING_ANSWERS, embed, find, every_hit=False
    )
    # How much is indexed, on every row: the whole question of whether a floor
    # separates anything is a question about this corpus, and the figure that
    # moves when somebody indexes a second repository is this one.
    passages = QdrantClient(url=settings.qdrant_url).count(
        settings.code_index_collection
    ).count

    _swept(
        _every_score(answered, embed, find),
        _every_score(THE_DESCRIPTIONS_NOTHING_ANSWERS, embed, find),
        passages
    )


if __name__ == "__main__":
    main()
