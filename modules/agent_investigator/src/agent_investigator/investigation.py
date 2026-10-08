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

import logging
from collections.abc import Sequence
from dataclasses import replace
from enum import StrEnum
from typing import Any, Final, assert_never

from argus_core import parse_iso, to_iso, to_iso_minute
from argus_core.anomaly import (
    AnomalyThresholds,
    earliest_bucket_is_anomalous,
    find_onset,
    has_a_reading_since,
    signals_judged_in,
)
from argus_core.events import (
    ChannelsUnread,
    HypothesisFormed,
    MetricsRetrieved,
    Narrator,
    OnsetDetected,
    PlacementRecorded,
    Publisher,
    RetrievalRequested,
    RetrievalUnanswered,
    nobody,
)
from argus_core.llm import (
    AnswerTruncated,
    Conversation,
    Conversations,
    ModelRefused,
    a_conversation_recorded_for,
    on_one_line,
)
from argus_core.models import (
    DISCARD_CACHE_ENTRIES,
    PIN_AUTOSCALER,
    PIN_TO_ACCELERATOR,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    RULE_READING_FIELD,
    SCALE_OUT,
    AlarmClaim,
    Alert,
    Ask,
    Attempt,
    Disproof,
    Evidence,
    Exchange,
    Findings,
    Hypothesis,
    MetricBucket,
    ModelPolicy,
    Reading,
    RecordedPlacement,
    RetrievalChannel,
    RuleReading,
    ToolCall,
    ToolResult,
    ToolResults,
    Turn,
    WorseWhen,
)

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both, where one of the two names has to say which it is.
from argus_core.replay import CallType, Recorder, Replay
from argus_core.replay import nobody as records_nothing
from pydantic import ValidationError

