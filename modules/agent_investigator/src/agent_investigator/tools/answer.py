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
                "items": {"type": _STRING_TYPE},
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
            }
        },
        "required": [
            "summary",
            "cause_type",
            "confidence",
            "supporting_evidence",
            "subject",
        ],
        "additionalProperties": False
    }
