"""One investigation: a conversation the model drives and the loop bounds.

Two things are deliberately not the model's. The onset is measured here,
before its first turn, and stated as a fact - a sampled anchor would make two
investigations of one incident incomparable and the eval suite a measurement
of noise. And the budget is arithmetic done between turns, never expressed to
the model, because a bound it could ask to extend is not a bound.

Everything else is the model's: which channel to read, over what window, in
what order, and when it has seen enough. The loop's job is to carry out what
it asks for, tell it what came back, and stop it when it has spent what it was
given.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from argus_core.anomaly import earliest_bucket_is_anomalous, find_onset
from argus_core.events import (
    ChannelsUnread,
    HypothesisFormed,
    MetricsRetrieved,
    Narrator,
    OnsetDetected,
    Publisher,
    RetrievalChannel,
    RetrievalRequested,
    nobody,
)
from argus_core.llm.client import AnswerTruncated, ModelRefused
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.models.reading import Reading
from argus_core.models.transcript import Ask, Exchange, ToolResult, ToolResults
from argus_core.models.turn import ToolCall, Turn

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both, where one of the two names has to say which it is.
from argus_core.replay import CallType, Recorder, Replay
from argus_core.replay import nobody as records_nothing
from argus_core.timestamps import to_iso
from pydantic import ValidationError

from agent_investigator.budget import Bound, Budget
from agent_investigator.reasoning import Conversation, a_conversation_recorded_for
from agent_investigator.retrieval import (
    ChangeFetcher,
    LogFetcher,
    MetricsFetcher,
    fetch_change_events,
    fetch_logs,
    fetch_metrics,
)
from agent_investigator.tools import (
    ANSWER_TOOL,
    HYPOTHESES_ARG,
    METRICS_TOOL,
    Dispatcher,
    investigator_tools,
)

# What the model is told it is doing, in the one message Argus writes as prose.
# It lives with the loop rather than with the adapter because it describes this
# loop's job - what the tools are for and what ends the conversation - and an
# adapter that carried it would be describing a caller it does not have.
BRIEF: Final = """\
You are the Investigator in an autonomous incident-response system. One \
production incident is described below. Find what caused it.

You have three ways to read evidence and one way to finish. Ask for whatever \
you need, in whatever order, over whatever windows look worth reading - that \
judgement is the reason you are here rather than a fixed sequence of reads. \
When you have seen enough, call final_answer.

Judge only from the evidence you actually retrieved. Saying the cause is \
undetermined is a correct and expected answer, not a failure: every window is \
bounded, and a cause outside the one you read will not be in it. A \
confident-sounding guess is worse than an honest "I don't know", because a \
human reading it cannot tell the two apart.

`confidence` is your probability that the cause you named is the real one, \
given this evidence - a probability, so 0.0 to 1.0 inclusive and nothing \
outside it. Calibrate it against what the evidence does, not against how \
cautious you feel: 0.9 to 1.0 when something in the evidence records the cause \
directly, 0.7 to 0.9 when it strongly implies it and nothing else in view \
accounts for the symptoms, 0.5 to 0.7 when it is the best of several \
explanations the evidence permits, and below 0.5 you are guessing - prefer no \
cause at all.

`subject` names the specific thing the cause is about - for a feature flag, \
the flag's own name, copied verbatim from the evidence. Something acts on that \
name, so a name that is not in the evidence identifies nothing.