from agent_investigator.budget import (
    Bound,
    Budget,
    InvestigationSettings,
    a_budget_for,
)
from agent_investigator.retrieval import (
    ChangeFetcher,
    DependencyFetcher,
    DeploymentDiffFetcher,
    LogFetcher,
    MetricsFetcher,
    PlacementFetcher,
    RolloutFetcher,
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

You have six ways to read evidence and one way to finish. Ask for whatever \
you need, in whatever order, over whatever windows look worth reading - that \
judgement is the reason you are here rather than a fixed sequence of reads. \
When you have seen enough, call final_answer.

Three of the six answer about something other than a stretch of time, and are \
easy to leave unread for that reason. One says what this service calls and whose \
each of those is. One says what a deployment changed, and it is the answer \
to a question the rest of the evidence cannot settle: a deployment that shipped \
bad code and a deployment that shipped a broken configuration value arrive \
identically and are fixed differently, so where a deployment is your best \
explanation, read what was in it before naming which of the two it was. It takes \
the revision the change channel gave you.

The third says whether the deployment that landed actually finished arriving, \
and it settles a question the change channel cannot even raise. A deploy history \
records syncs that completed; a rollout that stopped part way is in none of \
them, and for as long as it is stopped the service is running two versions at \
once - which fails the requests that cross between them and leaves neither \
revision at fault. So where a deployment precedes the onset, read the rollout \
before you blame the revision it carried. A deployment that converged is an \
answer worth having too: it rules the split out and leaves the revision itself \
as the subject.

One of the series you already have separates two causes that are otherwise \
identical, and it is easy to read past because it is not a symptom. \
`cpu_limit_cores` is the capacity a minute was served with. Held at one value \
across the window, it is capacity the load outgrew; taking more than one value, \
it is a controller that will not settle - and at the bottom of every cycle those \
two agree on the alert, the latency, the traffic and the change channels alike. \
So before naming the load outgrowing a resource, or a resource consumed on its \
own, look at what that series did across the window.

Where the service's replicas run is in front of you too, read once at the \
onset, and it is the only record of a cause nothing deployed. A platform can \
move a replica onto another node with nothing changing in the deploy history, \
the diff or the flags - and where that node carries a different accelerator \
card, the replica can answer differently from the rest without failing or \
slowing: it decides differently. So where the service's answers changed with no \
deployment at the onset, look for a pod marked started at the onset on an \
accelerator the pods serving before it do not run on.

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
cause at all. Being the only thing on offer is not being the best of several: \
a lone explanation nothing in the evidence supports belongs below 0.5, not in \
the middle of the range.

`subject` names the specific thing the cause is about - for a feature flag, \
the flag's own name; for a failure arriving from a service this one depends \
on, that service as the evidence names it - copied verbatim either way. \
Something acts on that name, so a name that is not in the evidence identifies \
nothing.

`from_state` and `to_state` are what that subject moved between, in the words \
the evidence uses - `off` and `on` for a feature flag, two versions for a \
deployment. Both or neither: a cause that is not a change from one state to \
another names no states at all. Do not leave them to be read back out of your \
summary - a sentence that merely uses the word "off" is not a transition, and \
whatever reads it cannot tell the difference.

`faulting_service` is different from all of those, and it is an address rather \
than a description: it names the service that will be acted on. Fill it in when \
the fault is in a service this one calls and the organisation owns - which is \
what `get_service_dependencies` tells you, and the only thing that tells you, \
since a host name is a spelling somebody chose. Name it exactly as the register \
does, because that is the name the platform knows it by. An answer of \
`internal-dependency-failure` naming no service is one nothing can act on; \
every other cause leaves this null, because the service at fault is the one \
that alerted.

Give every explanation the evidence supports, best first. The one you name \
first is tried first, and the rest are tried in turn if it does not help.\
"""

# The read tier's name for the placement tool, which is what the replay log
# files the loop's own read under - the vocabulary a reader of the log counts
# reads by, whichever caller asked.
_PLACEMENTS_TOOL: Final = "get_placements"

_SECONDS_IN_A_MINUTE: Final = 60

logger = logging.getLogger(__name__)


class HowTheMinuteIsKnown(StrEnum):
    """Where the minute an investigation works from came from.

    Three grades rather than measured-or-not, because the model is told a
    different thing in each and the difference is not a caveat. What it is told
    about a measured minute is a departure it can see in the rows below; about a
    stated one, testimony it cannot check; about the third, that the minute dates
    nothing at all and is only where to look from.

    Public because `_the_opening_message` names it in a signature a reader of
    this module has to be able to follow, not because anything outside calls it.
    """

    # The first minute a judged signal departed and stayed departed - derived
    # from the buckets Argus retrieved, and re-derivable by anyone reading the
    # incident.
    MEASURED = "measured"
    # Testimony from whatever raised the alert, for a window in which nothing
    # departs. Checkable against nothing Argus holds, which is exactly why the
    # model is told which of the two it has.
    STATED_BY_THE_ALERT = "stated-by-the-alert"
    # Neither. The window is flat, the alert dated nothing, and what stands in
    # for an onset is the minute the alarm itself fired in. Reached only by an
    # alert reporting a finding no series carries - a flat window under a rule
    # watching a series is a disproof rather than an incident with no date.
    NOTHING_DATES_IT = "nothing-dates-it"

_A_TURN_THAT_ANSWERED_NOTHING: Final = (
    "That turn asked for nothing and answered nothing. Ask for the evidence you need, "
    "or call final_answer with what you have."
)

_ONE_TURN_LEFT: Final = (
    "\n\nThis is your last turn: there is no budget for another retrieval. Answer now, "
    "with final_answer, from what you have already read."
)


def investigate(
    alert: Alert,
    incident_id: str,
    fetch_metrics: MetricsFetcher,
    fetch_logs: LogFetcher,
    fetch_change_events: ChangeFetcher,
    fetch_dependencies: DependencyFetcher,
    fetch_what_a_deployment_changed: DeploymentDiffFetcher,
    fetch_rollout: RolloutFetcher,
    fetch_placements: PlacementFetcher,
    *,
    settings: InvestigationSettings,
    thresholds: AnomalyThresholds,
    converse: Conversation | None = None,
    conversations: Conversations = a_conversation_recorded_for,
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
    speak = converse or conversations(
        incident_id,
        recorder,
        policy=ModelPolicy(
            model=settings.investigation_model,
            effort=settings.investigation_effort,
            brief=BRIEF
        )
    )

    # Read by the loop rather than offered as the first tool call, so that the
    # onset is a measurement instead of a decision. Anchored on the alert
    # rather than bounded, which is what the event says: the span is the
    # metrics tool's own (spec §16), not this loop's to name. Read for the rule
    # that paged, so the onset is measured on the series it fired on as well as
    # on the five.
    narrator.say(
        RetrievalRequested, channel=RetrievalChannel.METRICS, window_start=alert_time
    )

    try:
        metric_buckets = fetch_metrics(alert_time, alert.rule)
    except Exception as unanswered:
        # The one read no channel guard can absorb, because it happens before
        # there is a model to tell. Every window the model could ask for is
        # anchored on an onset, the onset is measured from these minutes, and
        # without them there is nothing to converse about - so this ends where
        # the empty window ends, with one candidate and no turn bought.
        #
        # Said first, though. Letting it out of here ended the walk with nothing
        # anywhere saying which read failed, and the incident's only account of
        # its own first act was the run's failure row.
        logger.warning("metrics could not be read", exc_info=True)
        narrator.say(
            RetrievalUnanswered,
            what_was_asked="the service's metrics",
            because=str(unanswered)
        )

        return _nothing_could_be_read(alert, incident_id, narrator)

    narrator.say(
        MetricsRetrieved,
        window_start=metric_buckets[0].bucket_id if metric_buckets else None,
        window_end=metric_buckets[-1].bucket_id if metric_buckets else None,
        buckets=metric_buckets,
        # Measured here and said here, because the alert's firing time is not in
        # the event and the story is told from the event alone.
        stopped_before_the_alert=_where_the_rows_stop(metric_buckets, alert) is not None
    )
    # One of the two retrievals the dispatcher never sees - the placement is the
    # other - and so one it cannot write down. Recorded here and now rather than at the end of the
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
        response={"buckets": [bucket.model_dump(mode="json") for bucket in metric_buckets]}
    )

    # Measured first, and preferred wherever there is one. A measured onset is
    # evidence - derived from buckets Argus retrieved and re-derivable by anyone
    # reading the incident - where a stated one is testimony from whatever fired
    # the alert. Where both exist they should agree; where they do not, the one
    # that can be checked is the one to keep.
    measured_onset = find_onset(metric_buckets, thresholds)
    stated_onset = _the_onset_the_alert_states(alert)
    onset = measured_onset or stated_onset
    the_window_cannot_contradict_it = _a_flat_window_says_nothing_about(
        alert, metric_buckets
    )

    if onset is None and not the_window_cannot_contradict_it and metric_buckets:
        # The window was read, it holds no departure in any judged signal, and
        # those signals include whatever the rule that fired was watching - the
        # five, or its own series where it named one. So the window is
        # not short of evidence about this alarm - it is evidence against it.
        #
        # A window with no minutes in it is not that, and falls through. The
        # retrieval answered and had nothing to say, which is nearer to not
        # having been able to see than to having seen a well service - and an
        # alarm closed on an empty window would be closed on no evidence.
        return _the_alarm_was_disproven(
            alert, incident_id, metric_buckets, narrator
        )

    if onset is None and the_window_cannot_contradict_it:
        # A rule whose subject this window does not carry, and no date. Nothing
        # here contradicts the alarm, so the investigation goes on - but it has
        # to be anchored on something, and the only minute anybody knows is the
        # one the alarm fired in. That is where to look from and not when this
        # began.
        #
        # Conditioned on the same measurement the branch above is conditioned on
        # the other way round, and the gap between the two is a real case rather
        # than a formality: a series alarm over a window with *no minutes in it*
        # is disproved by nothing and anchored by nothing either. It ends below,
        # where every undated incident ended before any of this - and the one
        # time this condition was missing, that case walked a whole
        # investigation of a service nothing had been read about.
        onset = _the_minute_the_alarm_fired_in(alert)

    if onset is None:
        # Nothing was read beyond the metrics, and nothing was spent. There is
        # also nothing to converse about: every window the model could ask for
        # is anchored on an onset the metrics do not contain, and nothing else
        # has offered one - not even the minute the alarm fired in, which this
        # alert did not say.
        return _nothing_to_say(alert, incident_id, metric_buckets, narrator)

    how_the_minute_is_known = _how_the_minute_is_known(measured_onset, stated_onset)

    narrator.say(OnsetDetected, onset=onset)

    # Read here, after the onset and before the model is asked anything, for the
    # reason the metrics are read above: a pin to a card is decided from it, and
    # what a later node acts on cannot depend on whether the model thought to
    # ask. Against the onset, because which pods started at it is what makes a
    # card a suspect.
    placement = _the_placement_recorded(
        alert.service, onset, fetch_placements, narrator, replay
    )

    # Whether the window says anything at all about the incident's own minutes.
    # Measured here because here is the only place holding both the onset and the
    # buckets, and carried out on the findings because what reads it - the gate
    # deciding whether an action could ever be confirmed - has the onset alone.
    the_incident_was_read = has_a_reading_since(metric_buckets, onset)

    dispatcher = Dispatcher(
        service=alert.service,
        onset=onset,
        alert_time=alert_time,
        # The rule the read above was made for, so the model's own re-read
        # comes back with the same columns rather than without the one this
        # alarm fired on.
        rule=alert.rule,
        settings=settings,
        # The same measurement the findings carry, handed here because it decides
        # a window as well as a gate: where no reading covers the incident's
        # minutes the onset is the last one before the evidence stopped, and what
        # stopped it lies at or after it.
        readings_cover_the_incident=the_incident_was_read,
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
        fetch_change_events=fetch_change_events,
        fetch_dependencies=fetch_dependencies,
        fetch_what_a_deployment_changed=fetch_what_a_deployment_changed,
        fetch_rollout=fetch_rollout
    )
    spend = budget if budget is not None else a_budget_for(settings)
    tools = investigator_tools()
    transcript: list[Exchange] = [
        Ask(text=_the_opening_message(
            alert,
            onset,
            metric_buckets,
            already_refuted or [],
            already_read or [],
            # Asked once, here, where the thresholds are: the message says
            # whether the window opened already elevated, and whether it did is
            # a measurement rather than a thing prose can work out.
            opened_already_elevated=earliest_bucket_is_anomalous(
                metric_buckets, thresholds
            ),
            # Whether the minute above came out of the buckets or out of the
            # alert. The message says which, because the two ask the model for
            # different readings of the same flat rows: evidence it has already
            # seen, or evidence it does not have.
            how_the_minute_is_known=how_the_minute_is_known,
            # The last minute the window carries, where it carries none as late as
            # the alert. A measurement rather than prose for the reason the
            # elevation above is one: the model is told when the alert fired and
            # never what time it is now, so rows that stop early are invisible to
            # it and the gap is Argus's to state.
            rows_stop_at=_where_the_rows_stop(metric_buckets, alert),
            placement=placement
        ))
    ]

    while True:
        try:
            turn = speak(transcript, tools)
        except AnswerTruncated as cut_short:
            # Charged before anything else, because running out of room means
            # the model generated to its cap and was stopped there: the turn
            # carried nothing back and was billed in full for it.
            #
            # Then ended, rather than asked again. A retry here would put the
            # same question to the same evidence - the transcript is
            # unchanged by a turn that carried nothing - through a seam that
            # has no more room to offer it, so it differs from the first
            # attempt only by resampling, and reliably spends another whole
            # cap of output to discover that. When the seam can carry a
            # larger bound, a retry becomes a thing with a mechanism behind
            # it and this is where it goes back.
            spend.record(cut_short.billed)
            logger.warning("answer truncated")

            return replace(
                _cut_short(alert, incident_id, metric_buckets, dispatcher, narrator),
                readings_cover_the_incident=the_incident_was_read,
                placement=placement
            )
        except ModelRefused:
            logger.warning("model declined to answer")

            return replace(
                _declined(alert, incident_id, metric_buckets, dispatcher, narrator),
                readings_cover_the_incident=the_incident_was_read,
                placement=placement
            )

        spend.record(turn)
        transcript.append(turn)

        answered = _the_answer_in(turn, incident_id)
        if isinstance(answered, list):
            for candidate in answered:
                _say_formed(narrator, candidate)

            narrator.say(ChannelsUnread, channels=dispatcher.channels_unread)

            return Findings(
                candidates=answered,
                already_read=dispatcher.readings,
                readings_cover_the_incident=the_incident_was_read,
                placement=placement
            )

        results = [
            *([answered] if answered is not None else []),
            *(dispatcher.dispatch(call) for call in turn.tool_calls if call.name != ANSWER_TOOL)
        ]

        reached = spend.bounds_reached()
        if reached:
            logger.info("investigation ran out of budget",
                        extra={"bounds": [bound.value for bound in reached]})

            return replace(
                _ran_out(
                    alert, incident_id, metric_buckets, reached, dispatcher, narrator
                ),
                readings_cover_the_incident=the_incident_was_read,
                placement=placement
            )

        transcript.append(_what_the_model_is_told_next(results, spend.is_on_its_last_call()))


def _the_placement_recorded(service: str,
                            onset: str,
                            fetch_placements: PlacementFetcher,
                            narrator: Narrator,
                            replay: Replay) -> RecordedPlacement | None:
    """Where the service's pods are running, recorded against the onset - or
    `None` where the platform would not say.

    Said either way, and written down where it answered. Published because it is
    the basis of an action and the one reading nothing else in the record holds;
    filed on the replay because it is a read the dispatcher never sees, as the
    metrics read is.

    `None` and never an empty placement where the read failed. An empty one says
    the service runs on no pod, and a strategy deciding from it finds no replica
    that moved - an outage read as an all-clear. And the investigation goes on
    without it: the placement is evidence for one mode, and a walk that stopped
    for want of it would lose every other.
    """
    try:
        pods = fetch_placements(service)
    except Exception as unanswered:
        logger.warning("placement could not be read", exc_info=True)
        narrator.say(
            RetrievalUnanswered,
            what_was_asked="where the service's replicas run",
            because=str(unanswered)
        )

        return None

    placement = RecordedPlacement(onset=parse_iso(onset), pods=tuple(pods))
    narrator.say(PlacementRecorded, placement=placement)
    replay.record(
        call_type=CallType.MCP,
        target=_PLACEMENTS_TOOL,
        request={"arguments": {"service": service}},
        response={"pods": [pod.model_dump(mode="json") for pod in pods]}
    )

    return placement


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
        logger.warning("answer could not be read", exc_info=True)

        return ToolResult(
            call_id=answering.id,
            content=(
                f"that answer could not be read: {malformed}. Call final_answer again "
                f"with one entry per explanation, each carrying a summary, a failure_mode "
                f"and confidence that are both null or both set, its supporting "
                f"evidence, a subject, and a from_state and to_state that are both "
                f"null or both set."
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

    The two prose fields are put on one line as they are accepted, because both
    are one sentence by definition and the model wraps whichever it happens to
    be writing when its line runs out. Here rather than in a view: this claim
    reaches a page, a postmortem and whoever is paged, and a repair living in
    one of those is missing from the other two.
    """
    return [
        Hypothesis(
            incident_id=incident_id,
            summary=on_one_line(explanation["summary"]),
            failure_mode=explanation["failure_mode"],
            confidence=explanation["confidence"],
            supporting_evidence=[
                _a_cited_fact(cited)
                for cited in explanation.get("supporting_evidence") or []
            ],
            subject=explanation.get("subject"),
            from_state=explanation.get("from_state"),
            to_state=explanation.get("to_state"),
            faulting_service=explanation.get("faulting_service"),
            rank=rank
        )
        for rank, explanation in enumerate(answering.arguments[HYPOTHESES_ARG], start=1)
    ]


def _a_cited_fact(cited: dict[str, Any]) -> Evidence:
    """One piece of evidence, with its claim said as the sentence it is.

    The instant is left exactly as it arrived. It is a value the model copied
    out of a line it retrieved, and pydantic is what decides whether it parses.
    """
    validated = Evidence.model_validate(cited)

    return validated.model_copy(update={"claim": on_one_line(validated.claim)})


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
             narrator: Narrator) -> Findings:
    """The outcome when the budget bound before the model answered.

    Every bound that ran out is named, not the first noticed: two bounds
    binding together is a different account of an investigation than one, and
    which one a human hears about should not depend on the order the checks
    happen to be written in.

    Only ever reached with a bound in hand. A turn the model never finished
    has its own ending below, because it is not a question of affordability
    and a sentence built from the bounds reached would have an empty space
    where the reason belongs.
    """
    spent = ", ".join(bound.value for bound in reached)
    ended = f"the investigation ran out of {spent} before it identified one"
    undetermined = _undetermined(alert, incident_id, ended, metric_buckets)
    _say_formed(narrator, undetermined)
    narrator.say(ChannelsUnread, channels=dispatcher.channels_unread)

    return Findings(candidates=[undetermined], already_read=dispatcher.readings)


