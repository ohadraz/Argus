"""What the model is asked, and the one shape its answer may take.

The model is handed the incident and the figures Argus already computed, and
asked only for the parts prose can carry - what went wrong, in what words, for
which audience. Not one number: every figure in the document is measured, and
a model asked for one term of an arithmetic it cannot check would be supplying
a guess that arrives looking like the rest.

The answer arrives as a tool call rather than as prose. A document parsed back
out of paragraphs is a document that can be parsed wrongly, and the failure is
silent: a summary that mentions a figure in passing becomes the figure. A tool
call has fields.
"""

from __future__ import annotations

from typing import Any, Final

from argus_core.models import Ask, ToolDefinition, ToolResult, ToolResults, Transcript, Turn
from pydantic import BaseModel, field_validator

from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.measuring import Measurements

# The tool's name and its fields, named once. Both ends of the exchange read
# them - the definition offered to the model, and the reader taking the call
# apart - and a spelling that differed between the two would leave a field
# quietly always missing.
SUBMIT_TOOL_NAME: Final = "submit_postmortem"
ROOT_CAUSE_FIELD: Final = "root_cause"
EXECUTIVE_SUMMARY_FIELD: Final = "executive_summary"
ASSUMPTIONS_FIELD: Final = "assumptions"

REQUIRED_FIELDS: Final = [
    ROOT_CAUSE_FIELD,
    EXECUTIVE_SUMMARY_FIELD
]


class SubmittedPostmortem(BaseModel):
    """What the model submitted, said as fields rather than as a mapping.

    The answer is read by four modules on its way to the page - the one that
    takes the call apart, the one that finds faults in it, the one composing the
    disclosures, and the one filling in the columns - and as a mapping each of
    those named its fields in strings. A field renamed here is now a type error
    in all four rather than a key that quietly returns nothing in three.

    Every field is optional, because finding out what is missing is the point:
    a required field the model left out is a fault to put back to it (see
    `checking`), not an answer that failed to arrive. `None` means unanswered,
    and reaches the document as an absent column rather than an empty one.

    The attribute names are the wire names above, and have to be: the call's
    arguments are validated into this as they stand.

    Nothing here refuses a submission, which is what the validators below are
    for. A field that did not arrive in its declared shape costs that field and
    no other: refusing the whole call would throw away a root cause the model
    wrote over an `assumptions` it sent as a bare string, and the document would
    then record as unanswered something that was answered. This agent spends its
    whole discipline telling an absence that was measured from one that was
    never asked, and an absence manufactured here would be neither.
    """

    root_cause: str | None = None
    executive_summary: str | None = None
    assumptions: list[str] = []

    @field_validator(ROOT_CAUSE_FIELD, EXECUTIVE_SUMMARY_FIELD, mode="before")
    @classmethod
    def _prose_however_it_arrived(cls, value: Any) -> Any:
        """A prose field made to cost only itself.

        A number is written out: a figure where a sentence was asked for is
        still an answer, and one dropped here would be a root cause the model
        supplied and the document denies. Anything structural is read as
        unanswered instead, which `checking` then names and asks about.
        """
        if value is None or isinstance(value, str):
            return value

        return str(value) if isinstance(value, int | float) else None

    @field_validator(ASSUMPTIONS_FIELD, mode="before")
    @classmethod
    def _however_many_were_stated(cls, value: Any) -> Any:
        """The assumptions, as the list they were asked for.

        A model with one thing to say sends it as a string often enough to be
        worth reading as the list containing it. Anything else in the list that
        is not a sentence is dropped rather than refused - a disclosure that
        cannot be read costs one line, and refusing it would cost the document.
        """
        if isinstance(value, str):
            return [value]

        if isinstance(value, list):
            return [stated for stated in value if isinstance(stated, str)]

        return []


