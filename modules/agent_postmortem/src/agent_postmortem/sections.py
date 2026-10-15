"""The sections of the document that code writes, from the record and what was
measured of it.

Impact, detection, trigger, resolution and the hypotheses considered are each a
fact the incident left behind, arranged for a reader - never a question for the
model. A model asked when the alert fired, or which change caused it, would be
answering something the record already holds, and an answer that disagreed
would be indistinguishable from one that agreed.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Final

from argus_core import parse_iso
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    Detection,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    ResolutionStep,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Verdict,
)

from agent_postmortem.evidence import ActionRecord, CandidateRecord, IncidentEvidence
from agent_postmortem.measuring import Measurements

# Who took every action in the record. Only Argus's own actions are recorded as
# taken; a person's resolution is read beside the document, not written into it.
TAKEN_BY = "Argus"

NEVER_TRIED = "never tried"
NO_VERDICT_RECORDED = "no verdict recorded"

# How an action item is named in conversation: `AI-1`, `AI-2`.
ACTION_ITEM_PREFIX = "AI-"

# How each kind of evidence is labelled for citing: a line of the narration
# `T1`, a change to production `P1`, a candidate `C1`, an action `M1` - and a
# group of log lines by its message, `G3fa2` (`log_groups`). Not `A` for an
# action: an action item is `AI-1`, and the two read alike. Not `C` for a
# change, which a candidate already is. Here rather than with the prompt,
# because the rows of the document carry the same labels the prompt gave, so
# the prose that cites one can be pointed at its row.
#
# A line of the narration outside the walk - a person's message, what was made
# of it, the relay failing to post - is `XW1`, counted apart from the walk's
# own: where one lands among them is timing, and counted with them a message
# written a second earlier would rename every line of the walk after it.
#
# What the alert said is `AL1`. Not `A`, which its figures are already named by
# (`{A1}`): a label and a figure's name that read alike are a citation of a
# number.
ALERT_PREFIX: Final = "AL"
NARRATION_PREFIX: Final = "T"
OUTSIDE_THE_WALK_PREFIX: Final = "XW"
PRODUCTION_CHANGE_PREFIX: Final = "P"
CANDIDATE_PREFIX: Final = "C"
ACTION_PREFIX: Final = "M"
REVIEW_THE_FIX = "Review and merge the proposed fix"


def detection_of(evidence: IncidentEvidence) -> Detection:
    """When the alert fired, which rule fired it, and how long after the onset.

    No gap without an onset: the alert's own time is not when the service
    broke, and a gap measured from it would read as an alert that fired the
    moment the fault began.
    """
    return Detection(
        alerted_at=evidence.started_at,
        rule=evidence.rule,
        onset_at=evidence.onset_at,
        gap=(evidence.started_at - evidence.onset_at
             if evidence.onset_at is not None else None)
    )


def impact_of(measured: Measurements) -> Impact:
    """How long the service was broken, what kind of figure that is, and how
    bad it got.

    Unobserved before a lower bound: metrics that stopped also never show a
    recovery, and a stretch nobody could see is not one the service is known
    to have spent broken.
    """
    if measured.unobserved_from is not None:
        extent = ImpactExtent.UNOBSERVED
    elif measured.recovered_at is None:
        extent = ImpactExtent.AT_LEAST
    else:
        extent = ImpactExtent.MEASURED

    rates = measured.error_rates

    return Impact(duration=timedelta(hours=measured.duration_in_hours),
                  extent=extent,
                  peak_error_rate=rates.at_its_worst if rates is not None else None,
                  requests_failed=rates.failed_requests if rates is not None else None)


def trigger_of(evidence: IncidentEvidence) -> Trigger | None:
    """The change the confirmed candidate blamed, dated where a change was read.

    The latest change to that subject, because a flag toggled last week and
    again this morning was triggered this morning. A change is to the subject
    when it names the subject, or when it names a whole word of the state the
    candidate moved to: a deployment's subject is the investigation's wording
    about it, and the revision it blames is the state, not the subject - which
    can name the revision moved *from* as well. `None` where no candidate
    was confirmed, or the one confirmed named no subject: a refuted candidate
    is not a weaker trigger, and the document says none was established rather
    than offering the best of the rest.

    One exception, said as such: where nothing was confirmed because the
    leading candidate was never tested - the action that would have tested it
    only recommended - and the change it blames was read, that change is the
    trigger, suspected. Never where the leader was refuted, and never on the
    candidate's word alone with no change read to point at.
    """
    confirmed = _the_confirmed(evidence.candidates)
    suspect = _the_untested_leader(evidence.candidates) if confirmed is None else None
    blamed = confirmed or suspect
    if blamed is None or blamed.subject is None:
        return None

    to_the_subject = [change for change in evidence.changes
                      if change.reference == blamed.subject
                      or _a_word_of(blamed.to_state, change.reference)]
    latest = max(to_the_subject, key=lambda change: parse_iso(change.occurred_at), default=None)
    if suspect is not None and latest is None:
        return None

    return Trigger(subject=blamed.subject,
                   from_state=blamed.from_state,
                   to_state=blamed.to_state,
                   changed_at=parse_iso(latest.occurred_at) if latest else None,
                   kind=latest.kind if latest else None,
                   actor=latest.actor if latest else None,
                   suspected=suspect is not None)


def resolution_of(evidence: IncidentEvidence) -> list[ResolutionStep]:
    """Every action taken, in order, with what it came to and whether it stands."""
    return [
        ResolutionStep(at=action.taken_at,
                       action=action.action,
                       by=TAKEN_BY,
                       reversible=action.reversible,
                       outcome=f"{action.verdict or NO_VERDICT_RECORDED}, {action.standing}",
                       label=label_of(ACTION_PREFIX, position))
        for position, action in enumerate(evidence.actions, start=1)
    ]


def hypotheses_of(evidence: IncidentEvidence) -> list[HypothesisConsidered]:
    """Every candidate ranked, with what became of it - untried ones included."""
    return [
        HypothesisConsidered(summary=candidate.summary,
                             confidence=candidate.confidence,
                             result=_what_became_of(candidate),
                             label=label_of(CANDIDATE_PREFIX, position))
        for position, candidate in enumerate(evidence.candidates, start=1)
    ]


def label_of(prefix: str, position: int) -> str:
    """What the evidence of one kind at `position` (from 1) is cited as."""
    return f"{prefix}{position}"


def action_item_number(position: int) -> str:
    """What the action item at `position` (from 1) is called in conversation."""
    return f"{ACTION_ITEM_PREFIX}{position}"


def record_action_items_of(evidence: IncidentEvidence) -> list[ActionItem]:
    """The action items the record implies, numbered from `AI-1`.

    What brought recovery is done, and is Argus's. The fix proposed and the
    action Argus declined are open, and nobody's: Argus edits no item after the
    document is written, so whoever takes one on does so somewhere else. An
    action that did not help is in the resolution and is not left to do.

    Numbered here, before the model is asked, so the model's contributing
    factors can name these and its own proposals follow on.
    """
    implied = [
        *(_an_item(ActionItemType.MITIGATE, action.action, owner=TAKEN_BY,
                   status=ActionItemStatus.DONE)
          for action in evidence.actions if action.verdict == Verdict.CONFIRMED),
        *([_an_item(ActionItemType.PREVENT, REVIEW_THE_FIX,
                    tracking=evidence.pull_request.url)]
          if evidence.pull_request is not None else []),
        *([_an_item(ActionItemType.MITIGATE, evidence.recommended_action)]
          if evidence.recommended_action is not None else [])
    ]

    return [item.model_copy(update={"number": action_item_number(position)})
            for position, item in enumerate(implied, start=1)]


def timeline_of(evidence: IncidentEvidence,
                recovered_at: datetime | None) -> list[TimelineEntry]:
    """The narration in order, each line under the label the prompt cited it
    by, with the four markers placed by code.

    `recovered_at` is the measured recovery rather than the recorded one: the
    document's duration ends there, and a timeline ending somewhere else would
    contradict the figure beside it.

    A marker whose moment is unknown is left out rather than placed near where
    it probably was. At the same moment, a marker sorts before the line about
    it where the line is the reaction - the alert fired, and Argus received it
    - and after it where the marker is the result: the mitigation is the line
    that took it, done.
    """
    markers = [
        *([_a_marker(evidence.onset_at, TimelineMarker.IMPACT_BEGINS,
                     "the incident began")]
          if evidence.onset_at is not None else []),
        _a_marker(evidence.started_at, TimelineMarker.DETECTED,
                  f"{evidence.alert_title} fired"),
        *([_a_marker(mitigated.taken_at, TimelineMarker.MITIGATED, mitigated.action)]
          if (mitigated := _what_brought_recovery(evidence)) is not None else []),
        *([_a_marker(recovered_at, TimelineMarker.IMPACT_ENDS, "the service recovered")]
          if recovered_at is not None else [])
    ]

    narration = [entry.model_copy(update={"label": label})
                 for entry, label in zip(evidence.timeline,
                                         labels_of_the_narration(evidence.timeline),
                                         strict=True)]

    return sorted([*markers, *narration], key=_in_order)


def labels_of_the_narration(timeline: list[TimelineEntry]) -> list[str]:
    """Each line's label, in order: the walk's lines counted as `T`, and the
    lines outside the walk counted apart as `XW`."""
    counted = {NARRATION_PREFIX: 0, OUTSIDE_THE_WALK_PREFIX: 0}
    labels = []

    for entry in timeline:
        prefix = OUTSIDE_THE_WALK_PREFIX if entry.outside_the_walk else NARRATION_PREFIX
        counted[prefix] += 1
        labels.append(label_of(prefix, counted[prefix]))

    return labels


def _in_order(entry: TimelineEntry) -> tuple[datetime, int]:
    """When it happened, and then which comes first at that moment: a marker
    the line reacts to, the line, and a marker that is the line's result."""
    if entry.marker is TimelineMarker.MITIGATED:
        return entry.at, 2

    return entry.at, 0 if entry.marker is not None else 1


