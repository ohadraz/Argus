"""The sections a postmortem has beyond its figures, each as the value it is.

The template is Google's (SRE book, ch. 15, and the example postmortem it links)
with ClickHouse's root-cause guidance folded into the cause: a chain of steps
that each cite what they rest on, and contributing factors that each name the
action item answering them. A section is a value rather than a paragraph for
the reason the figures are: two places render the document - the page and the
file sent onwards - and two renderers parsing one paragraph are two documents.

Which of these code writes and which the model writes is the agent's business,
not this module's. What is said here is only the shape each section has once
written.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, model_validator

from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.metrics import WorseWhen
from argus_core.models.refusal import Refusal
from argus_core.models.report import ReportChannel


class CitedEvidence(BaseModel):
    """One piece of evidence a step of the cause rests on: the label the prompt
    gave it, and what that label named.

    The text travels with the label because the label means nothing outside the
    prompt it was given in, and the stored document has to be readable without
    one.
    """

    label: str
    text: str
    # The other labels the same evidence was shown under - a candidate that is
    # one cause with another goes by both - so a citation of either is known
    # for what it names. Its figures are named by `label` alone.
    also: list[str] = []
    # Where a reader opens it, where it can be opened: a file as it ran, at the
    # revision that ran. `None` for everything else, and on a document written
    # before it was carried.
    address: str | None = None


class CitedChange(BaseModel):
    """A change to production the model was shown, under the label the prose
    cites it by.

    The change itself rather than the line the model read, so whoever shows it
    can lay out its parts - when, what, by whom, and where it can be opened -
    and `short_reference` is its reference as the prose writes it: a revision in
    its short form, and anything else, a flag's name, as given.
    """

    label: str
    change: ChangeEvent
    short_reference: str


class RuledOut(BaseModel):
    """Something else the record ruled out, and what ruled it out."""

    text: str
    cites: list[CitedEvidence]


class ChainStep(BaseModel):
    """One step from the symptom towards the cause, what it rests on, and what
    else the record ruled out there.

    What was ruled out is the step's own list rather than a step of the chain:
    told twice in words to say it at the step that ties the incident to the
    change, write-ups made it a why of its own. Empty on every step but that
    one, and on a document written before it was carried.
    """

    text: str
    cites: list[CitedEvidence]
    ruled_out: list[RuledOut] = []


class ContributingFactor(BaseModel):
    """A condition that was necessary and not sufficient, and the action items
    that answer it, by number (`AI-2`).

    Plural on purpose: a cause in a system of any size is a set of conditions
    that each had to hold, and a document naming one of them invites a fix to
    that one and leaves the others standing.
    """

    text: str
    addressed_by: list[str]


class ActionItemType(StrEnum):
    """What an action item is for, in Google's four kinds."""

    MITIGATE = "mitigate"
    PREVENT = "prevent"
    DETECT = "detect"
    PROCESS = "process"


class ActionItemStatus(StrEnum):
    DONE = "done"
    OPEN = "open"


class ActionItem(BaseModel):
    """One thing to do, numbered so it can be named in conversation.

    `owner` and `tracking` are `None` where nobody holds the item and nothing
    tracks it: Argus edits no action item after the document is written, so an
    open item is unowned until a person takes it on somewhere else.
    """

    number: str
    text: str
    type: ActionItemType
    owner: str | None
    tracking: str | None
    status: ActionItemStatus


class Lessons(BaseModel):
    """Google's three lists. Any of them may be empty; an incident with nothing
    lucky about it is an answer, not a gap."""

    went_well: list[str] = []
    went_wrong: list[str] = []
    got_lucky: list[str] = []


class DetectionMeasuredFrom(StrEnum):
    """What the time to the alert is weighed from: the onset; the onset where
    what it dates is the metrics stopping; or the first minute the rule's own
    series was past its line, where a fault that grows reached it later."""

    ONSET = "onset"
    METRICS_STOPPED = "metrics stopped"
    LINE_PASSED = "line passed"