SUBMIT_POSTMORTEM = ToolDefinition(
    name=SUBMIT_TOOL_NAME,
    description=(
        "Submit the postmortem for this incident. Every field is required. "
        "No number is asked of you: what the incident cost was measured from "
        "what the shop actually took, so do not restate the figures you were "
        "given as if you had computed them, and do not offer one of your own."
    ),
    properties={
        ROOT_CAUSE_FIELD: {
            "type": "string",
            "description": (
                "What caused the incident, in one or two sentences, written "
                "for an engineer who was not on the call."
            )
        },
        EXECUTIVE_SUMMARY_FIELD: {
            "type": "string",
            "description": (
                "The same incident for a reader who does not work on the "
                "service: what broke, for how long, who it affected, and what "
                "was done. No component names unless they are unavoidable."
            )
        },
        ASSUMPTIONS_FIELD: {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Anything else the reader should know was assumed rather than "
                "measured. Empty is a valid answer."
            )
        }
    },
    required=REQUIRED_FIELDS
)


def opening_ask(evidence: IncidentEvidence, measured: Measurements) -> Transcript:
    """The whole incident in one message, with nothing left to go and fetch.

    A single `Ask` rather than a conversation: by the time a postmortem is
    written the evidence is settled, and a model given tools to read more
    would re-open an investigation that has already finished.
    """
    return [Ask(text="\n".join([
        _the_whole_incident(evidence, measured),
        "",
        f"Call {SUBMIT_TOOL_NAME} with your answer."
    ]))]


def _the_whole_incident(evidence: IncidentEvidence, measured: Measurements) -> str:
    """Everything Argus knows, written once and used by both asks."""
    return "\n".join([
        "Write the postmortem for the incident below.",
        "",
        f"Alert: {evidence.alert_summary}",
        f"Started: {evidence.started_at.isoformat()}",
        f"Ended: {evidence.ended_at.isoformat()} "
        f"({measured.duration_in_hours:.2f} hours)",
        _rise_in_errors(measured.error_rate_delta),
        "",
        "What Argus did, in order:",
        *(f"  - {line}" for line in evidence.timeline),
        "",
        "Candidates it considered:",
        *(f"  - {candidate}" for candidate in evidence.candidates),
        "",
        "Actions it took:",
        *(f"  - {action}" for action in evidence.actions),
        "",
        "Log lines it read:",
        *(f"  - {line}" for line in evidence.log_lines)
    ])


def opening_ask_again(asked: Transcript, faults: list[str]) -> Transcript:
    """The same incident put again, for a model that answered with no call.

    The last resort, and only reachable when there is no submission to refuse
    (see `rejecting`). It repeats what was asked rather than referring back to
    it, because a conversation the model did not take part in the shape of is
    not a conversation to continue.
    """
    return [
        *asked,
        Ask(text="\n".join([
            "Your previous answer could not be used:",
            *(f"  - {fault}" for fault in faults),
            "",
            f"Answer by calling {SUBMIT_TOOL_NAME}, and not in prose."
        ]))
    ]


def rejecting(asked: Transcript, submitted: Turn, faults: list[str]) -> Transcript:
    """The same conversation, with the submission answered and refused.

    Not a second conversation. The model's answer was a tool call, and a call
    is answered by its result - which is exactly where a refusal belongs: the
    model sees what it submitted, is told what was wrong with it, and corrects
    that rather than writing a fresh document from an instruction that arrived
    out of nowhere. It is also the only shape a provider will take, since one
    that has seen a tool call expects its result next.

    The result is marked failed, which is how a tool says "this is something
    to fix" rather than "this is what I found out".
    """
    return [
        *asked,
        submitted,
        ToolResults(results=[ToolResult(
            call_id=submitted.tool_calls[0].id,
            content="\n".join([
                "Your postmortem was not accepted:",
                *(f"  - {fault}" for fault in faults),
                "",
                f"Call {SUBMIT_TOOL_NAME} again with the whole answer, corrected."
            ]),
            failed=True
        )])
    ]


def _rise_in_errors(delta: float | None) -> str:
    if delta is None:
        return "Error rate: not known - metrics for the incident could not be read."

    return f"Error rate: {delta:.1%} of traffic failed that otherwise would not have."
