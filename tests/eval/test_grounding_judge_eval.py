"""What the grounding judge flags and what it lets stand, against the real model.

The judge's own suite proves what code does with a flag; it says nothing about
whether the model flags what is wrong. That is measured here, two ways and as
two rates: a write-up the postmortem review cleared is let stand, and the same
kind of write-up with one fact changed has that change flagged. A judge that
flags everything passes the second and fails the first, and one that flags
nothing the reverse.

Each case's ask is pinned in `grounding_asks/` - the record, the document by
field, what is not judged, and the rows a flag may cite - copied out of the
judge recording it names. Pinned rather than read from the recordings, because
a re-record rewrites those, and a case reading them would pool two different
write-ups under one name. A write-up changes here only by a commit, which the
commit column already splits a pool on.

The rows are the labels the record prints, as production hands the judge the
labels it printed: in brackets beside each row for a write-up, and leading
each evidence line, or in brackets after a candidate, in the document an
overview is judged against.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from argus_testkit.assertions import Assertion, at_least
from argus_testkit.scenario import Scenario
from core import get_settings
from core.llm import build_llm_client
from core.llm.adapters.anthropic_adapter import AnthropicSettings, to_tool
from postmortem_writing.grounding import (
    DID_NOT_ANSWER,
    JUDGE_BRIEF,
    JUDGE_CLAIMS,
    Flag,
    flags_on,
    is_quoted_in,
    judge_policy,
)

from tests.framework.models import the_configured_models
from tests.framework.pooling import Outcome, Setup, the_samples_taken
from tests.framework.spending import Spend, Tally

# What the replay cannot say: a replayed judge answers as it was recorded
# answering, so whether the model still flags a wrong claim is measured here,
# against the real model, and spends tokens every run - about five to ten
# cents a judgement, so a case is under a dollar and the whole file several.
needs_the_real_api = pytest.mark.skipif(
    not AnthropicSettings().anthropic_api_key,
    reason="no ANTHROPIC_API_KEY: an eval has nothing to measure without the real model"
)

# The model samples, so one judgement is a draw and not a verdict. Each ask is
# judged this many times and scored as a rate - ten for the reason the
# Investigator's eval gives: it is the fewest that catches a regression.
RUNS_PER_CASE = 10

# What a sample is filed under. Spelled out rather than taken from the test's
# own name, because a pool outlives a rename.
THIS_EVAL = "grounding_judge"

# **Unmeasured** - no pooled samples yet. Written at the figure a single lapse
# survives and two do not, as a starting point; a failure before the first pool
# reads as "unmeasured", not as a regression. Re-derive per case once each has
# fifty samples, and re-measure after any change to the brief or the tool -
# both are in the digest, so a pool splits on its own.
MUST_LET_STAND = 9
MUST_FLAG = 9

ASKS = Path(__file__).resolve().parent / "grounding_asks"

# Where the judge's code says it did not answer.
THE_JUDGES_LOG = logging.getLogger("postmortem_writing.grounding")


@dataclass(frozen=True)
class Asked:
    """One ask as the judge is handed it."""

    record: str
    answer: dict[str, str]
    scope: list[str]
    rows: frozenset[str]


@dataclass(frozen=True)
class Cleared:
    """A write-up the postmortem review cleared, which the judge is to let stand."""

    case: str
    ask: str


@dataclass(frozen=True)
class Planted:
    """One fact changed in a cleared write-up: in one field, `find` said as
    `replace`, which the judge is to flag."""

    case: str
    ask: str
    field: str
    find: str
    replace: str


@dataclass(frozen=True)
class Judged:
    """One judgement: whether the judge answered, the flags code kept, and
    what it cost."""

    answered: bool
    flags: list[Flag]
    spent: Spend


# Each held with no flags in the review's re-records of 2026-11-12, and
# committed as judged. Write-ups and overviews both, since the two are asked
# against different records.
THE_CLEARED = [
    Cleared("a-bad-deployment-write-up-is-let-stand", "bad-deployment"),
    Cleared("a-cache-misconfigured-write-up-is-let-stand", "cache-misconfigured"),
    Cleared("a-categoriser-upgrade-write-up-is-let-stand", "categoriser-model-upgraded"),
    Cleared("a-slow-canary-write-up-is-let-stand", "slow-canary-rollout"),
    Cleared("a-bad-deployment-overview-is-let-stand", "bad-deployment-2"),
    Cleared("a-feature-flag-toggle-overview-is-let-stand", "feature-flag-toggle-2")
]

# One of each kind of error the judge exists to catch, each in a different
# cleared write-up, so a judge that learned one write-up does not pass them all.
THE_PLANTED = [
    Planted("a-wrong-number-is-flagged", "flag-toggle-red-herring",
            "causal_chain 2", "spend_summary.py:47", "spend_summary.py:52"),
    Planted("a-wrong-order-in-time-is-flagged", "monitoring-configuration-drift",
            "causal_chain 3 ruled_out 1", "The earlier deploy", "The later deploy"),
    Planted("a-false-absence-is-flagged", "half-finished-rollout",
            "causal_chain 4 ruled_out 1",
            "The metrics read before the onset showed the usual error rate",
            "No metrics from before the onset were read"),
    Planted("a-suspicion-said-as-confirmed-is-flagged", "fallback-disabled",
            "causal_chain 4", "account pages likely take",
            "account pages were confirmed to take"),
    Planted("code-fix-said-to-have-run-its-tests-is-flagged", "silent-data-corruption",
            "contributing_factors 2",
            "By Code-Fix's account, the derive-path cases it adds would fail against the "
            "old code.",
            "Code-Fix ran the derive-path cases it adds, and they failed against the old "
            "code."),
    Planted("a-wrong-recommended-step-in-an-overview-is-flagged",
            "upstream-dependency-failure-3", "overview",
            "Its recommended step is to ask IO Payments Ltd to restore io-pay",
            "Its recommended step is to roll io-shop back to its previous revision")
]


@pytest.mark.eval
@needs_the_real_api
@pytest.mark.parametrize("cleared", THE_CLEARED, ids=lambda cleared: cleared.case)
def test_a_write_up_the_review_cleared_is_let_stand(cleared: Cleared) -> None:
    Scenario() \
        .given(
            asked := _the_ask(cleared.ask)
        ) \
        .when(
            lambda: _the_real_judge_reads_repeatedly(asked)
        ) \
        .then(
            _scored(cleared.case, MUST_LET_STAND, _let_stand())
        )


@pytest.mark.eval
@needs_the_real_api
@pytest.mark.parametrize("planted", THE_PLANTED, ids=lambda planted: planted.case)
def test_a_fact_changed_in_a_cleared_write_up_is_flagged(planted: Planted) -> None:
    Scenario() \
        .given(
            asked := _the_ask(planted.ask)
        ) \
        .when(
            lambda: _the_real_judge_reads_repeatedly(_with(planted, asked))
        ) \
        .then(
            _scored(planted.case, MUST_FLAG, _flagged(planted, asked))
        )


def _the_ask(name: str) -> Asked:
    pinned = json.loads((ASKS / f"{name}.json").read_text(encoding="utf-8"))

    return Asked(record=pinned["record"], answer=pinned["answer"], scope=pinned["scope"],
                 rows=frozenset(pinned["rows"]))


def _with(planted: Planted, asked: Asked) -> Asked:
    """The ask with the one fact changed - refused, before anything is paid
    for, where the words to change are not in the field exactly once."""
    said = asked.answer[planted.field]

    if said.count(planted.find) != 1:
        raise AssertionError(
            f"Expected [{planted.find}] once in {planted.ask}'s {planted.field}; it is there "
            f"{said.count(planted.find)} times."
        )

    return replace(asked, answer={
        **asked.answer, planted.field: said.replace(planted.find, planted.replace)})


def _the_real_judge_reads_repeatedly(asked: Asked) -> list[Judged]:
    """Judges the same ask `RUNS_PER_CASE` times, concurrently, as the
    Postmortem Writer would: through `flags_on`, with the judge's own model,
    effort and brief.

    Each judgement is counted through a tally of its own, and listened for on
    its own thread, so what it cost and whether it answered are its own and
    not whatever the judgements beside it did.
    """
    settings = get_settings()
    client = build_llm_client(the_configured_models(),
                              None,
                              policy=judge_policy(AnthropicSettings().judge_model,
                                                  settings.judge_effort))

    def judge_once(_: int) -> Judged:
        tally = Tally(client)
        hearing = _Hearing(threading.get_ident())
        THE_JUDGES_LOG.addHandler(hearing)

        try:
            flags = flags_on(tally, record=asked.record, answer=asked.answer, rows=asked.rows,
                             scope=asked.scope)
        finally:
            THE_JUDGES_LOG.removeHandler(hearing)

        return Judged(answered=not hearing.heard, flags=flags, spent=tally.spent())

    with ThreadPoolExecutor(max_workers=RUNS_PER_CASE) as pool:
        return list(pool.map(judge_once, range(RUNS_PER_CASE)))


class _Hearing(logging.Handler):
    """Whether the judge's code said, on one thread, that it did not answer."""

    def __init__(self, thread: int) -> None:
        super().__init__(logging.WARNING)
        self._thread = thread
        self.heard = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread == self._thread and record.getMessage() == DID_NOT_ANSWER:
            self.heard = True


