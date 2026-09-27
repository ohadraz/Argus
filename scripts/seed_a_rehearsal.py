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
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from anthropic_double.recordings import RECORDINGS_DIR
from github_double.repository import DEFAULT_FILES

# The walk a set is built from by default, and the one it is stored as. Both
# carry the mode's prefix because a recording is captured under the tool list
# the stack offered, and a set stored without one is a set nothing replays -
# which is also why a borrowed set may only be stored under its own mode's
# prefix, and why the pair below is `both` and only `both`: the large-fix case
# is collected in that mode alone (`noxfile._the_cases_for`), so a `grep-` or
# `meaning-` set of it would answer a question no session asks.
#
# Overridable, because the rehearsal is not a property of that one case. Any
# new scenario has the same problem and the same answer: borrow a walk through
# a world shaped like this one, and rewrite whichever answers have to differ.
BORROWED_FROM: Final = "both-feature-flag-toggle"
STORED_AS: Final = "both-monthly-statement-panel"

# The answer that has to differ, and the only one. Everything before it is the
# investigation and the reading, which are the same in both worlds; everything
# after it is the postmortem, which is written from the incident rather than
# from the fix.
THE_TOOL_THAT_SUBMITS_A_FIX: Final = "submit_fix"
# The Investigator's own answer, which is the one that has to differ when the
# borrowed walk reached a different conclusion rather than merely fixed a
# different file.
THE_TOOL_THAT_ANSWERS: Final = "final_answer"
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


def _the_two_names_share_a_mode(borrowed_from: str, stored_as: str) -> None:
    """Refuses a borrow across modes, before anything is written.

    A mode is not a label on a recording - it is the world it was captured in.
    Under `grep` the read tier registers no retrieval-by-meaning tool at all, so
    a walk captured under `both` asks for one that was never offered; the double
    serves the answer regardless, because it is a queue seeded by name and never
    inspects the request, and the failure reads as an agent bug in a case nobody
    has touched.
    """
    borrowed_mode, _, _ = borrowed_from.partition("-")
    stored_mode, _, _ = stored_as.partition("-")

    if borrowed_mode != stored_mode:
        raise SystemExit(
            f"[{borrowed_from}] was captured under [{borrowed_mode}] and would "
            f"be stored under [{stored_mode}] - a walk replayed in a world "
            f"unlike the one its answers were given in calls tools that stack "
            f"never offered"
        )


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


# The dependency the register marks as this organisation's own, and the host
# the shop's log names. Two spellings of one thing, and both are load-bearing:
# the address is what a restart is sent to, and the host is what the model
# would have read the address off.
THE_FAILING_DEPENDENCY: Final = "io-pricing"
THE_HOST_THE_TIME_WENT_TO: Final = "pricing.io-internal.svc"


