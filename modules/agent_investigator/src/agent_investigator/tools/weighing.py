"""How the model says where a lead stands: supported, refuted or unverified.

A lead is something a person wrote in the incident's thread. The model is
shown it and must weigh it before it answers, because a lead is weighed and
never obeyed: a person can be wrong, and an investigation that acted on a lead
against what it read would be doing what it was told rather than what it found.

Not a retrieval and never dispatched, like the answer tool: the loop reads the
call itself, keeps the weighing, and tells the model it was kept. Offered only
once a lead has been shown - a tool for weighing nothing is a request that
changed for an incident nobody wrote about.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import Standing, ToolDefinition

WEIGH_TOOL: Final = "weigh_lead"

LEAD_ARG: Final = "lead"
STANDING_ARG: Final = "standing"
REASON_ARG: Final = "reason"

# JSON Schema's own vocabulary, as `answer` names it.
_STRING_TYPE: Final = "string"


def weigh_lead_tool() -> ToolDefinition:
    """The offer: say where one lead stands against what was read, and why."""
    return ToolDefinition(
        name=WEIGH_TOOL,
        description=(
            "Say where a lead - something a person wrote in the incident's thread - "
            "stands against what you have read. Weigh every lead you are shown before "
            "you call final_answer; a lead weighed again keeps the later weighing. "
            "supported: something you read agrees with it, and it is evidence like "
            "any other - cite it. refuted: something you read contradicts it, and it "
            "is never a reason to act. unverified: nothing you read bears on it either "
            "way; it may still be one of your explanations, ranked at the confidence "
            "the evidence leaves it."
        ),
        properties={
            LEAD_ARG: {
                "type": _STRING_TYPE,
                "description": "The lead's label, as it was shown to you - L1, L2, ..."
            },
            STANDING_ARG: {
                "type": _STRING_TYPE,
                "enum": [standing.value for standing in Standing],
                "description": "Where it stands against what you have read."
            },
            REASON_ARG: {
                "type": _STRING_TYPE,
                "description": (
                    "Why, in one sentence naming what you read - the person who wrote "
                    "it is told this."
                )
            }
        },
        required=[LEAD_ARG, STANDING_ARG, REASON_ARG]
    )