def _scored(case: str, passing: int, satisfy: Assertion[Judged]) -> Assertion[list[Judged]]:
    """Scores a batch against the bar, and files every sample it took.

    Wrapped around `at_least` rather than beside it, so a case cannot be scored
    without being recorded.
    """
    def assertion(judged: list[Judged]) -> bool:
        the_samples_taken(
            THIS_EVAL,
            case,
            [Outcome(_it_held(satisfy, one), one.spent, answered=one.answered)
             for one in judged],
            the_setup_under_test()
        )

        return at_least(passing, satisfy)(judged)

    return assertion


def the_setup_under_test() -> Setup:
    """What this batch is measuring, as far as pooling is concerned.

    The model and the effort are named because they are what gets tuned. The
    brief and the tool are kept whole, because they are what these rates are
    about.
    """
    settings = get_settings()

    return Setup(
        model=AnthropicSettings().judge_model,
        effort=settings.judge_effort,
        values={},
        texts={
            "brief": JUDGE_BRIEF,
            "tool": json.dumps(to_tool(JUDGE_CLAIMS), sort_keys=True)
        }
    )


def _it_held(satisfy: Assertion[Judged], judged: Judged) -> bool:
    """Whether one judgement satisfied the claim, as a boolean rather than a raise."""
    try:
        satisfy(judged)
    except AssertionError:
        return False

    return True


