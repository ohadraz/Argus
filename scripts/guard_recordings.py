#!/usr/bin/env python3
"""
Fails if any committed recording is of a walk that gave up partway.

A recording is a queue of answers served in order, so what a corpus is worth
depends entirely on the walk it came from finishing. A walk that stopped
halfway leaves a queue that runs dry mid-incident when it is replayed, and
where that surfaces is whichever stage happened to be next - as a timeout, or
as an agent reporting it could not do its job, in a suite nobody was touching.
It then gets diagnosed as an agent bug, days later, by somebody with no reason
to suspect a JSON file. Two such corpora were committed by a single re-record
and went unnoticed for exactly that reason.

Two rules, both of them properties every recording has whatever incident it is
of - so a scenario added tomorrow is guarded tonight and nothing here is
edited for it:

- **Every walk ends with a postmortem.** It is the last thing an incident
  produces, on every path including escalation: escalating means a person has
  to act, not that nothing was learned, and the document is the handover to
  whoever picks it up.
- **A walk that started Code-Fix has to have finished it.** `submit_fix` is
  how every ending but two is reached - a proposal, and a judgement that
  nothing needs changing, both go through it. Reaching the end of the loop
  without it is the agent reading until its bounds ran out, which is a
  statement about the bound rather than about the code, and the answers it
  leaves behind stop in the middle of reading a repository.

What each *particular* recording had to do - which cause, which action -
belongs to the run that captures it, where the incident's own events can be
read, and lives in `scripts/record_incident.py`. Here there are only the
answers, so here the questions are only the two above.

Free, and it needs no stack, no model and no docker: it reads the committed
files. Run by `uv run python -m nox -s guard_recordings`.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

# The three tools that say which stage a walk got to. Spelled here rather than
# imported: neither `agent_postmortem` nor `agent_codefix` exports its submit
# tool, and a guard over committed data has no business reaching past a
# package's front door to read a name. A rename fails this loudly on every
# recording at once, which is the cheapest possible way to find out.
THE_LAST_ANSWER: Final = "submit_postmortem"
# Code-Fix's opening move, and nothing else's - so its presence in a corpus is
# how a reader of the answers alone can tell that Code-Fix ran at all. The
# walks that escalate before reaching it have no business submitting a fix,
# and this is what tells them apart from the walks that reached it and failed.
CODE_FIX_BEGAN: Final = "list_repository_files"
CODE_FIX_ANSWERED: Final = "submit_fix"

RECORDINGS_DIR: Final = (
    Path(__file__).resolve().parent.parent
    / "modules" / "anthropic_double" / "recordings"
)

TOOL_USE_TYPE: Final = "tool_use"


def the_answers_of(corpus: str, stored: list[Path]) -> list[Path]:
    """Every file one walk's answers are stored across, in the order given.

    The digits are checked rather than just the prefix, because two recordings
    can share one: `both-feature-flag-toggle-red-herring` is not the fourth
    answer of `both-feature-flag-toggle`.
    """
    belonging = [
        path for path in stored
        if path.stem == corpus or (
            path.stem.startswith(f"{corpus}-")
            and path.stem[len(corpus) + 1:].isdigit()
        )
    ]

    # By the number rather than as text: the first answer carries no digits at
    # all, and sorting the rest as strings would put a tenth answer second.
    return sorted(belonging, key=lambda path: int(path.stem[len(corpus) + 1:] or 1))


def every_corpus() -> Iterator[tuple[str, list[Path]]]:
    """Each walk that was recorded, and the files its answers are stored across.

    A corpus is named by its first answer - the one file with no trailing
    number - so the walks are found by looking for those rather than by
    knowing which scenarios exist. A scenario added tomorrow is guarded
    tonight, and nothing here has to be edited for it.
    """
    stored = sorted(RECORDINGS_DIR.glob("*.json"))
    openings = [
        path.stem for path in stored
        if not path.stem.rsplit("-", 1)[-1].isdigit()
    ]

    for corpus in openings:
        yield corpus, the_answers_of(corpus, stored)


def what_it_asked_for(answer: Path) -> list[str]:
    """Every tool the model called in this answer, in the order it called them.

    Plural: one answer may ask for several files at once, and a check reading
    only the last of them would miss a submission made alongside a read.
    """
    said = json.loads(answer.read_text(encoding="utf-8"))

    return [
        str(block.get("name")) for block in said.get("content", [])
        if isinstance(block, dict) and block.get("type") == TOOL_USE_TYPE
    ]


def what_gave_up(corpus: str, answers: list[Path]) -> str | None:
    """How this corpus falls short of a finished walk, if it does.

    One sentence rather than a flag, because the two ways of falling short are
    repaired the same way but read completely differently - and a guard that
    said only "bad" would send a reader to the wrong bound.
    """
    asked_for = [called for answer in answers for called in what_it_asked_for(answer)]
    ended_on = asked_for[-1] if asked_for else None

    if ended_on != THE_LAST_ANSWER:
        return (f"{corpus}: {len(answers)} answers ending on "
                f"[{ended_on or 'no tool call'}] - the walk never wrote its "
                f"postmortem")

    if CODE_FIX_BEGAN in asked_for and CODE_FIX_ANSWERED not in asked_for:
        reading = sum(1 for called in asked_for if called.startswith("search_"))
        return (f"{corpus}: {len(answers)} answers, Code-Fix searched "
                f"{reading} times and never called [{CODE_FIX_ANSWERED}] - it "
                f"read until its bounds ran out")

    return None


def what_stopped_short() -> list[str]:
    """Every corpus that is of a walk which gave up, and how."""
    return [
        gave_up
        for corpus, answers in every_corpus()
        if answers and (gave_up := what_gave_up(corpus, answers)) is not None
    ]


def main() -> None:
    if not RECORDINGS_DIR.exists():
        return

    unfinished = what_stopped_short()

    if unfinished:
        print(
            "Recordings of walks that gave up partway, so they replay as a "
            "walk that runs out of answers mid-incident:\n"
            + "\n".join(f"  {one}" for one in unfinished)
            + "\n\nEach has to be captured again - "
              "`nox -s \"record(mode='<mode>')\" -- <name>` - which costs a "
              "real investigation apiece. A corpus cannot be repaired by hand: "
              "the answers are a walk, and one written in is a walk that never "
              "happened.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
