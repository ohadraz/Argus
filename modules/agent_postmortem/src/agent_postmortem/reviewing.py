"""Google's five review criteria, as far as a document can check itself.

Three are about what the document holds, and are checked here against it. Two -
every action item owned and dated, and the document reviewed and shared - are
things people do after it is written, and are left to them: `met` is `None`
rather than `False`, because a box that is always unticked teaches its reader
to stop looking at the boxes.

The criteria are stored by name, so the names are the stored vocabulary - the
page shows them as written here.
"""

from __future__ import annotations

from typing import Final

from argus_core.models import (
    PostmortemDocument,
    Refusal,
    ReviewCriterion,
    TimelineMarker,
    Verdict,
    why_it_was_refused,
)

from agent_postmortem.sections import is_a_code_reading, was_never_tried

KEY_DATA_COLLECTED: Final = "Key incident data collected"
IMPACT_ASSESSED: Final = "Impact assessed"
ANALYSIS_COMPLETE: Final = "Root-cause analysis complete"
ITEMS_OWNED_AND_DATED: Final = "Every action item owned and dated"
REVIEWED_AND_SHARED: Final = "Reviewed and shared"


def review_of(document: PostmortemDocument,
              faults: list[str],
              *,
              reaches_a_cause: bool,
              rests_on_an_unrun_reading: bool | None = None) -> list[ReviewCriterion]:
    """The five criteria, in Google's order, judged against `document`.

    `faults` are what the checks still found in the model's answer. They bear
    on the analysis alone: the timeline and the figures are written by code,
    and an answer that misspoke does not make them any less collected.

    `reaches_a_cause` is the answer's own word on its chain - whether it says
    why the change that set the incident off broke the service. Nothing in the
    document as written says so: a rollback confirms the change and stops there.

    An analysis that reaches its cause through a step resting on a reading of
    the source alone is left for a person, and says what they would do: nothing
    ran the reading, so the document calls the cause unverified, and a ticked
    box beside it would say the opposite. Not failed either - the analysis went
    as far as the evidence allowed, and what is left is somebody running it.

    Whether it does is `rests_on_an_unrun_reading`, the answer's own word: a
    reading cited beside a line showing the error still carries the mechanism
    alone, and only a reader of both can tell. `None` is an answer recorded
    before the question was asked, and is judged as it always was - on a step
    citing readings and nothing else.

    So is one that confirmed nothing only because the one test of its cause was
    refused at the gate as not Argus's to take, and impact whose loss was
    measured but whose end nothing could measure: a cross means the document
    fell short where Argus could have done more, and here the next step is a
    person's - which is what each says.
    """
    short = _what_the_analysis_lacks(document, faults, reaches_a_cause=reaches_a_cause)
    unrun = (_the_readings_it_rests_on(document, rests_on_an_unrun_reading)
             if not short else [])

    if unrun:
        analysis = ReviewCriterion(criterion=ANALYSIS_COMPLETE, met=None,
                                   because=_what_would_confirm(document, unrun))
    elif NONE_TRIED in short and (held := _the_leader_s_refusal(document)) is not None:
        because = _what_would_confirm_a_held_test(document, held)
        analysis = (ReviewCriterion(criterion=ANALYSIS_COMPLETE, met=None, because=because)
                    if short == [NONE_TRIED]
                    else _a_criterion(ANALYSIS_COMPLETE,
                                      [because if lack == NONE_TRIED else lack
                                       for lack in short]))
    else:
        analysis = _a_criterion(ANALYSIS_COMPLETE, short)

    return [
        _the_key_data_collected(document),
        _the_impact_assessed(document),
        analysis,
        ReviewCriterion(criterion=ITEMS_OWNED_AND_DATED, met=None),
        ReviewCriterion(criterion=REVIEWED_AND_SHARED, met=None)
    ]


# The refusals that hold the leading candidate's test back at a boundary of
# Argus's, each said in its own sentence - the refusals send a reader to
# different people, and one sentence for all of them misstates most. Not
# `NO_MITIGATION_PROPOSED`, which is evidence missing - an analysis short of
# what it needed - nor `ALREADY_TRIED_ENOUGH`, which follows a test rather than
# standing in for one.
_HELD_AT_A_BOUNDARY: Final = frozenset({
    Refusal.WOULD_UNDO_A_MEANT_CHANGE,
    Refusal.NOT_A_GENERIC_MITIGATION,
    Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH,
    Refusal.SOMEBODY_ELSES_SERVICE,
    Refusal.NOTHING_COULD_CONFIRM_IT
})