def _cut_short(alert: Alert,
               incident_id: str,
               metric_buckets: list[MetricBucket],
               dispatcher: Dispatcher,
               narrator: Narrator) -> Findings:
    """The outcome when the model's turn ran out of room before it finished.

    Its own ending rather than a flag on the out-of-budget one, because it is
    a different account of the same silence: nothing here was too expensive.
    Told that an investigation ran out of budget, a human buys it more and
    gets the identical turn cut off at the identical place.

    Final in the same way a refusal is, and for a related reason. The
    transcript is unchanged by a turn that carried nothing, so a second
    attempt puts the same question to the same evidence; and the seam a loop
    holds carries no larger bound to put it with. What separates the two is
    that a refusal would still be a refusal with more room, and this would
    not - so this is the one that comes back when the seam can say how much
    room to use.

    What was read still comes back, as it does from every other ending here: a
    later round should not pay to read it again on the way to a human.
    """
    undetermined = _undetermined(
        alert,
        incident_id,
        "the model's turn was cut short before it finished, and asking again "
        "would put the same question with no more room to answer it",
        metric_buckets
    )
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


def _a_flat_window_says_nothing_about(alert: Alert,
                                      metric_buckets: list[MetricBucket]) -> bool:
    """Whether this window, flat, would be no evidence about the alarm.

    Two ways it can be. The rule reported a finding of its own, which no series
    carries, so no window could contradict it. Or the rule watches a series of
    its own and the window was read without it - the read tier could not follow
    the rule's query, or the metrics backend answered nothing for it - so the
    window was never shown what the rule saw, and five flat signals say nothing
    about a sixth.

    A window with no minutes in it is not the second case. Nothing was read at
    all, which disproves nothing and anchors nothing, and is told apart from
    both by the caller.
    """
    if alert.claim is AlarmClaim.ITS_OWN_FINDING:
        return True

    return (
        alert.rule is not None
        and bool(metric_buckets)
        and _which_way_the_rules_series_is_worse(metric_buckets) is None
    )


