"""What the model is asked, and the one shape its answer may take.

The model is handed the incident and the figures Argus already computed, and
asked for the parts only prose can carry - what went wrong, in what words, for
which audience - plus exactly one number: how much of the affected path
carried revenue. That number is a judgment nothing measures, and the answer
carries its reasoning so the document can disclose both.

The answer arrives as a tool call rather than as prose. A document parsed back
out of paragraphs is a document that can be parsed wrongly, and the failure is
silent: a summary that mentions a figure in passing becomes the figure. A tool
call has fields.
"""

from __future__ import annotations

from typing import Final

from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, ToolResult, ToolResults, Transcript
from argus_core.models.turn import Turn

from agent_postmortem.evidence import IncidentEvidence

# The tool's name and its fields, named once. Both ends of the exchange read
# them - the definition offered to the model, and the reader taking the call
# apart - and a spelling that differed between the two would leave a field
# quietly always missing.
SUBMIT_TOOL_NAME: Final = "submit_postmortem"
ROOT_CAUSE_FIELD: Final = "root_cause"
EXECUTIVE_SUMMARY_FIELD: Final = "executive_summary"
IMPACT_WEIGHT_FIELD: Final = "impact_weight"
IMPACT_WEIGHT_REASON_FIELD: Final = "impact_weight_reason"
ASSUMPTIONS_FIELD: Final = "assumptions"

REQUIRED_FIELDS: Final = [
    ROOT_CAUSE_FIELD,
    EXECUTIVE_SUMMARY_FIELD,
    IMPACT_WEIGHT_FIELD,
    IMPACT_WEIGHT_REASON_FIELD
]

SUBMIT_POSTMORTEM = ToolDefinition(
    name=SUBMIT_TOOL_NAME,
    description=(
        "Submit the postmortem for this incident. Every field is required. "
        "Do not restate the figures you were given as if you had computed "
        "them, and do not offer a figure of your own for what the incident "
        "cost - the only number asked of you is the impact weight."
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
        IMPACT_WEIGHT_FIELD: {
            "type": "number",
            "description": (
                "Between 0 and 1: how much of the path that failed carried "
                "revenue. An account page nobody buys from is 0; a checkout "
                "is 1; a slow product listing is somewhere between, because "
                "some of those visitors would have bought and most would have "
                "come back."
            )
        },
        IMPACT_WEIGHT_REASON_FIELD: {
            "type": "string",
            "description": (
                "Why that weight, naming the evidence it rests on. This is "
                "published beside the estimate as a stated assumption."
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


def opening_ask(evidence: IncidentEvidence,
                duration_hours: float,
                error_rate_delta: float | None) -> Transcript:
    """The whole incident in one message, with nothing left to go and fetch.

    A single `Ask` rather than a conversation: by the time a postmortem is
    written the evidence is settled, and a model given tools to read more
    would re-open an investigation that has already finished.
    """
    return [Ask(text="\n".join([
        _the_whole_incident(evidence, duration_hours, error_rate_delta),
        "",
        f"Call {SUBMIT_TOOL_NAME} with your answer."
    ]))]


def _the_whole_incident(evidence: IncidentEvidence,
                        duration_hours: float,
                        error_rate_delta: float | None) -> str:
    """Everything Argus knows, written once and used by both asks."""
    return "\n".join([
        "Write the postmortem for the incident below.",
        "",
        f"Alert: {evidence.alert_summary}",
        f"Started: {evidence.started_at.isoformat()}",
        f"Ended: {evidence.ended_at.isoformat()} "
        f"({duration_hours:.2f} hours)",
        _rise_in_errors(error_rate_delta),
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