NONE_TRIED: Final = "no candidate was confirmed - none was tried"


def _the_leader_s_refusal(document: PostmortemDocument) -> Refusal | None:
    """The refusal that held the leading candidate's test back at a boundary,
    or `None` where it was not held back at one.

    The first refusal: the walk takes the candidates best first, so where
    nothing was tried the first one the gate refused was the leader's. A later
    candidate held back does not make the leader's own refusal any less what
    it was.
    """
    refused = next((step.refused for step in document.resolution if step.refused), None)

    return refused if refused in _HELD_AT_A_BOUNDARY else None


def _what_would_confirm_a_held_test(document: PostmortemDocument, held: Refusal) -> str:
    """Why the leader's test was held back, in that refusal's words, and the
    item the next step is done under: the recommended action, where the test
    itself is what was recommended, and the proposed fix, which would confirm
    the cause, where there is one."""
    said = why_it_was_refused(held)
    recommended = (_the_item_saying(document, document.recommended_action)
                   if held is Refusal.NOTHING_COULD_CONFIRM_IT else None)
    if recommended:
        said = f"{said} ({recommended})"

    fix = _the_fix_s_item(document)

    # The candidate by name: a bare "it" takes its meaning from the refusal's
    # sentence before it, which ends on the failure or the action.
    return f"{said}; the proposed fix would confirm the candidate ({fix})" if fix else said


def _the_item_saying(document: PostmortemDocument, text: str | None) -> str | None:
    """The number of the action item saying `text`, or `None` where none does."""
    return next((item.number for item in document.action_items
                 if text is not None and item.text == text), None)


def _the_impact_assessed(document: PostmortemDocument) -> ReviewCriterion:
    """Impact assessed: met where the loss is estimated and the end measured,
    or where the alarm was disproven and there was none;
    left to a person where the loss is and the end could not be - nothing
    measured the service back, and nothing will until a person reports it or
    the metrics resume; and not met, saying why, otherwise."""
    lacks = _what_the_impact_lacks(document)
    if document.customer_loss_estimate is None or not lacks:
        return _a_criterion(IMPACT_ASSESSED, lacks)

    stopped = any(entry.marker is TimelineMarker.METRICS_STOP for entry in document.timeline)
    end = ("how long the metrics stay missing is known once they resume" if stopped
           else "when the service is back to normal is for a person to report")

    return ReviewCriterion(criterion=IMPACT_ASSESSED, met=None,
                           because=f"the loss is measured to the close; {end}")


def _a_criterion(criterion: str, lacks: list[str]) -> ReviewCriterion:
    """A criterion the document checks itself on: met where it lacks nothing,
    and otherwise not met, saying what it lacks - a cross with nothing under it
    says only that something somewhere fell short."""
    return ReviewCriterion(criterion=criterion, met=not lacks,
                           because="; ".join(lacks) if lacks else None)


def _the_readings_it_rests_on(document: PostmortemDocument,
                              rests_on_an_unrun_reading: bool | None) -> list[str]:
    """The readings of the source the cause rests on, where it rests on one
    nothing ran: every one the chain cites where the answer says so, none where
    it says not, and those a step cites alone where it never said."""
    if rests_on_an_unrun_reading is None:
        return _readings_resting_alone(document)

    if not rests_on_an_unrun_reading:
        return []

    return list(dict.fromkeys(cited.label
                              for step in document.causal_chain
                              for cited in step.cites
                              if is_a_code_reading(cited.label)))


def _readings_resting_alone(document: PostmortemDocument) -> list[str]:
    """The labels of the readings of the source some step of the chain rests on
    and on nothing else, in the order the chain cites them.

    Any step rather than the deepest: the chain runs from the symptom down, and
    its last step is often the change that set it off, which is well evidenced -
    the mechanism is in the steps above it. A step citing a reading beside
    something observed rests on more than the reading.
    """
    return list(dict.fromkeys(
        cited.label
        for step in document.causal_chain
        if step.cites and all(is_a_code_reading(cited.label) for cited in step.cites)
        for cited in step.cites))


def _what_would_confirm(document: PostmortemDocument, readings: list[str]) -> str:
    """What the cause rests on, and - where a fix was proposed - what would
    confirm it and the item a person does it under."""
    rests = f"the cause rests on {', '.join(readings)}, a reading of the source nothing ran"
    item = _the_fix_s_item(document)

    if item is None:
        return rests

    return (f"{rests}; running the proposed fix's tests against the current code would "
            f"confirm it ({item})")


