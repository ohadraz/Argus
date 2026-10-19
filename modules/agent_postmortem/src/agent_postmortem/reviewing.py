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

from agent_postmortem.sections import CODE_READING_PREFIX

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
    complete = _analysis_complete(document, faults) and reaches_a_cause
    unrun = _readings_resting_alone(document) if complete else []

    return [
        ReviewCriterion(criterion=KEY_DATA_COLLECTED, met=_key_data_collected(document)),
        ReviewCriterion(criterion=IMPACT_ASSESSED, met=_impact_assessed(document)),
        ReviewCriterion(criterion=ANALYSIS_COMPLETE,
                        met=None if unrun else complete,
                        because=_what_would_confirm(document, unrun) if unrun else None),
        ReviewCriterion(criterion=ITEMS_OWNED_AND_DATED, met=None),
        ReviewCriterion(criterion=REVIEWED_AND_SHARED, met=None)
    ]


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


def _key_data_collected(document: PostmortemDocument) -> bool:
    """A timeline to read, and nothing in the cause resting on nothing."""
    return bool(document.timeline) and all(step.cites for step in document.causal_chain)


def _impact_assessed(document: PostmortemDocument) -> bool:
    """What it cost, and when it stopped costing. A duration with no end is a
    lower bound, and a lower bound is impact not yet measured."""
    ended = any(entry.marker is TimelineMarker.IMPACT_ENDS for entry in document.timeline)

    return document.customer_loss_estimate is not None and ended


def _analysis_complete(document: PostmortemDocument, faults: list[str]) -> bool:
    """More than one step, nothing left wrong with the answer, and a cause
    confirmed. One step is the symptom restated; the analysis is the steps
    below it. A chain ending on a cause nothing confirmed is a document saying,
    rightly, that the cause is not confirmed, and a ticked box beside it would
    say the opposite."""
    confirmed = any(hypothesis.result == Verdict.CONFIRMED for hypothesis in document.hypotheses)

    return not faults and len(document.causal_chain) > 1 and confirmed
