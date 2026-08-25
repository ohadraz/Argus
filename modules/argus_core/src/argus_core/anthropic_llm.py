"""The Anthropic-backed `LLMClient` - the only place Argus talks to a model.

Everything vendor-shaped lives here: the model id, the request parameters, the
wire schema the model fills in, and the prompt. Callers hold an `LLMClient`
and pass `Evidence`; nothing outside this module knows that Anthropic exists.

The one seam below this file is `Settings.anthropic_base_url`, which points
the SDK somewhere else. That is how the test double is selected, and it is
deliberately the *only* difference between a test run and a real one: the
prompt, the schema transform and the response parsing below all still run.
"""

from __future__ import annotations

import json

import anthropic
from pydantic import BaseModel, Field, ValidationError

from argus_core.config import Settings, get_settings
from argus_core.models.cause import CauseType
from argus_core.models.evidence import Evidence
from argus_core.models.hypothesis import Hypothesis

MODEL = "claude-opus-5"

# Non-streaming, so this stays under the SDK's HTTP timeout. A verdict is a
# short structured object; the tokens go on thinking, which this does not cap.
MAX_TOKENS = 16000

SYSTEM_PROMPT = """\
You are the Investigator in an autonomous incident-response system. You are \
given the evidence retrieved for one production incident and must decide what \
caused it.

Judge only from the evidence in front of you.

Saying the cause is undetermined is a correct and expected answer, not a \
failure. The evidence you are shown covers a bounded time window; a cause that \
happened before that window will simply not be in it. If nothing in the \
evidence identifies a cause, return no cause and no confidence, and say in the \
summary what you would need to see. A confident-sounding guess is worse than \
an honest "I don't know", because a human reading it cannot tell the two apart.

When you do name a cause, `confidence` is how strongly this specific evidence \
supports it, and `supporting_evidence` quotes the exact lines or buckets that \
did the supporting - not a paraphrase, and not the whole log.\
"""


class VerdictNotReached(Exception):
    """No usable verdict came back from the model.

    The base of a three-way split, because the three ways differ in what a
    caller should do next. Catch this to mean "there is no hypothesis"; catch
    a subclass to decide whether trying again could help.
    """


class MalformedVerdict(VerdictNotReached):
    """The model answered, but not with something that is a hypothesis.

    Covers both layers - a body that failed the schema on the way in, and one
    that passed the schema but failed the domain's own invariants on the way
    out. A caller has no use for the distinction: either way the request was
    fine and the answer was not.
    """


class ModelRefused(VerdictNotReached):
    """The model declined to answer (`stop_reason: "refusal"`).

    Not malformed - this is a complete, well-formed response that says no.
    Kept separate because it is the one outcome retrying cannot fix: the same
    evidence will be declined again. Escalate instead.
    """


class VerdictTruncated(VerdictNotReached):
    """The model ran out of output budget before finishing (`max_tokens`).

    Separate from `MalformedVerdict` because nothing is wrong with the model
    or the request - there was simply not enough room. This is the one failure
    here that a retry, with more room, can actually resolve.
    """


# The stop reasons that mean something other than "the model answered badly".
# Anything not listed falls through to `MalformedVerdict`: a response with no
# verdict and no explanation for its absence is exactly that.
_STOP_REASON_ERRORS: dict[str, type[VerdictNotReached]] = {
    "refusal": ModelRefused,
    "max_tokens": VerdictTruncated,
}


class Verdict(BaseModel):
    """The wire shape the model fills in - flat, and not a `Hypothesis`.

    Kept separate on purpose. A `Hypothesis` is an entity: it has an id, an
    incident it belongs to, and a `tested`/`result` life after the
    Investigator is done with it. None of that is the model's to invent, and a
    schema that offered those fields would be inviting it to.

    So the model fills in the four fields it can actually know, and the
    adapter joins them to the incident. `to_hypothesis` below is the single
    point where the wire shape and the domain shape meet.
    """

    summary: str = Field(
        description="One or two sentences: what happened and, if known, why.",
    )
    cause_type: CauseType | None = Field(
        description=(
            "The cause, if the evidence identifies one. Null when it does not - "
            "which is a valid answer, not a failure."
        ),
    )
    # Required, but nullable. No default on purpose: every other field here is
    # required, and a default would let the model omit the field instead of
    # deciding. "I have no confidence" is a statement it should have to make.
    confidence: float | None = Field(
        ge=0.0,
        le=1.0,
        description=(
            "How strongly this evidence supports the named cause, 0 to 1. "
            "Null exactly when cause_type is null."
        ),
    )
    supporting_evidence: list[str] = Field(
        description=(
            "The exact log lines or metric buckets the conclusion rests on, quoted. "
            "Empty when no cause was determined."
        ),
    )

    def to_hypothesis(self, incident_id: str) -> Hypothesis:
        """Joins this verdict to the incident it was formed for.

        `Hypothesis` rejects a cause without a confidence or the reverse, so a
        model that answered incoherently - a named cause at null confidence -
        is caught here rather than becoming a hypothesis nothing can act on.
        """
        try:
            return Hypothesis(
                incident_id=incident_id,
                summary=self.summary,
                cause_type=self.cause_type,
                confidence=self.confidence,
                supporting_evidence=self.supporting_evidence,
            )
        except ValidationError as error:
            raise MalformedVerdict(f"the model's verdict is not a hypothesis: {error}") from error


