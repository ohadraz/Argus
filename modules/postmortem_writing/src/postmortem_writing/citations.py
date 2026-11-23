"""The record's evidence as rows, each under the label a step of the cause
cites it by.

One list for the ask and the document alike: the model is shown these rows
(`prompting`), and the page lists the same rows under the same labels
(`writing`), so a label a sentence cites names the row a reader finds. Counted
twice, they would be two chances to disagree about which row `P2` is.

What each row says and the order the kinds come in are here; the headings a
kind is shown beneath, and what the writer is told beneath its rows, are the
ask's own (`prompting`).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
from typing import Final

from core import parse_iso, to_iso
from core.models import (
    ChangeEvent,
    CitedChange,
    CitedEvidence,
    DeploymentComparison,
    FailureMode,
    TimelineEntry,
    Verdict,
)
from narration import (
    for_the_candidate,
    level_said_in,
    said_as_a_share,
    short_form,
    whether_it_can_be_put_back,
)

from postmortem_writing.evidence import ActionRecord, DeploymentChangesRecord, IncidentEvidence
from postmortem_writing.figures import (
    Figure,
    the_day_it_began,
    the_levels_figures,
    the_shares_figures,
)
from postmortem_writing.labels import (
    ACTION_PREFIX,
    AS_IT_RAN_PREFIX,
    CANDIDATE_PREFIX,
    CAUSE_MEASURED_PREFIX,
    CODE_READING_PREFIX,
    DEPLOYMENT_CHANGES_PREFIX,
    PRODUCTION_CHANGE_PREFIX,
    USES_OUTSIDE_PREFIX,
    label_of,
)
from postmortem_writing.log_groups import grouped
from postmortem_writing.measuring import Measurements
from postmortem_writing.revisions import revisions_of
from postmortem_writing.sections import (
    OneCause,
    a_hypothesis_of,
    causes_of,
    labels_of_the_narration,
    said_of_a_line,
    the_alert_labelled,
    what_it_came_to,
)

# A volume's unit, joined to it as the candidates write theirs ("1200/min"), so
# the two read as one figure.
_PER_MINUTE: Final = "/min"

# Beside a change only Argus's own read of the flag provider's history found.
# Listed among the investigation's reads with nothing to tell them apart, a
# write-up credited the Investigator with ruling out a flag it never saw. Who
# found it, and no more: told also that the Investigator's read did not return
# it, a write-up repeated that as the Investigator's failing - its read ended at
# the onset by design - and the check that refuses the Investigator named beside
# such a change refused it, so the line baited the refusal it is there to spare.
_THE_WALK_ALONE_READ_IT: Final = " - found only by Argus's read of the flag provider's history"
# And why, where the record says: made after the investigation's reads of the
# changes ended, a contrast "only" leaves open was read as the changes feed
# failing to return it, and the feed was asked to be fixed.
_MADE_AFTER_THE_READS_ENDED: Final = (
    ": it came after {ended}, where the investigation's reads of the changes ended"
)


class EvidenceKind(Enum):
    """A kind of evidence the record lists beneath a heading of its own.

    In no order here: the order they are shown in is `the_evidence_by_kind`'s.
    """

    NARRATION = auto()
    CHANGES = auto()
    LOG_LINES = auto()
    CANDIDATES = auto()
    ACTIONS_TAKEN = auto()
    ACTIONS_NOT_TAKEN = auto()
    ACTIONS_UNANSWERED = auto()
    CAUSE_MEASURED = auto()
    DEPLOYMENT_CHANGES = auto()
    CODE_READING = auto()
    FILES_AS_THEY_RAN = auto()
    USES_OUTSIDE = auto()


def the_evidence_labelled(evidence: IncidentEvidence,
                          measured: Measurements) -> list[CitedEvidence]:
    """Every piece of evidence the model is shown, each under its own label:
    what the alert said, then the evidence listed beneath its headings.

    The label is what a step of the cause cites, so every line a claim could
    rest on has one and no two share it. Each kind is labelled on its own,
    and the logs by message rather than by place: a recorded answer is replayed
    in a run that read a different number of log lines, and a label counted
    across the kinds would then name a different line in every kind after the
    logs.

    `measured` says where the logs are split and the day their minutes are
    said against (`grouped`), and every reader of what the model was shown
    passes it, so the text a step cites is the text it was shown.
    """
    return [*the_alert_labelled(evidence), *the_evidence_listed(evidence, measured)]


def the_evidence_listed(evidence: IncidentEvidence,
                        measured: Measurements) -> list[CitedEvidence]:
    """The evidence listed beneath its headings, in the order it is shown."""
    return [cited
            for _, cited_of_a_kind in the_evidence_by_kind(evidence, measured)
            for cited in cited_of_a_kind]


def the_evidence_by_kind(evidence: IncidentEvidence,
                         measured: Measurements
                         ) -> list[tuple[EvidenceKind, list[CitedEvidence]]]:
    """Each kind of evidence the record lists, with its rows, in the order it
    is shown.

    The narration, the changes, the logs and the candidates are listed whether
    or not they hold anything: a heading over nothing tells the model there is
    something it has failed to see, and what is said beneath an empty one is
    the ask's (`prompting`).

    What each deployment it looked into changed and what Code-Fix read in the
    source are listed only where there is any: most incidents look into none,
    and a heading for them would say a read was missed.
    """
    # Numbered over every action, and listed under a heading for how far each
    # got: one never performed under "Actions it took" is a line saying "Did
    # not" beneath a heading saying it did, and one nobody answered is a claim
    # beneath it. The labels stay the resolution's.
    every_action = list(zip(_numbered(ACTION_PREFIX,
                                      [_an_action_as_a_line(action)
                                       for action in evidence.actions]),
                            evidence.actions, strict=True))
    actions = [line for line, action in every_action
               if action.progress.its_change_was_made() is True]
    not_taken = [line for line, action in every_action
                 if action.progress.its_change_was_made() is False]
    unanswered = [line for line, action in every_action
                  if action.progress.its_change_was_made() is None]
    cause_measured = the_cause_measured_labelled(evidence, measured)
    looked_into = the_deployment_changes_labelled(evidence)
    read_in_the_source = the_code_reading_labelled(evidence)
    as_it_ran = the_files_as_they_ran_labelled(evidence)
    uses_outside = the_uses_outside_labelled(evidence)

    return [
        (EvidenceKind.NARRATION, _the_narration_labelled(evidence)),
        (EvidenceKind.CHANGES, _the_changes_as_lines(evidence)),
        (EvidenceKind.LOG_LINES,
         grouped(evidence.log_lines, measured.metrics_stopped_at,
                 the_day_it_began(evidence, measured), acted_at=evidence.first_acted_at,
                 metrics_resumed_at=measured.metrics_resumed_at)),
        (EvidenceKind.CANDIDATES, the_candidates_labelled(evidence)),
        # "none" only where it is true: above an action nobody can say was
        # taken it says nothing was done, which nobody knows either.
        *([(EvidenceKind.ACTIONS_TAKEN, actions)] if actions or not unanswered else []),
        *([(EvidenceKind.ACTIONS_NOT_TAKEN, not_taken)] if not_taken else []),
        *([(EvidenceKind.ACTIONS_UNANSWERED, unanswered)] if unanswered else []),
        # Beside what Argus did about the load, and before Code-Fix's reading.
        *([(EvidenceKind.CAUSE_MEASURED, cause_measured)]
          if cause_measured and the_load_confirmed(evidence) is not None else []),
        *([(EvidenceKind.DEPLOYMENT_CHANGES, looked_into)] if looked_into else []),
        *([(EvidenceKind.CODE_READING, read_in_the_source)] if read_in_the_source else []),
        *([(EvidenceKind.FILES_AS_THEY_RAN, as_it_ran)] if as_it_ran else []),
        *([(EvidenceKind.USES_OUTSIDE, uses_outside)] if uses_outside else [])
    ]


def _the_narration_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Each line of the narration, under its label."""
    return [CitedEvidence(label=label, text=_a_line_of_the_narration(entry))
            for entry, label in zip(evidence.timeline,
                                    labels_of_the_narration(evidence.timeline),
                                    strict=True)]


