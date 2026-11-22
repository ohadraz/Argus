from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import pytest
from argus_testkit.assertions import Assertion, at_least
from argus_testkit.scenario import Scenario
from core import get_settings
from core.llm import build_llm_client
from core.llm.adapters.anthropic_adapter import to_tool
from core.models import Meaning, ModelPolicy
from message_intent.classifying import classify
from message_intent.prompting import SUBMIT_MEANING, opening_ask

from tests.framework.models import the_configured_models
from tests.framework.pooling import Outcome, Setup, the_samples_taken
from tests.framework.spending import Spend, Tally

# What the replay cannot say. `intent-resolve` proves a reading reaches the
# thread as an offer; it replays one answer to one message, so it says nothing
# about whether the model reads a message the way its writer meant it. That is
# measured here, against the real model, and spends tokens every run - a few
# hundred per reading, so a whole run is cents rather than dollars.
needs_the_real_api = pytest.mark.skipif(
    not get_settings().anthropic_api_key,
    reason="no ANTHROPIC_API_KEY: an eval has nothing to measure without the real model"
)

# The model samples, so one reading is a draw and not a verdict. Each message is
# read this many times and scored as a rate - ten for the reason the
# Investigator's eval gives: it is the fewest that catches a regression.
RUNS_PER_CASE = 10

# What a sample is filed under. Spelled out rather than taken from the test's
# own name, because a pool outlives a rename.
THIS_EVAL = "intent"

# Where the person wrote, by the name the chat platform's adapter gives it - the
# platform every pooled sample was taken on, so the model is asked what it was
# asked then.
THE_CHAT_PLATFORM = "Slack"

# **Unmeasured** - no pooled samples yet. Written at the figure a single lapse
# survives and two do not, as a starting point; a failure before the first pool
# reads as "unmeasured", not as a regression. Re-derive per case once each has
# fifty samples, and re-measure after any change to the tool's description or
# the opening ask - both are in the digest, so a pool splits on its own.
MUST_READ_AS_MEANT = 9


@dataclass(frozen=True)
class Labelled:
    """One message, as a person would write it in an incident's thread, and
    what they meant by it."""

    case: str
    words: str
    meant: Meaning


@dataclass(frozen=True)
class Reading:
    """One reading of a message, and what it cost."""

    meaning: Meaning
    spent: Spend


# Two or three per meaning, and the near misses on purpose. Only `resolve` acts,
# so the cases that matter most are the ones that read like it and are not -
# asking whether it is over, saying it is not - and the one that reads like
# `withdraw` and is `resolve`, which the tool's description settles explicitly.
#
# A reading the model could not give twice falls back to `other`. So the
# `other` cases also pass a model that answered nothing; the rest are where
# that shows.
THE_LABELLED_MESSAGES = [
    Labelled("a-fix-made-by-hand-is-resolve",
             "rolled the flag back by hand, we're fine",
             Meaning.RESOLVE),
    Labelled("an-ending-seen-is-resolve",
             "error rate's been back at baseline for 15 min, looks like it's over",
             Meaning.RESOLVE),
    Labelled("an-ending-that-also-says-stop-is-resolve",
             "fixed it on our side - you can stand down",
             Meaning.RESOLVE),
    Labelled("a-question-about-the-cause-is-a-question",
             "what changed right before this started?",
             Meaning.QUESTION),
    Labelled("asking-whether-it-is-over-is-not-resolve",
             "is this resolved now?",
             Meaning.QUESTION),
    Labelled("a-fact-from-another-team-is-information",
             "fyi payments are shipping a hotfix on their side in ~10 min",
             Meaning.INFORMATION),
    Labelled("saying-it-is-not-over-is-not-resolve",
             "not fixed yet, still seeing 503s on checkout",
             Meaning.INFORMATION),
    Labelled("taking-it-over-is-withdraw",
             "stop, I've got this one - leave it to me",
             Meaning.WITHDRAW),
    Labelled("cancelling-is-withdraw",
             "cancel whatever you're doing, I'm handling it manually",
             Meaning.WITHDRAW),
    Labelled("thanks-is-other",
             "thanks argus 🙏",
             Meaning.OTHER),
    Labelled("people-talking-to-each-other-is-other",
             "@dana can you jump on the bridge?",
             Meaning.OTHER),
    Labelled("a-reaction-is-other",
             "oof",
             Meaning.OTHER)
]


