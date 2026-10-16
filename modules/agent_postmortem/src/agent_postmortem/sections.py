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
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from argus_core import parse_iso
from argus_core.events import HUNK_HEADER, PATCH_LINE_INDENT
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ChangeEvent,
    ChangeKind,
    CitedEvidence,
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

from agent_postmortem.evidence import CandidateRecord, IncidentEvidence
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
DEPLOYMENT_CHANGES_PREFIX: Final = "D"
CODE_READING_PREFIX: Final = "F"
CANDIDATE_PREFIX: Final = "C"
ACTION_PREFIX: Final = "M"
REVIEW_THE_FIX = "Review and merge the proposed fix"

# How a line of a configuration file says it is a comment: YAML's, TOML's and
# INI's `#`, INI's `;`, and the `//` of JSON with comments.
_COMMENT_MARKS: Final = ("#", ";", "//")


def detection_of(evidence: IncidentEvidence) -> Detection:
    """When the alert fired, which rule fired it, and how long after the onset.

    No gap without an onset: the alert's own time is not when the service
    broke, and a gap measured from it would read as an alert that fired the
    moment the fault began. And what the alert said, under the label it is
    cited by, so a citation of it leads to a row.
    """
    return Detection(
        alerted_at=evidence.alerted_at,
        rule=evidence.rule,
        onset_at=evidence.onset_at,
        gap=(evidence.alerted_at - evidence.onset_at
             if evidence.onset_at is not None else None),
        said=next(iter(the_alert_labelled(evidence)), None)
    )


def the_alert_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """What the alert said, under the label a step of the cause cites it by -
    or nothing, where its sender said nothing of its own.

    Evidence like the rest, and the first a chain's symptom rests on: the check
    that paged measured what it paged on. Its figures keep the names they are
    shown by (`figures`), so it is no part of the evidence whose figures are
    named after their labels.
    """
    if not evidence.alert_finding:
        return []

    return [CitedEvidence(label=label_of(ALERT_PREFIX, 1), text=evidence.alert_finding)]


def impact_of(measured: Measurements) -> Impact:
    """How long the service was broken, what kind of figure that is, and how
    bad it got.

    Unobserved before a lower bound: metrics that stopped also never show a
    recovery, and a stretch nobody could see is not one the service is known
    to have spent broken.
    """
    if measured.unobserved_from is not None:
        extent = ImpactExtent.UNOBSERVED
    elif measured.back_to_normal_at is None:
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

    carrier = _the_deploy_that_carried(blamed, evidence) if latest is None else None
    dated = latest or (carrier[1] if carrier is not None else None)

    return Trigger(subject=blamed.subject,
                   from_state=blamed.from_state,
                   to_state=blamed.to_state,
                   changed_at=parse_iso(dated.occurred_at) if dated else None,
                   kind=latest.kind if latest else None,
                   actor=dated.actor if dated else None,
                   suspected=suspect is not None,
                   carried_by=(label_of(PRODUCTION_CHANGE_PREFIX, carrier[0])
                               if carrier is not None else None))


def _the_deploy_that_carried(blamed: CandidateRecord,
                             evidence: IncidentEvidence) -> tuple[int, ChangeEvent] | None:
    """The deploy that carried the setting the candidate blamed, and its place
    among the changes read - or `None` where not exactly one did.

    A setting is no change's reference, so what carried it is found in what each
    deploy changed: the deploy whose diff moves the setting from the state the
    candidate left to the one it went to (`_it_moves`), made at or before the
    onset - a change made after the incident began did not begin it. Two such
    deploys and the diffs cannot say which, and a trigger credited to either
    would be a guess said as a finding.
    """
    if blamed.subject is None or blamed.from_state is None or blamed.to_state is None:
        return None

    moved = {looked_into.revision for looked_into in evidence.deployment_changes
             if _it_moves(looked_into.said, blamed.subject, blamed.from_state, blamed.to_state)}
    carriers = [(position, change) for position, change in enumerate(evidence.changes, start=1)
                if change.kind is ChangeKind.DEPLOY and change.reference in moved
                and (evidence.onset_at is None
                     or parse_iso(change.occurred_at) <= evidence.onset_at)]

    return carriers[0] if len(carriers) == 1 else None


def _it_moves(said: list[str], subject: str, from_state: str, to_state: str) -> bool:
    """Whether a deploy's diff, as the read tier said it, moves the setting
    `subject` from `from_state` to `to_state`.

    Within one hunk: a removed line naming the setting - its last part or the
    whole of it - and the state it left, and an added line naming it and the
    state it went to - each the setting's own line, by `_it_is_the_setting`.
    """
    return any(_it_sets(hunk, "-", subject, from_state)
               and _it_sets(hunk, "+", subject, to_state)
               for hunk in _the_hunks(said))


