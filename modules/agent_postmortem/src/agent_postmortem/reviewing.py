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

from argus_core.models import PostmortemDocument, ReviewCriterion, TimelineMarker, Verdict

from agent_postmortem.sections import CODE_READING_PREFIX, NEVER_TRIED

KEY_DATA_COLLECTED: Final = "Key incident data collected"
IMPACT_ASSESSED: Final = "Impact assessed"
ANALYSIS_COMPLETE: Final = "Root-cause analysis complete"
ITEMS_OWNED_AND_DATED: Final = "Every action item owned and dated"
REVIEWED_AND_SHARED: Final = "Reviewed and shared"


def review_of(document: PostmortemDocument,
              faults: list[str],
              *,
              reaches_a_cause: bool) -> list[ReviewCriterion]:
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
    """
    short = _what_the_analysis_lacks(document, faults, reaches_a_cause=reaches_a_cause)
    unrun = _readings_resting_alone(document) if not short else []

    return [
        _a_criterion(KEY_DATA_COLLECTED, _what_the_key_data_lacks(document)),
        _a_criterion(IMPACT_ASSESSED, _what_the_impact_lacks(document)),
        (ReviewCriterion(criterion=ANALYSIS_COMPLETE, met=None,
                         because=_what_would_confirm(document, unrun)) if unrun
         else _a_criterion(ANALYSIS_COMPLETE, short)),
        ReviewCriterion(criterion=ITEMS_OWNED_AND_DATED, met=None),
        ReviewCriterion(criterion=REVIEWED_AND_SHARED, met=None)
    ]


def _a_criterion(criterion: str, lacks: list[str]) -> ReviewCriterion:
    """A criterion the document checks itself on: met where it lacks nothing,
    and otherwise not met, saying what it lacks - a cross with nothing under it
    says only that something somewhere fell short."""
    return ReviewCriterion(criterion=criterion, met=not lacks,
                           because="; ".join(lacks) if lacks else None)


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
        if step.cites and all(_is_a_reading(cited.label) for cited in step.cites)
        for cited in step.cites))


def _is_a_reading(label: str) -> bool:
    return label.startswith(CODE_READING_PREFIX) and label[len(CODE_READING_PREFIX):].isdigit()


def _what_would_confirm(document: PostmortemDocument, readings: list[str]) -> str:
    """What the cause rests on, and - where a fix was proposed - what would
    confirm it and the item a person does it under."""
    rests = f"the cause rests on {', '.join(readings)}, a reading of the source nothing ran"
    fix = document.pull_request
    item = next((item.number for item in document.action_items
                 if fix is not None and item.tracking == fix.url), None)

    if item is None:
        return rests

    return (f"{rests}; running the proposed fix's tests against the current code would "
            f"confirm it ({item})")


def _what_the_key_data_lacks(document: PostmortemDocument) -> list[str]:
    """A timeline to read, and nothing in the cause resting on nothing."""
    return [*(["there is no timeline"] if not document.timeline else []),
            *(["a step of the causal chain cites nothing"]
              if not all(step.cites for step in document.causal_chain) else [])]


def _what_the_impact_lacks(document: PostmortemDocument) -> list[str]:
    """What it cost, and when it stopped costing. A duration with no end is a
    lower bound, and a lower bound is impact not yet measured."""
    ended = any(entry.marker is TimelineMarker.IMPACT_ENDS for entry in document.timeline)

    return [*(["no loss was estimated"] if document.customer_loss_estimate is None else []),
            *(["the service was never seen back to normal"] if not ended else [])]


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
            *(["the chain does not reach a cause beyond the change that set it off"]
              if not reaches_a_cause else [])]


def _why_nothing_was_confirmed(results: list[str]) -> str:
    """That no candidate was confirmed, and - where it can say - why: none was
    tried, or every one tried was refuted. A candidate withdrawn, escalated or
    left with no verdict was tried all the same, and came to neither."""
    tried = [result for result in results if result != NEVER_TRIED]
    if not tried:
        return "no candidate was confirmed - none was tried"
    if all(result == Verdict.REFUTED for result in tried):
        return "no candidate was confirmed - those tried were refuted"
    return "no candidate was confirmed"