class DetectionLesson(BaseModel):
    """How soon the alert came against what the rule spends before it can
    fire - written by code from what was measured, never by the model.

    `gap` runs from `measured_from` to the alert. The parts it is weighed
    against are each carried as read, so the page can say what accounts for
    the time and not only how much: the rule's wait, the look-back its
    condition fills (nothing where the gap runs from the series' own line,
    whose readings already hold it), how often it is evaluated, and the time
    the samples take to be scraped and stored, which Argus does not read. The
    whole minute the start is measured to is the page's to add.
    """

    gap: timedelta
    measured_from: DetectionMeasuredFrom
    rule_waits: timedelta
    rule_looks_back: timedelta
    rule_evaluated_every: timedelta
    scraping_and_storing: timedelta


class DetectionPart(StrEnum):
    """Each span the lesson on detection says - for whoever shows it to say
    each in its own way: the page as a span, the brief by the figure's name."""

    GAP = "gap"
    RULE_WAITS = "rule_waits"
    RULE_LOOKS_BACK = "rule_looks_back"
    RULE_EVALUATED_EVERY = "rule_evaluated_every"
    SCRAPING_AND_STORING = "scraping_and_storing"
    ACCOUNTED_FOR = "accounted_for"
    BEYOND = "beyond"


# The whole minute each start is measured to, which the time from it to the
# alert can hold without the rule having spent any of it.
_A_WHOLE_MINUTE: Final = timedelta(minutes=1)

# What the gap runs from, as the sentence says it after "The alert came 5
# minutes" - only where it runs from its series passing its line, since the
# Detection section says the gap from any other start - and the whole minute
# each start is measured to, as its last part.
_AFTER_ITS_LINE: Final = "after its series passed its line"
_THE_WHOLE_MINUTE: Final = {
    DetectionMeasuredFrom.ONSET: "the whole minute the onset is measured to",
    DetectionMeasuredFrom.METRICS_STOPPED: "the whole minute the metrics' stopping is measured to",
    DetectionMeasuredFrom.LINE_PASSED: "the whole minute its series is read in"
}

_WHAT_TOOK_THE_REST: Final = "The record does not show what took the rest."


def accounted_for(lesson: DetectionLesson) -> timedelta:
    """Everything the rule and the reading spend before the alert can come."""
    return (lesson.rule_waits + lesson.rule_looks_back + lesson.rule_evaluated_every
            + lesson.scraping_and_storing + _A_WHOLE_MINUTE)


def within_what_was_accounted_for(lesson: DetectionLesson) -> bool:
    """Whether the alert came within what was accounted for, to the second."""
    return lesson.gap <= accounted_for(lesson)


def the_detection_lesson_said(lesson: DetectionLesson,
                              span: Callable[[DetectionPart, timedelta], str]) -> str:
    """The lesson as one sentence: how long after its start the alert came,
    how that stands against what was accounted for, and each part of that -
    a part of nothing left out, since it spends no time. Each span said by
    `span`, with the part it is.

    How long only where it runs from where the Detection section's does not:
    from the onset, or the metrics stopping it dates, Detection says it, and
    said here as well, a page told it twice.

    Here rather than with whoever shows it, because the page and the brief the
    model writes from both say it, and two spellings of one weighing read as
    two - one of them a lag the other counts as the rule's own time.
    """
    parts = [
        *((f"its rule waiting {span(DetectionPart.RULE_WAITS, lesson.rule_waits)} with its "
           f"condition holding",) if lesson.rule_waits else ()),
        *((f"its condition looking back over "
           f"{span(DetectionPart.RULE_LOOKS_BACK, lesson.rule_looks_back)}",)
          if lesson.rule_looks_back else ()),
        *((f"its evaluation at intervals of "
           f"{span(DetectionPart.RULE_EVALUATED_EVERY, lesson.rule_evaluated_every)}",)
          if lesson.rule_evaluated_every else ()),
        # An allowance nobody measured, said as one: in the voice of the
        # rule's own parts it would read as a fact about the stack.
        *((f"an unmeasured allowance of "
           f"{span(DetectionPart.SCRAPING_AND_STORING, lesson.scraping_and_storing)} for "
           f"scraping and storing its samples",) if lesson.scraping_and_storing else ()),
        _THE_WHOLE_MINUTE[lesson.measured_from]
    ]
    by = ", ".join(parts[:-1]) + f" and {parts[-1]}" if len(parts) > 1 else parts[0]
    total = span(DetectionPart.ACCOUNTED_FOR, accounted_for(lesson))
    went_well = within_what_was_accounted_for(lesson)
    gap_said = lesson.measured_from is DetectionMeasuredFrom.LINE_PASSED
    against = (f"within the {total}" if went_well
               else f"{span(DetectionPart.BEYOND, lesson.gap - accounted_for(lesson))} "
                    f"{'more' if gap_said else 'later'} than the {total}")
    # A rule can spend time the rule Argus reads does not say - an absence
    # check's own dwell - so the rest is said to be unknown rather than left
    # to read as detection's fault.
    unknown = "" if went_well else f" {_WHAT_TOOK_THE_REST}"
    came = f"{span(DetectionPart.GAP, lesson.gap)} {_AFTER_ITS_LINE}, " if gap_said else ""

    return f"The alert came {came}{against} accounted for by {by}.{unknown}"


