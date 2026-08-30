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

When you do name a cause, `supporting_evidence` quotes the exact lines or \
buckets that did the supporting - not a paraphrase, and not the whole log.

`subject` names the specific thing the cause is about - for a feature flag \
that was toggled, the flag's own name. Copy it verbatim from the evidence in \
front of you; do not correct it, complete it, or supply one from memory. \
Something acts on this name, and a name that is not in the evidence identifies \
nothing. Leave it null when the cause names nothing specific, and null when \
you named no cause at all.

`alternatives` is the other explanations this same evidence supports, if any. \
Something will try the one you named first, and try these in turn if it does \
not help - so an alternative is a competing account of the evidence in front of \
you, not a guess added to fill the list. Each one follows every rule above: its \
own cause, its own confidence, its own quoted evidence, its own verbatim \
subject. Leave it empty when the evidence points one way; that is a real \
answer, and padding it wastes a production change on a cause you do not \
believe in.

`confidence` is your probability that the cause you named is the real one, \
given this evidence. Calibrate it against what the evidence does, not against \
how cautious you feel:

- 0.9 and above: something in the evidence directly records the cause.
- 0.7 to 0.9: no single item records it, but the evidence strongly implies it \
and nothing else in view accounts for the symptoms.
- 0.5 to 0.7: it is the best of several explanations the evidence permits.
- below 0.5: you are guessing - prefer no cause at all.

Being under-confident about a well-supported cause is as misleading as being \
over-confident about a weak one. Both leave a human unable to tell what you \
actually found.\
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


class Explanation(BaseModel):
    """One account of what caused the incident - the wire shape the model fills
    in, flat, and not a `Hypothesis`.

    Kept separate on purpose. A `Hypothesis` is an entity: it has an id, an
    incident it belongs to, a rank among its siblings, and a `tested`/`result`
    life after the Investigator is done with it. None of that is the model's to
    invent, and a schema that offered those fields would be inviting it to.

    Its own type rather than a `Verdict` nested inside a `Verdict`, because a
    self-referential schema describes a tree the model could nest for ever -
    alternatives of alternatives - where what is wanted is one flat list of
    competing answers. The answer's *carrier* is `Verdict` below; this is what
    each answer in it looks like.
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
    # Optional, unlike every other field here - the one place this schema is
    # lenient, and deliberately. A verdict recorded before this field existed
    # is still a verdict, and every committed recording is one; refusing them
    # would turn a replayed answer into `MalformedVerdict` and cost the offline
    # suites their evidence to buy nothing. The description tells a live model
    # when to answer null, and a model that omits the field entirely says the
    # same thing.
    subject: str | None = Field(
        default=None,
        description=(
            "The specific thing the cause names - for a feature-flag toggle, the "
            "flag's name, exactly as it appears in the evidence. Null when the "
            "cause names nothing specific, or when no cause was determined."
        ),
    )

    def _to_hypothesis(self, incident_id: str, rank: int) -> Hypothesis:
        """Joins this explanation to the incident it was formed for.

        `Hypothesis` rejects a cause without a confidence or the reverse, and a
        subject named for no cause, so a model that answered incoherently is
        caught here rather than becoming a hypothesis nothing can act on.
        """
        try:
            return Hypothesis(
                incident_id=incident_id,
                summary=self.summary,
                cause_type=self.cause_type,
                confidence=self.confidence,
                supporting_evidence=self.supporting_evidence,
                subject=self.subject,
                rank=rank,
            )
        except ValidationError as error:
            raise MalformedVerdict(f"the model's verdict is not a hypothesis: {error}") from error


class Verdict(Explanation):
    """The model's answer: its best explanation, and the others it weighed.

    An `Explanation` itself rather than a wrapper holding one, because the best
    answer is not a different kind of thing from the runners-up - it is the one
    that happens to be carrying them.

    `alternatives` is competing accounts of the *same* evidence, which is what
    makes them worth trying in turn when the first is refuted. It is optional on
    the wire, the second place this schema is lenient and for the same reason as
    the first: every recording captured before the field existed omits it, and
    refusing those would turn a replayed answer into `MalformedVerdict` and cost
    the offline suites the evidence they exist to be.
    """

    alternatives: list[Explanation] = Field(
        default_factory=list,
        description=(
            "The other explanations this same evidence supports, if any, ranked "
            "by confidence. An alternative is a competing account of the "
            "evidence in hand - not a guess added to fill the list. Empty is a "
            "valid answer, and the right one when the evidence points one way."
        ),
    )

    def to_hypotheses(self, incident_id: str, limit: int | None = None) -> list[Hypothesis]:
        """Every explanation in this verdict, best first, joined to the incident.

        Ordered by descending confidence rather than by the order the model
        serialized them in: the model is asked for both, and where they disagree
        the numbers win, because the numbers are what the mitigate threshold
        already reads. Ties keep the model's order, which is the only thing left
        to break them with.

        An explanation with no confidence names no cause either - the two travel
        together - so it is the one entry nothing can be done about, and it
        sorts last. Kept rather than dropped, because it is still something the
        model said about the incident.

        `rank` is written here because it has to survive the trip through a
        table: rows come back in no order at all, and a position that lived only
        in list order would not come back with them.

        `limit` is how many of them the caller can afford to try - a ceiling,
        not a quota, so a shorter verdict is left as it is. It is a parameter
        rather than a setting read here, for the same reason
        `Hypothesis.is_confident_enough` takes its threshold: how Argus is
        configured is no business of a model's answer. The cut is made after
        every explanation has been converted, never before, so which answers
        are checked for coherence cannot depend on how many the model offered.
        """
        ordered = sorted(
            [self, *self.alternatives],
            key=lambda explanation: (
                explanation.confidence is None,
                -(explanation.confidence or 0.0),
            ),
        )
        candidates = [
            explanation._to_hypothesis(incident_id, rank)
            for rank, explanation in enumerate(ordered, start=1)
        ]

        return candidates if limit is None else candidates[:limit]


def build_prompt(evidence: Evidence) -> str:
    """Renders one iteration's evidence as the user turn.

    Metrics go in as JSON rather than prose: they are already structured, and
    re-describing them in sentences would only lose the per-minute alignment
    that makes an onset visible.

    The log window is stated explicitly even when the lines are many, because
    the system prompt's "the cause may be outside this window" instruction is
    only actionable if the model knows where the window ends.

    Changes come last and say plainly that they are candidates rather than
    culprits. They are the most causally suggestive thing in the evidence -
    something changed, and then things broke - which is exactly why the
    instruction not to treat proximity as proof belongs beside them rather
    than only in the system prompt.
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
    sections.extend(_change_section(evidence))
    sections.extend(_attempts_section(evidence))

    return "\n".join(sections)