def _the_rule_whose_series_was_not_read(alert: Alert,
                                        metric_buckets: list[MetricBucket]) -> str | None:
    """The rule that paged, where no minute of the window carries its reading.

    `None` where no rule paged, where the rule reported a finding of its own -
    which evaluates no series, so none is missing - or where its series was read,
    which is a window that says what the rule saw.
    """
    if (
        alert.rule is None
        or alert.claim is AlarmClaim.ITS_OWN_FINDING
        or _which_way_the_rules_series_is_worse(metric_buckets) is not None
    ):
        return None

    return alert.rule


def _which_way_the_rules_series_is_worse(metric_buckets: list[MetricBucket]
                                         ) -> WorseWhen | None:
    """The paging rule's direction, as the window's readings of it carry it.

    `None` where no minute carries a reading, which is a window that was read
    for no rule, or for one whose series the read tier could not follow or the
    metrics backend answered nothing for.
    """
    return next(
        (
            bucket.rule_reading.worse_when
            for bucket in metric_buckets
            if bucket.rule_reading is not None
        ),
        None
    )


def _the_minute_the_alarm_fired_in(alert: Alert) -> str | None:
    """The minute the alert went off, as a bucket id, where it says.

    An anchor rather than an onset, and the only thing standing in for one where
    nothing dates the incident at all. A minute is what every window here is
    anchored on, so an investigation with no minute cannot ask for anything -
    and the alarm's own firing is the one minute somebody actually recorded.

    `None` where the alert did not say when it fired, which leaves an
    investigation with nothing to work from and ends it where the ordinary
    undated incident ends.
    """
    return to_iso_minute(alert.started_at) if alert.started_at is not None else None