class TimelineMarker(StrEnum):
    """The four moments a reader looks for first in a timeline - the first of
    them where the metrics stop at the onset said as that, since what the onset
    dates then is the metrics stopping, and the service may never have been
    hurt at all."""

    IMPACT_BEGINS = "impact begins"
    METRICS_STOP = "metrics stop"
    DETECTED = "detected"
    MITIGATION_APPLIED = "mitigation applied"
    IMPACT_ENDS = "impact ends"


class ForCandidate(BaseModel):
    """The candidate a line acted for: its place among the incident's
    candidates as the document lists them, and the words the line names it in
    - so the document can say it by the label its row goes by instead, as it
    says the candidates a line formed."""

    place: int
    said_as: str


class TimelineEntry(BaseModel):
    """One moment of the incident. `who` is `None` on a marker no agent said -
    the onset is a property of the metrics, not a line anybody wrote."""

    at: datetime
    who: str | None
    text: str
    marker: TimelineMarker | None = None
    # Where, among the incident's candidates as the document lists them, the
    # ones this line formed sit - so a reader of both can be pointed from one
    # to the other rather than told the same candidate twice. Empty on every
    # line that formed none.
    candidates: list[int] = []
    # The candidate this line acted for, where it names one - an action taken
    # or reached for, a refusal, a recommendation. `None` on every other line.
    for_candidate: ForCandidate | None = None
    # The other incident this line is about, where it is about one - an earlier
    # one memory found - so the document can lead a reader there as the walk
    # page does. Named by a whole id, which is no name to look up by hand.
    names_incident: str | None = None
    # The label the document's prose cites this line by (`T1`). `None` on a
    # marker: code placed it among the lines, and no prose was shown it to cite.
    label: str | None = None
    # Whether a person's timing, or the relay's, put this line where it is
    # rather than a step of the walk - which is why it is labelled apart from
    # the walk's lines (`XW1`), so a message written a second earlier renames
    # nothing the walk said.
    outside_the_walk: bool = False
    # Whether the line says only that an agent was called in, which the line
    # after it - the agent at work - says already. The postmortem's page leaves
    # it out where nothing cites it; the incident's own page keeps every line.
    an_agent_called_in: bool = False


class CandidateConsidered(BaseModel):
    """One of the candidates a row of the hypotheses stands for, in its own
    words, mode and confidence - under the label it is cited by."""

    label: str
    summary: str
    confidence: float | None
    failure_mode: str | None


class HypothesisConsidered(BaseModel):
    """One candidate the Investigator formed, and what became of it - under
    the label the document's prose cites it by (`C1`)."""

    summary: str
    confidence: float | None
    result: str
    label: str
    # The labels of the candidates this row also stands for: ones that blamed
    # the same move of the same subject and came to the same end, shown once
    # rather than read as causes weighed apart. Each keeps its own label, so a
    # line citing it still has this row to lead to.
    also: list[str] = []
    # Where the row stands for several, each of them as it was ranked, best
    # first, and the label of the one whose test says what became of the row:
    # shown as the row's own, one candidate's figures read as another's. Empty
    # and `None` on a row of one, and on a document written before either was
    # carried.
    members: list[CandidateConsidered] = []
    decided_by: str | None = None

    def result_of(self, member: CandidateConsidered) -> str:
        """What became of one of the candidates the row stands for: the row's
        result, and whose test it was where that was another's.

        Here rather than with whoever shows it, because the page and the brief
        the model writes from both say it, and two spellings of one fact read
        as two facts.
        """
        if self.decided_by and self.decided_by != member.label:
            return f"{self.result}, as tested for {self.decided_by}"

        return self.result