def _attempts_section(evidence: Evidence) -> list[str]:
    """What has already been tried for this incident, and did not help.

    Omitted entirely when nothing has been tried, unlike the change section
    below, which reports its own emptiness. The two absences mean different
    things: "no changes in this window" is a finding about the world, while
    "nothing has been tried yet" is a fact about Argus, and every first-round
    prompt would carry it for nothing.

    Stated as record, not instruction. The model is not told to avoid these
    causes - it is told what happened when they were acted on, which is
    evidence, and left to draw its own conclusion. An instruction would forbid
    the one answer that is sometimes right: that the cause was named correctly
    and the action taken on it was not the one that undoes it.

    The direction is named because both directions are real - a feature flag is
    put back by switching it off, a withdrawn fallback by switching it on - and
    "the flag was changed" leaves the model unable to say which state is now in
    effect.
    """
    if not evidence.attempts:
        return []

    return [
        "",
        "## Already tried",
        "Argus took these actions on this incident and undid each one. The "
        "service did not return to its baseline after any of them.",
        *(
            f"- set {attempt.subject} {'on' if attempt.enabled else 'off'} "
            f"at {attempt.occurred_at}: the service did not recover"
            for attempt in evidence.attempts
        ),
    ]


def _change_section(evidence: Evidence) -> list[str]:
    """The changes made to the service, over a window wider than the logs'.

    Stated as a complete list over a named interval, then as something to
    judge. Both halves earn their place, and they were measured: the section
    once opened by discounting itself ("most changes break nothing", "not
    proof of cause") and the model duly discounted - the same deploy that
    scored 0.72 here scored 0.65 under that wording, while the guard against
    blaming an unrelated change was unaffected either way. No other evidence
    section tells the model its contents might not be real, and this one
    should not have.

    What the framing must still do is keep proximity from standing in for
    explanation: a change is the only thing in the evidence shaped like an
    actor, so a model handed one with no judgement rule will reach for it.
    That rule is now stated as a test to apply - does this account for the
    symptoms? - rather than as a prior about deploys in general.

    The window is named because the completeness claim is worthless without
    it. "This is every change" over an unstated interval tells the model
    nothing it can reason with, and leaves it holding back confidence for a
    change it cannot rule out.

    An empty list is reported explicitly rather than omitted: "nothing changed
    in this window" is a real, useful fact, and silence would read as "nobody
    looked".
    """
    window = _window_between(evidence.change_window_start, evidence.change_window_end)
    heading = [
        "",
        f"## Changes to this service ({window})",
        "Every deploy and configuration change recorded for this service in "
        "that window, which is deliberately wider than the log window above. "
        "This is the complete list for it - a change absent here did not "
        "happen in it. Judge each one against the symptoms: a change that "
        "accounts for what the metrics and logs show is evidence of cause; "
        "one that does not account for them is not the answer, however "
        "closely it precedes them.",
    ]

    if not evidence.change_events:
        return [*heading, "(no changes were recorded for this service in that window)"]

    return [
        *heading,
        json.dumps([change.model_dump() for change in evidence.change_events], indent=2),
    ]


def _window_between(start: str | None, end: str | None) -> str:
    """One retrieval window, rendered for a section heading.

    Says "not recorded" rather than inventing a bound when neither end is
    known: a window with a guessed edge would let the model reason about an
    interval nothing was actually retrieved over.
    """
    if start is None and end is None:
        return "window not recorded"

    return f"{start or 'unbounded'} to {end or 'unbounded'}"


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
        # Read here with the rest of the configuration, rather than at the call
        # site: how many candidates Argus can afford to try is a property of
        # this deployment, not of any one verdict.
        self._max_candidates = resolved.investigation_max_candidates

    def propose_hypotheses(self, evidence: Evidence) -> list[Hypothesis]:
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

        return verdict.to_hypotheses(evidence.incident_id, limit=self._max_candidates)
