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
from argus_core.events import HUNK_HEADER, PATCH_LINE_INDENT, names_as_changed
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ActionProgress,
    CandidateConsidered,
    ChangeEvent,
    ChangeKind,
    CitedEvidence,
    Detection,
    ErrorRateLevels,
    HypothesisConsidered,
    Impact,
    ImpactExtent,
    LogsInTheGap,
    ResolutionStep,
    RuleSeriesHarm,
    TimelineEntry,
    TimelineMarker,
    Trigger,
    Verdict,
)

from agent_postmortem.evidence import CandidateRecord, DeploymentChangesRecord, IncidentEvidence
from agent_postmortem.log_groups import labels_reaching_into
from agent_postmortem.measuring import Measurements
from agent_postmortem.stamps import the_last_minute_logged_inside

# Who took every action in the record. Only Argus's own actions are recorded as
# taken; a person's resolution ends the incident, but is no action of record.
TAKEN_BY = "Argus"

NEVER_TRIED = "never tried"
# What became of a cause whose action was reached for and ended before its
# write: never tried as surely as one nobody reached, and said apart from it,
# since the action's own row is about this cause and "never tried" beside it
# reads as no attempt at all.
ACTION_NOT_TAKEN = "action not taken"
NO_VERDICT_RECORDED = "no verdict recorded"
# What an action a person's ending stopped came to, and what became of a cause
# whose action was performed and never measured - a person's ending during the
# wait, or a wait whose every look went unanswered: nothing was judged, and the
# cause was tried all the same.
NOT_JUDGED = "not judged"
TRIED_NOT_JUDGED = "tried, not judged"
# What became of a cause whose action was performed and carries no verdict:
# the worker died with the change made, before the wait judged it or before it
# wrote down what the wait judged - and the row cannot say which.
TRIED_NO_VERDICT_RECORDED = "tried, no verdict recorded"
# What became of a cause whose action was claimed and never said more: nobody
# can tell whether the change was made.
NOT_KNOWN_WHETHER_TRIED = "not known whether tried"
# What a refusal to act came to, in the resolution's outcome column - and an
# action a person's ending stopped before it was done.
NOT_TAKEN = "not taken"

# How an action item is named in conversation: `AI-1`, `AI-2`.
ACTION_ITEM_PREFIX = "AI-"

# How a contributing factor is labelled in the model's answer, for the items it
# proposes to name: `CF-1`, `CF-2`. Never shown to a reader.
CONTRIBUTING_FACTOR_PREFIX: Final = "CF-"

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
AS_IT_RAN_PREFIX: Final = "S"
# How the code outside Code-Fix's patch uses what it changes, read off the code.
USES_OUTSIDE_PREFIX: Final = "U"
CANDIDATE_PREFIX: Final = "C"
ACTION_PREFIX: Final = "M"
REVIEW_THE_FIX = "Review and merge the proposed fix"
# When automatic sync an action left off goes back on, and what it does until
# then and sooner - one way, for the action item and the summary alike.
SYNC_GOES_BACK_ON: Final = "once its repository says what should run"
UNTIL_SYNC_IS_BACK_ON: Final = ("until then nothing merged reaches it, and turned on sooner "
                                "it puts back what the repository says, undoing what Argus "
                                "changed by hand")
TURN_SYNC_BACK_ON: Final = (f"Turn automatic sync of {{application}} back on "
                            f"{SYNC_GOES_BACK_ON} - {UNTIL_SYNC_IS_BACK_ON}")

# How a line of a configuration file says it is a comment: YAML's, TOML's and
# INI's `#`, INI's `;`, and the `//` of JSON with comments.
_COMMENT_MARKS: Final = ("#", ";", "//")
# A comment, from its mark to the end of the line: the whole line, or what
# follows the code after a space.
_A_COMMENT: Final = re.compile(
    rf"(?:^|\s)(?:{'|'.join(re.escape(mark) for mark in _COMMENT_MARKS)}).*$")