def build_prompt(evidence: Evidence) -> str:
    """Renders one iteration's evidence as the user turn.

    Metrics go in as JSON rather than prose: they are already structured, and
    re-describing them in sentences would only lose the per-minute alignment
    that makes an onset visible.

    The log window is stated explicitly even when the lines are many, because
    the system prompt's "the cause may be outside this window" instruction is
    only actionable if the model knows where the window ends.
    """
    alert = evidence.alert
    window = "not recorded"
    if evidence.log_window_start or evidence.log_window_end:
        window = f"{evidence.log_window_start or 'start of log'} to " \
                 f"{evidence.log_window_end or 'end of log'}"

    sections = [
        "## Alert",
        f"service: {alert.service}",
        f"name: {alert.alert_name}",
        f"severity: {alert.severity or 'unspecified'}",
        f"fired at: {alert.started_at.isoformat() if alert.started_at else 'unspecified'}",
        f"summary: {alert.summary or 'none given'}",
        "",
        "## Per-minute metrics",
        "One object per minute, in time order.",
        json.dumps([bucket.model_dump() for bucket in evidence.metric_buckets], indent=2),
        "",
        f"## Log lines ({window})",
    ]
    sections.extend(evidence.log_lines or ["(no log lines were returned for this window)"])
    return "\n".join(sections)


# What the SDK is handed when a `base_url` override means nothing is going to
# authenticate against Anthropic. It is a placeholder, and it says so.
_UNUSED_API_KEY = "not-a-real-key-the-base-url-is-overridden"


def _api_key_for(configured_key: str, base_url: str | None) -> str:
    """The key to give the SDK, which refuses to build a request without one.

    An overridden `base_url` means the requests are not going to Anthropic, so
    there is no key to have and requiring one would put an API key in the way
    of a test that never calls the API. A fresh clone has to be able to run the
    integration suite, and it has no key.

    The override is what makes this safe: with no override the configured key
    is passed through untouched, empty or not, and the SDK's own error is the
    right one to see. This never invents credentials for the real API.
    """
    if base_url is not None and not configured_key:
        return _UNUSED_API_KEY
    return configured_key


class AnthropicLLMClient:
    """`LLMClient` backed by the real Anthropic Messages API.

    The client is built once and reused: `messages.parse` is stateless, and a
    per-call client would throw away the connection pool for no benefit.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        resolved = settings if settings is not None else get_settings()
        base_url = resolved.anthropic_base_url or None
        self._client = anthropic.Anthropic(
            api_key=_api_key_for(resolved.anthropic_api_key, base_url),
            # An empty setting means the real API, which is what the SDK does
            # with `base_url=None`. Passing "" would point it at nothing.
            base_url=base_url,
        )

    def propose_hypothesis(self, evidence: Evidence) -> Hypothesis:
        """Asks the model what caused the incident this evidence was gathered for.

        Adaptive thinking at high effort: the judgment being asked for is
        "does this flag change explain this error rate, or does it only
        precede it", which is exactly the kind of question that gets worse
        without reasoning.
        """
        try:
            parsed = self._client.messages.parse(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                output_format=Verdict,
                output_config={"effort": "high"},
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_prompt(evidence)}],
            )
        except ValidationError as error:
            raise MalformedVerdict(
                f"the model's response did not match the verdict schema: {error}"
            ) from error

        verdict = parsed.parsed_output
        if verdict is None:
            error_type = _STOP_REASON_ERRORS.get(parsed.stop_reason or "", MalformedVerdict)
            raise error_type(
                f"the model returned no structured verdict (stop_reason={parsed.stop_reason})"
            )

        return verdict.to_hypothesis(evidence.incident_id)