def _how_the_minute_is_known(measured_onset: str | None,
                             stated_onset: str | None) -> HowTheMinuteIsKnown:
    """Which of the three the minute in hand came from.

    Read off the two candidates rather than carried alongside them, so that the
    answer cannot disagree with the minute it describes: a flag set at one branch
    and a minute chosen at another is two facts that can come apart.
    """
    if measured_onset is not None:
        return HowTheMinuteIsKnown.MEASURED

    if stated_onset is not None:
        return HowTheMinuteIsKnown.STATED_BY_THE_ALERT

    return HowTheMinuteIsKnown.NOTHING_DATES_IT


def _the_onset_the_alert_states(alert: Alert) -> str | None:
    """When the alert says the incident began, where it says anything at all.

    Almost every alert says nothing, and that silence is the normal case rather
    than a gap: a rule watching a series is reporting a departure the loop
    measures for itself, in minutes it has in front of it.

    An alert speaks here only where it knows something no series carries. A
    check that reconciles stored values against the records behind them finds
    what went wrong long after the writing did, and dates it from the oldest
    record it found wrong - a minute nothing marks, because nothing failed and
    nothing slowed. Read rather than derived from `started_at` for exactly that
    reason: that is when somebody noticed, and the two can differ by a week.
    """
    return to_iso(alert.stated_onset) if alert.stated_onset is not None else None


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


def _the_alarm_was_disproven(alert: Alert,
                             incident_id: str,
                             metric_buckets: list[MetricBucket],
                             narrator: Narrator) -> Findings:
    """The outcome when the window contradicts what the alarm claimed.

    A third shape beside `_nothing_to_say` and `_nothing_could_be_read`, and the
    reason the three are separate is the reason those two are: they are different
    claims about the service. One says Argus could not work out what is wrong;
    one says Argus could not see; this says there is nothing wrong, and the rule
    that said otherwise was looking at a series that never moved.

    Reached only for a rule watching such a series. A rule reporting a finding no
    series carries is not contradicted by a flat window and never arrives here,
    and nor is a rule whose own series the window was read without.

    The signals named are the ones this window was judged on: the five, and the
    rule's own series wherever the window carries it.

    It still carries an undetermined candidate, because `Findings.candidates` is
    never empty and a reader walking the candidates should find the account there
    like any other. What makes this ending its own is the disproof beside them.
    """
    disproof = Disproof(
        signals_judged=signals_judged_in(metric_buckets),
        earliest_minute=metric_buckets[0].bucket_id,
        latest_minute=metric_buckets[-1].bucket_id,
        minutes_judged=len(metric_buckets)
    )
    undetermined = _undetermined(
        alert,
        incident_id,
        (
            f"the alarm reported a condition on a series, and no minute of the "
            f"{disproof.minutes_judged} read between {disproof.earliest_minute} "
            f"and {disproof.latest_minute} departs from the service's baseline in "
            f"any of {', '.join(disproof.signals_judged)} - so what fired is the "
            f"rule rather than the service"
        ),
        metric_buckets
    )
    _say_formed(narrator, undetermined)

    return Findings(
        candidates=[undetermined], already_read=[], disproof=disproof
    )


