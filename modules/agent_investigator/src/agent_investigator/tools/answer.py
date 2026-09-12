"""The only exit that produces anything: the model's ranked answer.

Not a retrieval, and never dispatched - the loop ends when this is called and
builds its `Findings` from the call's own arguments. Its schema is what keeps
the seam impossible to satisfy without producing a verdict: a model that stops
calling tools and writes prose instead has not answered, and nothing here
invites it to think it has.

The shape is flat and ranked, and deliberately not a `Hypothesis`: an id, an
incident, a rank among siblings
and a life after the Investigator are none of the model's to invent, and a
schema offering those fields would be inviting it to.
"""

from __future__ import annotations

from typing import Any, Final

from argus_core.models.cause import CauseType
from argus_core.models.tool_definition import ToolDefinition

ANSWER_TOOL: Final = "final_answer"

HYPOTHESES_ARG: Final = "hypotheses"

# JSON Schema's own vocabulary, named here because this is the module that
# writes the one schema Argus does not derive from a model.
_STRING_TYPE: Final = "string"
_NUMBER_TYPE: Final = "number"
_ARRAY_TYPE: Final = "array"
_OBJECT_TYPE: Final = "object"
_NULL_TYPE: Final = "null"


def answer_tool() -> ToolDefinition:
    """The offer: say what caused it, best explanation first, and stop."""
    return ToolDefinition(
        name=ANSWER_TOOL,
        description=(
            "Give your answer and end the investigation. Every explanation the "
            "evidence supports, best first - something will try the first and fall "
            "through to the rest when it does not help. Naming no cause is a real "
            "answer: say so in one explanation carrying no cause and no confidence, "
            "and say what you would have needed to see."
        ),
        properties={
            HYPOTHESES_ARG: {
                "type": _ARRAY_TYPE,
                "description": (
                    "The competing accounts of this same evidence, most likely "
                    "first. Never empty."
                ),
                "items": _one_explanation()
            }
        },
        required=[HYPOTHESES_ARG]
    )


def _one_thing_it_rests_on() -> dict[str, Any]:
    """One cited fact, and the moment it happened at.

    The instant is asked for rather than read back out of the claim. The model
    is quoting a line it retrieved, so it has the timestamp in front of it;
    anything downstream that wanted the minute would otherwise have to
    pattern-match the sentence, and a match landing on the wrong minute points
    a reader confidently at evidence nobody cited.

    Null is a real answer: an absence of changes across a window happened at no
    instant, and a plausible time invented for it would be worse than none.
    """
    return {
        "type": _OBJECT_TYPE,
        "properties": {
            "claim": {
                "type": _STRING_TYPE,
                "description": (
                    "The line, bucket or absence this rests on, quoted rather "
                    "than paraphrased."
                )
            },
            "at": {
                "anyOf": [
                    {"type": _STRING_TYPE},
                    {"type": _NULL_TYPE}
                ],
                "description": (
                    "When it happened, copied from the evidence in the wire "
                    "format the tools speak - 2026-08-30T12:30:00Z. Null when "
                    "the claim names no moment, such as nothing having changed "
                    "in a window."
                )
            }
        },
        "required": ["claim", "at"],
        "additionalProperties": False
    }


def _a_state(description: str) -> dict[str, Any]:
    """One end of a transition, said in whatever vocabulary the evidence used.

    A string rather than an enum of `on` and `off`, for the reason `subject` is
    a string: the two ends of a bad deployment are versions, and a schema that
    only admitted a flag's positions would force every other kind of change to
    answer null. What the words mean is already fixed by `cause_type`.

    Asked for rather than read back out of the summary. A page recovering the
    transition from the sentence has to decide which of the `on`s and `off`s in
    it were the states, and a sentence that merely uses the word reads as a
    change it never described.
    """
    return {
        "anyOf": [
            {"type": _STRING_TYPE},
            {"type": _NULL_TYPE}
        ],
        "description": description
    }


def _one_explanation() -> dict[str, Any]:
    """One account of the incident, as the model fills it in.

    Every field is required, including the nullable ones. "I have no
    confidence" is a statement the model should have to make rather than
    something it can arrive at by omitting a field.
    """
    return {
        "type": _OBJECT_TYPE,
        "properties": {
            "summary": {
                "type": _STRING_TYPE,
                "description": "One or two sentences: what happened and, if known, why."
            },
            "cause_type": {
                # `anyOf` rather than a union type carrying the enum, which the
                # API rejects: it checks each enum value against the declared
                # type and will not accept a list there. The nullable half is
                # its own branch.
                "anyOf": [
                    {"type": _STRING_TYPE, "enum": [cause.value for cause in CauseType]},
                    {"type": _NULL_TYPE}
                ],
                "description": (
                    "The cause, if the evidence identifies one. Null when it does "
                    "not, which is a valid answer and not a failure."
                )
            },
            "confidence": {
                # Two branches for the same reason as above, and no `minimum`
                # or `maximum`: a strict tool schema rejects bounds on a
                # number. So the range is asked for in the description rather
                # than declared, and it is the model's to respect.
                "anyOf": [
                    {"type": _NUMBER_TYPE},
                    {"type": _NULL_TYPE}
                ],
                "description": (
                    "Your probability that this cause is the real one, given this "
                    "evidence, between 0 and 1. Null exactly when cause_type is null."
                )
            },
            "supporting_evidence": {
                "type": _ARRAY_TYPE,
                "items": _one_thing_it_rests_on(),
                "description": (
                    "The exact lines or buckets this rests on, quoted rather than "
                    "paraphrased. Empty when no cause was determined."
                )
            },
            "subject": {
                "type": [_STRING_TYPE, _NULL_TYPE],
                "description": (
                    "The specific thing the cause names - for a feature-flag toggle, "
                    "the flag's own name, copied verbatim from the evidence. Null "
                    "when the cause names nothing specific, and null when you named "
                    "no cause at all."
                )
            },
            "from_state": _a_state(
                "The state the subject was in before the change, copied from the "
                "evidence - for a feature flag, `off` or `on`. Null when the cause "
                "is not a change from one state to another, and null when there is "
                "no subject."
            ),
            "to_state": _a_state(
                "The state the subject was in after the change, in the same "
                "vocabulary as from_state. Null exactly when from_state is null: "
                "half a transition describes a position rather than a move."
            )
        },
        "required": [
            "summary",
            "cause_type",
            "confidence",
            "supporting_evidence",
            "subject",
            "from_state",
            "to_state"
        ],
        "additionalProperties": False
    }