def _the_changes_as_lines(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Each change to production the investigation read, as a line under its
    label - with who found it, where only the walk's own read did."""
    walk_alone = evidence.changes_the_walk_alone_read

    return [CitedEvidence(label=cited.label,
                          text=_a_change_as_a_line(cited.change)
                               + (_who_found_it(cited.change, evidence)
                                  if cited.change in walk_alone else ""))
            for cited in the_changes_labelled(evidence)]


def the_files_as_they_ran_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Each file Code-Fix's reading names that ran as other text than the
    branch read, under the label the model is shown it by - named by its path
    and the revision, then the file - or nothing, where there is none.

    Six of six write-ups called the file the cause turned on "Code-Fix's
    reading, nothing ran": right about where the text came from, since nothing
    in the record held the file as it ran. Public because the document lists
    it under the same label the prose cites it by, as it does the changes.

    Numbered in the order of their paths, not the order the reading names
    them: a reworded reading swapped two files' labels under a write-up
    recorded against the old ones, citing each for the other's claim.

    Each where it opens at the revision that ran, off the deploy read of that
    revision: the document names the file and leaves its text to the model,
    so a reader needs somewhere to open it. Nowhere, where no deploy read
    says where its files open.
    """
    shown = sorted((ran for ran in evidence.files_as_they_ran
                    if not ran.as_read and ran.content),
                   key=lambda ran: ran.path)
    files_open_at = {change.reference: change.revision_source.files_address
                     for change in evidence.changes
                     if change.revision_source is not None
                     and change.revision_source.files_address is not None}

    return [CitedEvidence(label=label_of(AS_IT_RAN_PREFIX, position),
                          text=f"{ran.path} at {ran.revision[:7]}\n{ran.content}",
                          address=(f"{files_open_at[ran.revision]}/{ran.path}"
                                   if ran.revision in files_open_at else None))
            for position, ran in enumerate(shown, start=1)]


def the_uses_outside_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Each line outside Code-Fix's patch that uses what it changes, and what
    the line does, under the label the model is shown it by - or nothing, where
    there is none.

    A write-up wrote "nothing derived the month from history" from a reading
    that counted the one reader adding the month up to check it among the ones
    trusting it. What each of those lines does is the code's to say. Public
    because the document lists it under the same label the prose cites it by,
    as it does the changes.
    """
    return [CitedEvidence(label=label_of(USES_OUTSIDE_PREFIX, position),
                          text=f"{use.name} at {use.path}:{use.line}"
                               f"{f', in {use.function}' if use.function else ''}: {use.does}")
            for position, use in enumerate(evidence.uses_outside, start=1)]


def the_code_reading_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """What Code-Fix said of the code, under the label the model is shown it
    by - or nothing, where it said nothing.

    Public because the document lists it under the same label the prose cites
    it by, as it does the changes.
    """
    if evidence.fix_explanation is None:
        return []

    return [CitedEvidence(label=label_of(CODE_READING_PREFIX, 1), text=evidence.fix_explanation)]


def the_deployment_changes_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """What each deployment the investigation looked into changed, under the
    label the model is shown it by - every line as it was read, one to a line.

    A deployment nothing was compared for is said in the write-up's own words:
    the read tier's answer was written for the Investigator, bracketed for a
    model and with advice to one - "what it shipped can [be read], by reading
    the repository" - which write-ups proposed as an item. It is a fact about
    the history rather than a diff, and its row says what the history held.

    Public because the document lists them under the same labels the prose
    cites them by, as it does the changes.
    """
    return _numbered(DEPLOYMENT_CHANGES_PREFIX,
                     [_what_a_deployment_read_found(looked_into)
                      for looked_into in evidence.deployment_changes])


def _what_a_deployment_read_found(looked_into: DeploymentChangesRecord) -> str:
    """A deployment's diff, every line as it was read - or, where nothing was
    compared, what the history held instead."""
    match looked_into.comparison:
        case DeploymentComparison.COMPARED:
            return "\n".join(looked_into.said)
        case DeploymentComparison.NOTHING_BEFORE_IT:
            return (f"{looked_into.revision} is the earliest deployment of "
                    f"{looked_into.service} the deployment history holds, so there was "
                    f"nothing before it to compare it against, and what it changed was not "
                    f"read.")
        case DeploymentComparison.NOT_DEPLOYED:
            return (f"The deployment history holds no deployment of {looked_into.service} "
                    f"at revision {looked_into.revision}, so nothing was compared.")


def the_changes_labelled(evidence: IncidentEvidence) -> list[CitedChange]:
    """Each change to production the investigation read, under the label the
    model is shown it by, with its reference as the prose writes it.

    Public because the document lists the changes under the same labels the
    prose cites them by, and a second counting would be a second chance to
    disagree about which change `P2` is. A revision is written short as the
    prose writes it (`revisions`), so a row and a sentence name it alike.
    """
    revisions = revisions_of(evidence)

    return [CitedChange(label=label_of(PRODUCTION_CHANGE_PREFIX, position),
                        change=change,
                        short_reference=(short_form(change.reference, revisions)
                                         if change.reference in revisions
                                         else change.reference))
            for position, change in enumerate(evidence.changes, start=1)]


def the_candidates_labelled(evidence: IncidentEvidence) -> list[CitedEvidence]:
    """Each candidate cause the investigation formed, under the label the model
    is shown it by.

    Public because a step of the cause may not rest on one - a candidate is a
    hypothesis, not evidence - and the check refusing such a step has to know
    which labels these are.
    """
    return [CitedEvidence(label=cause.label, also=cause.also, text=_a_cause_as_a_line(cause))
            for cause in causes_of(evidence.candidates)]


def the_cause_measured_labelled(evidence: IncidentEvidence,
                                measured: Measurements) -> list[CitedEvidence]:
    """What the metrics show of a cause confirmed to be the load, each series
    under its own label: the requests a minute, and the CPU in use against its
    limit where a limit was read. Nothing where no candidate confirmed is the
    load, or none was measured.

    Rows rather than figures, because every step of the cause cites a row: told
    the volume only in the candidate's words, which a step may not cite, a
    write-up rested the root cause on Code-Fix's reading of a slow default -
    the one deeper row it could cite. Public because the document lists them
    under the labels the prose cites them by.

    Each volume in its unit, as the candidate's are: said once before the
    figures, the model said it again after a name, in words the check refuses.
    """
    return [cited for cited, _ in the_cause_measured(evidence, measured)]


def the_cause_measured(evidence: IncidentEvidence, measured: Measurements
                       ) -> list[tuple[CitedEvidence, Callable[[CitedEvidence],
                                                                dict[str, Figure]]]]:
    """The load's rows, each with what reads its figures as what they measure:
    the volumes as levels, the CPU as shares."""
    demand = measured.demand
    if the_load_confirmed(evidence) is None or demand is None:
        return []

    requests = demand.requests
    cpu = demand.cpu_share
    rows = [
        (f"Requests: {_a_minute_s(requests.before)} before it began, "
         f"{_a_minute_s(requests.while_broken)} on average while it was broken, "
         f"{_a_minute_s(requests.at_its_highest)} at its highest.", the_levels_figures),
        *([(f"CPU in use, as a share of the service's CPU limit: "
            f"{said_as_a_share(cpu.before)} before it began, "
            f"{said_as_a_share(cpu.while_broken)} on average while it was broken, "
            f"{said_as_a_share(cpu.at_its_highest)} at its highest.", the_shares_figures)]
          if cpu is not None else [])
    ]

    return list(zip(_numbered(CAUSE_MEASURED_PREFIX, [line for line, _ in rows]),
                    [figures for _, figures in rows], strict=True))


def _a_minute_s(requests: float) -> str:
    """A volume as a rate, the one word `is_a_figure` reads it as."""
    return f"{level_said_in(requests, None)}{_PER_MINUTE}"


def the_load_confirmed(evidence: IncidentEvidence) -> str | None:
    """The label of the candidate the record confirmed as the load - wherever
    the investigation ranked it - or `None` where none was."""
    return next((label
                 for cause in causes_of(evidence.candidates)
                 for label, candidate in cause.members
                 if candidate.tested and candidate.result == Verdict.CONFIRMED
                 and candidate.failure_mode == FailureMode.DEMAND_SATURATION), None)


def _numbered(prefix: str, lines: list[str]) -> list[CitedEvidence]:
    return [CitedEvidence(label=label_of(prefix, position), text=line)
            for position, line in enumerate(lines, start=1)]


def _a_line_of_the_narration(entry: TimelineEntry) -> str:
    """One line of the narration, worded as the document's timeline words it -
    the candidates it formed named by label."""
    return f"{to_iso(entry.at)} {entry.who}: {said_of_a_line(entry)}"


def _who_found_it(change: ChangeEvent, evidence: IncidentEvidence) -> str:
    """Said beside a change only the walk's own read of the flag history found:
    that it did, and that it was made after the investigation's reads of the
    changes ended, where it was.

    Nothing more where it was made at or before that end: whether a read should
    have returned it is not something the record settles.
    """
    ended = evidence.change_reading_ended
    if ended is None or parse_iso(change.occurred_at) <= ended:
        return _THE_WALK_ALONE_READ_IT

    return _THE_WALK_ALONE_READ_IT + _MADE_AFTER_THE_READS_ENDED.format(ended=to_iso(ended))


def _a_change_as_a_line(change: ChangeEvent) -> str:
    """A change the investigation read: when, what kind, to what, by whom, and
    what it did.

    The instant to the second whatever its source wrote, and a change nobody is
    named for said to be, rather than shown with a blank where the name goes.
    """
    return (f"{to_iso(parse_iso(change.occurred_at))} {change.kind} {change.reference} "
            f"by {change.actor or 'someone unnamed'}: {change.summary}")


def _a_cause_as_a_line(cause: OneCause) -> str:
    """A cause in its candidate's words, its failure mode, its confidence, and
    what became of it - or, where it stands for several, a line naming the
    move they blame and each of them so on a line of its own.

    Said in the first one's words alone, a cause standing for several
    shows one candidate's words and confidence as all of theirs, and the
    verdict as reached by each. So each says what became of it as the page's
    row does (`result_of`): two spellings of one fact read as two facts.

    Where every one reads the move as a different kind of failure, the heading
    says so, and that they are not one cause counted twice. Told only that they
    blamed the same move, a write-up faulted the Investigator for giving one
    change as two candidates - of two readings it rested on telling apart.
    Where only some differ, it is said of none: of the ones alike, it is false.
    """
    if not cause.also:
        lead = cause.lead
        return _in_its_own_words(lead.summary, lead.failure_mode, lead.confidence, cause.became)

    considered = a_hypothesis_of(cause)
    read_apart = (len({member.failure_mode for member in considered.members})
                  == len(considered.members))
    how = (" each reading it as a different kind of failure - different accounts of what it "
           "did, not one cause counted twice -" if read_apart else "")

    return "\n".join([
        f"Candidates blaming the same move of {cause.lead.subject},{how} each in its own words:",
        *(f"{member.label}: " + _in_its_own_words(member.summary, member.failure_mode,
                                                  member.confidence,
                                                  considered.result_of(member))
          for member in considered.members)
    ])


def _in_its_own_words(summary: str,
                      failure_mode: str | None,
                      confidence: float | None,
                      became: str) -> str:
    """A candidate in the Investigator's words, its failure mode, its
    confidence, and what became of it - only the last for a candidate that
    names no cause, which has neither, and said as "None" they read as values."""
    if failure_mode is None and confidence is None:
        return f"{summary} [{became}]"

    return f"{summary} [{failure_mode}, confidence {confidence}, {became}]"


def _an_action_as_a_line(action: ActionRecord) -> str:
    """An action, the candidate it was for, whether it left anything to put
    back, its verdict, and whether it still stands.

    The candidate because nothing else in the brief says it: the move to
    mitigating names none, and a write-up told an action was taken after
    "to act on the leading candidate" credited it to the leader - and called
    the candidate it was for never acted on.

    Whether it can be put back is said in the page's own words: the brief said
    nothing of it, and a model guessed "reversible" a section away from a row
    saying "irreversible" - both the autonomy tier's words, about a restart.
    Only where there is a way back: one with none stands as "nothing to put
    back", and the same words beside it said it twice on one line.
    """
    way_back = (f" ({whether_it_can_be_put_back(action.has_a_way_back,
                                                action.left_behind_known)})"
                if action.has_a_way_back else "")
    candidate = (f" {for_the_candidate(f'[{label_of(CANDIDATE_PREFIX, action.candidate)}]')}"
                 if action.candidate is not None else "")
    return (f"{action.action}{candidate}{way_back} - "
            f"{what_it_came_to(action.verdict, action.progress)}, {action.standing}")
