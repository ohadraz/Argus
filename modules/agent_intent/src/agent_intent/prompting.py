"""What the model is asked about a person's message, and the one shape its
answer may take.

One question - what did they mean - with five answers, offered as a tool the
model must call. A meaning parsed back out of a sentence is a meaning that can
be parsed wrongly, and silently: "they don't say it's resolved" contains the
word. A tool call has a field, and the field has five values.

The person's words go in exactly as they were written. A paraphrase on the way
in would be Argus deciding what they meant before asking.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import Ask, Meaning, ToolDefinition, Transcript

# The tool's name and its one field, named once. Both ends of the exchange use
# them - the definition offered to the model, and `classifying` taking the call
# apart - and a spelling that differed between the two would leave every
# message classified as nothing to act on.
SUBMIT_TOOL_NAME: Final = "submit_meaning"
MEANING_FIELD: Final = "meaning"

SUBMIT_MEANING = ToolDefinition(
    name=SUBMIT_TOOL_NAME,
    description=(
        "Submit what the person meant by their message about an incident. "
        "Choose exactly one meaning."
    ),
    properties={
        MEANING_FIELD: {
            "type": "string",
            "enum": [str(meaning) for meaning in Meaning],
            "description": (
                f"`{Meaning.RESOLVE}` if they say the incident is over - they "
                f"ended it, or saw it end. `{Meaning.QUESTION}` if they ask "
                f"something about it. `{Meaning.INFORMATION}` if they tell you "
                f"something about it you may not know. `{Meaning.WITHDRAW}` if "
                f"they tell you to stop, stand down or cancel, and leave the "
                f"incident to them - they are taking it over. "
                f"`{Meaning.OTHER}` for anything else: "
                f"thanks, a reaction, people talking to each other. A message "
                f"saying it is not over, or asking whether it is, is not "
                f"`{Meaning.RESOLVE}`; a message saying it is over is "
                f"`{Meaning.RESOLVE}`, even if it also tells you to stop."
            )
        }
    },
    required=[MEANING_FIELD]
)


def opening_ask(words: str) -> Transcript:
    """The person's message, and the question, in one message."""
    return [Ask(text="\n".join([
        "A person wrote this in the Slack thread of an incident Argus is "
        "responding to:",
        "",
        words,
        "",
        f"Call {SUBMIT_TOOL_NAME} with what they meant."
    ]))]
