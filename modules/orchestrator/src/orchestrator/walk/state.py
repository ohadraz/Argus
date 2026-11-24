"""The walk's own state, and the machine that says where it stands.

Here rather than in the kernel because one module has a graph: `IncidentState`
is LangGraph's `StateGraph` state, and a type twenty packages install in order
to name a `UuidStr` has no business also describing this module's workflow.

`status_after` comes with it. It reads the state's fields and nothing else, so
wherever the state lives is the only place the machine can be stated without
one of the two importing the other across a boundary.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final, Literal

from core.models import (
    Action,
    Alert,
    Attempt,
    ChangeEvent,
    DeploymentChanges,
    Disproof,
    EstablishedOnset,
    FlagChange,
    Hypothesis,
    IncidentStatus,
    Platform,
    Reading,
    RecordedPlacement,
    ServiceDependency,
)
from pydantic import BaseModel, ConfigDict, Field

# Every group and every ending is checked afresh each time the state is built,
# as a field of the state always was. A group arrives as an instance a node's
# update made by copying, and either can arrive as one a checkpoint rebuilt
# without its constructor; neither checks anything, and pydantic takes an
# instance as it is - so a `None` written where none may stand would otherwise
# stay in the state unseen.
_CHECKED_AFRESH: Final = ConfigDict(revalidate_instances="always")


class CandidateCursor(BaseModel):
    """The candidates the latest round formed, best first, and which of them
    is under test."""

    model_config = _CHECKED_AFRESH

    # The candidate under test - the one the gate judges and Mitigation acts
    # on. Kept beside the list rather than derived at every use, because every
    # node downstream asks "the hypothesis this incident is about", and making
    # each of them index into a list would be four chances to index differently.
    hypothesis: Hypothesis | None = None
    # Every explanation the investigation offered, best first, and how far along
    # them the walk has got. The list is what makes a refuted mitigation
    # something other than a dead end: being wrong about a correlated change is
    # the ordinary case, and the second explanation is usually still on it.
    candidates: list[Hypothesis] = []
    candidate_index: int = 0


class RoundEvidence(BaseModel):
    """What every round reads afresh at its top, carried to the nodes that act
    on it rather than read again where it is used."""

    model_config = _CHECKED_AFRESH

    # What the flag provider recorded as having changed, read once at the top
    # of each round. Carried rather than fetched where it is used because it is
    # used three times over - deciding what each candidate would be answered
    # with, which of them memory demotes, and which action the chosen one gets
    # - and three reads of one history are three chances for the walk to reason
    # about two different worlds.
    #
    # `None` is not an empty history. It is the provider having failed to
    # answer, which leads the walk to the same place - no action, and a human -
    # while meaning the opposite thing, and an account that spelled them the
    # same would tell a reader nothing changed when nobody could say.
    flag_changes: list[FlagChange] | None = None
    # What the platform recorded as deployed to this service, read in the same
    # breath as the flag history and over the same window. Carried for the same
    # reason, and `None` for the same reason: one mode is answered by undoing
    # whichever of the two changes sits at its onset, and a history nobody could
    # read must not be taken for one in which nothing was deployed.
    deployments: list[ChangeEvent] | None = None
    # Where the alerting service's pods were running, as this round's
    # investigation recorded them against its onset. Carried rather than read
    # where it is used, because a pin to a card is decided from it and a read
    # made when acting is made after the walk may already have moved the pods.
    # `None` where the round could not read it, never an empty placement.
    placement: RecordedPlacement | None = None
    # What the service register says this service calls, read once at the top of
    # each round beside the flag history. Carried for the same reason: the gate
    # reads it to decide whether the service an action is addressed to is one
    # Argus may touch, and a gate that fetched it for itself would be one whose
    # answer depended on a document store being reachable at the instant it
    # asked.
    #
    # An empty list is what an unreadable register looks like here, and that is
    # deliberately not distinguished from a register that listed nothing. Both
    # leave every mitigation addressed to the alerting service exactly as
    # available as it was - the alerting service is within reach whatever the
    # register says - and both refuse an action aimed anywhere else, which is the
    # restrictive direction and the right one: an estate is not a thing to guess
    # at.
    dependencies: list[ServiceDependency] = []
    # Whether any reading covers the minutes from the onset onwards, as the round
    # that investigated found them. `True` until an investigation says otherwise,
    # which is what every incident before a window could stop was.
    readings_cover_the_incident: bool = True


class WhatWasLearnt(BaseModel):
    """What the incident's rounds have learnt, kept from one round to the next."""

    model_config = _CHECKED_AFRESH

    # What has already been tried and did not help. Carried into a later
    # investigation as evidence - it is the one thing a second round knows that
    # the first could not.
    attempts: list[Attempt] = []
    # What earlier rounds of this incident retrieved - which channel, over which
    # window. Carried so that a later round can be told what the one before it
    # saw: it may read the same window again, since that evidence is not in its
    # own transcript, but it should know it would be re-reading rather than
    # reaching somewhere new.
    already_read: list[Reading] = []
    # What each deployment this incident's investigations looked into changed,
    # by its revision. Kept across rounds, as `already_read` is: what a deploy
    # changed is a fact about its commit, and a later round blaming a file it
    # did not look into again still needs the diff to find the deploy that
    # carried it.
    deployment_changes: dict[str, DeploymentChanges] = {}
    # The minute the investigation dated the incident from, and how it is known,
    # as the first round that had one found it. Carried because Mitigation dates
    # the incident's end against it, and an end found by re-reading where the
    # incident began from another window can belong to an earlier episode of a
    # service that flaps - an incident that recovered before it started.
    #
    # The first round's stands, as it does for the postmortem, and is handed to
    # every later round: a later round re-reads a window Argus has since acted
    # on, and an onset found there dates whatever the action left behind rather
    # than the incident.
    onset: EstablishedOnset | None = None
    # How many times this incident has been investigated. What bounds the walk,
    # because what buys a later round is the refutation rather than the window:
    # an attempt that failed is evidence no amount of reading produces, and a
    # hard incident has usually spent its whole widening schedule by the time
    # the first attempt comes back refuted.
    rounds: int = 0
    # How many attempts the latest round was handed. What says whether anything
    # was refuted since it began - an action the gate refused or the tier could
    # not take adds no attempt - and so whether another round would be told
    # anything the last one was not.
    attempts_handed: int = 0
    # How many candidates this incident's rounds have formed, which is what the
    # next round numbers its own from (`Hypothesis.number`). Not `candidates`'
    # length: that is the latest round's alone.
    candidates_formed: int = 0
    # The platforms an attempt found were not answering. Carried rather than
    # re-derived, because by the time the next candidate is chosen all that is
    # left of the attempt is a verdict, and a verdict does not say which platform
    # failed - only the action that was in hand at the time could.
    #
    # A list rather than one platform, and not because two are expected: a walk
    # that held only the latest would forget the first the moment a second
    # failed, and go back to trying candidates it had already passed over.
    unreachable_platforms: list[Platform] = []