def _it_sets(hunk: list[str], marker: str, subject: str, state: str) -> bool:
    """Whether a line of `hunk` that the diff marks with `marker` - removed or
    added - is the setting `subject` at `state`: naming its last part, as a
    nested key does, or the whole of it, as a flat one does."""
    *parents, last = subject.split(".")

    return any(line.startswith(marker)
               and (_names(_own_text(line), last) or _names(_own_text(line), subject))
               and _names(_own_text(line), state)
               and _it_is_the_setting(hunk, at, subject, parents)
               for at, line in enumerate(hunk))


def _the_hunks(said: list[str]) -> list[list[str]]:
    """A deploy's diff as the read tier said it, cut into its hunks: each a run
    of patch lines with their marker, within one file, the `@@` line that opens
    one not among them - its text is git's nearest preceding section line, not
    the one the hunk is in.

    The read tier sets in by two spaces every line under the one naming its
    file - a patch line, or the notice that the file has none, which becomes a
    hunk of one line whose `(` no setting is read as moving by. Any other line
    is a header or a notice about the whole answer, and closes the hunk.
    """
    hunks: list[list[str]] = []
    current: list[str] | None = None
    for line in said:
        if not line.startswith(PATCH_LINE_INDENT):
            current = None
            continue

        patch = line.removeprefix(PATCH_LINE_INDENT)
        if current is None or patch.startswith(HUNK_HEADER):
            current = []
            hunks.append(current)
        if not patch.startswith(HUNK_HEADER):
            current.append(patch)

    return hunks


def _it_is_the_setting(hunk: list[str], at: int, subject: str, parents: list[str]) -> bool:
    """Whether the line at `at` is the setting `subject` itself, and not another
    of the same last name: it names the whole of it, as a flat `a.b = v` does,
    or - walking up from it - each nearest line set in less far names the next
    of its parents in turn, as a nested `a:` over `  b: v` does. A blank line
    and a comment name nothing, and are walked past."""
    if _names(_own_text(hunk[at]), subject):
        return True

    indent = _indent_of(hunk[at])
    for parent in reversed(parents):
        above = next((place for place in range(at - 1, -1, -1)
                      if _it_names_something(hunk[place]) and _indent_of(hunk[place]) < indent),
                     None)
        if above is None or not _names(_own_text(hunk[above]), parent):
            return False
        at, indent = above, _indent_of(hunk[above])

    return True


def _it_names_something(patch_line: str) -> bool:
    """Whether a patch line's own text is a line of the file that names a key -
    not blank, and not a comment."""
    text = _own_text(patch_line).strip()
    return bool(text) and not text.startswith(_COMMENT_MARKS)


def _indent_of(patch_line: str) -> int:
    """How far a patch line's own text is set in, its marker aside."""
    text = _own_text(patch_line)
    return len(text) - len(text.lstrip())


def _own_text(patch_line: str) -> str:
    """A patch line as the file has it, without the marker git puts before it -
    which a removed flat key's `-` would otherwise make part of its name."""
    return patch_line[1:]


def _names(line: str, word: str) -> bool:
    """Whether `word` is in `line` whole, not as part of a longer name."""
    return re.search(rf"(?<![\w.-]){re.escape(word)}(?![\w.-])", line) is not None


def resolution_of(evidence: IncidentEvidence) -> list[ResolutionStep]:
    """Every action taken, in order, with what it came to and whether it stands.

    And whether it left automatic sync off: until somebody turns it back on,
    nothing merged reaches the service.
    """
    return [
        ResolutionStep(at=action.taken_at,
                       action=action.action,
                       by=TAKEN_BY,
                       reversible=action.reversible,
                       outcome=(f"{action.verdict or NO_VERDICT_RECORDED}, {action.standing}"
                                f"{_SYNC_LEFT_OFF if action.paused_sync_of is not None else ''}"),
                       label=label_of(ACTION_PREFIX, position))
        for position, action in enumerate(evidence.actions, start=1)
    ]


# Said after an action's outcome where the action left automatic sync off.
_SYNC_LEFT_OFF: Final = " - automatic sync left off"


def hypotheses_of(evidence: IncidentEvidence) -> list[HypothesisConsidered]:
    """Every candidate ranked, with what became of it - untried ones included,
    and candidates that are one cause shown once (`causes_of`)."""
    return [
        HypothesisConsidered(summary=cause.lead.summary,
                             confidence=cause.lead.confidence,
                             result=cause.became,
                             label=cause.label,
                             also=cause.also)
        for cause in causes_of(evidence.candidates)
    ]


