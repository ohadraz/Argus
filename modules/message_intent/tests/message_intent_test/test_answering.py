"""A person's question, answered from the incident's record - asked once, and
once more.

The model is given the question exactly as written and the incident's timeline,
one line per event, as the page and the thread say it: when, who, and what. It
is given nothing else, and is held to it - an answer the record does not
support is worse than none, because the person reading it has no way to tell.

The answer is the one field of a tool the model must call, so a reply is never
parsed out of prose. How it is asked - again where the answer cannot be used,
and never more than the attempts it is given - is
`core.llm.ask_until_answered`'s, and tested there. What is this module's is
the question, the tool, the reading of an answer, and that it is asked twice.
What the person is told where there is no answer, and who else is, is
`understanding`'s to say.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from argus_testkit import Kept, Scenario, all_of, the_answer_was
from core import to_iso
from core.models import ToolCall, Turn
from message_intent.answering import ANSWER_FIELD, ANSWER_TOOL_NAME, answer
from narration import CandidateLine, NarrationLine

from message_intent_test.framework.assertions import (
    asked_through,
    reads,
    the_model_was_shown,
    the_tools_offered_were,
)
from message_intent_test.framework.builders import (
    Asked,
    a_model_never_asked,
    a_reply_in_prose,
    an_asking,
)

# Whether a line may support a rule-out: read by none of these cases.
DONT_CARE_MAY_RULE_OUT = True

SOME_QUESTION = "why did you revert the checkout flag?"
SOME_ANSWER = "The checkout flag was switched on at 12:01, a minute before errors rose."
# Where the question was asked, by the name a chat platform's adapter gives it.
SOME_PLATFORM = "Kukichat"
# How many times one question is asked about.
TWICE = 2
# What the asking finds where no answer was usable.
NO_ANSWER: str | None = None
A_BLANK_ANSWER = "   "

# What the model is held to - answering from the timeline alone, and saying so
# when the timeline is silent - in words rather than sentences, so the prose
# around them is free to be improved.
WHAT_THE_MODEL_IS_HELD_TO = "only from"
WHAT_IT_SAYS_OF_A_SILENT_RECORD = "does not say"
# And that a line's measure is told in that line's words: "no longer at the
# incident's level" retold as "back to normal" was an answer the record did not
# give, since the two are different measures with different times.
WHAT_A_MEASURE_IS_TOLD_IN = "in that line's own words"


@pytest.mark.unit
def test_what_the_asking_finds_is_the_answer_given() -> None:
    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_answer_was(SOME_ANSWER))


@pytest.mark.unit
def test_no_answer_found_leaves_the_question_unanswered() -> None:
    Scenario() \
        .given(an_asker := an_asking(answering=NO_ANSWER)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_the_model_is_asked_twice_at_most_and_through_the_model_given() -> None:
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(some_model := a_model_never_asked(),
               an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), some_model,
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(asked_through(asked, some_model, attempts=TWICE))


@pytest.mark.unit
def test_the_model_is_told_the_platform_the_question_was_asked_on() -> None:
    # Said by the name its adapter gives it, so the sentence names no vendor
    # of its own - and with Slack's name says exactly what it always said.
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_model_was_shown(asked, f"in the {SOME_PLATFORM} thread of an incident"))


@pytest.mark.unit
def test_the_question_reaches_the_model_exactly_as_written() -> None:
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_model_was_shown(asked, SOME_QUESTION))


@pytest.mark.unit
def test_the_model_is_shown_every_line_of_the_timeline_with_when_and_who() -> None:
    # The account a person could read for themselves, line for line - so an
    # answer is about what Argus recorded, in the words it recorded it in.
    asked: Kept[Asked[str]] = Kept()
    some_timeline = _a_timeline()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, some_timeline, a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(all_of(*(
            the_model_was_shown(asked, said)
            for line in some_timeline
            for said in (to_iso(line.at), line.who, line.text)
        )))


@pytest.mark.unit
def test_the_model_is_shown_what_a_line_says_beside_itself() -> None:
    # Where Code-Fix found nothing to change, what it said would have to change
    # elsewhere is the thread's likeliest question - and the answer is on the
    # line, beside its sentence rather than in it.
    asked: Kept[Asked[str]] = Kept()
    some_aside = "Code-Fix's reading of the code, which nothing ran: scrape.yaml names the old port"
    some_timeline = [
        NarrationLine(at=datetime(2026, 10, 11, 12, 9, tzinfo=UTC),
                      kind="fix-attempted",
                      who="Code-Fix Agent",
                      text="Read the code and found no code-level fix to make",
                      aside=some_aside, may_rule_out=DONT_CARE_MAY_RULE_OUT)
    ]

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, some_timeline, a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_model_was_shown(asked, some_aside))


@pytest.mark.unit
def test_every_line_of_an_aside_is_indented_under_its_line() -> None:
    # An explanation runs to more than one line; a later one at the margin
    # reads as a line of the timeline of its own, said by nobody at no time.
    asked: Kept[Asked[str]] = Kept()
    some_timeline = [
        NarrationLine(at=datetime(2026, 10, 11, 12, 9, tzinfo=UTC),
                      kind="fix-attempted",
                      who="Code-Fix Agent",
                      text="Read the code and found no code-level fix to make",
                      aside="Code-Fix's reading: scrape.yaml\nnames the old port",
                      may_rule_out=DONT_CARE_MAY_RULE_OUT)
    ]

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, some_timeline, a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_model_was_shown(asked,
                                   "\n  Code-Fix's reading: scrape.yaml\n  names the old port\n"))


@pytest.mark.unit
@pytest.mark.parametrize(("line", "said"), [
    (NarrationLine(at=datetime(2026, 10, 11, 12, 4, tzinfo=UTC), kind="action-taken",
                   who="Mitigator", text="Reverted the feature flag checkout, moved ",
                   moved_from="ON", moved_to="OFF", may_rule_out=DONT_CARE_MAY_RULE_OUT),
     "Reverted the feature flag checkout, moved from ON to OFF"),
    (NarrationLine(at=datetime(2026, 10, 11, 12, 3, tzinfo=UTC), kind="hypothesis-formed",
                   who="Investigator Agent", text="Formed 1 candidate cause, best first:",
                   candidates=[CandidateLine(hypothesis_id="h1", number=1,
                                             summary="The checkout flag broke the page",
                                             subject="checkout", confidence="0.8",
                                             evidence=[])], may_rule_out=DONT_CARE_MAY_RULE_OUT),
     "Formed 1 candidate cause, best first: The checkout flag broke the page")
], ids=["a-move", "candidates"])
def test_the_model_is_shown_each_line_in_full(line: NarrationLine, said: str) -> None:
    # Shown the line's text alone, the model read "Reverted the feature flag
    # monthly-spend-feature, moved " with nowhere it moved to, and "best
    # first:" with no candidate after it - what a page lays out beside the
    # sentence, and a thread has only the sentence for.
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, [line], a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_model_was_shown(asked, said))


@pytest.mark.unit
def test_the_model_is_held_to_the_timeline() -> None:
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(all_of(the_model_was_shown(asked, WHAT_THE_MODEL_IS_HELD_TO),
                     the_model_was_shown(asked, WHAT_IT_SAYS_OF_A_SILENT_RECORD)))


@pytest.mark.unit
def test_the_model_is_held_to_each_lines_own_words_for_what_it_measured() -> None:
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_model_was_shown(asked, WHAT_A_MEASURE_IS_TOLD_IN))


@pytest.mark.unit
def test_the_model_is_offered_the_one_tool_to_answer_with() -> None:
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(the_tools_offered_were(asked, [ANSWER_TOOL_NAME]))


@pytest.mark.unit
def test_a_submitted_answer_is_read_as_it() -> None:
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(reads(asked, _a_submission({ANSWER_FIELD: SOME_ANSWER}), SOME_ANSWER))


@pytest.mark.unit
@pytest.mark.parametrize("unusable", [
    lambda: a_reply_in_prose(),
    lambda: _a_submission({ANSWER_FIELD: A_BLANK_ANSWER}),
    lambda: _a_submission({})
], ids=["prose", "blank-answer", "no-answer-field"])
def test_an_answer_with_nothing_in_it_is_read_as_no_answer(
        unusable: Callable[[], Turn]) -> None:
    # Read as none, which is what the asking asks again about.
    asked: Kept[Asked[str]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_ANSWER, keeping=asked)) \
        .when(lambda: answer(SOME_QUESTION, _a_timeline(), a_model_never_asked(),
                             platform=SOME_PLATFORM, ask=an_asker)) \
        .then(reads(asked, unusable(), None))


def _a_timeline() -> list[NarrationLine]:
    """Two lines of an incident, as narration says them."""
    return [
        NarrationLine(at=datetime(2026, 10, 11, 12, 2, tzinfo=UTC),
                      kind="hypothesis-formed",
                      who="Investigator",
                      text="The checkout flag was switched on a minute before errors rose",
                      may_rule_out=DONT_CARE_MAY_RULE_OUT),
        NarrationLine(at=datetime(2026, 10, 11, 12, 5, tzinfo=UTC),
                      kind="action-taken",
                      who="Mitigator",
                      text="Reverted the checkout flag", may_rule_out=DONT_CARE_MAY_RULE_OUT)
    ]


def _a_submission(arguments: dict[str, Any]) -> Turn:
    dont_care_call_id = "dont-care-call-id"
    dont_care_tokens = 0

    return Turn(text="",
                tool_calls=[ToolCall(id=dont_care_call_id, name=ANSWER_TOOL_NAME,
                                     arguments=arguments)],
                input_tokens=dont_care_tokens, output_tokens=dont_care_tokens)