class ActionInFlight(BaseModel):
    """The action proposed for the candidate under test, from its proposal
    until the walk moves on: when it was taken, and what watching it found."""

    model_config = _CHECKED_AFRESH

    # Chosen by Mitigation and inspected by the tier gate before anything
    # mutating runs (spec §13). It lives in the graph's state rather than being
    # passed between the two, because a gate the acting node could bypass by
    # re-deriving the action would guard nothing.
    proposed_action: Action
    # When that action was taken, as the walk announced it. Carried because the
    # node that remembers the attempt runs after the wait for the service to
    # answer, and a later round reads the attempt beside the flag provider's
    # record of the same change - dated by when the walk moved on, the two
    # disagree by the length of that wait.
    acted_at: datetime | None = None
    # What the verification wait judged the attempt on, carried to the round
    # that reads it as an attempt (`Attempt.refuted_because`). `None` where
    # nothing was watched.
    action_because: str | None = None


class Disproven(BaseModel):
    """The window held none of what the alarm claimed, where the alarm was one
    a window can contradict and this one did.

    Not `NothingWorthTrying`, though the two leave the same empty candidate list
    behind: they are opposite findings. That one says Argus could not explain
    the incident; this says there was none, and the service was well across
    every minute that was judged. A reader of that one goes to look at the
    service and a reader of this one goes to look at the rule.
    """

    model_config = _CHECKED_AFRESH

    kind: Literal["disproven"] = "disproven"
    # Carrying its evidence rather than standing as a flag: a disproof is the
    # one claim in a walk that nothing later can check, so what it was made over
    # travels with it.
    disproof: Disproof


class NothingWorthTrying(BaseModel):
    """The round that just ran found no candidate worth acting on.

    The Investigator's own answer, kept because it is the one thing that
    distinguishes an investigation with nothing to offer from a walk that has
    worked through everything it was offered - the two leave the same list
    behind, and they are not the same incident.
    """

    model_config = _CHECKED_AFRESH

    kind: Literal["nothing-worth-trying"] = "nothing-worth-trying"


class Confirmed(BaseModel):
    """An action was taken and the service, re-read after it, had recovered."""

    model_config = _CHECKED_AFRESH

    kind: Literal["confirmed"] = "confirmed"