class ResolutionStep(BaseModel):
    """One thing done to end the incident, by whom, and what it came to -
    under the label the document's prose cites it by (`M1`). `None` on a
    refusal to act: nothing was done, and no prose cites it as an action."""

    at: datetime
    action: str
    by: str
    has_a_way_back: bool
    outcome: str
    label: str | None
    # The two halves of `outcome` - what the action came to, and whether it
    # still stands - for the one place that says the second beside a column
    # that may say it already. `None` for a standing on a refusal, which
    # leaves nothing, and for both on a document written before they were
    # carried.
    came_to: str | None = None
    standing: str | None = None
    # Which refusal a step is, on a refusal to act, and `None` on an action -
    # what the review reads to say whether the next step is a person's: a test
    # refused as not Argus's to take is the analysis gone as far as Argus may.
    refused: Refusal | None = None
    # Whether the action stopped the platform syncing the application from its
    # repository, and left it stopped while the change stands. Apart from the
    # outcome, which is cited wherever the action is: said inside it, the sync
    # is said in every place that cites the action. `False` on a document
    # written before it was carried, whose outcome says it already.
    sync_left_off: bool = False
    # Whether what the step left behind is known - false for an action whose
    # change request may have landed with nobody able to say, which is not one
    # with nothing to put back. `True` on a document written before it was
    # carried, which is what such a document claimed.
    left_behind_known: bool = True
    # The label of the candidate the step was for (`C3`) - an action's, or a
    # refusal's, whose words name it already - and `None` on a step for none
    # and on a document written before it was carried. The move to mitigating
    # names no candidate, so a step whose row does not either is read as the
    # leading one's.
    candidate: str | None = None


def for_the_candidate(label: str) -> str:
    """Which candidate an action was for, in the words every place showing it
    uses - the page's resolution and the brief the model writes from. Here for
    `whether_it_can_be_put_back`'s reason: two spellings of one fact read as
    two facts."""
    return f"for {label}"


def whether_it_can_be_put_back(has_a_way_back: bool, left_behind_known: bool) -> str:
    """Whether an action left something to put back, in the words every place
    showing it uses.

    Not "reversible" and "irreversible": those two name the autonomy tier
    (spec §13), where irreversible is the kind of action Argus never takes
    unasked. A restart has nothing to put back and is on the safe side of that
    line, and a page calling it irreversible said Argus had broken its own rule.

    Here rather than with whoever shows it, because the page and the brief the
    model writes from both say it, and two spellings of one fact read as two
    facts.

    An action nobody can account for is not said to leave nothing: it may have
    changed something nobody recorded. What it does carry can be put back.
    """
    if has_a_way_back:
        return "can be put back"

    return "nothing to put back" if left_behind_known else (
        "not known whether anything is left to put back"
    )


def shorter_than_the_rules_wait(waits_said: str, held_before_the_onset: bool | None) -> str:
    """An alert that came sooner after the onset than its rule's condition
    must hold, said with what the series bore out - in the words every place
    showing it uses.

    `waits_said` is the wait as the place showing it says a span, which is the
    one thing they do not share: the page writes its own, the brief the figure
    with its name. `held_before_the_onset` is whether the rule's series was
    past its line in every minute the wait reaches back to before the onset -
    `None` where that was not read, which says nothing of it.

    Here rather than with whoever shows it, because the page and the brief the
    model writes from both say it, and two spellings of one fact read as two
    facts.
    """
    shorter = f"shorter than the {waits_said} its rule's condition must hold before it fires"

    if held_before_the_onset is True:
        return f"{shorter}, so the condition held before the measured onset"

    if held_before_the_onset is False:
        return (f"{shorter}, though not every minute of that wait before the measured "
                f"onset met it")

    return shorter


