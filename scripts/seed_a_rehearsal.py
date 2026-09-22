"""Builds a fabricated answer set, so a new scenario can be driven before it is paid for.

A scenario with no recording cannot be replayed, and a scenario that has never
been replayed is one whose first run is the paid one - which is the arrangement
the `preflight-before-paid-runs` skill exists to prevent. Everything about a new
case except the model's judgement is checkable for free: the scenario seeds, the
walk reaches Code-Fix, the answer satisfies the tool schema, the branch is
written, the pull request is opened, and the e2e case's own assertions hold. All
of it needs answers, and answers are the one thing that costs money.

So this makes them up, out of a walk that already exists. It takes a recording
set captured for one scenario, rewrites the one answer that has to differ, and
stores the result under the new scenario's name. The double then replays it like
any other, `e2e_replay` runs the new case unmodified, and what a green run proves
is the pipeline - never the answer, which nobody has asked a model for yet.

**What it writes is not evidence and must not be committed.** A recording is a
claim about what the API said; these are a claim about what this script said. The
paid `record` run overwrites them with the real thing, and until it has, a green
replay of this case means the plumbing holds and nothing whatever about whether
the model can fix the file.

The source set is chosen rather than derived, and the choice is the argument: it
has to be a walk through the same world, because a recording is a queue of
answers served in order rather than a model that reasons afresh. A walk replayed
in a world unlike the one its answers were given in asks a question the queue has
no answer to, and the double runs dry mid-incident.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Final

from anthropic_double.recordings import RECORDINGS_DIR
from github_double.repository import DEFAULT_FILES

# The walk this set is built from, and the one it is stored as. Both carry the
# mode's prefix because a recording is captured under the tool list the stack
# offered, and a set stored without one is a set nothing replays.
#
# `both` and only `both`, which is a decision rather than a shortcut: the
# large-fix case is collected in that mode alone (`noxfile._the_cases_for`),
# because what it claims does not vary by which tool found the file. A
# `grep-` or `meaning-` set here would be answers to a question no session
# asks.
BORROWED_FROM: Final = "both-feature-flag-toggle"
STORED_AS: Final = "both-monthly-statement-panel"

# The answer that has to differ, and the only one. Everything before it is the
# investigation and the reading, which are the same in both worlds; everything
# after it is the postmortem, which is written from the incident rather than
# from the fix.
THE_TOOL_THAT_SUBMITS_A_FIX: Final = "submit_fix"
TOOL_USE_TYPE: Final = "tool_use"

# The file the fix is of - the largest module the shop has, and the whole reason
# this scenario exists. Read from the repository double rather than from the
# demo app's checkout, because what Code-Fix is answering about is what the
# repository served it, and the two are a copy of each other that can drift.
THE_LARGE_MODULE: Final = "src/io_shop/monthly_statement.py"

# The fault, and the repair. A rehearsal does not need a *good* fix - what is
# being exercised is the size of the answer and the path it travels - but it
# does need a plausible one, because an answer full of nonsense would make every
# later reading of this run an argument about the nonsense.
THE_FAULT: Final = (
    "    return max(purchase.price_cents for purchase in "
    "purchases_this_month(account))"
)
THE_REPAIR: Final = (
    "    bought = purchases_this_month(account)\n"
    "\n"
    "    if not bought:\n"
    "        raise ValueError(\"this shopper bought nothing this month\")\n"
    "\n"
    "    return max(purchase.price_cents for purchase in bought)"
)


def _the_answers_of(name: str) -> list[Path]:
    """Every file one recording's answers are stored across, in answer order.

    The same rule `scripts/record_incident.py` reads them by, and deliberately
    the same: the digits are checked rather than the prefix alone, because two
    recordings can share one and a set assembled by prefix would borrow another
    scenario's answers without saying so.
    """
    belonging = [
        path
        for path in RECORDINGS_DIR.glob(f"{name}*.json")
        if path.stem == name or path.stem[len(name) + 1:].isdigit()
    ]

    return sorted(belonging, key=lambda path: int(path.stem[len(name) + 1:] or 1))


def _the_fixed_module() -> str:
    """The large module with its fault repaired, as a whole file.

    Whole, because that is what `ProposedFile.content` is: a fix here replaces
    the file rather than patching it, which is the decision this whole scenario
    exists to put under load.
    """
    held = DEFAULT_FILES[THE_LARGE_MODULE]

    if THE_FAULT not in held:
        raise SystemExit(
            f"the fault this rehearsal repairs is no longer in "
            f"[{THE_LARGE_MODULE}] as the repository double serves it - the "
            f"fixture has moved, and a fabricated fix against a file that has "
            f"changed would be a rehearsal of nothing"
        )

    return held.replace(THE_FAULT, THE_REPAIR, 1)


def _a_fix_of_the_large_module(was: dict[str, Any]) -> dict[str, Any]:
    """The borrowed `submit_fix` answer, aimed at the large module instead.

    The envelope is kept exactly as it was recorded - the id, the model, the
    stop reason, the usage - and only the tool call's input is rewritten. What
    is being fabricated is the *content* of an answer, and an envelope invented
    alongside it would be a second fabrication nobody asked for, in the fields a
    later reader is most likely to trust.

    The usage figures are therefore the borrowed walk's and describe a fix of
    seven hundred tokens. That is wrong for this answer and is left wrong on
    purpose: a figure edited to look right is one somebody will measure from.
    """
    submitted = False
    content = []

    for block in was["content"]:
        if block.get("type") == TOOL_USE_TYPE and block.get("name") == THE_TOOL_THAT_SUBMITS_A_FIX:
            block = {
                **block,
                "input": {
                    "summary": "Guard the monthly statement against an empty month",
                    "explanation": (
                        "Cause: `the_biggest_purchase_this_month` asks `max` for "
                        "the largest purchase of the month without checking that "
                        "the month has any, so every account page the rollout "
                        "reached fails for a shopper who has bought nothing this "
                        "month. The statement promises a largest, a smallest and "
                        "an average, and a month with nothing in it has none of "
                        "them - so the panel raises rather than inventing a zero, "
                        "and the account page's boundary turns that into the "
                        "error rate this incident was paged on."
                    ),
                    "files": [
                        {"path": THE_LARGE_MODULE, "content": _the_fixed_module()}
                    ]
                }
            }
            submitted = True

        content.append(block)

    if not submitted:
        raise SystemExit(
            f"[{BORROWED_FROM}] has no [{THE_TOOL_THAT_SUBMITS_A_FIX}] answer to "
            f"rewrite, so the walk it records never reached Code-Fix"
        )

    return {**was, "content": content}


def _write(borrowed: list[Path]) -> list[Path]:
    """Stores the set under the new name, answer for answer.

    Numbered exactly as the source was, because the double serves a queue in
    order and a gap in the numbering is a walk that stops one answer early.
    """
    written = []

    for index, path in enumerate(borrowed, start=1):
        was = json.loads(path.read_text(encoding="utf-8"))
        now = (
            _a_fix_of_the_large_module(was)
            if any(
                block.get("name") == THE_TOOL_THAT_SUBMITS_A_FIX
                for block in was["content"]
            )
            else was
        )
        destination = RECORDINGS_DIR / (
            f"{STORED_AS}.json" if index == 1 else f"{STORED_AS}-{index}.json"
        )
        # `newline` said explicitly, because the default translates on Windows
        # and a recording is read on three platforms. A stored answer that
        # differs from a captured one by its line endings is a diff nobody can
        # see and every reviewer has to scroll past.
        destination.write_text(
            json.dumps(now, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n"
        )
        written.append(destination)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remove",
        action="store_true",
        help="delete the fabricated set instead of writing it, which is what to "
             "do the moment a real recording of this scenario exists",
    )
    arguments = parser.parse_args()

    if arguments.remove:
        for path in _the_answers_of(STORED_AS):
            path.unlink()
            print(f"removed {path.name}")

        return 0

    borrowed = _the_answers_of(BORROWED_FROM)

    if not borrowed:
        raise SystemExit(
            f"no recording named [{BORROWED_FROM}] to borrow a walk from"
        )

    written = _write(borrowed)

    print(f"fabricated {len(written)} answers as {STORED_AS}:")
    for path in written:
        print(f"  {path.name}  {path.stat().st_size:>7} bytes")
    print(
        "\nThese are made up. They prove the pipeline and nothing about the "
        "model.\nDo not commit them; `nox -s record` replaces them with the "
        "real thing."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
