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

KEY_DATA_COLLECTED: Final = "Key incident data collected"
IMPACT_ASSESSED: Final = "Impact assessed"
ANALYSIS_COMPLETE: Final = "Root-cause analysis complete"
ITEMS_OWNED_AND_DATED: Final = "Every action item owned and dated"
REVIEWED_AND_SHARED: Final = "Reviewed and shared"


def review_of(document: PostmortemDocument, faults: list[str]) -> list[ReviewCriterion]:
    """The five criteria, in Google's order, judged against `document`.

    `faults` are what the checks still found in the model's answer. They bear
    on the analysis alone: the timeline and the figures are written by code,
    and an answer that misspoke does not make them any less collected.
    """
    return [
        ReviewCriterion(criterion=KEY_DATA_COLLECTED, met=_key_data_collected(document)),
        ReviewCriterion(criterion=IMPACT_ASSESSED, met=_impact_assessed(document)),
        ReviewCriterion(criterion=ANALYSIS_COMPLETE,
                        met=_analysis_complete(document, faults)),
        ReviewCriterion(criterion=ITEMS_OWNED_AND_DATED, met=None),
        ReviewCriterion(criterion=REVIEWED_AND_SHARED, met=None)
    ]


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