class FirstTold(BaseModel):
    """When Argus first posted about the incident where people could read it,
    and on which chat platform.

    `at` is when the platform accepted that post - the moment the thread it
    opened was written down - and not when the alert came: an opening post the
    platform refused leaves the first line said after it to open the thread.
    `channel` names the platform as a thread's reference does, by its report
    channel. Nothing says anybody read it.
    """

    channel: ReportChannel
    at: datetime


class Detection(BaseModel):
    """How the incident came to be known about.

    `gap` is carried rather than left to each reader's subtraction: two
    renderers of one document subtracting separately are two chances to
    disagree. `None` with `onset_at`, where no onset was measured.

    `said` is what the alert said of its own finding, under the label the
    prose cites it by - so a citation of it leads to a row like any other's.
    `None` where its sender said nothing of its own.

    `rule_waits` is how long the paging rule's condition must hold before it
    fires, which is said beside the gap and never inside it. `None` where no
    rule paged, or where its wait could not be read, which `rule_wait_unread`
    says - a rule nobody could read is not one that fires at once. Both
    default to saying nothing, which a document written before either was
    carried reads as.

    `held_before_the_onset` is whether the series the rule evaluates was past
    its line in every minute its wait reaches back to before the onset - what
    an alert sooner after the onset than the wait claims, and what only the
    writer, holding the series, can check. `None` where no minute there was
    read, or the line, the wait or the onset was not.

    `first_told` is when Argus first posted about the incident where people
    could read it - written by code, because a write-up whose model was told
    only that nobody was paged said nobody was told at all. `None` where no
    post was accepted, and in a document written before it was carried.
    """

    alerted_at: datetime
    rule: str | None
    onset_at: datetime | None
    gap: timedelta | None
    said: CitedEvidence | None = None
    rule_waits: timedelta | None = None
    rule_wait_unread: bool = False
    held_before_the_onset: bool | None = None
    first_told: FirstTold | None = None

    @model_validator(mode="after")
    def _a_wait_read_is_not_unread(self) -> Detection:
        """Refuse a wait that was read and could not be: the page would say
        both, and a reader could believe neither."""
        if self.rule_waits is not None and self.rule_wait_unread:
            raise ValueError("A rule's wait cannot be both read and unread.")

        return self


class ImpactExtent(StrEnum):
    """What a duration is: a measurement, one ended by a person's report, a
    floor, a stretch the metrics carry nothing of - or none at all, the alarm
    having been disproven.

    Five rather than a flag, because the two ways a duration falls short of a
    measurement are different facts: a service still failing when the metrics
    ran out, and a service whose metrics stopped at the onset - which says
    nothing of whether it was failing at all. And an end a person reported is
    not one the metrics showed: their report is the fact (spec §16), and said
    as the metrics', it is credited to what never measured it.

    A disproven alarm is the ending for an incident there was none of: no
    minute departed, so there is no stretch to measure, and measured from the
    alert to the close it read as a service broken for seconds and never back.
    """

    MEASURED = "measured"
    REPORTED = "reported"
    AT_LEAST = "at least"
    METRICS_MISSING = "metrics missing"
    DISPROVEN = "disproven"


class ErrorRateLevels(BaseModel):
    """The error rate before the incident began and on average while it ran,
    and whether that was a rise measured beyond what the rate reaches alone.

    Carried where it did not rise as much as where it did: a rate left off the
    page reads as one nobody measured, and a write-up saying the pages kept
    loading rests on this one. `rose` is `None` where the rate went above the
    calm and nobody could say how high it goes alone: "no rise" is a claim, and
    nothing measured it.
    """

    before: float
    while_broken: float
    rose: bool | None


class RuleSeriesHarm(BaseModel):
    """What the series the paging rule evaluates did, where it got worse: before
    the incident began, on average while it ran, and at its worst minute - in
    whatever unit the rule watches, which only the rule knows.

    The direction travels with the levels, because a worst that is the lowest
    of a share and one that is the highest of a latency read alike as numbers.

    `line` is the threshold the rule pages past, in the same unit: what lets a
    reader bridge the levels to the alert's words, which may say "80%" of a
    series read as 0.8, without anything guessing a unit. `None` where it could
    not be read.

    `unit` is the unit the levels and the line are in, as Grafana names it, and
    `None` where nothing said one - which a document written before the unit was
    carried reads as.

    `is_the_error_rate` is the series being the very query the error rate is
    read by: then its worst minute is the peak error rate, already said, and is
    not said again beside it.
    """

    before: float
    while_broken: float
    at_its_worst: float
    worse_when: WorseWhen
    line: float | None = None
    unit: str | None = None
    is_the_error_rate: bool = False