def _a_failing_internal_dependency(was: dict[str, Any]) -> dict[str, Any]:
    """The borrowed `final_answer`, replaced by a conclusion about a dependency.

    The envelope is kept exactly as recorded, for the reason the fix rewrite
    keeps it: what is being fabricated is the content of an answer, and an
    invented envelope is a second fabrication in the fields a later reader is
    most likely to trust.

    One hypothesis rather than the borrowed walk's several. What the rehearsal
    is exercising is the address surviving into the hypothesis, past the gate
    and into the platform call - and a runner-up would only add a second walk
    through the same plumbing if the first were refuted, which it is not.

    `faulting_service` is the whole point. A borrowed answer carries a subject,
    which is the model's description of the fault; nothing in the recorded
    corpus carries an address, because until this scenario no mitigation could
    be aimed anywhere but the service that alerted.
    """
    answered = False
    content = []

    for block in was["content"]:
        if block.get("type") == TOOL_USE_TYPE and block.get("name") == THE_TOOL_THAT_ANSWERS:
            block = {
                **block,
                "input": {
                    "hypotheses": [
                        {
                            "confidence": 0.74,
                            "failure_mode": "internal-dependency-failure",
                            "faulting_service": THE_FAILING_DEPENDENCY,
                            "subject": THE_HOST_THE_TIME_WENT_TO,
                            "summary": (
                                f"Every quantile climbed together while the "
                                f"error rate stayed flat and the deploy history "
                                f"is empty, which rules out the release the "
                                f"shape suggests. The shop's own log names "
                                f"where the time went: each account page render "
                                f"waits on {THE_HOST_THE_TIME_WENT_TO}, and the "
                                f"register says that host is "
                                f"{THE_FAILING_DEPENDENCY}, a service this "
                                f"organisation runs. Nothing is wrong with the "
                                f"shop - it is waiting on a dependency that has "
                                f"become an order of magnitude slower to answer."
                            ),
                            "supporting_evidence": [
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        f"WARN io-shop: pricing lookup to "
                                        f"{THE_HOST_THE_TIME_WENT_TO} took "
                                        f"1489ms"
                                    )
                                },
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "p50 44ms -> 1546ms, p95 224ms -> "
                                        "1716ms, p99 379ms -> 1881ms with the "
                                        "error rate unmoved - a wait added to "
                                        "every request rather than a slow "
                                        "revision multiplying it"
                                    )
                                },
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "the deploy history is empty over the "
                                        "whole window, so nothing was released"
                                    )
                                }
                            ]
                        }
                    ]
                }
            }
            answered = True

        content.append(block)

    if not answered:
        raise SystemExit(
            f"the borrowed walk has no [{THE_TOOL_THAT_ANSWERS}] answer to "
            f"rewrite, so it records an investigation that never concluded"
        )

    return {**was, "content": content}


def _a_deployment_that_is_too_small(was: dict[str, Any]) -> dict[str, Any]:
    """The borrowed `final_answer`, replaced by a conclusion about capacity.

    Borrowed from the dependency walk rather than from the leak's, which is the
    choice that makes the set replayable: that walk is a latency incident with an
    empty deploy history, no flag staged and no patch proposed - the same world in
    every channel the answers were given over, and the same shape of ending, since
    capacity is no more a defect to patch than a neighbour's slowness is.

    One hypothesis, for the reason the dependency rewrite states: what this
    exercises is the mode reaching the scale-out strategy, past the gate, into the
    platform call and back out as a confirmed verdict. A runner-up would buy a
    second walk through that plumbing only if the first were refuted.

    No `faulting_service`. The fault is the deployment's own size, and the field
    belongs to the one cause that carries an address somebody else's service is
    reached at - naming the shop there would be offering a dependency that does
    not exist.
    """
    answered = False
    content = []

    for block in was["content"]:
        if block.get("type") == TOOL_USE_TYPE and block.get("name") == THE_TOOL_THAT_ANSWERS:
            block = {
                **block,
                "input": {
                    "hypotheses": [
                        {
                            "confidence": 0.78,
                            "failure_mode": "demand-saturation",
                            "subject": "io-shop CPU (cpu_used_cores at a 3.0 core limit)",
                            "summary": (
                                "Request volume climbed from 1200 to 5400 a "
                                "minute and stayed there, and CPU rose with it "
                                "until it reached the deployment's 3.0 cores and "
                                "stopped - a gauge pinned at its ceiling while "
                                "every quantile went on climbing. The heap is "
                                "flat, the error rate never stirred, and neither "
                                "the deploy history nor the flag provider records "
                                "a change. Nothing is wrong with the shop: the "
                                "load has outgrown the capacity it was sized for."
                            ),
                            "supporting_evidence": [
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "cpu_used_cores 0.74 -> 3.00 against a "
                                        "cpu_limit_cores of 3.00, flat at the "
                                        "ceiling for the last nine minutes"
                                    )
                                },
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "request_volume 1200 -> 5400 over the "
                                        "same minutes, so the consumption moved "
                                        "with the traffic rather than "
                                        "independently of it"
                                    )
                                },
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "memory_used_bytes unchanged at ~440MiB "
                                        "and the error rate at baseline, which "
                                        "rules out a leak"
                                    )
                                },
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "the deploy history is empty over the "
                                        "whole window and no flag changed, so "
                                        "nothing was released or toggled"
                                    )
                                }
                            ]
                        }
                    ]
                }
            }
            answered = True

        content.append(block)

    if not answered:
        raise SystemExit(
            f"the borrowed walk has no [{THE_TOOL_THAT_ANSWERS}] answer to "
            f"rewrite, so it records an investigation that never concluded"
        )

    return {**was, "content": content}