def _a_marker(at: datetime, marker: TimelineMarker, text: str) -> TimelineEntry:
    return TimelineEntry(at=at, who=None, text=text, marker=marker)


def _what_brought_recovery(evidence: IncidentEvidence) -> ActionRecord | None:
    confirmed = [action for action in evidence.actions if action.verdict == Verdict.CONFIRMED]

    return confirmed[0] if confirmed else None


def _an_item(kind: ActionItemType,
             text: str,
             owner: str | None = None,
             tracking: str | None = None,
             status: ActionItemStatus = ActionItemStatus.OPEN) -> ActionItem:
    """An item not yet numbered - its number is its place in the whole list."""
    return ActionItem(number="", text=text, type=kind, owner=owner,
                      tracking=tracking, status=status)


def _the_confirmed(candidates: list[CandidateRecord]) -> CandidateRecord | None:
    confirmed = [candidate for candidate in candidates
                 if candidate.tested and candidate.result == Verdict.CONFIRMED]

    return confirmed[0] if confirmed else None


def _the_untested_leader(candidates: list[CandidateRecord]) -> CandidateRecord | None:
    return candidates[0] if candidates and not candidates[0].tested else None


def _a_word_of(text: str | None, reference: str) -> bool:
    # Bounded by what a sha or a flag's name can be spelled with, so a short sha
    # is never found inside a long one, nor a flag inside a longer flag's name -
    # while the full stop that ends a sentence still ends the word. An empty
    # reference names nothing, and would otherwise be found between any two.
    return text is not None and reference != "" and re.search(
        rf"(?<![\w-]){re.escape(reference)}(?![\w-])", text
    ) is not None


def _what_became_of(candidate: CandidateRecord) -> str:
    if not candidate.tested:
        return NEVER_TRIED

    return candidate.result or NO_VERDICT_RECORDED