class RuleSeriesBeforeTheAlert(BaseModel):
    """What the series the paging rule evaluates read over the minutes the rule
    looked at before it fired - its wait, and how far its condition looks
    back: the lowest and the highest, and the first and last minute read.

    The grounds of a disproof, in figures. The alarm claims its condition held,
    and these are the minutes it claims it held in: given only that no minute
    departed, a reader takes the disproof on trust.

    `line`, `unit` and `is_the_error_rate` as on `RuleSeriesHarm`, so the two
    say a level alike.
    """

    lowest: float
    highest: float
    first_minute: datetime
    last_minute: datetime
    line: float | None = None
    unit: str | None = None
    is_the_error_rate: bool = False


class LogsInTheGap(BaseModel):
    """What the service's own logs show of a stretch its metrics missed: the
    one account there is of how it was doing there.

    `labels` are the log rows with a line inside the stretch, in the order
    they were first logged, and `reach_until` the last minute any of them was
    logged in - `None` with no rows. `read_until` is where the reading of the
    logs ended, since where the lines stop is as often where the reading did,
    and `read_until_the_alert` whether it ended at the alert, which is where
    it ends unless the investigation asked for more. `read` is whether any
    were read at all: a read that came back empty is a read, and the service
    gone quiet in its logs too is not nobody having looked.

    `serving_as_before` is whether those rows show the service serving as it
    had before the metrics stopped - the model's reading of them, and the one
    thing here it gives. Said by the document from this rather than by the
    model in prose: told to bound the claim, a write-up bounded it in one
    sentence and said it unbounded in the next. `None` where it was not asked,
    which is wherever no row reaches in.
    """

    read: bool
    labels: list[str]
    reach_until: datetime | None
    read_until: datetime | None
    read_until_the_alert: bool
    serving_as_before: bool | None = None


class Impact(BaseModel):
    """How long the service was broken, what that duration is, and how bad it
    got at its worst.

    The duration is carried rather than left to each reader's subtraction of
    the timeline's markers, for `Detection.gap`'s reason. `peak_error_rate` and
    `requests_failed` are `None` where the metrics could not be read, and so
    is `error_rates`.

    `rule_series_harm` is `None` wherever the series held, or none was read:
    the series is what paged, so where it got worse it is harm whatever the
    failed requests did, and where it did not it is none. Both default to
    `None`, which a document written before either was carried reads as.

    `logs_in_the_gap` is what the logs show where the metrics stopped, and
    `None` where they never did - or on a document written before it was
    carried.

    `before_the_alert` is the rule's series over the minutes it looked at
    before firing, on a disproven alarm - its grounds in figures - and `None`
    on any other ending, or where no minute there carried the series. A
    disproven alarm's duration is nothing: there was no stretch to measure.

    `metrics_read` is `False` where no minute of the metrics came back for the
    incident window at all, which leaves collecting them to a person; `True`
    otherwise, which a document written before it was carried reads as.
    """

    duration: timedelta
    extent: ImpactExtent
    peak_error_rate: float | None
    requests_failed: int | None = None
    error_rates: ErrorRateLevels | None = None
    rule_series_harm: RuleSeriesHarm | None = None
    logs_in_the_gap: LogsInTheGap | None = None
    before_the_alert: RuleSeriesBeforeTheAlert | None = None
    metrics_read: bool = True


