"""A model that says exactly what a test told it to say.

The loop's control flow is now the model's to decide, so a test of the loop is
a test of what it does with a given sequence of turns. Scripted rather than
recorded: every branch here - a bound binding, a turn that only talks, a model
that never answers - is one a real model reaches rarely and a recording cannot
be relied on to contain.

The tool names and argument keys are restated here rather than imported from
the code under test. They are the vocabulary the model and the loop have to
agree on, and a test that imports the code's own spelling agrees with it even
when both are wrong.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import Mock, create_autospec

from agent_investigator.reasoning import converse
from argus_core.llm.client import AnswerTruncated, ModelDidNotAnswer, ModelRefused
from argus_core.models.turn import ToolCall, Turn

METRICS_TOOL = "get_metrics"
LOGS_TOOL = "get_logs"
CHANGES_TOOL = "get_changes"
ANSWER_TOOL = "final_answer"

WINDOW_START_ARG = "window_start"
WINDOW_END_ARG = "window_end"
HYPOTHESES_ARG = "hypotheses"

# What a turn cost, where the test is not about cost. Zero rather than a
# plausible number, so that a budget bound is only ever reached by a test that
# asked for it.
NO_TOKENS = 0


def a_model_that_says(*turns: Turn | ModelDidNotAnswer) -> Mock:
    """A model that answers with these turns, in order.

    A turn that is an exception is raised rather than returned, because that is
    what the seam does with it: a turn the model did not finish carries nothing
    to hand back, and the loop's handling of it is the point of the tests that
    script one.

    Running out is deliberately an error rather than a repeat: a loop that
    asked for more turns than the test wrote is doing something the test did
    not describe, and repeating the last turn would hide that behind whatever
    the budget does next.
    """
    return cast(Mock, create_autospec(converse, side_effect=list(turns)))


def a_model_that_never_stops_reading() -> Mock:
    """A model that keeps asking for one more window and never answers.

    The case every bound exists for. It answers nothing, so what ends the
    investigation is only ever the budget - which is the thing under test.

    Each turn names a *different* window, one minute earlier than the last.
    A model repeating one window is refused by the dispatcher, which would end
    this loop for a reason that has nothing to do with the budget.
    """
    windows = iter(_a_window_starting_earlier_each_time())

    return cast(Mock, create_autospec(
        converse,
        side_effect=lambda *args, **kwargs: a_turn_calling(
            LOGS_TOOL, {WINDOW_START_ARG: next(windows)}
        )
    ))


def a_model_that_is_always_cut_short() -> Mock:
    """A model whose every turn runs out of room before it finishes.

    The same failure each time, which is the point: a retry is worth buying
    once, and a loop that keeps buying one has no answer coming and nothing
    charging it for the attempts - only the clock can end it.
    """
    return cast(Mock, create_autospec(converse, side_effect=a_turn_that_was_cut_short()))


def some_windows(how_many: int) -> list[str]:
    """As many distinct window starts as a test needs, each earlier than the
    last.

    Distinct because the dispatcher refuses a window it has already read, so a
    test wanting several reads has to ask for several windows - and which
    minutes they are is not what any of those tests is about.
    """
    windows = _a_window_starting_earlier_each_time()

    return [next(windows) for _ in range(how_many)]


def _a_window_starting_earlier_each_time() -> Iterator[str]:
    minute = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
    while True:
        minute -= timedelta(minutes=1)
        yield minute.strftime("%Y-%m-%dT%H:%M:%SZ")


def a_turn_calling(name: str,
                   arguments: dict[str, str] | None = None,
                   *,
                   call_id: str = "toolu_dont_care",
                   input_tokens: int = NO_TOKENS,
                   output_tokens: int = NO_TOKENS) -> Turn:
    """One turn in which the model asked for something and said nothing.

    The arguments are one mapping rather than keywords, so that a caller can
    pass the argument names the tools actually use without them colliding with
    this builder's own parameters.
    """
    return Turn(
        text="",
        tool_calls=[ToolCall(id=call_id, name=name, arguments=dict(arguments or {}))],
        input_tokens=input_tokens,
        output_tokens=output_tokens
    )


def a_turn_saying(text: str,
                  input_tokens: int = NO_TOKENS,
                  output_tokens: int = NO_TOKENS) -> Turn:
    """One turn that is only words - no answer, and nothing asked for."""
    return Turn(
        text=text, tool_calls=[], input_tokens=input_tokens, output_tokens=output_tokens
    )


def a_turn_answering(*explanations: dict[str, Any],
                     call_id: str = "toolu_dont_care",
                     input_tokens: int = NO_TOKENS,
                     output_tokens: int = NO_TOKENS) -> Turn:
    """The turn that ends an investigation: the answer tool, called."""
    return Turn(
        text="",
        tool_calls=[
            ToolCall(
                id=call_id,
                name=ANSWER_TOOL,
                arguments={HYPOTHESES_ARG: list(explanations)}
            )
        ],
        input_tokens=input_tokens,
        output_tokens=output_tokens
    )


def a_turn_that_was_cut_short() -> AnswerTruncated:
    """A turn that ran out of room before the model finished it.

    The one failure a retry can actually fix - nothing is wrong with the model
    or the request, there was simply not enough space - which is why the loop
    is allowed to buy another turn with budget it has left.
    """
    return AnswerTruncated("the model ran out of room before finishing its turn")


def a_turn_the_model_declined() -> ModelRefused:
    """A complete, well-formed turn that says no.

    Asking again is asking the same question of the same evidence, so this one
    is final however much budget is left.
    """
    return ModelRefused("the model declined to answer")


def an_explanation(summary: str = "a feature flag was toggled on just before the errors began",
                   cause_type: str | None = "feature-flag-toggle",
                   confidence: float | None = 0.8,
                   supporting_evidence: list[str] | None = None,
                   subject: str | None = None) -> dict[str, Any]:
    """One account of the incident, as the model fills the answer schema in."""
    return {
        "summary": summary,
        "cause_type": cause_type,
        "confidence": confidence,
        "supporting_evidence": supporting_evidence or [],
        "subject": subject
    }


def an_explanation_naming_no_cause(
    summary: str = "nothing in the evidence identifies a cause"
) -> dict[str, Any]:
    """The honest answer, which carries no cause and no confidence."""
    return an_explanation(summary=summary, cause_type=None, confidence=None)
