"""One exchange with the model, as the Investigator's loop reads it.

The counterpart to `test_verdict.py`. That file covers the answer the model
gives when it is asked one question and replies once; this one covers the turn
it takes when it can ask for evidence first - what it said, what it wants
called, and what the round cost. Offline for the same reason: what is under
test is the translation, not the call.

A turn is deliberately not the SDK's `Message` passed along. The loop dispatches
on it, counts a budget from it, and narrates it, and none of those should be
written against a vendor's response shape.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Final

import pytest
from anthropic.types import (
    ContentBlock,
    Message,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged
from core.models import ToolDefinition, Turn
from llm_anthropic import (
    ASSISTANT_ROLE,
    END_TURN_STOP_REASON,
    MESSAGE_TYPE,
    TEXT_TYPE,
    THINKING_TYPE,
    TOOL_USE_STOP_REASON,
    TOOL_USE_TYPE,
    to_turn,
)

# The logger the adapter writes under: its module's name.
THE_ADAPTER: Final = "llm_anthropic.adapter"

# A tool shaped like Code-Fix's submission, which is where the tag form was
# met: two prose arguments and a list of whole files. Named once, so every tag
# below is derived from the name it carries.
SUMMARY: Final = "summary"
EXPLANATION: Final = "explanation"
FILES: Final = "files"
A_PATCH_TOOL: Final = ToolDefinition(
    name="submit_fix",
    description="dont care what it does",
    properties={
        SUMMARY: {"type": "string"},
        EXPLANATION: {"type": "string"},
        FILES: {"type": "array", "items": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]
        }}
    },
    required=[SUMMARY, EXPLANATION, FILES]
)
SOME_PATCH: Final = [{"path": "src/io_shop/spend_summary.py", "content": "return 0\n"}]
# What arrives in `files` when the patch went into the prose instead.
A_POINTER_TO_THE_PATCH: Final = [{"path": "src/io_shop/spend_summary.py",
                                  "content": "(see explanation)"}]


def _opening(argument: str) -> str:
    """The tag the model opens a parameter with in its own call syntax."""
    return f'<parameter name="{argument}">'


def _closing(argument: str) -> str:
    """The tag that closes one."""
    return f"</{argument}>"


@pytest.mark.unit
def test_a_requested_tool_call_reaches_the_turn_whole() -> None:
    # The loop dispatches on all three: the name picks the function, the
    # arguments are its window, and the id is what the result must be sent
    # back under. A turn that dropped any of them could not be answered.
    #
    # Asserted together rather than one at a time, because a translation that
    # lost the arguments should say so even while it is also losing the id.
    some_call_id = "toolu_01ABC"
    some_tool_name = "get_logs"
    some_window = {"window_start": "2026-08-29T22:00:00Z"}

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(
                    call_id=some_call_id, name=some_tool_name, arguments=some_window
                )
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            all_of(
                _the_calls_are_identified_by(some_call_id),
                _the_calls_name(some_tool_name),
                _the_calls_ask_for(some_window)
            )
        )


@pytest.mark.unit
def test_every_tool_call_of_one_turn_is_carried() -> None:
    # The model may ask for several channels at once, and the API returns them
    # as one turn. Keeping only the first would silently halve the evidence it
    # asked for, and the missing result would be one the model is still
    # waiting on.
    some_tool_name = "get_logs"
    another_tool_name = "get_changes"
    dont_care_call_id = "toolu_1"
    dont_care_another_call_id = "toolu_2"

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(call_id=dont_care_call_id, name=some_tool_name),
                _a_tool_call(call_id=dont_care_another_call_id, name=another_tool_name)
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _the_calls_name(some_tool_name, another_tool_name)
        )


@pytest.mark.unit
def test_a_tool_call_written_as_prose_is_not_a_tool_call() -> None:
    # Two things at once, because they are the same check: how the loop tells
    # "I am still working" from "I have stopped", and that only a real request
    # counts as one.
    #
    # A real failure mode, not a hypothetical: with thinking turned off the
    # model sometimes writes a tool call into its visible text instead of
    # emitting a request for one. The turn succeeds, nothing runs, and no
    # error is raised. A translation that read text would dispatch a call the
    # model never made - and worse, would keep the loop going on evidence
    # nobody asked for.
    some_prose_shaped_like_a_request = (
        '{"name": "get_logs", "input": {"window_start": "2026-08-29T22:00:00Z"}}'
    )

    Scenario() \
        .given(
            some_message := _a_message_that_only_spoke(some_prose_shaped_like_a_request)
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _nothing_was_asked_for()
        )


@pytest.mark.unit
def test_what_the_model_said_reaches_the_turn() -> None:
    # Narration reads this. The model's own account of what it is doing is the
    # readable half of an investigation's transcript, and a turn that dropped
    # it would leave a human with a list of windows and no reasoning.
    some_narration = "The error rate climbs at 22:15; checking what changed before it."

    Scenario() \
        .given(
            some_message := _a_message_asking_for(_a_tool_call(), said=some_narration)
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _the_model_said(some_narration)
        )


@pytest.mark.unit
def test_the_models_thinking_is_not_what_it_said() -> None:
    # Every real answer from a thinking model opens with a thinking block, so
    # this is the shape the translation meets in production and the one it is
    # least likely to have been written against.
    #
    # Reasoning is not narration. It is the model working, often revising
    # itself; publishing it as Argus's account of the incident would put
    # discarded conclusions in front of a human as though they were held ones.
    dont_care_what_it_thought = "Could be the deploy. No - the timing is wrong."
    some_narration = "The error rate climbs at 22:15; checking what changed before it."

    Scenario() \
        .given(
            some_message := _a_message_that_thought_before_saying(
                dont_care_what_it_thought, some_narration
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _the_model_said(some_narration)
        )


@pytest.mark.unit
def test_the_models_thinking_is_kept_even_though_it_is_not_what_it_said() -> None:
    # Not narration, and not nothing either. For a system whose product is
    # judgement, why a wrong hypothesis looked right is the most useful thing
    # a later reader can have - and it exists only here: the reasoning is in
    # the response this translation reads, and whatever is not carried out of
    # it is gone the moment the response is discarded.
    #
    # Carried apart from what the model said rather than joined to it, which
    # is what lets both be true at once: the replay log stores a whole turn
    # and so keeps this for free, while nothing that narrates an incident
    # reaches for it.
    some_reasoning = "Could be the deploy. No - the timing is wrong."
    some_narration = "The error rate climbs at 22:15; checking what changed before it."

    Scenario() \
        .given(
            some_message := _a_message_that_thought_before_saying(
                some_reasoning, some_narration
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            all_of(
                _the_model_reasoned(some_reasoning),
                _the_model_said(some_narration)
            )
        )


def _the_model_reasoned(expected: str) -> Assertion[Turn]:
    """What the model was working through on its way to the turn.

    Asserted alongside what it said, never instead of it: the failure worth
    catching is not that the reasoning went missing but that it arrived in
    the wrong place, and a turn narrating its own discarded conclusions
    passes any assertion that only asks whether the words are present
    somewhere.
    """
    def assertion(turn: Turn) -> bool:
        if turn.reasoning != expected:
            raise AssertionError(
                f"Expected the turn to have reasoned [{expected}], got [{turn.reasoning}]."
            )

        return True

    return assertion


@pytest.mark.unit
def test_everything_the_model_said_reaches_the_turn() -> None:
    # One turn's words can arrive as several blocks - a thinking model splits
    # them routinely - and they are one account, not the first of several. A
    # translation that took the first block would truncate the reasoning at
    # whatever point the API happened to break it.
    some_first_words = "The error rate climbs at 22:15."
    some_later_words = "Checking what changed in the minutes before it."

    Scenario() \
        .given(
            some_message := _a_message_that_spoke_in_parts(
                some_first_words, some_later_words
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _the_model_said(f"{some_first_words}\n{some_later_words}")
        )


@pytest.mark.unit
def test_a_character_the_model_escaped_is_said_as_that_character() -> None:
    # The model occasionally escapes a character rather than writing it - an
    # arrow between two flag states, a dash between two times. Accepted as it
    # arrived, six characters of machinery land in the middle of a sentence,
    # and every reader of that sentence sees them: the page, the postmortem,
    # and whoever is paged about it.
    #
    # Resolved on the way in rather than on the way out, which is why the check
    # is here: a repair living in one of those three readers is missing from
    # the other two.
    the_character_it_names = "→"
    some_escape_the_model_wrote = "\\u2192"
    some_narration_before_the_arrow = "The flag moved off"
    some_narration_after_the_arrow = "on at 22:15."

    Scenario() \
        .given(
            some_message := _a_message_that_only_spoke(
                f"{some_narration_before_the_arrow}{some_escape_the_model_wrote}"
                f"{some_narration_after_the_arrow}"
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _the_model_said(
                f"{some_narration_before_the_arrow}{the_character_it_names}"
                f"{some_narration_after_the_arrow}"
            )
        )


@pytest.mark.unit
def test_a_character_escaped_inside_an_argument_is_asked_for_as_that_character() -> None:
    # Where it actually happens. The recorded case is a postmortem assumption -
    # one string inside a list inside the arguments - so an answer repaired
    # only at its text would leave the escape standing in the record itself.
    #
    # A number rides along because arguments are not all prose: a walk that
    # reached every value rather than every string would hand the tool a
    # confidence it could not compare.
    the_character_it_names = "–"
    some_escape_the_model_wrote = "\\u2013"
    some_span = "18:00"
    some_span_it_ran_to = "21:47"
    some_confidence = 0.68

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(
                    name="submit_postmortem",
                    arguments={
                        "assumptions": [
                            f"The change record for {some_span}"
                            f"{some_escape_the_model_wrote}{some_span_it_ran_to} "
                            f"is complete."
                        ],
                        "confidence": some_confidence
                    }
                )
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _the_calls_ask_for({
                "assumptions": [
                    f"The change record for {some_span}{the_character_it_names}"
                    f"{some_span_it_ran_to} is complete."
                ],
                "confidence": some_confidence
            })
        )


@pytest.mark.unit
def test_an_argument_written_as_a_parameter_tag_inside_another_is_given_back() -> None:
    # Measured on two paid runs, five submissions, every one the same. The model
    # closes the prose with `</explanation>`, opens `<parameter name="files">`,
    # and writes the whole patch as JSON inside the explanation string - while
    # the `files` argument that arrives properly holds a phrase pointing at it.
    # This model's own call syntax, in the middle of a JSON argument.
    #
    # Nothing was lost and nothing was wrong with the fix: what it cost was the
    # run, resubmitting an answer written correctly the first time. Repaired
    # rather than refused, here where every agent's answer passes: the syntax is
    # the model's, and any agent's argument can carry it.
    some_summary = "guard the monthly divisor"
    some_prose = "The month with no purchases raises from `max`."

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(
                    name=A_PATCH_TOOL.name,
                    arguments={
                        SUMMARY: some_summary,
                        EXPLANATION: (f"{some_prose}{_closing(EXPLANATION)}\n"
                                      f"{_opening(FILES)}{json.dumps(SOME_PATCH)}"),
                        FILES: A_POINTER_TO_THE_PATCH
                    }
                )
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            _the_calls_ask_for({SUMMARY: some_summary, EXPLANATION: some_prose,
                                FILES: SOME_PATCH})
        )


@pytest.mark.unit
def test_an_argument_named_in_a_tag_is_given_back_when_it_never_arrived_at_all() -> None:
    # The value in the tag is the one the model wrote, whether or not anything
    # arrived under that name beside it - a submission that dropped `files`
    # altogether had still written the patch.
    some_prose = "Guard the divisor."

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(
                    name=A_PATCH_TOOL.name,
                    arguments={EXPLANATION: (
                        f"{some_prose}{_closing(EXPLANATION)}"
                        f"{_opening(FILES)}{json.dumps(SOME_PATCH)}{_closing('parameter')}"
                    )}
                )
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            _the_calls_ask_for({EXPLANATION: some_prose, FILES: SOME_PATCH})
        )


@pytest.mark.unit
def test_an_earlier_tag_for_another_parameter_does_not_hide_the_one_carrying_the_value() -> None:
    # The model can slip into its call syntax for more than one parameter in a
    # row. A tag for a prose argument carries no value to give back - prose is
    # not JSON, so nothing says where it ends - and the patch in the tag after it
    # is still the patch.
    some_prose = "Why the month with no purchases raises."
    a_summary_written_as_a_tag = f"{_opening(SUMMARY)}Fix it{_closing('parameter')}"
    written = (f"{some_prose}{_closing(EXPLANATION)}\n{a_summary_written_as_a_tag}\n"
               f"{_opening(FILES)}{json.dumps(SOME_PATCH)}")

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(name=A_PATCH_TOOL.name,
                             arguments={EXPLANATION: written, FILES: A_POINTER_TO_THE_PATCH})
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            _the_calls_ask_for({
                EXPLANATION: (f"{some_prose}{_closing(EXPLANATION)}\n"
                              f"{a_summary_written_as_a_tag}"),
                FILES: SOME_PATCH
            })
        )


@pytest.mark.unit
def test_a_value_of_a_type_the_tool_does_not_take_leaves_a_readable_argument_alone() -> None:
    # The tool takes its files as a list. An object written after the tag is
    # not one, and given back it would replace a list the agent could have read
    # with one it reads as no patch at all.
    some_files = [{"path": "src/io_shop/spend_summary.py", "content": "return 0\n"}]
    written = (f"Guard it.{_closing(EXPLANATION)}"
               f"{_opening(FILES)}{json.dumps({'path': 'src/io_shop/other.py'})}")

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(name=A_PATCH_TOOL.name,
                             arguments={EXPLANATION: written, FILES: some_files})
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            _the_calls_ask_for({EXPLANATION: written, FILES: some_files})
        )


@pytest.mark.unit
@pytest.mark.parametrize("named", [FILES, "attachments"], ids=["declared", "undeclared"])
def test_a_tag_the_prose_mentions_is_not_a_call(named: str) -> None:
    # A root cause can quote the syntax - a write-up about this very slip would -
    # and a tag opened mid-sentence is something the prose says. Read as a call,
    # it would cut the prose short at the quote and empty an argument the model
    # wrote properly; one the tool does not declare would arrive as an argument
    # the dispatcher was never written for.
    some_files = [{"path": "src/io_shop/spend_summary.py", "content": "return 0\n"}]
    written = f"The model wrote {_opening(named)}[] where it meant the list itself."

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(name=A_PATCH_TOOL.name,
                             arguments={EXPLANATION: written, FILES: some_files})
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            _the_calls_ask_for({EXPLANATION: written, FILES: some_files})
        )


@pytest.mark.unit
def test_a_tag_naming_an_argument_the_tool_does_not_declare_is_left_as_written() -> None:
    # Even in the shape of a slip, a name the offer never declared is not an
    # argument: given back, it would reach the dispatcher - and be echoed to the
    # model - as one nothing was written to handle.
    written = (f"Guard it.{_closing(EXPLANATION)}"
               f"{_opening('attachments')}{json.dumps(SOME_PATCH)}")

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(name=A_PATCH_TOOL.name, arguments={EXPLANATION: written})
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            _the_calls_ask_for({EXPLANATION: written})
        )


@pytest.mark.unit
def test_with_no_tool_offered_nothing_is_given_back() -> None:
    # What an argument may be given back as is the offer's to say. A reading
    # with no offer to hand - a recording read on its own - has nothing to say
    # it with, and leaves the call as it arrived.
    written = (f"Guard it.{_closing(EXPLANATION)}"
               f"{_opening(FILES)}{json.dumps(SOME_PATCH)}")

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(name=A_PATCH_TOOL.name,
                             arguments={EXPLANATION: written, FILES: A_POINTER_TO_THE_PATCH})
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _the_calls_ask_for({EXPLANATION: written, FILES: A_POINTER_TO_THE_PATCH})
        )


@pytest.mark.unit
def test_an_argument_given_back_out_of_a_tag_is_said_naming_the_tool_and_both_arguments(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The repaired call is what the transcript echoes and the replay log keeps,
    # so after the repair nothing shows the model slipped. The line is the one
    # trace left, and a model that starts slipping more often is seen by it.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.WARNING)),
            some_message := _a_message_asking_for(
                _a_tool_call(
                    name=A_PATCH_TOOL.name,
                    arguments={EXPLANATION: (f"Guard the divisor.{_closing(EXPLANATION)}"
                                             f"{_opening(FILES)}{json.dumps(SOME_PATCH)}")}
                )
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            one_record_was_logged(caplog, THE_ADAPTER, logging.WARNING,
                                  "tool argument recovered from tag form",
                                  values={"tool": A_PATCH_TOOL.name, "argument": FILES,
                                          "written_inside": EXPLANATION})
        )


@pytest.mark.unit
def test_a_tag_with_nothing_recoverable_after_it_is_not_said_to_be_recovered(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Said only where a value was actually given back: a line for every tag the
    # model wrote would read as repairs that never happened.
    a_pointer_rather_than_a_patch = (
        f"Guard it.{_closing(EXPLANATION)}{_opening(FILES)}src/io_shop/spend_summary.py"
    )

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.WARNING)),
            some_message := _a_message_asking_for(
                _a_tool_call(name=A_PATCH_TOOL.name,
                             arguments={EXPLANATION: a_pointer_rather_than_a_patch})
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            _nothing_was_said_by_the_adapter(caplog)
        )


@pytest.mark.unit
@pytest.mark.parametrize("written", [
    f"Guard it.{_closing(EXPLANATION)}{_opening(FILES)}src/io_shop/spend_summary.py, rewritten",
    f'Guard it.{_closing(EXPLANATION)}{_opening(FILES)}"just a string"',
    f'Guard it.{_closing(EXPLANATION)}{_opening(EXPLANATION)}["a list"]',
    f'Guard it.{_closing(EXPLANATION)}<parameter name="{FILES}" with no end'
], ids=["not-json", "json-but-not-a-structure", "names-itself", "tag-never-closed"])
def test_a_tag_with_nothing_recoverable_after_it_is_left_as_written(written: str) -> None:
    # A patch written into prose carries the files' own newlines, so it is
    # often not JSON at all - and a guess at it would invent a value the model
    # did not send. What arrived is what the agent reads, and its own checks
    # are what catch it.
    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(name=A_PATCH_TOOL.name,
                             arguments={EXPLANATION: written, FILES: A_POINTER_TO_THE_PATCH})
            )
        ) \
        .when(
            lambda: to_turn(some_message, [A_PATCH_TOOL])
        ) \
        .then(
            _the_calls_ask_for({EXPLANATION: written, FILES: A_POINTER_TO_THE_PATCH})
        )


@pytest.mark.unit
def test_a_turn_that_only_asked_carries_no_words() -> None:
    # A model that has nothing to say and simply asks is answering normally,
    # not failing. The absence has to arrive as an empty account rather than
    # as nothing at all, because narration renders it either way.
    some_tool_name = "get_logs"

    Scenario() \
        .given(
            some_message := _a_message_asking_only_for(
                _a_tool_call(name=some_tool_name)
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            all_of(
                _the_model_said(""),
                _the_calls_name(some_tool_name)
            )
        )


@pytest.mark.unit
def test_a_turn_carries_what_it_cost() -> None:
    # The budget is enforced between turns, so it can only be enforced from
    # what a turn reports. Tokens are the bound that a wide window blows
    # through while the tool-call count still looks healthy.
    some_input_tokens = 1200
    some_output_tokens = 340

    Scenario() \
        .given(
            some_message := _a_message_asking_for(
                _a_tool_call(),
                input_tokens=some_input_tokens,
                output_tokens=some_output_tokens
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            _the_turn_cost(some_input_tokens, some_output_tokens)
        )


@pytest.mark.unit
def test_a_turn_carries_what_was_served_from_cache() -> None:
    # Four numbers, not two, because they are billed at three different rates:
    # a cache read is a tenth of an input token and a cache write is a quarter
    # more. A turn reporting only `input_tokens` says a cached turn was nearly
    # free when it was not, and says nothing at all about the turn that paid to
    # fill the cache.
    #
    # The uncached remainder is what `input_tokens` means once caching is on -
    # the total prompt is the three of them summed - so a reader adding the
    # cached counts to a total that already included them would double-count.
    some_input_tokens = 22
    some_output_tokens = 5551
    some_cache_read_tokens = 90514
    some_cache_write_tokens = 45214

    Scenario() \
        .given(
            some_message := _a_message_that_read_from_cache(
                input_tokens=some_input_tokens,
                output_tokens=some_output_tokens,
                cache_read_tokens=some_cache_read_tokens,
                cache_write_tokens=some_cache_write_tokens
            )
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            all_of(
                _the_turn_cost(some_input_tokens, some_output_tokens),
                _the_turn_read_from_cache(some_cache_read_tokens),
                _the_turn_wrote_to_cache(some_cache_write_tokens)
            )
        )


@pytest.mark.unit
def test_a_turn_that_used_no_cache_reports_none_used() -> None:
    # The first turn of every investigation, and every turn of a run against a
    # model or a double that does not cache. Zero rather than null: nothing was
    # served from cache is a measured quantity, and a reader summing a column
    # of costs should not have to decide what a missing one meant.
    Scenario() \
        .given(
            some_message := _a_message_asking_for(_a_tool_call())
        ) \
        .when(
            lambda: to_turn(some_message)
        ) \
        .then(
            all_of(
                _the_turn_read_from_cache(0),
                _the_turn_wrote_to_cache(0)
            )
        )


def _the_calls_are_identified_by(*call_ids: str) -> Assertion[Turn]:
    """The ids a tool result must be labelled with to answer this turn."""
    def assertion(turn: Turn) -> bool:
        identified_by = [call.id for call in turn.tool_calls]

        if identified_by != list(call_ids):
            raise AssertionError(
                f"Expected tool calls identified by {list(call_ids)}, got {identified_by}."
            )

        return True

    return assertion


def _the_calls_name(*names: str) -> Assertion[Turn]:
    """The functions this turn asks to have run, in the order it asked."""
    def assertion(turn: Turn) -> bool:
        named = [call.name for call in turn.tool_calls]

        if named != list(names):
            raise AssertionError(f"Expected tool calls naming {list(names)}, got {named}.")

        return True

    return assertion


def _the_calls_ask_for(*arguments: dict[str, Any]) -> Assertion[Turn]:
    """The arguments each call carries - for a retrieval tool, its window."""
    def assertion(turn: Turn) -> bool:
        asked_for = [call.arguments for call in turn.tool_calls]

        if asked_for != list(arguments):
            raise AssertionError(
                f"Expected tool calls asking for {list(arguments)}, got {asked_for}."
            )

        return True

    return assertion


def _nothing_was_said_by_the_adapter(caplog: pytest.LogCaptureFixture) -> Assertion[Turn]:
    def assertion(_: Turn) -> bool:
        said = [record.getMessage() for record in caplog.records if record.name == THE_ADAPTER]

        if said:
            raise AssertionError(f"Expected the adapter to say nothing, and it said {said}.")

        return True

    return assertion


def _nothing_was_asked_for() -> Assertion[Turn]:
    """A turn the loop has nothing to dispatch for.

    Its own assertion rather than `_the_calls_name()` with no arguments: the
    absence of a request is the thing being checked, and a reader should not
    have to notice an empty argument list to see that.
    """
    def assertion(turn: Turn) -> bool:
        if turn.tool_calls:
            raise AssertionError(
                f"Expected no tool call, got {[call.name for call in turn.tool_calls]}."
            )

        return True

    return assertion


def _the_model_said(said: str) -> Assertion[Turn]:
    """What the model wrote alongside its request, as narration carries it."""
    def assertion(turn: Turn) -> bool:
        if turn.text != said:
            raise AssertionError(f"Expected the model to say [{said}], got [{turn.text}].")

        return True

    return assertion


def _the_turn_cost(input_tokens: int, output_tokens: int) -> Assertion[Turn]:
    """What the budget reads between turns."""
    def assertion(turn: Turn) -> bool:
        if input_tokens != turn.input_tokens:
            raise AssertionError(
                f"Expected the turn to cost [{input_tokens}] input tokens, "
                f"got [{turn.input_tokens}]."
            )

        if output_tokens != turn.output_tokens:
            raise AssertionError(
                f"Expected the turn to cost [{output_tokens}] output tokens, "
                f"got [{turn.output_tokens}]."
            )

        return True

    return assertion


def _a_tool_call(call_id: str = "toolu_dont_care",
                 name: str = "get_logs",
                 arguments: dict[str, Any] | None = None) -> ToolUseBlock:
    return ToolUseBlock(
        type=TOOL_USE_TYPE,
        id=call_id,
        name=name,
        input=arguments if arguments is not None else {}
    )


def _a_message_asking_for(*calls: ToolUseBlock,
                          said: str = "dont care what it said",
                          input_tokens: int = 1,
                          output_tokens: int = 1) -> Message:
    return _a_message(
        content=[TextBlock(type=TEXT_TYPE, text=said), *calls],
        stop_reason=TOOL_USE_STOP_REASON,
        input_tokens=input_tokens,
        output_tokens=output_tokens
    )


def _a_message_asking_only_for(*calls: ToolUseBlock) -> Message:
    """A request with no words around it - no text block at all, not an empty one.

    The distinction is the point: a model with nothing to say omits the block
    rather than sending a blank one, so a translation reaching for `content[0]`
    would find a tool call where it expected prose.
    """
    dont_care_input_tokens = 1
    dont_care_output_tokens = 1

    return _a_message(
        content=list(calls),
        stop_reason=TOOL_USE_STOP_REASON,
        input_tokens=dont_care_input_tokens,
        output_tokens=dont_care_output_tokens
    )


def _a_message_that_only_spoke(said: str) -> Message:
    dont_care_input_tokens = 1
    dont_care_output_tokens = 1

    return _a_message(
        content=[TextBlock(type=TEXT_TYPE, text=said)],
        stop_reason=END_TURN_STOP_REASON,
        input_tokens=dont_care_input_tokens,
        output_tokens=dont_care_output_tokens
    )


def _a_message_that_spoke_in_parts(*parts: str) -> Message:
    """One account of the turn, arriving as several text blocks."""
    dont_care_input_tokens = 1
    dont_care_output_tokens = 1

    return _a_message(
        content=[TextBlock(type=TEXT_TYPE, text=part) for part in parts],
        stop_reason=END_TURN_STOP_REASON,
        input_tokens=dont_care_input_tokens,
        output_tokens=dont_care_output_tokens
    )


def _a_message_that_thought_before_saying(thought: str, said: str) -> Message:
    """The shape every real answer from a thinking model arrives in.

    The thinking block comes first, as the API orders it - which is exactly
    why a translation that reads the first block of the content gets the
    reasoning and calls it the answer.
    """
    dont_care_signature = "dont-care-signature"
    dont_care_input_tokens = 1
    dont_care_output_tokens = 1

    return _a_message(
        content=[
            ThinkingBlock(
                type=THINKING_TYPE, thinking=thought, signature=dont_care_signature
            ),
            TextBlock(type=TEXT_TYPE, text=said)
        ],
        stop_reason=END_TURN_STOP_REASON,
        input_tokens=dont_care_input_tokens,
        output_tokens=dont_care_output_tokens
    )


def _a_message(content: list[ContentBlock],
               stop_reason: StopReason,
               input_tokens: int,
               output_tokens: int) -> Message:
    """One API response, with the fields this file does not care about filled in.

    A real `Message` rather than a stand-in: the translation under test reads
    the SDK's own types, and a hand-rolled shape would let it pass against
    something the API never sends.
    """
    return Message(
        id="dont_care_id",
        model="dont_care_model",
        role=ASSISTANT_ROLE,
        type=MESSAGE_TYPE,
        stop_reason=stop_reason,
        stop_sequence=None,
        content=content,
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens)
    )


def _the_turn_read_from_cache(cache_read_tokens: int) -> Assertion[Turn]:
    """What this turn was served from cache, billed at a tenth of an input token."""
    def assertion(turn: Turn) -> bool:
        if turn.cache_read_tokens != cache_read_tokens:
            raise AssertionError(
                f"Expected the turn to have read [{cache_read_tokens}] tokens from "
                f"cache, got [{turn.cache_read_tokens}]."
            )

        return True

    return assertion


def _the_turn_wrote_to_cache(cache_write_tokens: int) -> Assertion[Turn]:
    """What this turn put into the cache, billed at a quarter more than input."""
    def assertion(turn: Turn) -> bool:
        if turn.cache_write_tokens != cache_write_tokens:
            raise AssertionError(
                f"Expected the turn to have written [{cache_write_tokens}] tokens to "
                f"cache, got [{turn.cache_write_tokens}]."
            )

        return True

    return assertion


def _a_message_that_read_from_cache(input_tokens: int,
                                    output_tokens: int,
                                    cache_read_tokens: int,
                                    cache_write_tokens: int) -> Message:
    """A response from a conversation already under way.

    Its own builder rather than more parameters on `_a_message`: every other
    case in this file predates caching and reports neither count, and adding
    two arguments to all of them would make the ordinary shape read like the
    exceptional one.
    """
    return Message(
        id="dont_care_id",
        model="dont_care_model",
        role=ASSISTANT_ROLE,
        type=MESSAGE_TYPE,
        stop_reason=TOOL_USE_STOP_REASON,
        stop_sequence=None,
        content=[_a_tool_call()],
        usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_tokens,
            cache_creation_input_tokens=cache_write_tokens
        )
    )