class Trigger(BaseModel):
    """The change the confirmed cause blamed. `changed_at` is `None` where no
    retrieved change dated it, `kind` where none said what sort of change it
    was - a subject's name alone does not say whether it is a flag - and
    `actor` where the source named nobody.

    `suspected` where nothing confirmed the cause and nothing refuted it: the
    leading candidate was never tested, and the change it blames was read.
    Said as suspected, because a trigger nothing tested is not one.

    `carried_by` is the label of the change to production that carried it,
    where that is not the trigger itself: a setting that moved in a deploy is
    dated and credited as the deploy is, and the deploy is named by its row.
    `None` wherever the trigger is a change of its own, or nothing says what
    carried it.

    `dated_by` is the label of the change read that is the trigger itself and
    dates it - carried out of where it was chosen, since a second search for
    it, by its instant, finds whichever change of that instant is listed first.
    `None` where it is carried by a deploy, or no change read is it."""

    subject: str
    from_state: str | None
    to_state: str | None
    changed_at: datetime | None
    kind: ChangeKind | None = None
    actor: str | None = None
    suspected: bool = False
    carried_by: str | None = None
    dated_by: str | None = None


class WhyNoTrigger(StrEnum):
    """Why a confirmed cause came to no trigger - each a different fact about
    what was read, and so a different sentence. "No trigger was established"
    beside a confirmed cause reads as the cause in doubt, and is true only
    where nothing was confirmed.

    - `CARRIED_BY_SEVERAL_BY_THE_ONSET`, `CARRIED_BY_SEVERAL`: more than one
      deploy read changed what it blames, by the onset or - with no onset -
      at all, and which set it off a diff cannot say.
    - `CARRIED_AFTER_THE_ONSET`: only deploys after the onset changed it.
    - `ANOTHER_SERVICE_S_DEPLOYS_UNREAD`: it blames a service other than the
      one alerting, and only the alerting service's deploys are read.
    - `NAMES_NOTHING_SPECIFIC`: it names nothing a change could be to.
    - `CHANGES_UNREAD`: the deploys or the flag history were not read, or
      went unanswered - which the document says from its own readings.
    - `THE_SERVICE_ITSELF`: it blames the alerting service as a whole, and a
      deploy's reference is a revision, never the service's name.
    - `NO_DEPLOYS_READ`, `NO_DEPLOY_READ_CHANGED_IT`,
      `NOT_EVERY_DEPLOY_READ_IN_FULL`, `NO_DEPLOY_READ_IN_FULL`: it blames a
      file, and the deploys read came to none, changed it in none of their
      full listings, or were not all read in full.
    - `NOT_TIED`: anything else - nothing read was tied to it.
    """

    CARRIED_BY_SEVERAL_BY_THE_ONSET = "carried_by_several_by_the_onset"
    CARRIED_BY_SEVERAL = "carried_by_several"
    CARRIED_AFTER_THE_ONSET = "carried_after_the_onset"
    ANOTHER_SERVICE_S_DEPLOYS_UNREAD = "another_service_s_deploys_unread"
    NAMES_NOTHING_SPECIFIC = "names_nothing_specific"
    CHANGES_UNREAD = "changes_unread"
    THE_SERVICE_ITSELF = "the_service_itself"
    NO_DEPLOYS_READ = "no_deploys_read"
    NO_DEPLOY_READ_CHANGED_IT = "no_deploy_read_changed_it"
    NOT_EVERY_DEPLOY_READ_IN_FULL = "not_every_deploy_read_in_full"
    NO_DEPLOY_READ_IN_FULL = "no_deploy_read_in_full"
    NOT_TIED = "not_tied"


class NoTrigger(BaseModel):
    """Why the confirmed cause, `candidate` (`C1`), came to no trigger - and
    what the sentence saying so names: what it blames (`subject`), the service
    (`service`), and the deploys, by the labels the changes read go by
    (`deploys`). Each `None` or empty where the reason says none of it."""

    why: WhyNoTrigger
    candidate: str
    subject: str | None = None
    service: str | None = None
    deploys: list[str] = []


class ReviewCriterion(BaseModel):
    """One of Google's review criteria, and whether the document meets it.

    `met` is `None` for a criterion only people can meet - an item owned, a
    document read - rather than `False`: a box that is always unticked teaches
    its reader to stop looking at the boxes.

    `because` is what a person has to do to meet a criterion left to them,
    where that is not the criterion itself: an analysis resting on a reading
    of the source nothing ran is met once somebody runs it. `None` everywhere
    else, and on a document written before it was carried.
    """

    criterion: str
    met: bool | None
    because: str | None = None
