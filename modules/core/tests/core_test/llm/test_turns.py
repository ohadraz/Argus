"""The loop an agent drives a model in, until its policy says it has ended.

What is the loop's: whether to go on, whether the incident is still wanted,
asking the model, the two ways a turn can fail to arrive, charging the turn and
keeping it, and putting what the model is told next after it. Everything else
- what a turn means, what it is told, and every ending - is the agent's policy,
handed in. Both agents ran their own copy of this loop.

Whether to go on is asked before whether the incident is still wanted, and both
before every turn: an agent out of room and no longer wanted at once ends as out
of room, which is the order Code-Fix has always asked them in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    attempting,
    the_answer_was,
    the_same_error_reached_the_caller,
)
from core.llm import AnswerTruncated, Ended, ModelRefused, ModelUnavailable, converse_until
from core.models import Ask, Exchange, ToolDefinition, Transcript, Turn

SOME_OPENING = Ask(text="Investigate the alert.")
SOME_TOOLS = [ToolDefinition(name="read_logs", description="Read the logs.",
                             properties={}, required=[])]
# What the policy offers after its first turn: an agent's tools change as it
# goes, as the Investigator's do once a lead has been written.
SOME_LATER_TOOLS = [*SOME_TOOLS, ToolDefinition(name="weigh_lead", description="Weigh a lead.",
                                                properties={}, required=[])]
SOME_REPLY = Ask(text="Here is what you asked for.")
DONT_CARE_REASON = "dont care"
# What each of the policy's endings ends with, so a test can tell which one did.
RAN_OUT = "ran out"
STOPPED = "stopped"
CUT_SHORT = "cut short"
DECLINED = "declined"
ANSWERED = "answered"
# Turns enough that a policy given them never runs out within a test.
TURNS_ENOUGH = 10
NEVER = 0


@pytest.mark.unit
def test_a_policy_that_does_not_go_on_has_run_out_and_the_model_is_never_asked() -> None:
    Scenario() \
        .given(a_policy := _a_policy(going_on_for=0)) \
        .when(lambda: _run(a_policy, _a_model_that_must_not_be_asked())) \
        .then(the_answer_was(RAN_OUT))


@pytest.mark.unit
def test_going_on_is_asked_before_whether_the_incident_is_still_wanted() -> None:
    # Out of room and no longer wanted at once ends as out of room.
    Scenario() \
        .given(a_policy := _a_policy(going_on_for=0)) \
        .when(lambda: _run(a_policy, _a_model_that_must_not_be_asked(), wanted=[False])) \
        .then(the_answer_was(RAN_OUT))


@pytest.mark.unit
def test_going_on_is_asked_again_before_every_turn() -> None:
    # One turn, and then no more: the model has one answer, and says so if
    # asked for a second.
    Scenario() \
        .given(a_policy := _a_policy(going_on_for=1)) \
        .when(lambda: _run(a_policy, _a_model_answering(_a_turn()))) \
        .then(the_answer_was(RAN_OUT))


@pytest.mark.unit
def test_an_incident_no_longer_wanted_is_stopped_and_the_model_is_never_asked() -> None:
    Scenario() \
        .given(a_policy := _a_policy()) \
        .when(lambda: _run(a_policy, _a_model_that_must_not_be_asked(), wanted=[False])) \
        .then(the_answer_was(STOPPED))


@pytest.mark.unit
def test_whether_the_incident_is_still_wanted_is_asked_again_before_every_turn() -> None:
    Scenario() \
        .given(a_policy := _a_policy()) \
        .when(lambda: _run(a_policy, _a_model_answering(_a_turn()), wanted=[True, False])) \
        .then(the_answer_was(STOPPED))


@pytest.mark.unit
def test_the_model_is_asked_with_the_conversation_so_far_and_the_policy_s_tools() -> None:
    asked: Kept[tuple[Transcript, list[ToolDefinition]]] = Kept()

    Scenario() \
        .given(a_policy := _a_policy(ending_on_turn=1)) \
        .when(lambda: _run(a_policy, _a_model_answering(_a_turn(), asked=asked))) \
        .then(_asked_once_with(asked, [SOME_OPENING], SOME_TOOLS))


@pytest.mark.unit
@pytest.mark.parametrize("failure, ending", [
    (AnswerTruncated(DONT_CARE_REASON), CUT_SHORT),
    (ModelRefused(DONT_CARE_REASON), DECLINED)
], ids=["truncated", "refused"])
def test_a_turn_that_never_arrived_ends_as_the_policy_says_and_is_charged_nothing(
        failure: Exception, ending: str) -> None:
    # The failure itself is handed on: the Investigator charges what a
    # truncation was billed, and Code-Fix raises from it. Charging it is the
    # policy's, so the loop charges nothing.
    handed: Kept[object] = Kept()
    charged: Kept[Turn] = Kept()

    Scenario() \
        .given(a_policy := _a_policy(keeping=handed)) \
        .when(lambda: _run(a_policy, _a_model_answering(failure), charged=charged)) \
        .then(all_of(the_answer_was(ending),
                     _handed_exactly(handed, [failure]),
                     _kept(charged, [])))


@pytest.mark.unit
def test_any_other_failure_to_reach_the_model_reaches_the_caller() -> None:
    some_outage = ModelUnavailable(DONT_CARE_REASON)

    Scenario() \
        .given(a_policy := _a_policy()) \
        .when(attempting(lambda: _run(a_policy, _a_model_answering(some_outage)))) \
        .then(the_same_error_reached_the_caller(some_outage))


@pytest.mark.unit
def test_each_turn_is_charged_and_kept_before_the_policy_reads_it() -> None:
    # Before: a policy deciding what a turn means asks what is left to spend,
    # and the turn in front of it is part of what has been spent.
    charged: Kept[Turn] = Kept()
    transcript: list[Exchange] = [SOME_OPENING]
    saw_charged: Kept[list[Turn]] = Kept()
    saw_kept: Kept[list[Exchange]] = Kept()
    handed: Kept[object] = Kept()

    Scenario() \
        .given(some_turn := _a_turn(),
               a_policy := _a_policy(ending_on_turn=1,
                                     looking_at=(charged, transcript),
                                     seeing_into=(saw_charged, saw_kept),
                                     keeping=handed)) \
        .when(lambda: _run(a_policy, _a_model_answering(some_turn),
                           transcript=transcript, charged=charged)) \
        .then(all_of(_handed_exactly(handed, [some_turn]),
                     _kept(saw_charged, [[some_turn]]),
                     _kept(saw_kept, [list[Exchange]([SOME_OPENING, some_turn])])))


@pytest.mark.unit
def test_what_the_policy_says_next_is_put_after_the_turn_and_the_loop_goes_on() -> None:
    # Asked again with the tools the policy offers then, not those it offered
    # first.
    asked: Kept[tuple[Transcript, list[ToolDefinition]]] = Kept()

    Scenario() \
        .given(first := _a_turn(),
               a_policy := _a_policy(ending_on_turn=2)) \
        .when(lambda: _run(a_policy, _a_model_answering(first, _a_turn(), asked=asked))) \
        .then(all_of(the_answer_was(ANSWERED),
                     _second_asked_with(asked, [SOME_OPENING, first, SOME_REPLY],
                                        SOME_LATER_TOOLS)))


@pytest.mark.unit
def test_an_ending_a_policy_raises_reaches_the_caller() -> None:
    # Code-Fix ends by raising: what stopped it is the whole of what a reader
    # can act on.
    some_ending = RuntimeError(DONT_CARE_REASON)

    Scenario() \
        .given(a_policy := _a_policy(raising_when_stopped=some_ending)) \
        .when(attempting(lambda: _run(a_policy, _a_model_that_must_not_be_asked(),
                                      wanted=[False]))) \
        .then(the_same_error_reached_the_caller(some_ending))


class _ScriptedPolicy:
    """Goes on for as many turns as it is told, offers SOME_TOOLS on its first
    turn and SOME_LATER_TOOLS after, answers every turn with SOME_REPLY until
    the one it ends on, and ends each other way with a value naming the way.
    It keeps every turn and failure it is handed, and where it is given what
    was charged and what was kept, notes what each held when it read a turn."""

    def __init__(self, *, going_on_for: int, ending_on_turn: int,
                 looking_at: tuple[Kept[Turn], list[Exchange]] | None,
                 seeing_into: tuple[Kept[list[Turn]], Kept[list[Exchange]]] | None,
                 keeping: Kept[object],
                 raising_when_stopped: Exception | None) -> None:
        self._going_on_for = going_on_for
        self._ending_on_turn = ending_on_turn
        self._looking_at = looking_at
        self._seeing_into = seeing_into
        self._keeping = keeping
        self._raising_when_stopped = raising_when_stopped
        self._turns = 0

    def goes_on(self) -> bool:
        return self._turns < self._going_on_for

    def stopped(self) -> str:
        if self._raising_when_stopped is not None:
            raise self._raising_when_stopped
        return STOPPED

    def tools(self) -> list[ToolDefinition]:
        return SOME_TOOLS if self._turns == 0 else SOME_LATER_TOOLS

    def cut_short(self, cut_short: AnswerTruncated, /) -> str:
        self._keeping.take(cut_short)
        return CUT_SHORT

    def declined(self, declined: ModelRefused, /) -> str:
        self._keeping.take(declined)
        return DECLINED

    def on_turn(self, turn: Turn, /) -> Ended[str] | Exchange:
        self._keeping.take(turn)
        self._turns += 1
        if self._looking_at is not None and self._seeing_into is not None:
            charged, transcript = self._looking_at
            saw_charged, saw_kept = self._seeing_into
            saw_charged.take(list(charged.taken))
            saw_kept.take(list(transcript))

        return Ended(ANSWERED) if self._turns == self._ending_on_turn else SOME_REPLY

    def ran_out(self) -> str:
        return RAN_OUT


def _a_policy(*, going_on_for: int = TURNS_ENOUGH, ending_on_turn: int = NEVER,
              looking_at: tuple[Kept[Turn], list[Exchange]] | None = None,
              seeing_into: tuple[Kept[list[Turn]], Kept[list[Exchange]]] | None = None,
              keeping: Kept[object] | None = None,
              raising_when_stopped: Exception | None = None) -> _ScriptedPolicy:
    dont_care_keeping: Kept[object] = Kept()

    return _ScriptedPolicy(going_on_for=going_on_for, ending_on_turn=ending_on_turn,
                           looking_at=looking_at, seeing_into=seeing_into,
                           keeping=keeping if keeping is not None else dont_care_keeping,
                           raising_when_stopped=raising_when_stopped)


def _run(policy: _ScriptedPolicy,
         converse: Callable[[Transcript, list[ToolDefinition]], Turn],
         *,
         wanted: Sequence[bool] = (True,) * TURNS_ENOUGH,
         transcript: list[Exchange] | None = None,
         charged: Kept[Turn] | None = None) -> str:
    """Runs the loop, wanted turn by turn as `wanted` says."""
    answers = iter(wanted)
    dont_care_charge: Kept[Turn] = Kept()

    return converse_until(policy, converse=converse,
                          transcript=transcript if transcript is not None else [SOME_OPENING],
                          record=(charged if charged is not None else dont_care_charge).take,
                          still_wanted=lambda: next(answers))


def _a_model_answering(*answers: Turn | Exception,
                       asked: Kept[tuple[Transcript, list[ToolDefinition]]] | None = None
                       ) -> Callable[[Transcript, list[ToolDefinition]], Turn]:
    """Answers each call from the list in turn - raising where the answer is an
    error - and keeps a copy of what it was asked, as it stood then. Asked more
    times than it has answers, it fails the test."""
    remaining = list(answers)

    def converse(transcript: Transcript, tools: list[ToolDefinition], /) -> Turn:
        if asked is not None:
            asked.take((list(transcript), tools))
        if not remaining:
            raise AssertionError("The model was called more times than the test expected.")

        answer = remaining.pop(0)
        if isinstance(answer, Exception):
            raise answer

        return answer

    return converse


def _a_model_that_must_not_be_asked() -> Callable[[Transcript, list[ToolDefinition]], Turn]:
    return _a_model_answering()


def _a_turn() -> Turn:
    dont_care_text = ""
    dont_care_tokens = 1

    return Turn(text=dont_care_text, tool_calls=[], input_tokens=dont_care_tokens,
                output_tokens=dont_care_tokens)


def _asked_once_with(asked: Kept[tuple[Transcript, list[ToolDefinition]]],
                     transcript: Transcript,
                     tools: list[ToolDefinition]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if asked.taken != [(transcript, tools)]:
            raise AssertionError(
                f"Expected the model asked once, with {transcript} and {tools}; it was asked "
                f"{asked.taken}.")

        return True

    return assertion


def _second_asked_with(asked: Kept[tuple[Transcript, list[ToolDefinition]]],
                       transcript: Transcript,
                       tools: list[ToolDefinition]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if len(asked.taken) < 2 or asked.taken[1] != (transcript, tools):
            raise AssertionError(
                f"Expected the second ask to be with {transcript} and {tools}; the asks "
                f"were {asked.taken}.")

        return True

    return assertion


def _handed_exactly(handed: Kept[object], expected: list[object]) -> Assertion[object]:
    """That the policy was handed these very objects, in this order - not equal
    ones the loop made."""
    def assertion(_: object) -> bool:
        if len(handed.taken) != len(expected) or any(
                got is not wanted for got, wanted in zip(handed.taken, expected, strict=True)):
            raise AssertionError(f"Expected the policy handed {expected} itself, got "
                                 f"{handed.taken}.")

        return True

    return assertion


def _kept[T](kept: Kept[T], expected: list[T]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if kept.taken != expected:
            raise AssertionError(f"Expected {expected} kept, got {kept.taken}.")

        return True

    return assertion