Give every explanation the evidence supports, best first. The one you name \
first is tried first, and the rest are tried in turn if it does not help.\
"""

_MILLISECONDS_PER_SECOND: Final = 1000

_A_TURN_THAT_ANSWERED_NOTHING: Final = (
    "That turn asked for nothing and answered nothing. Ask for the evidence you need, "
    "or call final_answer with what you have."
)

_ONE_TURN_LEFT: Final = (
    "\n\nThis is your last turn: there is no budget for another retrieval. Answer now, "
    "with final_answer, from what you have already read."
)


@dataclass(frozen=True)
class Findings:
    """What one investigation concluded, and what it read to conclude it.

    Named for the product rather than the process: an investigation is the
    thing that runs, and this is what it hands back.

    `candidates` is every explanation the model offered, best first, and is
    never empty - an investigation that identified no cause says so in one
    candidate carrying the reason. Whether any of them is worth acting on is
    the mitigate threshold's business, not this type's.

    `already_read` is what a later round cannot work out for itself. A round is
    bought by a refutation, not by a wider window, and the round that follows
    should know what the one before it saw - both so it does not pay again for
    the same evidence, and so that a channel nobody asked for stays
    distinguishable from one that was asked and came back empty.
    """

    candidates: list[Hypothesis]
    already_read: list[Reading]


def investigate(
    alert: Alert,
    incident_id: str,
    fetch_metrics: MetricsFetcher = fetch_metrics,
    fetch_logs: LogFetcher = fetch_logs,
    fetch_change_events: ChangeFetcher = fetch_change_events,
    converse: Conversation | None = None,
    budget: Budget | None = None,
    already_read: Sequence[Reading] | None = None,
    already_refuted: Sequence[Attempt] | None = None,
    publisher: Publisher = nobody,
    recorder: Recorder = records_nothing
) -> Findings:
    """Investigates one incident as a tool-use conversation (spec §9),
    returning what it concluded - including that it concluded nothing.

    The metrics are read first and the onset located from them, before the
    model has seen anything. That is not a retrieval the model was denied: it
    may read the metrics again itself. It is that the anchor every window is
    measured from must be the same on every run of the same incident.

    From there the model decides. Each turn it asks for evidence, gets it, and
    asks again; the loop ends when it calls the answer tool, or when a bound
    binds and it is reported as having run out - naming which bound, because "I
    ran out of time" and "I read everything I was allowed to and still could
    not tell" call for different things from the human who reads it.

    `already_refuted` and `already_read` are how a later round differs from a
    first. The refutations are the valuable half: a cause was named, acted on,
    and the service stayed broken, which is evidence no amount of reading would
    have produced.

    The collaborators are default-argument seams: the real retrieval calls and
    the real model in production, doubles in a test, and no monkeypatching
    either way. `publisher` and `recorder` are two of the same kind, and the
    only two whose absence changes nothing - the investigation reaches the same
    conclusion whether or not anybody is listening or filing the receipts (spec
    §4 principle 6).

    `converse` is the exception among them, and defaults to nothing rather than
    to the real call. The conversation for a real investigation has to be built
    from this incident and this recorder, which are not known until here - so
    what a caller omitting it gets is constructed below, and a caller injecting
    a scripted one never reaches the construction or the SDK behind it.
    """
    alert_time = to_iso(alert.started_at) if alert.started_at is not None else None
    narrator = Narrator(incident_id, publisher)
    # Built here for the same reason the narrator beside it is: both bind this
    # incident to a collaborator the caller supplied, and both would otherwise
    # have to thread an incident id through every call that uses them.
    replay = Replay(incident_id, recorder)
    speak = converse or a_conversation_recorded_for(incident_id, recorder)

    # Read by the loop rather than offered as the first tool call, so that the
    # onset is a measurement instead of a decision. Anchored on the alert
    # rather than bounded, which is what the event says: the span is the
    # metrics tool's own (spec §16), not this loop's to name.
    narrator.say(
        RetrievalRequested, channel=RetrievalChannel.METRICS, window_start=alert_time
    )
    started_reading_at = time.monotonic()
    metric_buckets = fetch_metrics(alert_time)
    narrator.say(
        MetricsRetrieved,
        window_start=metric_buckets[0].bucket_id if metric_buckets else None,
        window_end=metric_buckets[-1].bucket_id if metric_buckets else None,
        buckets=metric_buckets
    )
    # The one retrieval the dispatcher never sees, and so the one it cannot
    # write down. Recorded here and now rather than at the end of the
    # investigation: an incident whose metrics show nothing returns below
    # without a model ever being asked, and that is exactly the run someone
    # later asks what it actually had in front of it.
    #
    # Filed under the model's own name for this channel, because it is the same
    # channel read by a different caller - a reader counting what an
    # investigation retrieved should not have to know which of the two asked.
    replay.record(
        call_type=CallType.MCP,
        target=METRICS_TOOL,
        # No window of its own: the span belongs to the metrics source, and
        # what identifies this read is the alert it was anchored on (spec §16).
        request={"arguments": {}, "window_start": alert_time, "window_end": None},
        # The buckets as they came back, rather than as the opening message
        # renders them. Nothing rendered them at this point, and the numbers are
        # what a later reader wants - the prose around them is reconstructible
        # and the measurements are not.
        response={"buckets": [bucket.model_dump(mode="json") for bucket in metric_buckets]},
        latency_ms=int((time.monotonic() - started_reading_at) * _MILLISECONDS_PER_SECOND)
    )

    onset = find_onset(metric_buckets)

    if onset is None:
        # Nothing was read beyond the metrics, and nothing was spent. There is
        # also nothing to converse about: every window the model could ask for
        # is anchored on an onset the metrics do not contain.
        return _nothing_to_say(alert, incident_id, metric_buckets, narrator)

    narrator.say(OnsetDetected, onset=onset)

    dispatcher = Dispatcher(
        service=alert.service,
        onset=onset,
        alert_time=alert_time,
        narrator=narrator,
        # The same `Replay` the metrics read above went through, so that every
        # call one investigation made reaches one place: what the model was
        # asked and what the tools answered are two halves of one run.
        replay=replay,
        # The metrics are read above, before the model's first turn, and their
        # buckets go into the opening message - so they are read, and asking
        # for the same fixed span again would return what is already in front
        # of it.
        having_read=[Reading(RetrievalChannel.METRICS, window_start=alert_time)],
        fetch_metrics=fetch_metrics,
        fetch_logs=fetch_logs,
        fetch_change_events=fetch_change_events
    )
    spend = budget if budget is not None else Budget.from_settings()
    tools = investigator_tools()
    transcript: list[Exchange] = [
        Ask(text=_the_opening_message(
            alert, onset, metric_buckets, already_refuted or [], already_read or []
        ))
    ]

    while True:
        try:
            turn = speak(transcript, tools)
        except AnswerTruncated:
            # Recoverable, and the loop is the only one that can say whether
            # recovering is affordable: the turn carried nothing, so nothing
            # was charged for it and the transcript is unchanged - asking
            # again is asking the same question, not continuing a broken one.
            reached = spend.bounds_reached()
            if reached:
                return _ran_out(
                    alert, incident_id, metric_buckets, reached, dispatcher, narrator,
                    cut_short=True
                )

            continue
        except ModelRefused:
            return _declined(alert, incident_id, metric_buckets, dispatcher, narrator)

        spend.record(turn)
        transcript.append(turn)

        answered = _the_answer_in(turn, incident_id)
        if isinstance(answered, list):
            for candidate in answered:
                _say_formed(narrator, candidate)

            narrator.say(ChannelsUnread, channels=dispatcher.channels_unread)

            return Findings(candidates=answered, already_read=dispatcher.readings)

        results = [
            *([answered] if answered is not None else []),
            *(dispatcher.dispatch(call) for call in turn.tool_calls if call.name != ANSWER_TOOL)
        ]

        reached = spend.bounds_reached()
        if reached:
            return _ran_out(alert, incident_id, metric_buckets, reached, dispatcher, narrator)

        transcript.append(_what_the_model_is_told_next(results, spend.is_on_its_last_turn()))


def _the_answer_in(turn: Turn, incident_id: str) -> list[Hypothesis] | ToolResult | None:
    """The investigation's answer, if this turn carried one.

    Three outcomes, because the answer tool can be called well, called badly,
    or not called. `None` means the model is still working. A list means it has
    finished. A `ToolResult` means it called the answer tool with something
    that is not an answer - which is the model's to correct, like any other bad
    call, rather than the end of an investigation that may have read plenty.
    """
    answering = next((call for call in turn.tool_calls if call.name == ANSWER_TOOL), None)
    if answering is None:
        return None

    try:
        return _hypotheses_in(answering, incident_id)
    except (ValidationError, TypeError, AttributeError) as malformed:
        return ToolResult(
            call_id=answering.id,
            content=(
                f"that answer could not be read: {malformed}. Call final_answer again "
                f"with one entry per explanation, each carrying a summary, a cause_type "
                f"and confidence that are both null or both set, its supporting "
                f"evidence, and a subject."
            ),
            failed=True
        )


def _hypotheses_in(answering: ToolCall, incident_id: str) -> list[Hypothesis]:
    """The model's ranked explanations, joined to the incident they explain.

    The order is the model's own, because it was asked for one: the first is
    what a mitigation tries first. `rank` is written down rather than left as
    list position, since rows come back from a table in no order at all.

    `incident_id` is supplied here rather than asked of the model. It is not
    something the model knows, and a schema offering the field would be
    inviting it to invent one.
    """
    return [
        Hypothesis(
            incident_id=incident_id,
            summary=explanation["summary"],
            cause_type=explanation["cause_type"],
            confidence=explanation["confidence"],
            supporting_evidence=explanation.get("supporting_evidence") or [],
            subject=explanation.get("subject"),
            rank=rank
        )
        for rank, explanation in enumerate(answering.arguments[HYPOTHESES_ARG], start=1)
    ]


def _what_the_model_is_told_next(results: list[ToolResult], one_turn_left: bool) -> Exchange:
    """The reply the model reads before its next turn.

    Results when it asked for something, and a plain remark when it did not:
    a turn that asked for nothing still has to be answered with something, or
    the conversation has two consecutive turns from the model and no thread to
    continue.

    The warning rides on whatever is being sent rather than travelling as its
    own message, because it is not a separate thing to consider - it is the
    condition under which everything else in this reply should be read.
    """
    warning = _ONE_TURN_LEFT if one_turn_left else ""

    if not results:
        return Ask(text=_A_TURN_THAT_ANSWERED_NOTHING + warning)

    last = results[-1]

    return ToolResults(results=[
        *results[:-1],
        ToolResult(call_id=last.call_id, content=last.content + warning, failed=last.failed)
    ])


def _ran_out(alert: Alert,
             incident_id: str,
             metric_buckets: list[MetricBucket],
             reached: list[Bound],
             dispatcher: Dispatcher,
             narrator: Narrator,
             cut_short: bool = False) -> Findings:
    """The outcome when the budget bound before the model answered.

    Every bound that ran out is named, not the first noticed: two bounds
    binding together is a different account of an investigation than one, and
    which one a human hears about should not depend on the order the checks
    happen to be written in.

    `cut_short` says the last turn was one the model never finished. It is
    worth saying because it reads as a different failure: the investigation
    was not merely out of budget, it was out of budget at the one moment more
    of it would have bought a finished answer.
    """
    spent = ", ".join(bound.value for bound in reached)
    ended = (
        f"the model's last turn was cut short and the investigation ran out of {spent} "
        f"before it could be asked again"
        if cut_short
        else f"the investigation ran out of {spent} before it identified one"
    )
    undetermined = _undetermined(alert, incident_id, ended, metric_buckets)
    _say_formed(narrator, undetermined)
    narrator.say(ChannelsUnread, channels=dispatcher.channels_unread)

    return Findings(candidates=[undetermined], already_read=dispatcher.readings)


def _declined(alert: Alert,
              incident_id: str,
              metric_buckets: list[MetricBucket],
              dispatcher: Dispatcher,
              narrator: Narrator) -> Findings:
    """The outcome when the model declined to answer.

    Final however much budget is left, which is what separates it from a turn
    that was cut short: the same question over the same evidence is declined
    again, so a retry spends a turn to be told no twice. What the
    investigation read still comes back, because a later round should not pay
    for it again on the way to a human.
    """
    undetermined = _undetermined(
        alert,
        incident_id,
        "the model declined to answer, and asking again would put the same "
        "evidence to it",
        metric_buckets
    )
    _say_formed(narrator, undetermined)
    narrator.say(ChannelsUnread, channels=dispatcher.channels_unread)

    return Findings(candidates=[undetermined], already_read=dispatcher.readings)


def _nothing_to_say(alert: Alert,
                    incident_id: str,
                    metric_buckets: list[MetricBucket],
                    narrator: Narrator) -> Findings:
    """The outcome when the metrics show no incident to investigate."""
    undetermined = _undetermined(
        alert, incident_id, _reason_nothing_was_found(metric_buckets), metric_buckets
    )
    _say_formed(narrator, undetermined)

    return Findings(candidates=[undetermined], already_read=[])


def _undetermined(alert: Alert,
                  incident_id: str,
                  reason: str,
                  metric_buckets: list[MetricBucket]) -> Hypothesis:
    """The honest outcome: no cause, and no confidence to go with it.

    Carries no `cause_type` and no `confidence` at all - a hypothesis refuses
    to hold one without the other - so that whoever picks the incident up can
    tell "nothing identified" from a real diagnosis. The summary says *why* it
    stopped, since "I ran out of time" and "I read everything I was allowed to
    and still could not tell" call for different next steps.
    """
    return Hypothesis(
        incident_id=incident_id,
        summary=(
            f"no cause determined for {alert.alert_name} on {alert.service}: {reason}"
        ),
        cause_type=None,
        confidence=None,
        supporting_evidence=[]
    )


def _reason_nothing_was_found(metric_buckets: list[MetricBucket]) -> str:
    if not metric_buckets:
        return "no metrics were retrieved for the incident window"

    return "no minute in the metrics window departs from the service's baseline"


def _say_formed(narrator: Narrator, hypothesis: Hypothesis) -> None:
    """One candidate as the narration carries it.

    The candidate's own id travels with it, so the story and the walk are the
    same hypothesis seen twice rather than two accounts to be reconciled.
    """
    narrator.say(
        HypothesisFormed,
        hypothesis_id=hypothesis.id,
        summary=hypothesis.summary,
        cause_type=hypothesis.cause_type,
        confidence=hypothesis.confidence,
        subject=hypothesis.subject,
        rank=hypothesis.rank,
        evidence=hypothesis.supporting_evidence
    )


def _the_opening_message(alert: Alert,
                         onset: str,
                         metric_buckets: list[MetricBucket],
                         already_refuted: Sequence[Attempt],
                         already_read: Sequence[Reading]) -> str:
    """Everything the model is told before it decides anything.

    The onset is stated as a fact rather than offered as a question, and where
    it is only a lower bound that is said plainly - a model that does not know
    its window may have opened mid-incident cannot know to reach further back,
    and confidence will not tell it: it cannot miss what it was never shown.
    """
    said = [
        BRIEF,
        "",
        "## Alert",
        f"service: {alert.service}",
        f"name: {alert.alert_name}",
        f"severity: {alert.severity or 'unspecified'}",
        f"fired at: {to_iso(alert.started_at) if alert.started_at else 'unspecified'}",
        f"summary: {alert.summary or 'none given'}",
        "",
        "## Onset",
        f"The incident began at {onset}, measured from the per-minute metrics below: "
        f"it is the first minute that departs from the service's own baseline and "
        f"stays departed."
    ]

    if earliest_bucket_is_anomalous(metric_buckets):
        said.append(
            "The metrics window opens already elevated, so that minute is a lower "
            "bound rather than the onset itself - the incident began before anything "
            "retrievable, and a window anchored on it may not contain the cause."
        )

    said.extend([
        "",
        "## Per-minute metrics",
        "One object per minute, in time order. These are the minutes the onset was "
        "measured from, and they are the whole span the metrics source keeps - there "
        "is no more of this channel to ask for.",
        json.dumps([bucket.model_dump() for bucket in metric_buckets], indent=2)
    ])

    if already_refuted:
        said.extend([
            "",
            "## Already tried",
            "Argus took these actions on this incident and undid each one. The service "
            "did not return to its baseline after any of them.",
            *(
                f"- set {attempt.subject} {'on' if attempt.enabled else 'off'} at "
                f"{attempt.occurred_at}: the service did not recover"
                for attempt in already_refuted
            )
        ])

    if already_read:
        said.extend([
            "",
            "## Already read",
            "An earlier round of this investigation read these. You may read them "
            "again - what they contained is not in front of you - but nothing in them "
            "identified a cause that held.",
            *(f"- {reading}" for reading in already_read)
        ])

    return "\n".join(said)