@dataclass(frozen=True)
class OneCause:
    """Candidates that are one cause, best-ranked first, each under its label."""

    members: tuple[tuple[str, CandidateRecord], ...]

    @property
    def label(self) -> str:
        """The label the cause is listed under: its best-ranked candidate's."""
        return self.members[0][0]

    @property
    def also(self) -> list[str]:
        """The labels of the rest, which it is listed under too."""
        return [label for label, _ in self.members[1:]]

    @property
    def lead(self) -> CandidateRecord:
        """The best-ranked candidate, whose words the cause is said in."""
        return self.members[0][1]

    @property
    def decided(self) -> CandidateRecord:
        """The candidate whose test says what became of the cause - the first
        tested, or the lead where none was."""
        return next((candidate for _, candidate in self.members if candidate.tested), self.lead)

    @property
    def became(self) -> str:
        """What became of the cause, in the words its row and the brief both
        say it in: its verdict, or that it was never tried, or tried and never
        judged."""
        if not self.decided.tested:
            return NEVER_TRIED

        return self.decided.result or NO_VERDICT_RECORDED


def causes_of(candidates: list[CandidateRecord]) -> list[OneCause]:
    """The candidates as the causes they are, in rank order, each under its
    label: candidates blaming the same move of the same subject are one cause,
    and listed apart they read as two the investigation weighed.

    Only where the record agrees they are one - at most one tested, or all
    tested to the same verdict. Two tested apart are two findings, and one row
    would show one verdict and hide the other. A candidate naming no subject
    blames nothing anybody can compare, and is a cause of its own.
    """
    by_move: dict[tuple[str | None, ...], list[tuple[int, str, CandidateRecord]]] = {}
    for position, candidate in enumerate(candidates, start=1):
        label = label_of(CANDIDATE_PREFIX, position)
        move = ((candidate.subject, candidate.from_state, candidate.to_state)
                if candidate.subject is not None else (label,))
        by_move.setdefault(move, []).append((position, label, candidate))

    causes: list[tuple[int, OneCause]] = []
    for members in by_move.values():
        verdicts = {candidate.result for _, _, candidate in members if candidate.tested}
        together = [members] if len(verdicts) <= 1 else [[member] for member in members]
        causes += [(group[0][0],
                    OneCause(tuple((label, candidate) for _, label, candidate in group)))
                   for group in together]

    return [cause for _, cause in sorted(causes, key=lambda placed: placed[0])]


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
                back_to_normal_at: datetime | None,
                back_before_the_action: bool = False) -> list[TimelineEntry]:
    """The narration in order, each line under the label the prompt cited it
    by, with the four markers placed by code.

    `back_to_normal_at` is where the service was back to normal rather than the
    recorded recovery: the document's duration ends there, and a timeline
    ending somewhere else would contradict the figure beside it. The end says
    when it came before the action credited with it (`back_before_the_action`),
    since the order of the two markers is otherwise left to be noticed.

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
        _a_marker(evidence.alerted_at, TimelineMarker.DETECTED,
                  f"{evidence.alert_title} fired"),
        *([_a_marker(mitigated.taken_at, TimelineMarker.MITIGATED, mitigated.action)]
          if (mitigated := evidence.credited_action) is not None else []),
        *([_a_marker(back_to_normal_at, TimelineMarker.IMPACT_ENDS,
                     "the service was back to normal, before the action credited with it"
                     if back_before_the_action else "the service was back to normal")]
          if back_to_normal_at is not None else [])
    ]

    narration = [entry.model_copy(update={"label": label,
                                          "text": said_of_a_line(entry)})
                 for entry, label in zip(evidence.timeline,
                                         labels_of_the_narration(evidence.timeline),
                                         strict=True)]

    return sorted([*markers, *narration], key=_in_order)


def said_of_a_line(entry: TimelineEntry) -> str:
    """A line of the narration as the document and the prompt both say it: as
    it was written, except a line that formed candidates, which names them by
    the labels their rows go by.

    Said in full, such a line repeats every candidate's paragraph, which the
    hypotheses considered show under its label already - so the model would
    read each one twice with nothing to say the two are one, and a reader of
    the page would read it twice beside the row it is.
    """
    if not entry.candidates:
        return entry.text

    formed = len(entry.candidates)
    labels = ", ".join(label_of(CANDIDATE_PREFIX, position + 1) for position in entry.candidates)

    return f"Formed {formed} candidate cause{'s' if formed != 1 else ''}, best first: {labels}"


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

