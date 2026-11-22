"""What a person meant, as the model classifies it - asked once, and once more.

One question with five answers, put to the model as a tool it must call. The
person's words go to it exactly as written: a paraphrase on the way in would be
Argus deciding what they meant before asking.

How it is asked - again where the answer cannot be used, and never more than
the attempts it is given - is `core.llm.ask_until_answered`'s, and tested there.
What is this module's is the question, the tool, the reading of an answer, and
that it is asked twice: never more, because the intent reader takes every
message in order and a message that is never classified holds up every message
behind it. What an unclassified message counts as, and who is told, is
`understanding`'s to say: only it knows which incident and which message it
was.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from argus_testkit import Kept, Scenario, the_answer_was
from core.models import Meaning, ToolCall, Turn
from message_intent.classifying import classify
from message_intent.prompting import MEANING_FIELD, SUBMIT_TOOL_NAME

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

SOME_WORDS = "rolled the flag back by hand, we're fine now"
# Where the words were written, by the name a chat platform's adapter gives it.
SOME_PLATFORM = "Kukichat"
SOME_MEANING = Meaning.RESOLVE
# How many times one message is asked about.
TWICE = 2
# What the asking finds where no answer was usable.
NO_MEANING: Meaning | None = None
A_MEANING_NOBODY_OFFERED = "a-meaning-nobody-offered"


@pytest.mark.unit
def test_what_the_asking_finds_is_the_meaning_classified() -> None:
    Scenario() \
        .given(an_asker := an_asking(answering=SOME_MEANING)) \
        .when(lambda: classify(SOME_WORDS, a_model_never_asked(), platform=SOME_PLATFORM,
                               ask=an_asker)) \
        .then(the_answer_was(SOME_MEANING))


@pytest.mark.unit
def test_no_meaning_found_leaves_the_message_unclassified() -> None:
    Scenario() \
        .given(an_asker := an_asking(answering=NO_MEANING)) \
        .when(lambda: classify(SOME_WORDS, a_model_never_asked(), platform=SOME_PLATFORM,
                               ask=an_asker)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_the_model_is_asked_twice_at_most_and_through_the_model_given() -> None:
    asked: Kept[Asked[Meaning]] = Kept()

    Scenario() \
        .given(some_model := a_model_never_asked(),
               an_asker := an_asking(answering=SOME_MEANING, keeping=asked)) \
        .when(lambda: classify(SOME_WORDS, some_model, platform=SOME_PLATFORM,
                               ask=an_asker)) \
        .then(asked_through(asked, some_model, attempts=TWICE))


@pytest.mark.unit
def test_the_model_is_told_the_platform_the_person_wrote_on() -> None:
    # Said by the name its adapter gives it, so the sentence names no vendor
    # of its own - and with Slack's name says exactly what it always said.
    asked: Kept[Asked[Meaning]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_MEANING, keeping=asked)) \
        .when(lambda: classify(SOME_WORDS, a_model_never_asked(), platform=SOME_PLATFORM,
                               ask=an_asker)) \
        .then(the_model_was_shown(asked, f"in the {SOME_PLATFORM} thread of an incident"))


@pytest.mark.unit
def test_the_persons_words_reach_the_model_exactly_as_written() -> None:
    asked: Kept[Asked[Meaning]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_MEANING, keeping=asked)) \
        .when(lambda: classify(SOME_WORDS, a_model_never_asked(), platform=SOME_PLATFORM,
                               ask=an_asker)) \
        .then(the_model_was_shown(asked, SOME_WORDS))


@pytest.mark.unit
def test_the_model_is_offered_the_one_tool_to_answer_with() -> None:
    asked: Kept[Asked[Meaning]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_MEANING, keeping=asked)) \
        .when(lambda: classify(SOME_WORDS, a_model_never_asked(), platform=SOME_PLATFORM,
                               ask=an_asker)) \
        .then(the_tools_offered_were(asked, [SUBMIT_TOOL_NAME]))


@pytest.mark.unit
@pytest.mark.parametrize("meaning", list(Meaning))
def test_a_submission_of_one_of_the_five_meanings_is_read_as_it(meaning: Meaning) -> None:
    asked: Kept[Asked[Meaning]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_MEANING, keeping=asked)) \
        .when(lambda: classify(SOME_WORDS, a_model_never_asked(), platform=SOME_PLATFORM,
                               ask=an_asker)) \
        .then(reads(asked, _a_submission({MEANING_FIELD: str(meaning)}), meaning))


@pytest.mark.unit
@pytest.mark.parametrize("unusable", [
    lambda: a_reply_in_prose(),
    lambda: _a_submission({MEANING_FIELD: A_MEANING_NOBODY_OFFERED}),
    lambda: _a_submission({})
], ids=["prose", "unoffered-meaning", "no-meaning"])
def test_an_answer_that_names_none_of_the_five_is_read_as_no_meaning(
        unusable: Callable[[], Turn]) -> None:
    # Read as none, which is what the asking asks again about.
    asked: Kept[Asked[Meaning]] = Kept()

    Scenario() \
        .given(an_asker := an_asking(answering=SOME_MEANING, keeping=asked)) \
        .when(lambda: classify(SOME_WORDS, a_model_never_asked(), platform=SOME_PLATFORM,
                               ask=an_asker)) \
        .then(reads(asked, unusable(), None))


def _a_submission(arguments: dict[str, Any]) -> Turn:
    dont_care_call_id = "dont-care-call-id"
    dont_care_tokens = 0

    return Turn(text="",
                tool_calls=[ToolCall(id=dont_care_call_id, name=SUBMIT_TOOL_NAME,
                                     arguments=arguments)],
                input_tokens=dont_care_tokens, output_tokens=dont_care_tokens)
