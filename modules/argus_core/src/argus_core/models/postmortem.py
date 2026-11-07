"""What a postmortem says, and what it says once it has been written down.

Here rather than in `agent_postmortem` because three modules name this shape:
the agent that produces it, the repository that persists it, and the walk that
carries it between them. A type two modules both have to name is a contract
between them, and a contract kept inside one of the parties is one the other
imports an agent to read.

Three quantities in three units (spec §21.3), and none of them convertible into
the others: what the incident cost the business, what it cost the people who
responded, and what it cost Argus. Only the first is an estimate.

Almost every figure is optional, because a figure whose source could not be read
is absent rather than zero - and `assumptions` is where the document says so. A
reader must never have to guess whether nothing was lost or nothing was known.
The lists are the exception: an empty one says the question was answered and the
answer was none, which is a different thing again.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from argus_core.ids import UuidStr
from argus_core.models.postmortem_sections import (
    ActionItem,
    ChainStep,
    CitedChange,
    CitedEvidence,
    ContributingFactor,
    Detection,
    DetectionLesson,
    HypothesisConsidered,
    Impact,
    Lessons,
    NoTrigger,
    ResolutionStep,
    ReviewCriterion,
    TimelineEntry,
    Trigger,
)
from argus_core.models.pull_request import OpenedPullRequest
from argus_core.models.reading import ChannelReading
from argus_core.models.thread_message import Weighing


class PostmortemLead(BaseModel):
    """One thing a person told the incident, as the postmortem reports it.

    The record's facts - who wrote, what they wrote, when, and what the
    investigation made of it - carried across rather than restated, and the
    model's one sentence on whether it changed what was done beside them.
    That sentence is the only part prose can carry; the rest was settled while
    the incident ran.

    `label` is what the model was shown the lead as (`L1`), and what the
    prose cites it by - written where the prompt numbered the leads, so
    nothing downstream numbers them a second time.

    `person_name` is `None` where the chat platform could not name the writer,
    when their id stands in. `weighing` is `None` for a lead no investigation
    weighed - written after the last one, or shown to one that ended before it
    answered. `effect` is `None` where the model said nothing of it - reported
    anyway, because the person who wrote it is owed the line.
    """

    label: str
    person_id: str
    person_name: str | None
    text: str
    written_at: datetime
    weighing: Weighing | None
    effect: str | None


class PostmortemDocument(BaseModel):
    """The finished postmortem, as the agent hands it over.

    Not yet the `postmortem` row - that is `Postmortem` below, which is this and
    three more fields. What the agent produces has no id and no date because it
    has not been written down yet, and an agent that filled either in would be
    an agent deciding something the database decides.

    `review` is the agent's own verdict on its output (spec §7.6) - a criterion
    unmet is a legitimate outcome, not a failure, because an incident that is
    over is not improved by an agent that refuses to stop.
    """

    root_cause: str | None
    # The cause as the summary says it, in the model's one sentence for a
    # reader who does not work on the service. Kept on its own as well as
    # inside the summary: a line that sets it apart there has nothing else to
    # find it by. `None` where the model gave none.
    cause_in_plain_words: str | None = None
    executive_summary: str | None
    # What a reader saw go wrong, in the model's words and no more - "Account
    # pages failed". The page puts the change it began with beside it from
    # the trigger, which is the record's to say. `None` where unanswered.
    symptom: str | None = None
    customer_loss_estimate: Decimal | None
    # What currency that figure is in, carried rather than looked up. The
    # reporting currency is configured, so a document that left a reader to
    # read it back from settings would relabel figures already published the
    # day somebody changed it. `None` where there is no figure to label.
    estimate_currency: str | None
    engineer_minutes: int | None
    responders: int | None
    # What those responders were, never who. Empty where the source could say
    # how many people responded and not what any of them was called - a
    # description missing, rather than a measurement.
    responder_titles: list[str] = []
    # What those minutes were worth, at the midpoint of each responder's band.
    # Absent - never zero, and never a partial sum - where any one of them
    # could not be priced, since a cost missing a responder is wrong in the
    # flattering direction rather than merely small.
    responder_cost_estimate: Decimal | None = None
    # The same minutes at the bottom and top of the same bands, published
    # beside the figure so a midpoint is not read as measured to the dollar.
    responder_cost_minimum: Decimal | None = None
    responder_cost_maximum: Decimal | None = None
    # What the bands were quoted in, carried for the same reason
    # `estimate_currency` is: a figure relabelled from settings would rewrite
    # documents already published.
    responder_cost_currency: str | None = None
    # How that cost was arrived at - the working year, the band each title was
    # priced at, or what stopped it. Kept beside the figure for whoever is shown
    # the figure, and apart from `assumptions`: the postmortem says nothing of
    # pay, since its readers are the people it would price.
    response_cost_basis: list[str] = []
    tokens_spent: int | None
    assumptions: list[str]
    # Where the permanent fix can be read, for the incidents that produced one.
    # A field rather than a sentence the model was asked to include: the walk
    # opened the pull request and recorded the address, so a document that
    # depended on the prose mentioning it would lose the one thing a reader
    # goes on to do - and would lose it silently, on the runs where the summary
    # read perfectly well without it.
    #
    # `None` for the ordinary ending, where a flag went back and there was
    # nothing in the code to change. An empty address would read as a proposal
    # whose link went missing.
    pull_request: OpenedPullRequest | None = None
    # What Argus worked out to do, declined to do, and is handing to a person.
    # A field rather than a sentence the model was asked to include, for the
    # reason the address above is one - and with more at stake. A document that
    # loses a link still describes an incident somebody can act on; one that
    # loses this describes an incident as over while the cause is still live.
    #
    # `None` for every ending Argus reached itself, where the action was taken
    # and watched. Prose here would send somebody to repeat a change already
    # made.
    recommended_action: str | None = None
    # When Argus closed the incident as disproven - the ending for an incident
    # there was none of: the window held none of what the alarm claimed. Every
    # part that says how an incident ended reads it, since measured as an
    # incident, a disproven alarm reads as a service broken from the alert and
    # never back. `None` on every other ending, and on a document written
    # before it was carried.
    disproven_at: datetime | None = None
    # What people told the incident in its thread, and what each changed. Empty
    # where nobody wrote, which is an answer: the question of what people said
    # was asked of the record, and the record held nothing.
    leads: list[PostmortemLead] = []
    # The template's sections (`postmortem_sections`). Each absent or empty
    # where nothing wrote it, as every field above is: `None` for a section
    # that is one value, an empty list for one that is many.
    impact: Impact | None = None
    detection: Detection | None = None
    trigger: Trigger | None = None
    # Why a confirmed cause came to no trigger - `None` where there is one,
    # where nothing was confirmed, and on a document written before it was
    # carried.
    no_trigger: NoTrigger | None = None
    resolution: list[ResolutionStep] = []
    causal_chain: list[ChainStep] = []
    contributing_factors: list[ContributingFactor] = []
    hypotheses: list[HypothesisConsidered] = []
    action_items: list[ActionItem] = []
    lessons: Lessons | None = None
    # The lesson on detection, which code writes from what was measured and
    # the page puts first in the list it belongs in. `None` where the gap
    # cannot be weighed - no onset, no rule read, an alert before the onset or
    # sooner than the wait - which Detection already says.
    detection_lesson: DetectionLesson | None = None
    timeline: list[TimelineEntry] = []
    # The changes to production, the log messages and what each deployment it
    # looked into changed, as the model was shown them, each under the label it
    # was shown by. No other section is a row for any of them, and the prose
    # cites them all - so without them a reader told "the deploy P2" has
    # nowhere to find out what P2 was. A change is kept whole, so its row can
    # name where it can be opened; a deployment's diff is its lines, one to a
    # line of `text`. And what Code-Fix read in the source, which is a
    # reading nothing ran - and each file it names that ran as other text than
    # it read, named by its path at the revision on its first line, then the
    # file as it ran. And how the code outside its patch uses what the patch
    # changes, one line of it to a row, read off the code rather than said by
    # Code-Fix. And what the metrics show of a cause confirmed to be the load,
    # measured by Argus - empty for any other cause, and on a document written
    # before it was carried.
    changes_read: list[CitedChange] = []
    log_messages_read: list[CitedEvidence] = []
    deployment_changes_read: list[CitedEvidence] = []
    code_read: list[CitedEvidence] = []
    as_it_ran_read: list[CitedEvidence] = []
    uses_outside_read: list[CitedEvidence] = []
    cause_measured: list[CitedEvidence] = []
    # The branch Code-Fix read, which the uses outside its patch were read on -
    # not the revision that ran, as a reader takes rows for unless told.
    fix_branch_read: str | None = None
    # What came of reading the deploys, the flags and the logs, for a list of
    # them that is empty: read and found nothing, never asked, and asked with
    # nothing back are three things to know, and an empty list is all three.
    # Deploys and flags apart, because the walk reads the flags every time and
    # the deploys only when the investigation asks. `None` on a document
    # written before they were carried.
    deploys_reading: ChannelReading | None = None
    flags_reading: ChannelReading | None = None
    logs_reading: ChannelReading | None = None
    review: list[ReviewCriterion] = []


class Postmortem(PostmortemDocument):
    """The same document, once it is a row: identified, and dated.

    Inheritance rather than a second field list. The row *is* the document - the
    agent's own docstring says the two are distinct, and the distinction is
    exactly these three fields - so a mapping between them would be fifteen
    lines of transcription whose only failure mode is silence.
    """

    id: UuidStr
    incident_id: UuidStr
    created_at: datetime