class Recommended(BaseModel):
    """What Argus worked out to do and declined to do, because nothing would
    say afterwards whether it worked.

    The one thing a `recommended` incident is for saying, and the reason that
    status is not escalation: a reader learns to go and do this, rather than to
    work out what to do.
    """

    model_config = _CHECKED_AFRESH

    kind: Literal["recommended"] = "recommended"
    action: Action


class NoMitigationForTheMode(BaseModel):
    """The candidate the gate last held names a mode no mitigation answers.

    Ends the mitigation phase rather than passing to the next candidate: the
    candidate in hand is the likeliest explanation still standing, and where it
    says no mitigation applies, acting on a less likely one is acting against
    the diagnosis.
    """

    model_config = _CHECKED_AFRESH

    kind: Literal["no-mitigation-for-the-mode"] = "no-mitigation-for-the-mode"
    # The candidate whose fault is in a service another company runs, by id,
    # where that is why. Code-Fix is not asked about it: a change written around
    # somebody else's outage is nobody's to merge, and the refusal's own line has
    # already said whom to ask. By the candidate rather than as a flag on the
    # incident, so a walk that went on to another candidate - one whose fault is
    # in this code - is asked about as any walk is.
    somebody_elses_fault_for: str | None = None


class Escalated(BaseModel):
    """An action that settled nothing Argus can go on from: nothing was measured,
    or nothing can be - a change that may or may not stand, or one nobody can
    account for."""

    model_config = _CHECKED_AFRESH

    kind: Literal["escalated"] = "escalated"


# How the walk's search for a mitigation ended, as one finding: two of them
# cannot stand at once. Code-Fix's answer is not among them, since Code-Fix runs
# after three of them; it is `fix_found`, beside this.
type Ending = Annotated[
    Disproven | NothingWorthTrying | Confirmed | Recommended | NoMitigationForTheMode
    | Escalated,
    Field(discriminator="kind")
]


class IncidentState(BaseModel):
    """LangGraph `StateGraph` state (spec §7.1), mirroring the Postgres
    schema (§11.1)."""

    incident_id: str
    alert: Alert
    status: IncidentStatus
    # The walk's work, by what each part of it is about. None of them has a
    # default, so a checkpoint written before they existed fails to load rather
    # than resuming with an empty walk: LangGraph fills only the channels a graph
    # declares, and a default would stand in for everything the walk had found.
    # The worker settles that walk as it settles any that fails before an ending.
    cursor: CandidateCursor
    evidence: RoundEvidence
    history: WhatWasLearnt
    # `None` while no action is proposed.
    action: ActionInFlight | None
    # How the search for a mitigation ended, `None` while it goes on. No
    # default, for the groups' reason.
    ending: Ending | None
    # What Code-Fix found, and `None` until it has run. Three-valued rather than
    # a bool, because "no fix yet" and "no fix to be had" are the difference
    # between an incident still being worked on and one a human now owns.
    fix_found: bool | None = None
    # How many steps the walk has taken, counted by the wrapper every node runs
    # in (`stepping.stepped`) rather than by any node. What a step's rows are
    # stamped with, and so what a step run again from its checkpoint finds its
    # interrupted attempt's rows by: the checkpoint carries the count from
    # before the step, so both attempts read the same one.
    steps: int = 0


