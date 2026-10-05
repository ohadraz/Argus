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

# The extension a set's capture instant is stored beside its answers under, spelled
# here for the reason the two names above it are: this is not a package the e2e
# framework can be imported from.
ANCHOR_SUFFIX: Final = ".anchor"

# The file the fix is of - the largest module the shop has, and the whole reason
# this scenario exists. Read from the repository double rather than from the
# demo app's checkout, because what Code-Fix is answering about is what the
# repository served it, and the two are a copy of each other that can drift.
THE_LARGE_MODULE: Final = "src/io_shop/monthly_statement.py"

# Where the shop's summary cache answers, as `deploy/values-production.yaml`
# names it. The address a conclusion about a promoted stale replica has to name,
# and the subject that conclusion is filed under - not the shop, which is
# serving every request correctly from a copy nobody told anything.
THE_PROMOTED_CACHE: Final = "cache.io-shop.svc.cluster.local"

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


def _a_cache_serving_figures_the_ledger_moved_past(
    was: dict[str, Any]
) -> dict[str, Any]:
    """The borrowed `final_answer`, replaced by a conclusion about a stale copy.

    Borrowed from the blind spot's walk, and that choice is what makes the set
    replayable rather than merely plausible. Both incidents are paged by the
    shop's own monitoring rather than by a rule on a series, both are dated by a
    minute the alert states rather than one the loop measured, and both end
    `MITIGATED` with an action taken, a verdict reached and Code-Fix asked
    afterwards. So the borrowed walk makes the same model calls in the same
    order, which is the only thing a queue seeded by name can be right about.

    Not borrowed from `both-silent-data-corruption`, which is the nearer world
    and the wrong shape: that walk ends `RECOMMENDED`, so the gate refuses its
    action and `route_after_mitigation` sends it to the escalation rather than to
    Code-Fix. Its queue therefore holds no answer for a fix, and a walk that got
    as far as asking for one would find the double dry - a failure that reads as
    an agent bug rather than as a borrow that was never going to work.

    Nothing but the mode is load-bearing in what this writes. The discard is
    addressed by the keys the alert carried and aimed at the service it named, so
    `DiscardCacheEntriesStrategy` reads neither the hypothesis nor the recorded
    flag changes - which is the whole reason a fabricated conclusion can drive
    this plumbing honestly. The summary and the evidence are here to stop a later
    reading of this run becoming an argument about nonsense, not because anything
    consumes them.

    The subject is the cache rather than the shop. It is prose the model wrote
    about the fault, and the fault is not the shop - which is serving every
    request correctly from a copy that stopped being told things. What the per-
    subject cap counts is the *action's* subject, which is the service the alert
    named, so the two do not have to agree and should not.
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
                            "confidence": 0.81,
                            "failure_mode": "state-divergence",
                            "subject": THE_PROMOTED_CACHE,
                            "summary": (
                                f"Nothing is failing and nothing is slow - every "
                                f"series the monitoring watches is flat across "
                                f"the whole window, which is why no rule fired "
                                f"and the shop's own data check is what paged. "
                                f"What the check found is that the summary cache "
                                f"holds spend figures the purchases behind them "
                                f"have moved past. The shop's log records it "
                                f"reconnecting to a new primary for "
                                f"{THE_PROMOTED_CACHE}, which is a promotion: "
                                f"the standby that took over had stopped being "
                                f"replicated to some hours earlier, so it is "
                                f"serving whatever it last managed to copy. The "
                                f"ledger is intact and was never written wrongly "
                                f"- only the copy in front of it is behind."
                            ),
                            "supporting_evidence": [
                                {
                                    "at": "2026-09-30T21:10:00Z",
                                    "claim": (
                                        "the shop's data check reports stored "
                                        "summary figures disagreeing with the "
                                        "purchases they were derived from, with "
                                        "each disagreeing entry named"
                                    )
                                },
                                {
                                    "at": "2026-09-30T21:10:00Z",
                                    "claim": (
                                        f"INFO io-shop: summary cache "
                                        f"reconnected to a new primary at "
                                        f"{THE_PROMOTED_CACHE}"
                                    )
                                },
                                {
                                    "at": "2026-09-30T21:10:00Z",
                                    "claim": (
                                        "error rate, p50, p95, p99, heap and "
                                        "replica count are unmoved over the "
                                        "whole window - nothing a monitor "
                                        "watches departed at any minute"
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


def _a_controller_that_will_not_settle(was: dict[str, Any]) -> dict[str, Any]:
    """The borrowed `final_answer`, replaced by a conclusion about a controller.

    Borrowed from the saturation walk, which is the nearest world there is: the
    same ramp to the same plateau, the same empty change channels, the same
    latency climb, and at the bottom of every cycle the same readings exactly.
    That closeness is the scenario's whole point and it is what makes this the
    rehearsal most likely to flatter itself - a fabricated answer cannot be wrong
    about the one series the real model has to notice, because it is written by
    somebody who already knows which mode this is.

    So what a green replay of this set proves is the plumbing and nothing else:
    the mode reaching the fifth strategy, the gate admitting it, the tier reading
    the live bounds before it patches, the controller stopping, and the walk
    carrying on to a postmortem. Whether a model reads a moving `cpu_limit_cores`
    correctly is measured by the eval pair and by the paid recording, never here.

    One hypothesis, for the reason the two rewrites above give. No
    `faulting_service`: the fault is this deployment's own controller, and that
    field names a service somebody else's outage is reached at.
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
                            "confidence": 0.76,
                            "failure_mode": "autoscaling-pathology",
                            "subject": (
                                "io-shop's horizontal pod autoscaler "
                                "(cpu_limit_cores moving between 3.0 and 6.0)"
                            ),
                            "summary": (
                                "The deployment is a different size every few "
                                "minutes: cpu_limit_cores takes two values across "
                                "this window rather than one, so the capacity is "
                                "not a number the load outgrew but a number that "
                                "will not settle. Two minutes in every three are "
                                "served at the floor and saturate; the third runs "
                                "at the ceiling, reports a fraction of its CPU "
                                "target, and the controller answers by taking the "
                                "replicas straight back. The heap is flat, the "
                                "error rate never stirred, and neither the deploy "
                                "history nor the flag provider records a change. "
                                "Adding capacity is undone within a minute here - "
                                "what ends it is taking away the controller's room "
                                "to scale down."
                            ),
                            "supporting_evidence": [
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "cpu_limit_cores alternates 3.00 -> 6.00 "
                                        "-> 3.00 across the window, which is the "
                                        "one series that separates this from "
                                        "demand saturation, where it holds a "
                                        "single value throughout"
                                    )
                                },
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "p95 alternates with it - about 1700ms in "
                                        "the minutes served at 3.0 cores against "
                                        "about 215ms in the minutes served at 6.0 "
                                        "- so the service is starved in some "
                                        "minutes and comfortable in others"
                                    )
                                },
                                {
                                    "at": "2026-09-24T09:16:00Z",
                                    "claim": (
                                        "request_volume is flat at its plateau "
                                        "across both kinds of minute, so what "
                                        "changes between them is the capacity and "
                                        "not the load"
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


# The two revisions serving at once, as the platform's deploy history names them.
# Carried here because a rollout is the one subject whose two states are commits:
# the hypothesis has to say which revision the fleet is split across, and a
# fabricated pair would be a rehearsal of a diff the repository does not hold.
THE_REVISION_ROLLING_OUT: Final = "696c33a68b36aed6456cdc5b3806f33038488515"
THE_REVISION_STILL_SERVING: Final = "5470c1a64205bb28f9f2e8a96dc6ffa5eb2e611e"


def _a_rollout_that_stopped_half_way(was: dict[str, Any]) -> dict[str, Any]:
    """The borrowed `final_answer`, replaced by a conclusion about a split fleet.

    Borrowed from the bad-deployment walk, which is the only world with the thing
    this one turns on: a deploy at the onset and a rollback at the end. The
    difference is which series moved - that walk read a latency climb, this one an
    error rate that steps while every quantile holds - and the difference does not
    reach the plumbing, because the channels are the same channels and the ending
    is the same ending.

    One hypothesis, for the reason the rewrites above give. The mode is the whole
    of what this rehearsal exercises and the whole of what it cannot judge: the
    conclusion is written by somebody who already knows the rollout is paused, and
    whether a model reads a paused rolling update as nobody's fault is measured by
    the eval pair and by the paid recording, never here.

    `from_state` and `to_state` are the two revisions serving at once rather than
    a good state and a bad one, which is this mode's whole claim - neither is at
    fault, and what a rollback achieves is that one of them is serving alone. No
    `faulting_service`: nothing outside the shop is involved.
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
                            "confidence": 0.81,
                            "failure_mode": "in-flight-compatibility-break",
                            "subject": "src/io_shop/summary_cache.py (the stored entry's shape)",
                            "from_state": THE_REVISION_STILL_SERVING,
                            "to_state": THE_REVISION_ROLLING_OUT,
                            "summary": (
                                f"The rolling update of "
                                f"{THE_REVISION_ROLLING_OUT} is paused with three "
                                f"of six replicas on it, so two revisions are "
                                f"serving at once. That revision changed what a "
                                f"summary-cache entry is - a figure became a "
                                f"figure and the purchases behind it - and kept "
                                f"no read path for the old shape, which is the "
                                f"expand step of a migration nobody performed. An "
                                f"account page fails when a replica still on "
                                f"{THE_REVISION_STILL_SERVING} draws an entry a "
                                f"newer replica wrote, which is about one request "
                                f"in five and is why the error rate steps while "
                                f"every quantile holds where it was. Neither "
                                f"revision is at fault and both pass the shop's "
                                f"own tests; what is wrong is that both are "
                                f"running. Returning the deployment ends it by "
                                f"leaving one shape being read and written, not "
                                f"by removing anything that was broken."
                            ),
                            "supporting_evidence": [
                                {
                                    "at": "2026-09-28T07:03:00Z",
                                    "claim": (
                                        f"deployed revision "
                                        f"{THE_REVISION_ROLLING_OUT}, from deploy"
                                    )
                                },
                                {
                                    "at": "2026-09-28T07:03:00Z",
                                    "claim": (
                                        "the rolling update reports 3 of 6 "
                                        "replicas updated and paused, so the "
                                        "revision above and the one before it are "
                                        "both serving"
                                    )
                                },
                                {
                                    "at": "2026-09-28T07:03:00Z",
                                    "claim": (
                                        "error_rate 0.010 -> 0.197 from the deploy "
                                        "minute onward with p50, p95 and p99 "
                                        "unmoved - requests that fail outright "
                                        "rather than a revision that made every "
                                        "request slower"
                                    )
                                },
                                {
                                    "at": None,
                                    "claim": (
                                        "the diff stores `{\"figure\": ..., "
                                        "\"purchases\": [...]}` where the revision "
                                        "before it stored the figure alone, and no "
                                        "reader of the older shape was kept"
                                    )
                                },
                                {
                                    "at": "2026-09-28T07:08:00Z",
                                    "claim": (
                                        "no flag changed over the whole window and "
                                        "the cache answers at its usual nine "
                                        "lookups in ten, which rules out a toggle "
                                        "and a cache that stopped working"
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


# The two changes that moved in the control-plane scenario's window, as the
# platform and the provider report them. Real values rather than invented ones:
# the revision pair is what `/argocd/io-shop` serves for that scenario, and a
# rehearsal naming a revision the platform does not hold would have the rollback
# refused for having nothing to roll back to - an ending that looks like this
# case's and is reached for the wrong reason.
# A pair that moves whenever the scenario restages, which is the one thing to
# check before borrowing this recipe again: the demo app names them in
# `scenarios.py` as `THE_COMMIT_THAT_MOVED_THE_MONTH_BOUNDARY` and the commit
# before it, and a copy here that has fallen behind fabricates a walk against a
# deployment that is not the one staged.
THE_REVISION_THAT_WENT_OUT: Final = "3398e10e131ea6c16f468f1bc1ac0fa6426d1b0c"
THE_REVISION_BEFORE_IT: Final = "f0bcdb929bc6e89981742d03b02f36a40cd19ca0"
THE_FLAG_THAT_WENT_ON: Final = "monthly-spend-feature"


def _a_deployment_ranked_above_a_flag(was: dict[str, Any]) -> dict[str, Any]:
    """The borrowed `final_answer`, replaced by two candidates in a fixed order.

    The one rehearsal here whose rewrite is about the *order* rather than the
    conclusion. What the case replaying it asserts is that Argus reaches for the
    rollback, is told the platform cannot carry it, passes over the other actions
    that go through that platform, and ends on the flag revert - and none of that
    happens unless the deployment outranks the flag. So both candidates are
    named, deployment first, and the confidences are close enough that the order
    is a judgement rather than a formality.

    Borrowed from the flag walk rather than the deployment one, because the
    answers *after* this are what decide which set is replayable: this world ends
    with a flag reverted and a fault still in the code, so the fix the borrowed
    walk proposes is the fix this walk would propose, and the postmortem is
    written about the same incident. The deployment walk ends with no patch at
    all and would run the queue dry at Code-Fix.

    What it cannot prove is the thing it fabricates, and that was established the
    expensive way. Staged against a revision that reworked some other function, a
    real model ranked the flag first and said why: a deploy whose diff cannot
    reach the failing call path is not a better explanation for being nearer in
    time. The scenario was restaged so the deploy owns that path, and only then
    did the ranking come back the way this recipe assumes. So a green replay of a
    fabricated set says the walk narrows correctly *given* the ranking, and never
    that the ranking is what a model returns.
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
                            "confidence": 0.71,
                            "failure_mode": "bad-deployment",
                            "faulting_service": None,
                            "from_state": THE_REVISION_BEFORE_IT,
                            "subject": (
                                f"revision {THE_REVISION_THAT_WENT_OUT} "
                                f"(the month boundary the average divides by)"
                            ),
                            "summary": (
                                f"Two changes reached the account page in the "
                                f"same window and this is the one that owns the "
                                f"failing path: revision "
                                f"{THE_REVISION_THAT_WENT_OUT} went out at the "
                                f"onset minute and moves the boundary deciding "
                                f"which purchases fall in this month, which is "
                                f"the divisor the monthly average divides by. "
                                f"The error rate steps "
                                f"from the shop's 1% baseline to a third while "
                                f"every quantile and both resource gauges hold "
                                f"flat, which is a code path that fails rather "
                                f"than one that slows. Returning the deployment "
                                f"to {THE_REVISION_BEFORE_IT} puts the boundary "
                                f"back."
                            ),
                            "supporting_evidence": [
                                {
                                    "at": "2026-09-28T21:38:00Z",
                                    "claim": (
                                        f"deployed revision "
                                        f"{THE_REVISION_THAT_WENT_OUT}, from "
                                        f"deploy"
                                    )
                                },
                                {
                                    "at": "2026-09-28T21:38:00Z",
                                    "claim": (
                                        "account page request failed - "
                                        "ZeroDivisionError: division by zero at "
                                        "src/io_shop/spend_summary.py:47"
                                    )
                                },
                                {
                                    "at": "2026-09-28T21:39:00Z",
                                    "claim": (
                                        "error rate 0.01 -> 0.33 with p50/p95/p99 "
                                        "and cpu_used_cores unmoved"
                                    )
                                }
                            ],
                            "to_state": THE_REVISION_THAT_WENT_OUT
                        },
                        {
                            "confidence": 0.63,
                            "failure_mode": "feature-flag-toggle",
                            "faulting_service": None,
                            "from_state": "off",
                            "subject": THE_FLAG_THAT_WENT_ON,
                            "summary": (
                                f"The runner-up, and the same symptom from the "
                                f"other direction: {THE_FLAG_THAT_WENT_ON} was "
                                f"switched on for two in five account pages in "
                                f"the same window, and the shop's own "
                                f"evaluations move with the failures. It is "
                                f"ranked second because it explains which pages "
                                f"reach the failing path and not why that path "
                                f"fails: the flag exposed code the deploy had "
                                f"just changed. Switching it back off ends the "
                                f"incident either way."
                            ),
                            "supporting_evidence": [
                                {
                                    "at": "2026-09-28T21:38:00Z",
                                    "claim": (
                                        f"feature flag {THE_FLAG_THAT_WENT_ON} "
                                        f"was switched on"
                                    )
                                },
                                {
                                    "at": "2026-09-28T21:39:00Z",
                                    "claim": (
                                        f"{THE_FLAG_THAT_WENT_ON}=off 120 / on "
                                        f"80 - 200 evaluations"
                                    )
                                }
                            ],
                            "to_state": "on"
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


# The tool Code-Fix ends with when it finds nothing to change - what the borrowed
# blind-spot walk answered, and what the drift rehearsal turns into a fix.
THE_TOOL_THAT_FINDS_NOTHING: Final = "report_nothing_to_change"

# The scrape configuration a roll-forward writes, and where the shop's checkout
# holds it. Read from the checkout rather than from the repository double, which
# carries the shop's source and not its deployment files.
THE_SCRAPE_CONFIGURATION: Final = "deploy/scrape.yaml"
THE_SHOPS_CHECKOUT: Final = Path(__file__).resolve().parent.parent.parent / "Argus-Demo-Target-App"
THE_STALE_SELECTOR: Final = "- port: metrics\n"
THE_SELECTOR_ROLLED_FORWARD: Final = "- port: http-metrics\n"

# The test a roll-forward brings: the scrape selects the port the values name.
# Fails against `main`, where the two disagree, and passes once they agree.
THE_TEST_OF_THE_SCRAPE: Final = "tests/io_shop/test_scrape_configuration.py"
THE_TEST_OF_THE_SCRAPE_READS: Final = '''from __future__ import annotations

from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def test_the_scrape_selects_the_port_the_metrics_are_served_on() -> None:
    values = yaml.safe_load(
        (DEPLOY / "values-production.yaml").read_text(encoding="utf-8"))
    scrape = yaml.safe_load((DEPLOY / "scrape.yaml").read_text(encoding="utf-8"))

    selected = {endpoint["port"] for endpoint in scrape["spec"]["endpoints"]}

    assert values["metrics"]["portName"] in selected
'''


def _a_rename_the_monitoring_did_not_follow(was: dict[str, Any]) -> dict[str, Any]:
    """The borrowed `final_answer`, replaced by drift ranked above a bad deployment.

    Borrowed from the blind spot's walk, which is the same world in every channel:
    the absence alert, the rows that stop, the logs, one revision at the onset.
    The second candidate is the point. A rollback answers it and a deployment is
    recorded for it, so a walk that passed to it would roll back - and what the
    rehearsal exercises is that it does not.
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
                            "confidence": 0.8,
                            "failure_mode": "monitoring-configuration-drift",
                            "faulting_service": None,
                            "subject": "metrics.portName",
                            "summary": (
                                "The revision at the onset renamed every port in "
                                "io-shop's values to one convention - web to "
                                "http, admin to http-admin, metrics to "
                                "http-metrics - and states the convention in a "
                                "comment. The rename was meant. The scrape still "
                                "selects the old name, so collection stopped "
                                "while the logs show the shop serving normally. "
                                "What is behind is the scrape configuration."
                            ),
                            "supporting_evidence": [
                                {
                                    "at": None,
                                    "claim": (
                                        "-    portName: metrics\n"
                                        "+    portName: http-metrics"
                                    )
                                }
                            ]
                        },
                        {
                            "confidence": 0.3,
                            "failure_mode": "bad-deployment",
                            "faulting_service": None,
                            "subject": "io-shop revision",
                            "summary": (
                                "The same revision read as a mistake to return."
                            ),
                            "supporting_evidence": []
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


def _the_scrape_rolled_forward() -> str:
    """The shop's scrape configuration, selecting the port's new name."""
    held = (THE_SHOPS_CHECKOUT / THE_SCRAPE_CONFIGURATION).read_text(encoding="utf-8")

    if THE_STALE_SELECTOR not in held:
        raise SystemExit(
            f"[{THE_SCRAPE_CONFIGURATION}] in the shop's checkout no longer "
            f"selects [{THE_STALE_SELECTOR.strip()}] - the fixture has moved, and "
            f"a fabricated fix against a file that has changed rehearses nothing"
        )

    return held.replace(THE_STALE_SELECTOR, THE_SELECTOR_ROLLED_FORWARD, 1)


def _a_fix_of_the_scrape_configuration(was: dict[str, Any]) -> dict[str, Any]:
    """The borrowed "nothing to change", replaced by the scrape rolled forward.

    The envelope kept as recorded, for the reason every rewrite here keeps it; the
    block's name and input are the fabrication.
    """
    answered = False
    content = []

    for block in was["content"]:
        if block.get("type") == TOOL_USE_TYPE and block.get("name") == THE_TOOL_THAT_FINDS_NOTHING:
            block = {
                **block,
                "name": THE_TOOL_THAT_SUBMITS_A_FIX,
                "input": {
                    "summary": "Select the metrics port by the name the convention gave it",
                    "explanation": (
                        "The revision named every port for its protocol, and the "
                        "scrape configuration still selects the metrics port as "
                        "'metrics'. It now selects 'http-metrics', the name the "
                        "values file gives it; the rename is kept."
                    ),
                    "files": [
                        {
                            "path": THE_SCRAPE_CONFIGURATION,
                            "content": _the_scrape_rolled_forward()
                        },
                        {
                            "path": THE_TEST_OF_THE_SCRAPE,
                            "content": THE_TEST_OF_THE_SCRAPE_READS
                        }
                    ]
                }
            }
            answered = True

        content.append(block)

    if not answered:
        raise SystemExit(
            f"the borrowed walk has no [{THE_TOOL_THAT_FINDS_NOTHING}] answer to "
            f"rewrite, so its Code-Fix did not end by finding nothing"
        )

    return {**was, "content": content}


# Which answers have to be rewritten, by the set being fabricated, and which tool
# call marks each. A rehearsal borrows a walk through a world shaped like the new
# one, so most answers are already right: the investigation read evidence of the
# same shape, and the postmortem is written from the incident rather than from
# what was done about it. A set absent from here is one where *nothing* has to
# differ and the borrowed answers are stored as they stand - which is the
# ordinary case rather than a shortcut, and is what makes a scenario whose walk
# differs only in its prose free to rehearse.
#
# The tool is named beside each rewrite rather than assumed, because the
# rehearsals differ in which answers they touch. The large-fix set borrows a walk
# that reached the right conclusion about the wrong file, so only the fix
# differs; the dependency set borrows a walk that reached a different conclusion
# entirely, so it is the investigation's own answer that has to change and the
# fix after it is left as the borrowed walk wrote it. The drift set needs both:
# a different conclusion, and a fix where the borrowed walk found none.
_THE_ANSWERS_THAT_HAVE_TO_DIFFER: Final[
    dict[str, tuple[tuple[str, Callable[[dict[str, Any]], dict[str, Any]]], ...]]
] = {
    STORED_AS: ((THE_TOOL_THAT_SUBMITS_A_FIX, _a_fix_of_the_large_module),),
    "grep-pricing-service-degraded": ((THE_TOOL_THAT_ANSWERS,
                                       _a_failing_internal_dependency),),
    "both-pricing-service-degraded": ((THE_TOOL_THAT_ANSWERS,
                                       _a_failing_internal_dependency),),
    "grep-cpu-saturation": ((THE_TOOL_THAT_ANSWERS, _a_deployment_that_is_too_small),),
    "both-cpu-saturation": ((THE_TOOL_THAT_ANSWERS, _a_deployment_that_is_too_small),),
    # `both` alone, as the large-fix set is and for its reason: the case that
    # replays this is collected in that mode only (`noxfile._the_cases_for`), so a
    # `grep-` set of it would answer a question no session asks.
    "both-autoscaler-flapping": ((THE_TOOL_THAT_ANSWERS,
                                  _a_controller_that_will_not_settle),),
    # `both` alone, for the reason above it: the two cases that replay this are
    # collected in that mode only.
    "both-half-finished-rollout": ((THE_TOOL_THAT_ANSWERS,
                                    _a_rollout_that_stopped_half_way),),
    # `both` alone, for the reason above it: the case that replays this is
    # collected in that mode only.
    "both-control-plane-unreachable": ((THE_TOOL_THAT_ANSWERS,
                                        _a_deployment_ranked_above_a_flag),),
    # `both` alone, and here the reason is the opposite of the four above it.
    # Those are collected in that mode only because nothing about their claim
    # varies by which tool found a file. This one is *excluded* from `meaning`
    # only, and will be recorded under `grep` as well - so the day that happens
    # a `grep-` set becomes worth fabricating too. Until then `both` is the mode
    # anybody runs, so it is the mode worth rehearsing.
    "both-cache-failed-over": ((THE_TOOL_THAT_ANSWERS,
                                _a_cache_serving_figures_the_ledger_moved_past),),
    # `both` alone, as the blind spot it borrows from is recorded. Two answers
    # differ, which no set above needed: the investigation reaches a different
    # conclusion, and Code-Fix, which found nothing to change in the blind spot,
    # rolls the scrape configuration forward here.
    "both-monitoring-configuration-drift": (
        (THE_TOOL_THAT_ANSWERS, _a_rename_the_monitoring_did_not_follow),
        (THE_TOOL_THAT_FINDS_NOTHING, _a_fix_of_the_scrape_configuration)
    )
}


def _the_anchor_of(name: str) -> Path:
    """Where a set keeps the instant the world it was captured in was seeded.

    Spelled here rather than imported from `tests.e2e.framework.argus`, which
    owns the reading half: a script under `scripts/` is not part of that package
    tree, and importing across into it would give one module two names for the
    sake of one suffix.
    """
    return RECORDINGS_DIR / f"{name}{ANCHOR_SUFFIX}"


def _borrow_the_anchor(borrowed_from: str, stored_as: str) -> Path | None:
    """Copies the source set's seeding instant across, unchanged.

    The answers carry retrieval windows frozen at the instant they were captured,
    and the replay moves them into this run's world by the gap between the two
    seedings. That gap is measured from the anchor, so a fabricated set without
    one is replayed unshifted: every channel is asked about an hour that no longer
    holds an incident, answers correctly with nothing, and the case fails for a
    property of the borrowing rather than of Argus.

    The source's instant and not a new one, because the windows being rebased are
    the source's. A set whose source has no anchor gets none either - that is a
    recording captured before anchors were written, and inventing one would claim
    a world was seeded at an instant nobody observed.
    """
    anchor = _the_anchor_of(borrowed_from)

    if not anchor.exists():
        return None

    destination = _the_anchor_of(stored_as)
    destination.write_text(
        anchor.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
    )

    return destination


def _write(borrowed: list[Path], stored_as: str) -> list[Path]:
    """Stores the set under the new name, answer for answer.

    Numbered exactly as the source was, because the double serves a queue in
    order and a gap in the numbering is a walk that stops one answer early.
    """
    differs = _THE_ANSWERS_THAT_HAVE_TO_DIFFER.get(stored_as, ())
    written = []

    for index, path in enumerate(borrowed, start=1):
        now = json.loads(path.read_text(encoding="utf-8"))

        for tool, rewrite in differs:
            if any(block.get("name") == tool for block in now["content"]):
                now = rewrite(now)
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

        anchor = _the_anchor_of(arguments.stored_as)

        if anchor.exists():
            anchor.unlink()
            print(f"removed {anchor.name}")

        return 0

    _the_two_names_share_a_mode(arguments.borrowed_from, arguments.stored_as)
    borrowed = _the_answers_of(arguments.borrowed_from)

    if not borrowed:
        raise SystemExit(
            f"no recording named [{arguments.borrowed_from}] to borrow a walk "
            f"from"
        )

    written = _write(borrowed, arguments.stored_as)
    anchored = _borrow_the_anchor(arguments.borrowed_from, arguments.stored_as)

    print(f"fabricated {len(written)} answers as {arguments.stored_as}:")
    for path in written:
        print(f"  {path.name}  {path.stat().st_size:>7} bytes")

    if anchored is not None:
        print(f"  {anchored.name}  the source's seeding instant, so the windows "
              f"rebase")
    else:
        print(f"  no anchor beside [{arguments.borrowed_from}], so nothing is "
              f"rebased and the recorded windows are replayed as captured")

    print(
        "\nThese are made up. They prove the pipeline and nothing about the "
        "model.\nDo not commit them; `nox -s record` replaces them with the "
        "real thing."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