def _let_stand() -> Assertion[Judged]:
    """The judge answered, and kept no flag. A judge that did not answer let
    nothing stand: it judged nothing."""
    def assertion(judged: Judged) -> bool:
        if not judged.answered:
            raise AssertionError("Expected the judge to answer; it did not.")

        if judged.flags:
            raise AssertionError(
                f"Expected no flags on a write-up the review cleared; the judge kept "
                f"{[flag.quote for flag in judged.flags]}."
            )

        return True

    return assertion


def _flagged(planted: Planted, asked: Asked) -> Assertion[Judged]:
    """The judge answered, and kept a flag in the planted field quoting words
    the change put there.

    A flag quotes the change where its quote is in the field as changed - code
    kept it, so it is - and not in the field as the review cleared it: a flag
    on another sentence of the same field is not a catch.
    """
    as_cleared = asked.answer[planted.field]

    def assertion(judged: Judged) -> bool:
        if not judged.answered:
            raise AssertionError("Expected the judge to answer; it did not.")

        on_the_change = [flag for flag in judged.flags
                         if planted.field in flag.fields
                         and not is_quoted_in(flag.quote, as_cleared)]

        if not on_the_change:
            raise AssertionError(
                f"Expected a flag in {planted.field} quoting [{planted.replace}]; the judge "
                f"kept {[(flag.fields, flag.quote) for flag in judged.flags]}."
            )

        return True

    return assertion
