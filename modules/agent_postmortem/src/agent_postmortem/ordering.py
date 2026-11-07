"""The causal chain put in the order its whys answer each other.

The write-up is asked for the cause as the five whys, each step answering why
the one before it happened, and a write-up gave its steps in the wrong order
anyway: the step saying why the symptom happened came after the one it
explains. Nothing in code can tell which step answers which, so the model is
asked once more, about the answer the document will carry - accepted, or the
second attempt whatever faults it still has - for an order and nothing else.

By the steps' numbers, not their words: a step said again is a step that can
come back changed, and one a character off is no longer the step it was. And
with the first and the last held where they are - the first agrees with the
symptom and the last with the root cause, both said elsewhere in the document,
and moved they would disagree. Anything but those steps rearranged leaves the
chain as written: an order is a suggestion the model makes about its own
answer, and one that drops or repeats a step is not taken.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from argus_core.llm import LLMClient, ModelDidNotAnswer, ModelUnavailable
from argus_core.models import Ask, ToolDefinition, Transcript, Turn

from agent_postmortem.prompting import SubmittedStep

ORDER_TOOL_NAME: Final = "order_chain"
ORDER_FIELD: Final = "order"

# The shortest chain with a step that can move: with both ends held, a chain of
# three has one step in the middle and nowhere for it to go.
_SHORTEST_TO_ORDER: Final = 4

ORDER_CHAIN = ToolDefinition(
    name=ORDER_TOOL_NAME,
    description=(
        "Give the order the causal chain's steps should be read in, as their "
        "numbers. Change nothing else."
    ),
    properties={
        ORDER_FIELD: {
            "type": "array",
            "items": {"type": "integer"},
            "description": (
                "Every step's number, each once, in the order that makes each step "
                "answer why the step directly before it happened. The first and the "
                "last stay where they are."
            )
        }
    },
    required=[ORDER_FIELD]
)


def put_in_order(llm: LLMClient, chain: Sequence[SubmittedStep]) -> list[SubmittedStep]:
    """The chain in the order the model gives - or as written, where it is too
    short to have a step that could move, the order given is not the same
    steps rearranged with both ends in place, or the model gave no answer or
    could not be reached for now.

    Those two are caught and nothing else is: the write-up is kept by then,
    and an order not suggested is no reason to lose it. A request refused as
    asked is neither - in a replay it is a recording that no longer matches,
    which has to be loud rather than a chain quietly left unordered.
    """
    if len(chain) < _SHORTEST_TO_ORDER:
        return list(chain)

    try:
        answered = llm.converse(ordering_asked(chain), [ORDER_CHAIN])
    except (ModelDidNotAnswer, ModelUnavailable):
        return list(chain)

    return in_its_order(chain, answered)


def ordering_asked(chain: Sequence[SubmittedStep]) -> Transcript:
    """The chain as written, its steps numbered, and the rule an order follows."""
    return [Ask(text="\n".join([
        "The causal chain of a postmortem, its steps numbered as written:",
        *(f"{number}. {step.step}" for number, step in enumerate(chain, start=1)),
        "",
        "Put the steps in the order in which each step answers why the step directly "
        "before it happened - the first and the last stay where they are. Call "
        f"{ORDER_TOOL_NAME} with the steps' numbers in that order."
    ]))]


def in_its_order(chain: Sequence[SubmittedStep], answered: Turn) -> list[SubmittedStep]:
    """The chain in the order `answered` gives, where that is every step once
    by its whole number, the first first and the last last - and as written
    otherwise.

    A whole number and nothing that compares equal to one: a string among them
    cannot be sorted, a float equal to its step's number fails as an index, and
    `True` is the first step only to Python.
    """
    order = next((call.arguments.get(ORDER_FIELD) for call in answered.tool_calls
                  if call.name == ORDER_TOOL_NAME), None)
    numbers = list(range(1, len(chain) + 1))

    if (not isinstance(order, list)
            or not all(type(number) is int for number in order)
            or sorted(order) != numbers
            or order[0] != numbers[0]
            or order[-1] != numbers[-1]):
        return list(chain)

    return [chain[number - 1] for number in order]