def _nothing_could_be_read(alert: Alert,
                           incident_id: str,
                           narrator: Narrator) -> Findings:
    """The outcome when the metrics could not be read at all.

    The same shape as `_nothing_to_say` above and deliberately not the same
    sentence. That one reports a window that was read and held no incident; this
    reports a window nobody could ask about, and the two are opposite claims
    about the service - one says it is well, the other says nothing about it. A
    reader handed "no metrics were retrieved" for this would go looking for a
    shop that turned out fine.

    No buckets, because there are none: the account carries what was read, and
    nothing was.
    """
    undetermined = _undetermined(
        alert,
        incident_id,
        (
            "the service's metrics could not be read, so nothing here says "
            "whether any minute departed from its baseline - which is not the "
            "same as none having departed"
        ),
        []
    )
    _say_formed(narrator, undetermined)

    return Findings(candidates=[undetermined], already_read=[])


def _undetermined(alert: Alert,
                  incident_id: str,
                  reason: str,
                  metric_buckets: list[MetricBucket]) -> Hypothesis:
    """The honest outcome: no cause, and no confidence to go with it.

    Carries no `failure_mode` and no `confidence` at all - a hypothesis refuses
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
        failure_mode=None,
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
        failure_mode=hypothesis.failure_mode,
        confidence=hypothesis.confidence,
        subject=hypothesis.subject,
        from_state=hypothesis.from_state,
        to_state=hypothesis.to_state,
        rank=hypothesis.rank,
        evidence=hypothesis.supporting_evidence
    )


def _the_opening_message(alert: Alert,
                         onset: str,
                         metric_buckets: list[MetricBucket],
                         already_refuted: Sequence[Attempt],
                         already_read: Sequence[Reading],
                         opened_already_elevated: bool,
                         how_the_minute_is_known: HowTheMinuteIsKnown,
                         rows_stop_at: str | None = None,
                         placement: RecordedPlacement | None = None) -> str:
    """Everything about *this incident* the model is told before it decides.

    This incident, and nothing standing. What the Investigator is and what its
    tools are for is `BRIEF`, and that travels as the request's `system` rather
    than at the top of this message - see `ModelPolicy.brief`. The split is not
    tidiness: it is what lets the unchanging half be read from cache on every
    incident after the first, and what stops an operator's instructions sharing
    a channel with the evidence they are used to judge.

    The onset is stated as a fact rather than offered as a question, and where
    it is only a lower bound that is said plainly - a model that does not know
    its window may have opened mid-incident cannot know to reach further back,
    and confidence will not tell it: it cannot miss what it was never shown.

    `how_the_minute_is_known` says whether that fact was measured, stated by the
    alert, or neither - and the paragraph changes rather than gaining a caveat. An
    unmeasured onset comes with a window in which nothing departs, and a model
    reading flat rows under a sentence about a measured departure has been handed
    a contradiction to resolve on its own - which it resolves, reasonably, by
    concluding the service is well and there is nothing here. So the flatness is
    named as the shape of the fault, in the same breath as the minute it cannot be
    seen at.
    """
    said = [
        "## Alert",
        f"service: {alert.service}",
        f"name: {alert.alert_name}",
        f"severity: {alert.severity or 'unspecified'}",
        f"fired at: {to_iso(alert.started_at) if alert.started_at else 'unspecified'}",
        f"summary: {alert.summary or 'none given'}",
        "",
        "## Onset",
        _the_onset_paragraph(
            alert, onset, how_the_minute_is_known, rows_stop_at,
            _the_rule_whose_series_was_not_read(alert, metric_buckets)
        )
    ]

    if opened_already_elevated:
        said.append(
            "The metrics window opens already elevated, so that minute is a lower "
            "bound rather than the onset itself - the incident began before anything "
            "retrievable, and a window anchored on it may not contain the cause."
        )

    # What the rows below are evidence *of*, which is not the same question in
    # the two cases. Where the onset was measured they are what it was measured
    # from; where it was stated they are what says the flatness is real, and a
    # model told they are the minutes a departure was found in would be reading
    # rows that contradict the sentence above them.
    said.extend([
        "",
        "## Per-minute metrics",
        f"One row per minute, in time order, comma-separated under the header. "
        f"{_what_the_rows_are(how_the_minute_is_known, rows_stop_at)} An empty cell is a "
        f"reading this service does not have at all, which is not the same as a "
        f"reading of zero."
    ])

    worse_when = _which_way_the_rules_series_is_worse(metric_buckets)
    if worse_when is not None:
        # Said once, here, rather than carried in every row: a column the model
        # cannot place is a number with no meaning, and the one thing its values
        # cannot say for themselves is which way the rule calls worse. Above the
        # rows rather than after them, where it would read as one more row.
        rule_named = (
            f"the rule that paged ({alert.rule})" if alert.rule else "the rule that paged"
        )
        said.append(
            f"rule_reading is the series {rule_named} evaluates, and that rule calls "
            f"it worse when {worse_when} its threshold. A departure in it is a "
            f"departure in exactly what paged, even where every other column is flat."
        )

    said.append(_the_minutes_as_rows(metric_buckets))

    if placement is not None:
        said.extend(["", "## Where the replicas run", *_the_placement_as_lines(placement)])

    if already_refuted:
        said.extend([
            "",
            "## Already tried",
            "Argus took these actions on this incident and undid each one. The service "
            "did not return to its baseline after any of them.",
            *(
                f"- {_what_was_done_in(attempt)} at {attempt.occurred_at}: "
                f"the service did not recover"
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


def _the_placement_as_lines(placement: RecordedPlacement) -> list[str]:
    """Each pod on a line of its own, marked where it started at the onset.

    One line per pod because the mark is a claim about one pod: said anywhere in
    a paragraph, it would be true of whichever pod a reader guessed. The rule
    deciding which pods carry it is `RecordedPlacement`'s, so the message marks
    the pods the timeline and the strategy mark.

    A node whose card the platform does not report is said to have none rather
    than left blank, because blank reads as a card nobody wrote down.
    """
    at_the_onset = placement.started_at_the_onset()

    return [
        "Each of the service's pods as the platform placed it, read at the onset: "
        "the node it runs on, the accelerator card that node carries, and when the "
        "pod started. A pod marked started at the onset was placed within a minute "
        "of the incident beginning, or since, and has only ever served during it.",
        *(
            f"- {pod.pod} on {pod.node} "
            f"({pod.accelerator or 'no accelerator reported'}), "
            f"started {to_iso(pod.started_at)}"
            f"{' - started at the onset' if pod in at_the_onset else ''}"
            for pod in placement.pods
        )
    ]


def _where_the_rows_stop(metric_buckets: list[MetricBucket],
                         alert: Alert) -> str | None:
    """The window's last minute, where the window ends before the alert fired.

    `None` for every window that runs on to the alert, which is every window a
    service still reporting produces - so the sentences this selects are reached
    only by a service that stopped, and no existing incident's message moves.

    Measured against the alert rather than against the onset, because what makes
    the stopping legible is the distance from something the model was given. The
    onset is the other end of the same gap and tells it nothing it does not
    already have.
    """
    if not metric_buckets or alert.started_at is None:
        return None

    last_minute = metric_buckets[-1].bucket_id

    return last_minute if last_minute < to_iso_minute(alert.started_at) else None


def _the_onset_paragraph(alert: Alert,
                         onset: str,
                         how_the_minute_is_known: HowTheMinuteIsKnown,
                         rows_stop_at: str | None,
                         unread_rule: str | None) -> str:
    """What the model is told about the minute it is working from.

    Four cases, and each of the last three is one a model gets wrong unprompted.
    A measured onset is evidence the model can see for itself. A stated onset over
    a window that was read throughout is testimony about rows that are all present
    and all flat. A stated onset over a window whose rows *stop* is testimony about
    rows that are not there - and the rows that are there describe the time before
    the fault, which is exactly what makes them misleading.

    The fourth is the minute the alarm fired in, standing in for an onset nobody
    has. It is the only case where the minute given is not a claim about when
    anything began, and a model told it plainly as an onset would date the
    incident from the moment somebody noticed - then look for a change there and
    find the one that was deploying while the alarm went off. Its last sentence
    says why nothing dates it, which `unread_rule` decides: a rule whose own
    series the window lacks, or something that knows what no series carries.

    The first two are left as they were. Every incident built before a window
    could stop walks one of them, and the flat wording was written for a window
    that is flat.
    """
    if how_the_minute_is_known is HowTheMinuteIsKnown.MEASURED:
        return (
            f"The incident began at {onset}, measured from the per-minute metrics "
            f"below: it is the first minute that departs from the service's own "
            f"baseline and stays departed."
        )

    if how_the_minute_is_known is HowTheMinuteIsKnown.NOTHING_DATES_IT:
        return (
            f"Nothing dates this incident. No series departs from its baseline "
            f"anywhere in the window below, and whatever raised this did not say "
            f"when it began - so {onset} is the minute the alarm fired in and is "
            f"where to look from, not when anything started. Do not treat it as "
            f"the onset and do not reach for a change at it: a change in that "
            f"minute is a change that happened while somebody was being paged. "
            f"{_what_raised_it(unread_rule)}"
        )

    if rows_stop_at is not None:
        return (
            f"The incident began at {onset}, stated by the alert rather than "
            f"measured, and the metrics below stop at {rows_stop_at} - "
            f"{_how_far_apart(rows_stop_at, alert)}. Nothing covers the minutes "
            f"between, so the rows below describe the service before this began and "
            f"say nothing whatever about it. That the rows stop is what was alerted "
            f"on: read it as the service having gone unreported rather than as a "
            f"window that is merely short, and expect the cause at the minute they "
            f"stop rather than at the minute the alert fired."
        )

    return (
        f"The incident began at {onset}, stated by the alert rather than measured: "
        f"no series departs from its baseline anywhere in the window below, so the "
        f"metrics carry no evidence about this incident at all. Read that flatness "
        f"as the shape of the fault rather than as the service being well - "
        f"whatever raised this knows something no series does, and the minute it "
        f"gives is long before the alert fired. The change that caused it is at "
        f"that minute, not at this one."
    )


def _what_raised_it(unread_rule: str | None) -> str:
    """Why nothing in the window dates the incident, said of whatever paged.

    Two different absences. A check's own finding knows something no series
    carries, so the metrics were never going to show it. A rule watching a
    series fired on a series this window lacks, so the departure is real and
    simply out of sight - and a model told the first of a case that is the
    second stops looking at the metrics for the one thing they would show.
    """
    if unread_rule is not None:
        return (
            f"It was raised by the rule {unread_rule}, which watches a series of "
            f"its own, and that series could not be read - it is not among the rows "
            f"below. Whatever departed is in that series, and how long it had been "
            f"departed before anybody looked is not in any of the evidence."
        )

    return (
        "What raised this knows something no series does, and how long it had "
        "been true before anybody looked is not in any of the evidence."
    )


def _how_far_apart(rows_stop_at: str, alert: Alert) -> str:
    """The distance from the last row to the alert, said in minutes.

    Worked out here because Argus holds both figures and the model holds one: it
    is told when the alert fired and never what time it is now, so the rows
    stopping early is invisible to it as arithmetic. The same reason the window's
    opening elevation is measured and passed in rather than described.
    """
    if alert.started_at is None:
        return "and the alert does not say when it fired"

    minutes = int(
        (alert.started_at - parse_iso(rows_stop_at)).total_seconds() // _SECONDS_IN_A_MINUTE
    )

    return (
        f"the alert fired at {to_iso(alert.started_at)}, {minutes} minute"
        f"{'' if minutes == 1 else 's'} later"
    )


def _what_the_rows_are(how_the_minute_is_known: HowTheMinuteIsKnown,
                       rows_stop_at: str | None) -> str:
    """What the rows below are evidence *of*, which is three questions not one.

    The sentence this replaces told a model over any unmeasured window that
    none of the rows departs and that there is no more of the channel to ask for.
    Both are true of a flat window. Over a window that stops, the first is
    vacuously true of the minutes that are present and silent about the ones that
    are not, and the second is said about the one channel whose return is what
    ends the incident.

    A window under an undated finding is the flat case, and deliberately not a
    fourth sentence. What differs there is what the minute *means*, which the
    onset paragraph says; what the rows are is the same thing it is whenever a
    window is flat and present throughout.
    """
    if how_the_minute_is_known is HowTheMinuteIsKnown.MEASURED:
        return (
            "These are the minutes the onset was measured from, and they are the "
            "whole span the metrics source keeps - there is no more of this channel "
            "to ask for."
        )

    if rows_stop_at is not None:
        return (
            f"These are the minutes the service reported before it stopped "
            f"reporting, and none of the minutes it does carry departs from its "
            f"baseline - which says the service was well up to {rows_stop_at} and "
            f"says nothing at all about the minutes after it, because there are no "
            f"rows for them. What is missing here is whole minutes rather than "
            f"readings within a minute."
        )

    return (
        "These are what the service reported around the alert, and none of them "
        "departs from its baseline, and they are the whole span the metrics source "
        "keeps - there is no more of this channel to ask for."
    )


def _the_minutes_as_rows(metric_buckets: list[MetricBucket]) -> str:
    """The window as a header and a row per minute, rather than an object each.

    Every reading of every minute still goes in front of the model - what
    changes is that each is labelled once for the window instead of once for
    the minute. Over a full three-hundred-and-sixty-minute window that is the
    difference between 59,468 tokens and 17,057, and none of it is
    information: the field names are four fifths of the payload, and the
    readings they label are the fifth worth sending. It is also the largest
    thing in an opening message, resent on every turn of the conversation, so
    what it costs is paid once per turn rather than once per investigation.

    The fields are taken from the model rather than listed here, so a reading
    added to a bucket arrives in the header without anyone remembering this.
    An absent reading is an empty cell and a zero is a zero, which the prose
    above says plainly: a service consulting no cache has no hit ratio, and a
    cache answering nothing has one of zero, and a reader that could not tell
    them apart would diagnose the second as the first.

    The rule's reading is the one field left out when no minute carries it. It
    is not a measurement of the service a deployment may lack, as the hit ratio
    is, but what the paging rule evaluates - and a window read for no rule has
    no such column to report empty. Where it is present its cell is the value
    alone: the direction is the same on every minute, and is said once beside
    the rows rather than in each of them.
    """
    fields = [
        field
        for field in MetricBucket.model_fields
        if field != RULE_READING_FIELD
        or _which_way_the_rules_series_is_worse(metric_buckets) is not None
    ]
    rows = [
        ",".join(_the_cell(getattr(bucket, field)) for field in fields)
        for bucket in metric_buckets
    ]

    return "\n".join([",".join(fields), *rows])


def _the_cell(reading: object) -> str:
    """One reading as a row writes it: empty where there is none, and a rule's
    reading as the number its rule compares."""
    if reading is None:
        return ""

    if isinstance(reading, RuleReading):
        return str(reading.value)

    return str(reading)


def _what_was_done_in(attempt: Attempt) -> str:
    """One earlier attempt, in the vocabulary of the kind of thing it was.

    Every attempt used to be rendered as "set <subject> on/off", which is true
    of a flag and false of everything else. Told that a heap had been set off, a
    real investigation reasoned about the switch: it proposed that a toggle had
    been flipped, found no record of one, and spent a round of its budget on a
    cause that had never existed. A model reasons about the action it is told
    about, so the line has to describe the action that was taken.
    """
    kind = attempt.identity.action_type
    subject = attempt.identity.subject

    if kind == REVERT_FEATURE_FLAG:
        return f"set {subject} {'on' if attempt.enabled else 'off'}"

    if kind == RESTART_SERVICE:
        return f"restarted {subject}"

    if kind == ROLL_BACK_DEPLOYMENT:
        return f"rolled {subject} back to the revision it ran before"

    if kind == SCALE_OUT:
        return f"scaled {subject} out"

    if kind == PIN_AUTOSCALER:
        return f"stopped {subject}'s autoscaler scaling it down"

    if kind == DISCARD_CACHE_ENTRIES:
        # Copies thrown away, never data cleared or deleted. Told the latter, a
        # model reasons about what is missing from the shop - where the records
        # behind those figures never moved and the next read of each one works it
        # out again. It also has to be able to reason about what the attempt
        # argues: stale copies already discarded, and the figures still
        # disagreeing, is evidence against a divergence being the cause.
        return f"discarded {subject}'s stale cached figures"

    if kind == PIN_TO_ACCELERATOR:
        return f"held {subject}'s pods to one accelerator card"

    assert_never(kind)