def _the_fix_s_item(document: PostmortemDocument) -> str | None:
    """The number of the action item the proposed fix is done under, or `None`
    where no fix was proposed or no item tracks it."""
    fix = document.pull_request

    return next((item.number for item in document.action_items
                 if fix is not None and item.tracking == fix.url), None)


# Why the key data is left to a person where no minute of the metrics came
# back: Argus can collect no more of a window that came back empty, and the
# next step is a person's. Nothing of the deploys or the logs, which an alert
# dating its own onset still has read, and which the document lists anyway.
_NOTHING_CAME_BACK: Final = ("no minute of metrics came back for the incident window; collecting "
                             "them is for a person")


def _the_key_data_collected(document: PostmortemDocument) -> ReviewCriterion:
    """Key incident data collected: met where the document lacks nothing; left
    to a person where all it lacks is a window that came back empty, which
    Argus can collect no more of; and not met, saying why, otherwise."""
    lacks = _what_the_key_data_lacks(document)
    if document.impact is None or document.impact.metrics_read:
        return _a_criterion(KEY_DATA_COLLECTED, lacks)

    if lacks:
        return _a_criterion(KEY_DATA_COLLECTED, [*lacks, _NOTHING_CAME_BACK])

    return ReviewCriterion(criterion=KEY_DATA_COLLECTED, met=None, because=_NOTHING_CAME_BACK)


def _what_the_key_data_lacks(document: PostmortemDocument) -> list[str]:
    """A timeline to read, and nothing in the cause resting on nothing."""
    return [*(["there is no timeline"] if not document.timeline else []),
            *(["a step of the causal chain cites nothing"]
              if not all(step.cites for step in document.causal_chain) else []),
            *(["something the causal chain ruled out cites nothing"]
              if not all(ruled.cites for step in document.causal_chain
                         for ruled in step.ruled_out) else [])]


def _what_the_impact_lacks(document: PostmortemDocument) -> list[str]:
    """What it cost, and when it stopped costing. A duration with no end is a
    lower bound, and a lower bound is impact not yet measured.

    Nothing, for a disproven alarm: there was no incident to cost or to see
    end, and that is the assessment."""
    if document.disproven_at is not None:
        return []

    ended = any(entry.marker is TimelineMarker.IMPACT_ENDS for entry in document.timeline)
    # Where the metrics stopped, the end is unknown because nothing measured
    # it - not because the service was seen staying broken.
    stopped = any(entry.marker is TimelineMarker.METRICS_STOP for entry in document.timeline)
    unended = ("the metrics stopped, so the service was never measured back to normal"
               if stopped else "the service was never seen back to normal")

    return [*(["no loss was estimated"] if document.customer_loss_estimate is None else []),
            *([unended] if not ended else [])]


def _what_the_analysis_lacks(document: PostmortemDocument, faults: list[str], *,
                             reaches_a_cause: bool) -> list[str]:
    """Nothing left wrong with the answer, more than one step, a cause
    confirmed, and a chain reaching past the change that set it off - in that
    order. One step is the symptom restated; the analysis is the steps below
    it. A chain ending on a cause nothing confirmed is a document saying,
    rightly, that the cause is not confirmed, and a ticked box beside it would
    say the opposite."""
    results = [hypothesis.result for hypothesis in document.hypotheses]

    return [*(["the answer still had faults the checks found"] if faults else []),
            *(["the causal chain stops at the symptom"] if len(document.causal_chain) <= 1
              else []),
            *([_why_nothing_was_confirmed(results)] if Verdict.CONFIRMED not in results else []),
            *([_where_the_chain_stops(document)] if not reaches_a_cause else [])]


def _where_the_chain_stops(document: PostmortemDocument) -> str:
    """That the chain reaches no cause - past the change that set the incident
    off, where the document established one. Where it established none there is
    no such change to reach past, and a line naming one would contradict the
    trigger section saying so."""
    if document.trigger is None:
        return "the chain does not reach a cause"

    return "the chain does not reach a cause beyond the change that set it off"


def _why_nothing_was_confirmed(results: list[str]) -> str:
    """That no candidate was confirmed, and - where it can say - why: none was
    tried, or every one tried was refuted. A candidate stopped, escalated or
    left with no verdict was tried all the same, and came to neither."""
    tried = [result for result in results if not was_never_tried(result)]
    if not tried:
        return NONE_TRIED
    if all(result == Verdict.REFUTED for result in tried):
        return "no candidate was confirmed - those tried were refuted"
    return "no candidate was confirmed"