@pytest.mark.eval
@needs_the_real_api
@pytest.mark.parametrize("message", THE_LABELLED_MESSAGES, ids=lambda message: message.case)
def test_a_message_is_read_as_its_writer_meant_it(message: Labelled) -> None:
    Scenario() \
        .given(
            message
        ) \
        .when(
            lambda: _the_real_model_reads_repeatedly(message.words)
        ) \
        .then(
            _scored(message.case, MUST_READ_AS_MEANT, _read_as(message.meant))
        )


def _the_real_model_reads_repeatedly(words: str) -> list[Reading]:
    """Reads the same message `RUNS_PER_CASE` times, concurrently, as the
    intent reader would: through `classify`, with the intent reader's own model and
    effort, and its second ask included.

    Each reading is counted through a tally of its own, so what it cost is its
    own and not whatever the readings beside it spent.

    Nothing is recorded. What an eval reads is the meaning and what it cost, and
    a run that also filed receipts would be measuring the same model through
    more code.
    """
    settings = get_settings()
    llm = build_llm_client(
        the_configured_models(),
        policy=ModelPolicy(model=settings.intent_model, effort=settings.intent_effort)
    )

    def read_once(_: int) -> Reading:
        tally = Tally(llm)
        # Unclassified counts as the intent reader counts it: nothing to act on.
        meaning = classify(words, tally, platform=THE_CHAT_PLATFORM)

        return Reading(meaning if meaning is not None else Meaning.OTHER, tally.spent())

    with ThreadPoolExecutor(max_workers=RUNS_PER_CASE) as pool:
        return list(pool.map(read_once, range(RUNS_PER_CASE)))


def _scored(case: str,
            passing: int,
            satisfy: Assertion[Reading]) -> Assertion[list[Reading]]:
    """Scores a batch against the bar, and files every sample it took.

    Wrapped around `at_least` rather than beside it, so a case cannot be scored
    without being recorded.
    """
    def assertion(readings: list[Reading]) -> bool:
        the_samples_taken(
            THIS_EVAL,
            case,
            [Outcome(_it_held(satisfy, reading), reading.spent) for reading in readings],
            the_setup_under_test()
        )

        return at_least(passing, satisfy)(readings)

    return assertion


def the_setup_under_test() -> Setup:
    """What this batch is measuring, as far as pooling is concerned.

    The model and the effort are named because they are what gets tuned. The
    prompt is kept whole, because it is what these rates are about: the tool as
    the model is offered it, and the ask with a stand-in where the message goes.
    """
    settings = get_settings()

    return Setup(
        model=settings.intent_model,
        effort=settings.intent_effort,
        values={},
        texts={
            "tool": json.dumps(to_tool(SUBMIT_MEANING), sort_keys=True),
            "ask": json.dumps(
                [said.model_dump(mode="json")
                 for said in opening_ask("<the message>", THE_CHAT_PLATFORM)],
                sort_keys=True
            )
        }
    )


def _it_held(satisfy: Assertion[Reading], reading: Reading) -> bool:
    """Whether one reading satisfied the claim, as a boolean rather than a raise."""
    try:
        satisfy(reading)
    except AssertionError:
        return False

    return True


def _read_as(meant: Meaning) -> Assertion[Reading]:
    def assertion(read: Reading) -> bool:
        if read.meaning != meant:
            raise AssertionError(
                f"Expected the message to be read as [{meant}]; it was read as "
                f"[{read.meaning}]."
            )

        return True

    return assertion