def status_after(state: IncidentState, max_rounds: int) -> IncidentStatus:
    """Where the incident stands, given everything done to it so far (spec §10).

    The state machine, stated once. Every node in the graph produces work - a
    verdict measured against re-queried metrics, a list of candidates, an
    attempt that did not help - and the status is a conclusion drawn from that
    work rather than a decision any node gets to make. Five nodes each drawing
    it separately is how `fixing` came to mean "looking for the next candidate"
    in one place and "Code-Fix is working" in another.

    Pure, and deliberately so. Every input here was measured: a verdict comes
    from metrics re-queried after the change, an index from a list the
    investigation produced. A model asked to re-derive this would be
    second-guessing evidence with prose, and would make the one part of an
    incident that has to be reproducible depend on a sampled call.

    `max_rounds` is a parameter rather than read from `Settings`, for the reason
    `Hypothesis.is_confident_enough` takes its threshold: a domain rule has no
    business knowing how Argus is configured, and the caller already holds the
    value.

    The order of the questions is the design, and the first of them asks whether
    there was an incident at all: an alarm the window contradicted is `disproven`,
    and every rule under it is about how far Argus got with something it was
    working on. Of the questions about that, the first is "did the symptom stop".
    A confirmed action is the strongest evidence anything here has - metrics
    re-queried after the change and recovered - so it is asked first, and it is
    asked before `fix_found` because an incident that was mitigated and then had
    a fix proposed for it carries both at once.

    Only then does the walk's own arithmetic decide, and `fixing` is what is
    left when every question above it has been answered no.

    **Nothing here returns `resolved`.** A mitigation stops a symptom and a
    draft pull request proposes a change nobody has made; neither ends the
    cause, and Argus cannot merge (spec §13). What this derives is how far
    Argus got, and the furthest it gets is `mitigated`.

    `state.status` is never read. Deriving a status from a status would put the
    node that set the previous one back in the business this function takes it
    out of.
    """
    ending = state.ending

    # Asked first because this is the one question here that is not about how
    # far Argus got: every rule below decides what an incident Argus was working
    # on has reached, and this one says there was no incident. A rule about
    # whether the subject exists belongs above every rule about the subject's
    # state.
    #
    # Placed above the escalation rules rather than merely before them, because
    # a disproven walk leaves the fields those rules read exactly as an
    # untouched incident leaves them - no candidate, no action, no fix - and the
    # last of them sends anything that reaches it onwards rather than to an
    # ending. A rule that sits below them answers a question they have already
    # answered differently.
    if isinstance(ending, Disproven):
        return IncidentStatus.DISPROVEN

    if isinstance(ending, Confirmed):
        return IncidentStatus.MITIGATED

    # Asked before `fix_found` for the reason `mitigated` is: this walk goes on
    # to Code-Fix, so both facts are set by the time the status is derived, and
    # asking the fix first would report the incident escalated and lose the one
    # thing it exists to say. Escalated would also be untrue - Argus did not run
    # out of moves, it declined the move it had.
    if isinstance(ending, Recommended):
        return IncidentStatus.RECOMMENDED

    # A fix reached without a confirmed mitigation is one Argus arrived at
    # having stopped nothing: the symptom is still happening, and a proposal
    # does not stop it. Whether one was found decides what the incident carries,
    # not what state it is in.
    if state.fix_found is not None:
        return IncidentStatus.ESCALATED

    # The gate ended the mitigation phase with its candidate still in hand, so
    # the index below would read as a candidate under test. Nothing is: no
    # mitigation answers the mode, and the walk is on its way to Code-Fix.
    if isinstance(ending, NoMitigationForTheMode):
        return IncidentStatus.FIXING

    # Not a third opinion on the hypothesis: nothing was measured, or nothing
    # can be - a change that may or may not stand, or one nobody can account
    # for - so a further experiment would run against a world Argus cannot
    # describe.
    if isinstance(ending, Escalated):
        return IncidentStatus.ESCALATED

    # The investigation's own answer, and the one place it differs from the
    # walk's. A round that named nothing worth trying has already widened its
    # window as far as it can, so the rounds that remain would buy a re-read of
    # the same evidence - unlike a refuted attempt, which is evidence no amount
    # of reading produces.
    if isinstance(ending, NothingWorthTrying):
        return IncidentStatus.ESCALATED

    # Every node that sets the index sets it to something worth trying, or past
    # the end of the list - so the index alone says whether a candidate is under
    # test, and this function never re-runs the search that produced it.
    if state.cursor.candidate_index < len(state.cursor.candidates):
        return IncidentStatus.MITIGATING

    # Past the end of the list with a platform that is not answering, which is a
    # different ending from being past the end having tried everything. Another
    # round would re-read the same evidence and arrive at candidates on the same
    # dead platform, and a permanent fix is not what an incident needs when the
    # thing that failed is how Argus acts at all.
    #
    # Asked *after* the index check and not before it, which is the whole of why
    # this is here rather than beside the recommendation above. "A platform is
    # down and nothing is confirmed" is true the instant the first action on it
    # comes back - at which point a candidate on a reachable platform may still
    # be ahead, and the incident is mitigating. A rule that can only fire once
    # the list is spent cannot make that mistake.
    if state.history.unreachable_platforms:
        return IncidentStatus.ESCALATED

    if another_round_is_bought(state, max_rounds):
        return IncidentStatus.INVESTIGATING

    return IncidentStatus.FIXING


def another_round_is_bought(state: IncidentState, max_rounds: int) -> bool:
    """Whether the walk, out of candidates, investigates again.

    Bought by a refutation, and only by one made since the latest round began:
    Argus changed production and the service did not answer, which is evidence
    no amount of re-reading produces and the model has never seen. A list spent
    without one - every action refused by the gate, or one the tier had nowhere
    to take - leaves the next round the evidence the last was handed, and a
    re-read of it is the round `NothingWorthTrying` already declines to pay
    for.

    The first round is owed rather than bought: nothing has been read yet, so
    there is nothing for it to repeat.

    Stated once, because two callers ask it: `status_after`, and the node that
    says why the walk moved. Asked separately, the two could disagree about
    where the incident went and why.
    """
    history = state.history

    if history.rounds == 0:
        return max_rounds > 0

    return history.rounds < max_rounds and len(history.attempts) > history.attempts_handed