# Which answer has to be rewritten, by the set being fabricated, and which tool
# call marks it. A rehearsal borrows a walk through a world shaped like the new
# one, so most answers are already right: the investigation read evidence of the
# same shape, and the postmortem is written from the incident rather than from
# what was done about it. A set absent from here is one where *nothing* has to
# differ and the borrowed answers are stored as they stand - which is the
# ordinary case rather than a shortcut, and is what makes a scenario whose walk
# differs only in its prose free to rehearse.
#
# The tool is named beside the rewrite rather than assumed, because the two
# rehearsals differ in which answer they touch. The large-fix set borrows a walk
# that reached the right conclusion about the wrong file, so only the fix
# differs; the dependency set borrows a walk that reached a different conclusion
# entirely, so it is the investigation's own answer that has to change and the
# fix after it is left as the borrowed walk wrote it.
_THE_ANSWER_THAT_HAS_TO_DIFFER: Final[
    dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]]
] = {
    STORED_AS: (THE_TOOL_THAT_SUBMITS_A_FIX, _a_fix_of_the_large_module),
    "grep-pricing-service-degraded": (THE_TOOL_THAT_ANSWERS,
                                      _a_failing_internal_dependency),
    "both-pricing-service-degraded": (THE_TOOL_THAT_ANSWERS,
                                      _a_failing_internal_dependency),
    "grep-cpu-saturation": (THE_TOOL_THAT_ANSWERS, _a_deployment_that_is_too_small),
    "both-cpu-saturation": (THE_TOOL_THAT_ANSWERS, _a_deployment_that_is_too_small)
}


def _write(borrowed: list[Path], stored_as: str) -> list[Path]:
    """Stores the set under the new name, answer for answer.

    Numbered exactly as the source was, because the double serves a queue in
    order and a gap in the numbering is a walk that stops one answer early.
    """
    differs = _THE_ANSWER_THAT_HAS_TO_DIFFER.get(stored_as)
    written = []

    for index, path in enumerate(borrowed, start=1):
        was = json.loads(path.read_text(encoding="utf-8"))
        now = (
            differs[1](was)
            if differs is not None and any(
                block.get("name") == differs[0] for block in was["content"]
            )
            else was
        )
        destination = RECORDINGS_DIR / (
            f"{stored_as}.json" if index == 1 else f"{stored_as}-{index}.json"
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
        "--from",
        dest="borrowed_from",
        default=BORROWED_FROM,
        help="the recorded walk to borrow answers from - one through a world "
             "shaped like the new scenario's, under the same mode's prefix",
    )
    parser.add_argument(
        "--as",
        dest="stored_as",
        default=STORED_AS,
        help="the name to store the fabricated set under, which is the name the "
             "case replaying it asks the double for",
    )
    parser.add_argument(
        "--remove",
        action="store_true",
        help="delete the fabricated set instead of writing it, which is what to "
             "do the moment a real recording of this scenario exists",
    )
    arguments = parser.parse_args()

    if arguments.remove:
        for path in _the_answers_of(arguments.stored_as):
            path.unlink()
            print(f"removed {path.name}")

        return 0

    _the_two_names_share_a_mode(arguments.borrowed_from, arguments.stored_as)
    borrowed = _the_answers_of(arguments.borrowed_from)

    if not borrowed:
        raise SystemExit(
            f"no recording named [{arguments.borrowed_from}] to borrow a walk "
            f"from"
        )

    written = _write(borrowed, arguments.stored_as)

    print(f"fabricated {len(written)} answers as {arguments.stored_as}:")
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