def detection_of(evidence: IncidentEvidence,
                 rule_waits: timedelta | None = None,
                 rule_wait_unread: bool = False,
                 held_before_the_onset: bool | None = None) -> Detection:
    """When the alert fired, which rule fired it, and how long after the onset.

    No gap without an onset: the alert's own time is not when the service
    broke, and a gap measured from it would read as an alert that fired the
    moment the fault began. And what the alert said, under the label it is
    cited by, so a citation of it leads to a row.

    And how long the rule's condition must hold before it fires, as measured
    (`rule_waits`, `rule_wait_unread`): what a reader weighs the gap against.
    And whether the series bore out what an alert sooner than that claims
    (`held_before_the_onset`), which only the writer, holding the series, can
    say. And when Argus first posted about it where people could read it, as
    recorded.
    """
    return Detection(
        alerted_at=evidence.alerted_at,
        rule=evidence.rule,
        onset_at=evidence.onset_at,
        gap=(evidence.alerted_at - evidence.onset_at
             if evidence.onset_at is not None else None),
        said=next(iter(the_alert_labelled(evidence)), None),
        rule_waits=rule_waits,
        rule_wait_unread=rule_wait_unread,
        held_before_the_onset=held_before_the_onset,
        first_told=evidence.first_told
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


def logs_in_the_gap_of(evidence: IncidentEvidence,
                       measured: Measurements,
                       serving_as_before: bool | None = None) -> LogsInTheGap | None:
    """What the service's own logs show of the stretch its metrics missed -
    `None` where they never stopped.

    Which rows reach in and how far, by the rule the brief tells it by
    (`labels_reaching_into`, `the_last_minute_logged_inside`), and where the
    reading of them ended, at the alert or past it.

    And `serving_as_before`, the model's reading of those rows - only where a
    row reaches in, since with none there is nothing for it to be a reading of.
    """
    since = measured.unobserved_from
    if since is None:
        return None

    read_until = evidence.logs_read_until
    labels = labels_reaching_into(evidence.log_lines, since)

    return LogsInTheGap(
        read=bool(evidence.log_lines) or read_until is not None,
        labels=labels,
        reach_until=the_last_minute_logged_inside(evidence.log_lines, since),
        read_until=read_until,
        read_until_the_alert=read_until is not None and read_until == evidence.alerted_at,
        serving_as_before=serving_as_before if labels else None
    )


def impact_of(measured: Measurements, *, logs_in_the_gap: LogsInTheGap | None) -> Impact:
    """How long the service was broken, what kind of figure that is, and how
    bad it got - in failed requests, and in the series its rule pages on
    where that got worse - and what the logs show where the metrics stopped.

    Unobserved before a lower bound: metrics that stopped also never show a
    recovery, and a stretch the metrics carry nothing of is not one the
    service is known to have spent broken.

    `logs_in_the_gap` is asked for rather than defaulted: left off, a gap the
    logs reach into would be said with nothing of them.
    """
    if measured.unobserved_from is not None:
        extent = ImpactExtent.UNOBSERVED
    elif measured.reported_by is not None:
        extent = ImpactExtent.REPORTED
    elif measured.back_to_normal_at is None:
        extent = ImpactExtent.AT_LEAST
    else:
        extent = ImpactExtent.MEASURED

    rates = measured.error_rates
    series = measured.rule_series

    return Impact(duration=timedelta(hours=measured.duration_in_hours),
                  extent=extent,
                  peak_error_rate=rates.at_its_worst if rates is not None else None,
                  requests_failed=rates.failed_requests if rates is not None else None,
                  error_rates=ErrorRateLevels(before=rates.baseline,
                                              while_broken=rates.while_broken,
                                              rose=rates.a_rise_was_measured)
                  if rates is not None else None,
                  rule_series_harm=RuleSeriesHarm(before=series.baseline,
                                                  while_broken=series.while_broken,
                                                  at_its_worst=series.at_its_worst,
                                                  worse_when=series.worse_when,
                                                  line=series.line,
                                                  unit=measured.rule_series_unit,
                                                  is_the_error_rate=(
                                                      measured.rule_series_is_the_error_rate))
                  if series is not None and series.got_worse else None,
                  logs_in_the_gap=logs_in_the_gap)


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
    than offering the best of the rest. `None` too where the one confirmed
    names no change - no state it moved between, and no change read to it or
    carrying it - as a dependency that slowed does not: its subject alone is
    the candidate again, already among the hypotheses, and under "Trigger" it
    reads as a change somebody made.

    One exception, said as such: where nothing was confirmed because the
    leading candidate was never tested - the action that would have tested it
    only recommended, or none Argus can take answering it - and a change read
    made what it blames, that change is the trigger, suspected: one naming
    it, or the deploy whose diff carried it. Never where the leader was
    refuted, and never on the candidate's word alone with no change read to
    point at.

    A candidate naming a deployed revision as its subject, with no states, is
    given the deploy's: the revision it put out, and the one it replaced. Left
    without them, the trigger says a deploy happened and not what it deployed.
    """
    confirmed = _the_confirmed(evidence.candidates)
    suspect = _the_untested_leader(evidence.candidates) if confirmed is None else None
    blamed = confirmed or suspect
    if blamed is None or blamed.subject is None:
        return None

    to_the_subject = [(position, change)
                      for position, change in enumerate(evidence.changes, start=1)
                      if change.reference == blamed.subject
                      or _a_word_of(blamed.to_state, change.reference)]
    found = max(to_the_subject, key=lambda each: parse_iso(each[1].occurred_at), default=None)
    latest = found[1] if found is not None else None

    carrier = _the_deploy_that_carried(blamed, evidence) if latest is None else None
    moved = bool(blamed.from_state or blamed.to_state)
    if latest is None and carrier is None and (suspect is not None or not moved):
        return None

    dated = latest or (carrier[1] if carrier is not None else None)
    from_state, to_state = blamed.from_state, blamed.to_state
    if (not moved and latest is not None and latest.kind is ChangeKind.DEPLOY
            and latest.reference == blamed.subject):
        from_state, to_state = _the_revision_deployed_before(latest, evidence), latest.reference

    return Trigger(subject=blamed.subject,
                   from_state=from_state,
                   to_state=to_state,
                   changed_at=parse_iso(dated.occurred_at) if dated else None,
                   kind=latest.kind if latest else None,
                   actor=dated.actor if dated else None,
                   suspected=suspect is not None,
                   carried_by=(label_of(PRODUCTION_CHANGE_PREFIX, carrier[0])
                               if carrier is not None else None),
                   dated_by=(label_of(PRODUCTION_CHANGE_PREFIX, found[0])
                             if found is not None else None))


def _the_revision_deployed_before(deploy: ChangeEvent, evidence: IncidentEvidence) -> str | None:
    """The revision `deploy` replaced: the one the deploy just before it put
    out, which is what its own diff is compared against - or `None` where no
    deploy before it was read, since a revision nobody read is not guessed.
    Never itself: deployed again with nothing changed, it replaced what came
    before that."""
    at = parse_iso(deploy.occurred_at)
    before = [change for change in evidence.changes
              if change.kind is ChangeKind.DEPLOY and parse_iso(change.occurred_at) < at
              and change.reference != deploy.reference]
    latest = max(before, key=lambda change: parse_iso(change.occurred_at), default=None)

    return latest.reference if latest is not None else None


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

    A candidate blaming a file and naming no states blames no setting in it:
    what carried it is the deploy whose diff names that file among those it
    changed (`_the_part_about`).

    A setting named with the file it lives in is the key, and is looked for in
    that file's part of each diff alone: the same key in another file is
    another setting. The file is set off from the key by a colon or a space
    (`_the_file_and_key`). Named with no states, it is still the key and not
    the file: what carried it is the deploy whose part of the diff about that
    file removes or adds the key's own line (`_it_changes_the_setting`). A file
    named alone with two states blames the one key in it that went between
    them (`_one_key_moves`).
    """
    subject, from_state, to_state = blamed.subject, blamed.from_state, blamed.to_state
    if subject is None or (from_state is None) != (to_state is None):
        return None

    path, key = _the_file_and_key(subject, evidence.deployment_changes)
    moved = {looked_into.revision for looked_into in evidence.deployment_changes
             if _it_carries(looked_into.said, path, key, from_state, to_state)}
    carriers = [(position, change) for position, change in enumerate(evidence.changes, start=1)
                if change.kind is ChangeKind.DEPLOY and change.reference in moved
                and (evidence.onset_at is None
                     or parse_iso(change.occurred_at) <= evidence.onset_at)]

    return carriers[0] if len(carriers) == 1 else None


def _the_file_and_key(subject: str,
                      read: list[DeploymentChangesRecord]) -> tuple[str | None, str]:
    """The file a subject names and the key it names in that file - `None` and
    the whole subject where it names no file.

    The file is the longest start of the subject that a diff read names among
    the files it changed, ending where the subject does or at a colon or a
    space, the rest being the key: `deploy/values-production.yaml:ports.metrics.portName`,
    `deploy/values-production.yaml cache.port`, `deploy/values-production.yaml`.

    Where no diff read names the file, a start set off from the rest by a
    colon, or holding a path's `/`, is still a file: the key is in a file no
    deploy read changed, so nothing read carried it. Read whole instead, its
    words would be found in another file's keys.
    """
    ends = [at for at, character in enumerate(subject) if character in _WHAT_ENDS_A_FILE]
    for end in sorted([*ends, len(subject)], reverse=True):
        if any(names_as_changed(line, subject[:end])
               for looked_into in read for line in looked_into.said):
            return subject[:end], subject[end:].lstrip(_WHAT_ENDS_A_FILE)

    end = min(ends, default=len(subject))
    if subject[end:end + 1] == _A_FILE_S_KEY or _A_PATH_S_SEPARATOR in subject[:end]:
        return subject[:end], subject[end:].lstrip(_WHAT_ENDS_A_FILE)
    return None, subject


# What sets a file off from the key in it where a setting is named with its
# file: `deploy/values-production.yaml:ports.metrics.portName`, or the same
# with a space - and what says the start is a file at all, where no diff read
# names it.
_A_FILE_S_KEY: Final = ":"
_WHAT_ENDS_A_FILE: Final = f"{_A_FILE_S_KEY} "
_A_PATH_S_SEPARATOR: Final = "/"


def _it_carries(said: list[str], path: str | None, key: str,
                from_state: str | None, to_state: str | None) -> bool:
    """Whether a deploy's diff, as the read tier said it, carries the setting
    `key` - in the file `path` where one is named - from `from_state` to
    `to_state`, or changes it at all where no states are named."""
    if path is None:
        return (from_state is not None and to_state is not None
                and _it_moves(said, key, from_state, to_state))

    part = _the_part_about(said, path)
    if from_state is None or to_state is None:
        return _it_changes_the_setting(part, key) if key else bool(part)
    return (_it_moves(part, key, from_state, to_state) if key
            else _one_key_moves(part, from_state, to_state))


def _the_part_about(said: list[str], path: str) -> list[str]:
    """A deploy's diff as the read tier said it, cut to the part about `path`:
    the line naming it as changed, and the patch lines set in under it."""
    part: list[str] = []
    inside = False
    for line in said:
        if not line.startswith(PATCH_LINE_INDENT):
            inside = names_as_changed(line, path)
        if inside:
            part.append(line)

    return part


def _it_changes_the_setting(said: list[str], subject: str) -> bool:
    """Whether a deploy's diff, as the read tier said it, removes or adds a
    line that is the setting `subject` itself - naming its last part or the
    whole of it, by `_it_is_the_setting` - whatever states it went between."""
    *parents, last = subject.split(".")

    return any(line.startswith(("-", "+"))
               and (_names(_code_of(line), last) or _names(_code_of(line), subject))
               and _it_is_the_setting(hunk, at, subject, parents)
               for hunk in _the_hunks(said)
               for at, line in enumerate(hunk))


def _it_moves(said: list[str], subject: str, from_state: str, to_state: str) -> bool:
    """Whether a deploy's diff, as the read tier said it, moves the setting
    `subject` from `from_state` to `to_state`.

    Within one hunk: a removed line naming the setting - its last part or the
    whole of it - and the state it left, and an added line naming it and the
    state it went to - each the setting's own line, by `_it_is_the_setting`.

    A setting the investigation named in its own words - "metrics port name"
    - is named by no line, and there the value is what the diff spells: one
    key, under one parent, losing the state the setting left and gaining the
    one it went to, each the whole value - the key and the key it sits under
    sharing two words with the setting's name, or every word of a name of
    one. The two states alone would credit any key moving that way - one to
    two, v1 to v2 - and one word, a "version" or a "name", any key of that
    kind.
    """
    return any((_it_sets(hunk, "-", subject, from_state)
                and _it_sets(hunk, "+", subject, to_state))
               or (not _it_names_the_setting(hunk, subject)
                   and _a_key_like_it_moves(hunk, subject, from_state, to_state))
               for hunk in _the_hunks(said))


def _it_names_the_setting(hunk: list[str], subject: str) -> bool:
    """Whether any line of `hunk` names the setting - its last part or the
    whole of it."""
    last = subject.split(".")[-1]
    return any(_names(_code_of(line), last) or _names(_code_of(line), subject)
               for line in hunk)


def _a_key_like_it_moves(hunk: list[str], subject: str, from_state: str, to_state: str) -> bool:
    """Whether one key in `hunk` goes from `from_state` to `to_state` - removed
    at the one and added at the other under the same parent, each the key's
    whole value - where the key and the nearest key it sits under share with
    `subject` two of its words, or all of a one-word name."""
    words = _the_words_of(subject)
    needed = min(2, len(words))

    return any(len(words & _the_words_of(key, parent)) >= needed
               for key, parent in _the_keys_moved(hunk, from_state, to_state))


def _one_key_moves(said: list[str], from_state: str, to_state: str) -> bool:
    """Whether exactly one key, across a diff's hunks, goes from `from_state`
    to `to_state` (`_the_keys_moved`) - two, and the diff cannot say which a
    file named alone meant."""
    return len({moved for hunk in _the_hunks(said)
                for moved in _the_keys_moved(hunk, from_state, to_state)}) == 1


def _the_keys_moved(hunk: list[str], from_state: str, to_state: str) -> set[tuple[str, str]]:
    """Each key in `hunk`, with the key it sits under, removed at `from_state`
    and added at `to_state` under the same parent, each the key's whole value."""
    keyed = _the_keyed_lines(hunk)
    left = {(key, parent) for marker, key, value, parent in keyed
            if marker == "-" and value == from_state}

    return {(key, parent) for marker, key, value, parent in keyed
            if marker == "+" and value == to_state and (key, parent) in left}


def _the_keyed_lines(hunk: list[str]) -> list[tuple[str, str, str, str]]:
    """Each line of `hunk` setting a key to a value: its marker, the key, the
    value without quotes, and the key it sits under - the nearest line above
    set in less far that names something, or nothing."""
    keyed = []
    for at, line in enumerate(hunk):
        found = _A_KEYED_LINE.match(_code_of(line))
        if found is None:
            continue
        indent = _indent_of(line)
        above = next((hunk[place] for place in range(at - 1, -1, -1)
                      if _it_names_something(hunk[place]) and _indent_of(hunk[place]) < indent),
                     None)
        parent = _A_KEYED_LINE.match(_code_of(above)) if above is not None else None
        keyed.append((line[:1], found["key"], found["value"].strip("'\""),
                      parent["key"] if parent is not None else ""))
    return keyed


# A line setting a key, flat or nested: `key: value` or `key = value`, the
# value possibly empty where the key opens a block.
_A_KEYED_LINE: Final = re.compile(r"^\s*(?P<key>[\w.-]+)\s*[:=]\s*(?P<value>.*?)\s*$")


def _the_words_of(*names: str) -> set[str]:
    """The words names are made of, lower-cased: split at dots, dashes,
    underscores, spaces and each capital starting a word, as `portName` is
    port and name."""
    return {word.lower() for name in names
            for part in re.split(r"[\s._-]+", name)
            for word in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", part)}


def _it_sets(hunk: list[str], marker: str, subject: str, state: str) -> bool:
    """Whether a line of `hunk` that the diff marks with `marker` - removed or
    added - is the setting `subject` at `state`: naming its last part, as a
    nested key does, or the whole of it, as a flat one does."""
    *parents, last = subject.split(".")

    return any(line.startswith(marker)
               and (_names(_code_of(line), last) or _names(_code_of(line), subject))
               and _names(_code_of(line), state)
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
    if _names(_code_of(hunk[at]), subject):
        return True

    indent = _indent_of(hunk[at])
    for parent in reversed(parents):
        above = next((place for place in range(at - 1, -1, -1)
                      if _it_names_something(hunk[place]) and _indent_of(hunk[place]) < indent),
                     None)
        if above is None or not _names(_code_of(hunk[above]), parent):
            return False
        at, indent = above, _indent_of(hunk[above])

    return True


def _it_names_something(patch_line: str) -> bool:
    """Whether a patch line's own text is a line of the file that names a key -
    not blank, and not a comment."""
    return bool(_code_of(patch_line).strip())


def _indent_of(patch_line: str) -> int:
    """How far a patch line's own text is set in, its marker aside."""
    text = _own_text(patch_line)
    return len(text) - len(text.lstrip())


def _own_text(patch_line: str) -> str:
    """A patch line as the file has it, without the marker git puts before it -
    which a removed flat key's `-` would otherwise make part of its name."""
    return patch_line[1:]


def _code_of(patch_line: str) -> str:
    """A patch line's own text with its comment cut off - nothing left of a
    line that is one, and the code alone of a line that ends in one. What a
    comment spells is never a setting, a state or the key above one."""
    return _A_COMMENT.sub("", _own_text(patch_line))


def _names(line: str, word: str) -> bool:
    """Whether `word` is in `line` whole, not as part of a longer name."""
    return re.search(rf"(?<![\w.-]){re.escape(word)}(?![\w.-])", line) is not None


def what_it_came_to(verdict: str | None, progress: ActionProgress) -> str:
    """An action's verdict as the resolution and the brief both say it - a
    stopped one as not judged, which is what it was, or as not taken where a
    person ended the incident before the action was done. One spelling, so the
    model writes from the words the page shows.

    Not taken only where the row says the action ended before its write: a
    claim nobody answered may have been made, so its stop is not judged."""
    if verdict is None:
        return NO_VERDICT_RECORDED

    if verdict == Verdict.STOPPED:
        return NOT_TAKEN if progress is ActionProgress.NOT_PERFORMED else NOT_JUDGED

    return verdict


def resolution_of(evidence: IncidentEvidence) -> list[ResolutionStep]:
    """Every action taken, in order, with what it came to and whether it stands
    - and the candidate it was for, under that candidate's label.

    And whether it left automatic sync off: until somebody turns it back on,
    nothing merged reaches the service. Marked apart from the outcome, which is
    cited wherever the action is - said inside it, the sync would be said in
    every place that cites the action.

    And every refusal to act, in its place among them: declining an action is
    how an incident ended as much as taking one is. Said and dated as the
    timeline's line says it, with nothing to put back, and under no label -
    the labels count the actions, which is what the prose cites.
    """
    taken = [
        ResolutionStep(at=action.taken_at,
                       action=action.action,
                       by=TAKEN_BY,
                       has_a_way_back=action.has_a_way_back,
                       outcome=(f"{what_it_came_to(action.verdict, action.progress)}, "
                                f"{action.standing}"),
                       label=label_of(ACTION_PREFIX, position),
                       sync_left_off=action.paused_sync_of is not None,
                       left_behind_known=action.left_behind_known,
                       candidate=(label_of(CANDIDATE_PREFIX, action.candidate)
                                  if action.candidate is not None else None))
        for position, action in enumerate(evidence.actions, start=1)
    ]
    declined = [
        ResolutionStep(at=evidence.timeline[refused.line].at,
                       action=said_of_a_line(evidence.timeline[refused.line]),
                       by=TAKEN_BY,
                       has_a_way_back=False,
                       outcome=NOT_TAKEN,
                       label=None,
                       refused=refused.refusal,
                       # Refused before anything was asked of anybody.
                       left_behind_known=True,
                       candidate=_the_label_it_names(evidence.timeline[refused.line]))
        for refused in evidence.refusals
    ]

    return sorted([*taken, *declined], key=lambda step: step.at)


def _the_label_it_names(entry: TimelineEntry) -> str | None:
    """The label of the candidate a line acted for, as `said_of_a_line` says
    it - `None` where the line names none."""
    if entry.for_candidate is None:
        return None

    return label_of(CANDIDATE_PREFIX, entry.for_candidate.place + 1)


def hypotheses_of(evidence: IncidentEvidence) -> list[HypothesisConsidered]:
    """Every candidate formed, with what became of it - untried ones included,
    and candidates that are one cause shown once (`causes_of`).

    A row standing for several carries each of them in its own words, mode and
    confidence, and which one's test decided it: shown as the row's own, one
    candidate's figures read as another's.
    """
    return [a_hypothesis_of(cause) for cause in causes_of(evidence.candidates)]


def a_hypothesis_of(cause: OneCause) -> HypothesisConsidered:
    """One cause as the document's row of it.

    Public because the brief says a cause standing for several the way the row
    does, and says what became of each through the row's own `result_of`.
    """
    return HypothesisConsidered(summary=cause.lead.summary,
                                confidence=cause.lead.confidence,
                                result=cause.became,
                                label=cause.label,
                                also=cause.also,
                                members=[CandidateConsidered(label=label,
                                                             summary=candidate.summary,
                                                             confidence=candidate.confidence,
                                                             failure_mode=candidate.failure_mode)
                                         for label, candidate in cause.members]
                                if cause.also else [],
                                decided_by=cause.decided_by if cause.also else None)


@dataclass(frozen=True)
class OneCause:
    """Candidates that are one cause, first formed first, each under its label."""

    members: tuple[tuple[str, CandidateRecord], ...]

    @property
    def label(self) -> str:
        """The label the cause is listed under: its first-formed candidate's."""
        return self.members[0][0]

    @property
    def also(self) -> list[str]:
        """The labels of the rest, which it is listed under too."""
        return [label for label, _ in self.members[1:]]

    @property
    def lead(self) -> CandidateRecord:
        """The first-formed candidate, whose words the cause is said in."""
        return self.members[0][1]

    @property
    def decided(self) -> CandidateRecord:
        """The candidate whose test says what became of the cause - the first
        tested, or the lead where none was."""
        return next((candidate for _, candidate in self.members if candidate.tested), self.lead)

    @property
    def decided_by(self) -> str | None:
        """The label of the candidate whose test says what became of the cause
        - `None` where none was tested."""
        return next((label for label, candidate in self.members if candidate.tested), None)

    @property
    def became(self) -> str:
        """What became of the cause, in the words its row and the brief both
        say it in: its verdict, or that it was never tried or its action not
        taken - and why, where its row recorded it - or tried and never judged,
        or tried with no verdict on file, or not known whether tried at all.

        The why because the gate writes on the row why it held the test back,
        and "never tried" alone left a reader to guess whether the
        investigation ran out or Argus declined."""
        if not self.decided.tested:
            progress = self.decided.progress

            # Acted on and never measured - a person ended the incident while
            # the service was watched, or no look at it was answered. Tried,
            # so never "never tried". With no verdict on file at all, the
            # worker died with the change made, and nobody knows whether a
            # verdict was reached.
            if progress is ActionProgress.PERFORMED:
                return (TRIED_NOT_JUDGED if self.decided.verdict_recorded
                        else TRIED_NO_VERDICT_RECORDED)

            # Claimed, and nothing said since - the walk should never leave a
            # claim at that before a write-up is written, and a claim nobody
            # could answer reads the same. Either may have changed the service,
            # so never "never tried" either.
            if progress in (ActionProgress.CLAIMED, ActionProgress.UNKNOWN):
                return NOT_KNOWN_WHETHER_TRIED

            untried = ACTION_NOT_TAKEN if progress is ActionProgress.NOT_PERFORMED else NEVER_TRIED
            why = self.decided.result
            return f"{untried}: {why}" if why else untried

        return self.decided.result or NO_VERDICT_RECORDED


def was_never_tried(result: str) -> bool:
    """Whether what became of a cause is that it was never tried - with the
    reason its row recorded, or without one, and its action not taken among
    them. A reason read as a verdict would make a cause nobody tested one that
    was tried and came to nothing."""
    return any(result == untried or result.startswith(f"{untried}: ")
               for untried in (NEVER_TRIED, ACTION_NOT_TAKEN))


def causes_of(candidates: list[CandidateRecord]) -> list[OneCause]:
    """The candidates as the causes they are, in the order formed, each under its
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


def inside_a_sentence(action: str) -> str:
    """An action as the narration words it - the opening of a sentence whose
    subject is Argus, "Reverted the feature flag checkout-v2" - lowered to go
    on inside one: "before Argus reverted the feature flag checkout-v2"."""
    return action[:1].lower() + action[1:]


def label_of(prefix: str, position: int) -> str:
    """What the evidence of one kind at `position` (from 1) is cited as."""
    return f"{prefix}{position}"


def is_a_code_reading(label: str) -> bool:
    """Whether `label` cites a reading of the source - one nothing ran."""
    return label.startswith(CODE_READING_PREFIX) and label[len(CODE_READING_PREFIX):].isdigit()


def action_item_number(position: int) -> str:
    """What the action item at `position` (from 1) is called in conversation."""
    return f"{ACTION_ITEM_PREFIX}{position}"


def contributing_factor_label(position: int) -> str:
    """The label the contributing factor at `position` (from 1) is given under."""
    return f"{CONTRIBUTING_FACTOR_PREFIX}{position}"


def record_action_items_of(evidence: IncidentEvidence,
                           back_to_normal_at: datetime | None) -> list[ActionItem]:
    """The action items the record implies, numbered from `AI-1`.

    What brought recovery is done, and is Argus's. The fix proposed and the
    action Argus declined are open, and nobody's: Argus edits no item after the
    document is written, so whoever takes one on does so somewhere else. An
    action that did not help is in the resolution and is not left to do.

    The fix prevents a recurrence where the service is known back
    (`back_to_normal_at` - the metrics show it, or a person reported it over),
    and is a mitigation where it is not: merging it is then what ends the
    incident. Not read off a confirmed action, because an incident can be over
    without one - a flap back before a refuted action, or a person's report.

    Automatic sync an action left off is open too, once for each application:
    until somebody turns it back on, nothing merged reaches the service. After
    the fix, because the fix is what should arrive when it is.

    Numbered here, before the model is asked, so the model's contributing
    factors can name these and its own proposals follow on.
    """
    left_off = dict.fromkeys(action.paused_sync_of for action in evidence.actions
                             if action.paused_sync_of is not None)
    the_fix_is = (ActionItemType.PREVENT if back_to_normal_at is not None
                  else ActionItemType.MITIGATE)
    implied = [
        *(_an_item(ActionItemType.MITIGATE, action.action, owner=TAKEN_BY,
                   status=ActionItemStatus.DONE)
          for action in evidence.actions if action.verdict == Verdict.CONFIRMED),
        *([_an_item(the_fix_is, REVIEW_THE_FIX, tracking=evidence.pull_request.url)]
          if evidence.pull_request is not None else []),
        *(_an_item(ActionItemType.MITIGATE, TURN_SYNC_BACK_ON.format(application=application))
          for application in left_off),
        *([_an_item(ActionItemType.MITIGATE, evidence.recommended_action)]
          if evidence.recommended_action is not None else [])
    ]

    return [item.model_copy(update={"number": action_item_number(position)})
            for position, item in enumerate(implied, start=1)]


def timeline_of(evidence: IncidentEvidence,
                back_to_normal_at: datetime | None,
                back_before_the_action: bool = False,
                metrics_stopped_at_onset: bool = False,
                ended_by_a_report: bool = False) -> list[TimelineEntry]:
    """The narration in order, each line under the label the prompt cited it
    by, with the four markers placed by code.

    The onset is marked as where the metrics stopped, where they carry no
    minute from it on (`metrics_stopped_at_onset`): what it dates then is the
    metrics stopping, and the service may have gone on serving as before.

    Three of the markers are rows of their own, because nobody said them: the
    onset and the end are properties of the metrics, and the alert is what the
    line about it reacts to. The fourth is on the line that took the action
    credited with the recovery, which already says what was done, by whom and
    when - a row of the marker's own would say the same action twice.

    An end a person reported (`ended_by_a_report`) is on the line of their
    report instead, for the fourth marker's reason - and because a row of its
    own would say the service was back to normal, which is the metrics' word
    for an end they never showed.

    `back_to_normal_at` is where the service was back to normal rather than the
    recorded recovery: the document's duration ends there, and a timeline
    ending somewhere else would contradict the figure beside it. The end says
    when it came before the action credited with it (`back_before_the_action`),
    since the order of the two markers is otherwise left to be noticed.

    A marker whose moment is unknown is left out rather than placed near where
    it probably was - and so is the mitigation's where no line says it, since
    its only other moment is the row's claim, written before anything was done.
    At the same moment, the onset's and the alert's rows sort before the lines,
    because the line is the reaction: the alert fired, and Argus received it.
    The end sorts after them, because it is the effect: the action was taken,
    and the service was back. The two share an instant exactly: the end is set
    to the credited action's moment, and that moment is the `at` of the line
    that took it, not the action row's own time. Read off the row instead, the
    end would fall a fraction of a second before the line and sort ahead of it
    again.
    """
    resolution = evidence.resolution if ended_by_a_report else None
    reported = resolution.line if resolution is not None else None
    if resolution is not None:
        ended = f"{resolution.by} reported the incident resolved"
    elif back_before_the_action:
        ended = "the service was back to normal, before the action credited with it"
    else:
        ended = "the service was back to normal"
    markers = [
        *([_a_marker(evidence.onset_at, TimelineMarker.METRICS_STOP, "the metrics stopped")
           if metrics_stopped_at_onset else
           _a_marker(evidence.onset_at, TimelineMarker.IMPACT_BEGINS, "the incident began")]
          if evidence.onset_at is not None else []),
        _a_marker(evidence.alerted_at, TimelineMarker.DETECTED,
                  f"{evidence.alert_title} fired"),
        *([_a_marker(back_to_normal_at, TimelineMarker.IMPACT_ENDS, ended)]
          if back_to_normal_at is not None and reported is None else [])
    ]

    credited = evidence.credited_action
    marked = {
        **({credited.line: TimelineMarker.MITIGATION_APPLIED}
           if credited is not None and credited.line is not None else {}),
        **({reported: TimelineMarker.IMPACT_ENDS} if reported is not None else {})
    }
    narration = [entry.model_copy(update={"label": label,
                                          "text": said_of_a_line(entry),
                                          "marker": marked.get(position, entry.marker)})
                 for position, (entry, label) in enumerate(
                     zip(evidence.timeline,
                         labels_of_the_narration(evidence.timeline),
                         strict=True))]

    return sorted([*markers, *narration], key=_in_order)


def said_of_a_line(entry: TimelineEntry) -> str:
    """A line of the narration as the document and the prompt both say it: as
    it was written, except a line that formed candidates, which names them by
    the labels their rows go by.

    Said in full, such a line repeats every candidate's paragraph, which the
    hypotheses considered show under its label already - so the model would
    read each one twice with nothing to say the two are one, and a reader of
    the page would read it twice beside the row it is.

    And a line acting for a candidate, which names it by its label too: in
    the narration's words, "candidate cause #3" beside a row and a resolution
    saying C3 reads as two candidates.
    """
    label = _the_label_it_names(entry)
    if entry.for_candidate is not None and label is not None:
        return entry.text.replace(entry.for_candidate.said_as, label)

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
    """When it happened, and then which comes first at that moment: a marker's
    own row the lines react to, then the lines, as they were said, then the end
    of the impact, which is what a line at its moment brought about.

    A marker's own row by its having no label, not by its carrying a marker: a
    line the mitigation marks is still a line, and sorted as a marker it would
    jump ahead of the line said before it at the same instant."""
    if entry.label is not None:
        return entry.at, 1

    return entry.at, 2 if entry.marker is TimelineMarker.IMPACT_ENDS else 0


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

