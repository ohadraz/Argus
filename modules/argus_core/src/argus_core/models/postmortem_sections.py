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

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel

from argus_core.models.change_event import ChangeEvent, ChangeKind


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


class ChainStep(BaseModel):
    """One step from the symptom towards the cause, and what it rests on."""

    text: str
    cites: list[CitedEvidence]


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


class TimelineMarker(StrEnum):
    """The four moments a reader looks for first in a timeline."""

    IMPACT_BEGINS = "impact begins"
    DETECTED = "detected"
    MITIGATED = "mitigated"
    IMPACT_ENDS = "impact ends"


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
    # The label the document's prose cites this line by (`T1`). `None` on a
    # marker: code placed it among the lines, and no prose was shown it to cite.
    label: str | None = None
    # Whether a person's timing, or the relay's, put this line where it is
    # rather than a step of the walk - which is why it is labelled apart from
    # the walk's lines (`XW1`), so a message written a second earlier renames
    # nothing the walk said.
    outside_the_walk: bool = False


class HypothesisConsidered(BaseModel):
    """One candidate the Investigator ranked, and what became of it - under
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


class ResolutionStep(BaseModel):
    """One thing done to end the incident, by whom, and what it came to -
    under the label the document's prose cites it by (`M1`)."""

    at: datetime
    action: str
    by: str
    reversible: bool
    outcome: str
    label: str


class Detection(BaseModel):
    """How the incident came to be known about.

    `gap` is carried rather than left to each reader's subtraction: two
    renderers of one document subtracting separately are two chances to
    disagree. `None` with `onset_at`, where no onset was measured.

    `said` is what the alert said of its own finding, under the label the
    prose cites it by - so a citation of it leads to a row like any other's.
    `None` where its sender said nothing of its own.
    """

    alerted_at: datetime
    rule: str | None
    onset_at: datetime | None
    gap: timedelta | None
    said: CitedEvidence | None = None


class ImpactExtent(StrEnum):
    """What a duration is: a measurement, a floor, or a stretch nobody saw.

    Three rather than a flag, because the two ways a duration falls short of a
    measurement are different facts: a service still failing when the metrics
    ran out, and a service whose metrics stopped while it was failing.
    """

    MEASURED = "measured"
    AT_LEAST = "at least"
    UNOBSERVED = "unobserved"


class Impact(BaseModel):
    """How long the service was broken, what that duration is, and how bad it
    got at its worst.

    The duration is carried rather than left to each reader's subtraction of
    the timeline's markers, for `Detection.gap`'s reason. `peak_error_rate` and
    `requests_failed` are `None` where the metrics could not be read.
    """

    duration: timedelta
    extent: ImpactExtent
    peak_error_rate: float | None
    requests_failed: int | None = None


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
    carried it."""

    subject: str
    from_state: str | None
    to_state: str | None
    changed_at: datetime | None
    kind: ChangeKind | None = None
    actor: str | None = None
    suspected: bool = False
    carried_by: str | None = None


class ReviewCriterion(BaseModel):
    """One of Google's review criteria, and whether the document meets it.

    `met` is `None` for a criterion only people can meet - an item owned, a
    document read - rather than `False`: a box that is always unticked teaches
    its reader to stop looking at the boxes.
    """

    criterion: str
    met: bool | None
