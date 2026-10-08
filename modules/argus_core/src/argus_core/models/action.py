from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Final, Literal, assert_never, get_args

from pydantic import BaseModel, Field, GetCoreSchemaHandler, ValidationError
from pydantic_core import CoreSchema, core_schema

from argus_core.models.undo_descriptor import FlagUndo, UndoDescriptor


class Verdict(StrEnum):
    """What an attempted mitigation says about the hypothesis behind it.

    `CONFIRMED` and `REFUTED` are the two answers spec §7.3 asks Mitigation
    for. A confirmed action resolves the incident; a refuted one leaves it
    where it was, in `mitigating`, for the next explanation on the list.
    `ESCALATED` is not a third opinion on the hypothesis - it means no verdict
    was reached at all, because nothing could be done or because the
    environment was left in a state Argus cannot account for.

    `WITHDRAWN` is the other way no verdict is reached: the action was taken and
    then abandoned, because somebody took the incident back while the service
    was still being watched. It is not `REFUTED` - nothing was measured, and
    recording evidence against a hypothesis nobody finished testing is the one
    thing a stopped experiment must not leave behind. The change it made is
    still out there, which is why the outcome carries its undo descriptor.

    `NOT_ATTEMPTED` is the fourth way no verdict is reached, and it is the one
    that keeps the walk moving. The action was admitted and then refused by the
    tier that performs it, because the action itself is exhausted: a deployment
    already at the most replicas Argus may ask for, an autoscaler whose floor
    already meets its ceiling. Nothing is broken and nothing was changed.

    It is neither of the two it would otherwise collapse into, and both
    collapses cost something real. `ESCALATED` stops the walk, so an incident
    whose second candidate is a flag toggle Argus could revert in seconds
    reaches a human because its first candidate had no capacity left to add.
    `REFUTED` would be worse: it means "this explanation was tested and did not
    hold", so recording it for an action that never ran puts a measurement in
    the record that never happened, and the postmortem then says the evidence
    ruled a cause out when nothing ruled it out.

    So it says what is true - the action could not be taken, and the cause is
    still open - and the walk moves to its next candidate on those terms.

    `PLATFORM_UNREACHABLE` is the fifth, and the only one that is not about the
    action at all. The tier was reached and the platform it would have acted
    through was not, so nothing was asked and nothing was changed. It keeps the
    walk moving like `NOT_ATTEMPTED`, and says something `NOT_ATTEMPTED` cannot:
    that every *other* action through that platform is unavailable too, which is
    what lets a walk pass over three candidates and reach for the fourth instead
    of ending. Folded into `NOT_ATTEMPTED` it would make that member cover two
    reasons - a bound reached, and a platform that never answered - and a
    postmortem reading it would report a bound nothing ever hit.
    """

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    ESCALATED = "escalated"
    WITHDRAWN = "withdrawn"
    NOT_ATTEMPTED = "not-attempted"
    PLATFORM_UNREACHABLE = "platform-unreachable"


class UnreadVerdict(str):
    """A verdict on file that no `Verdict` spells.

    A verdict and not an `Outcome`, which is the other thing in this module
    that a stored action produces: an `Outcome` is a verdict with the detail
    and the way back beside it, and this is the one field of it that could not
    be read. Every branch that meets one asks `isinstance(..., Verdict)`, which
    is the question the name has to answer.

    The `action` table stores its outcome as text and goes on storing it as
    text: a row written before a verdict was renamed is history, and history
    still has to come back out of the table. So the column has three states
    rather than two, and this is the third - not the absence of an outcome,
    which means the worker died between acting and recording what it found,
    and is the one case a resuming walk has to ask the provider about.

    A `str`, because `Verdict` is a `StrEnum` and every destination that shows
    an outcome shows this one the same way: the timeline, the dashboard and the
    evidence the postmortem reads all interpolate whichever they were handed
    and print what the column holds. A state carrying no spelling would tell an
    operator less than the row does, and leave an escalation unable to name
    what stopped it.

    Which is also why it refuses a spelling `Verdict` knows. Both are `str`, so
    `UnreadVerdict("confirmed")` would compare equal to `Verdict.CONFIRMED`
    while failing every `isinstance` narrowing decided against it - read as a
    verdict where an outcome is shown, and absent where one is judged. Nothing
    on the read path can produce such a value, since a spelling a verdict has
    becomes that verdict; the invariant is here so that nothing off the read
    path can produce one either.
    """

    def __new__(cls, spelling: str) -> UnreadVerdict:
        if spelling in _THE_SPELLINGS_OF_A_VERDICT:
            raise ValueError(
                f"[{spelling}] is how a `Verdict` is spelled, so it is not a "
                f"verdict nobody can read - `Verdict({spelling!r})` is."
            )

        return super().__new__(cls, spelling)

    @classmethod
    def __get_pydantic_core_schema__(cls,
                                     source: Any,
                                     handler: GetCoreSchemaHandler) -> CoreSchema:
        """Validated as a string and then built through the constructor above.

        Pydantic knows nothing about a bare `str` subclass, and a field
        annotated with one is a schema error rather than a default. Saying so
        here keeps the refusal on the way in: a model handed a spelling a
        verdict has raises where it is built, not somewhere downstream that
        expected the narrowing to hold.
        """
        return core_schema.no_info_after_validator_function(cls,
                                                            core_schema.str_schema())


_THE_SPELLINGS_OF_A_VERDICT: Final = frozenset(verdict.value for verdict in Verdict)


class RevertFeatureFlag(BaseModel):
    """Putting one feature flag back where it was (spec §7.3, §13).

    Here rather than in `agent_mitigation` for the same reason `Hypothesis` is
    here: it crosses agent boundaries. Mitigation proposes one, the
    Orchestrator's gate node inspects it, the graph's state carries it between
    the two, and the `action` table stores what became of it - so it belongs to
    no single agent.

    `enabled` is the state to leave the flag in, which is whatever undoes the
    change that caused the incident - off for a flag that was switched on, on
    for one that was switched off. Stating the target state rather than "revert
    it" is what lets this one action serve both directions.

    `undo_descriptor` is populated at proposal time, before anything is called,
    and is *required on this action* - not because a way back is what admits an
    action, which it is not (that is membership of the declared set of generic
    mitigations, §13), but because this kind of change genuinely leaves
    something behind. A flag Argus moved is a flag somebody has to be able to
    move back, and an optional field here would reach a withdrawal hours later
    as a `None` nobody can act on.
    """

    action_type: Literal["revert-feature-flag"] = "revert-feature-flag"
    flag: str
    enabled: bool
    undo_descriptor: FlagUndo


class RestartService(BaseModel):
    """Restarting the service, as the first mitigation that puts nothing back.

    The industry's most common first response to a resource leak, and a
    *generic mitigation* in Google SRE's sense: applied before the cause is
    known, because what it buys is the service coming back while somebody works
    out why it went.

    It carries **no undo descriptor, and no field for one**. A restart changes
    no persistent state - there is no prior value to record and nothing a
    withdrawal could put back - so a nullable field here would be a hole every
    reader had to interpret, where an absent one cannot be misread. What tells
    that apart from a change nobody accounted for is the `action` row's own
    column, written from the kind.

    The subject is a service rather than a workload, a pod or a deployment.
    What Argus names is what the alert and the metrics name; how that maps onto
    a thing that can be restarted belongs to the write tier's adapter, which is
    the only place that knows whether it is talking to Argo CD, to Kubernetes
    or to something with no orchestrator at all.
    """

    action_type: Literal["restart-service"] = "restart-service"
    service: str


class RollBackDeployment(BaseModel):
    """Returning a deployment to the revision it ran before.

    Named for the deployment rather than for its configuration, because one
    revision carries the code and the configuration it shipped with, and the
    platform's rollback is one operation over both. So this is the answer to a
    configuration changed into a broken state and to new code that broke it
    alike - what differs between those is the mode Argus diagnosed and the fix
    that remains afterwards, not the action.

    A generic mitigation in the same sense a restart is: applied before the
    cause is fully understood, because what it buys is the service being well
    while somebody works out what to write. It is admissible unasked for one
    specific reason - the revision it applies was reviewed and ran before, so
    Argus is replaying somebody's change rather than authoring one. Writing to
    the repository would be the opposite, and is not this.

    The application, and nothing else. Which revision to return to is not
    named here because nothing that proposes this action could name it
    honestly: a strategy reads a hypothesis, the recorded flag changes and a
    service name, none of which carry a deployment platform's history. The
    platform resolves it - the immediately preceding deployment, which is what
    `argocd app rollback APPNAME` does with its history id omitted - and the
    tier that performed it reports back which entry that was.

    It carries **no undo descriptor, and no field for one**, which is the same
    shape a restart has for the opposite reason. A restart leaves nothing to
    put back; this leaves a great deal, and every fact about it - the entry
    that was running, the revision at it, whether the platform was
    reconciling - is known only to the tier that did the work. A field here
    would have to be filled at proposal time by something that cannot know
    any of it. What tells the two apart is the kind: `leaves_something_to_put_back`
    says this one does, so a row recording it with no descriptor against it is
    a change nobody accounted for.
    """

    action_type: Literal["roll-back-deployment"] = "roll-back-deployment"
    application: str


class ScaleOut(BaseModel):
    """Giving a deployment more replicas than it was sized for.

    The fourth generic mitigation, and the only one that adds something rather
    than restoring something. That is not a weakening of the criterion: what
    admits an action unasked is membership of the declared set (spec §13), never
    whether the change can be put back - and this one happens to be reversible
    anyway. Google SRE's own list of generic mitigations names adding capacity
    beside draining, rolling back and restarting.

    The application, and no count. Which count to scale to is named nowhere here
    for a stronger version of the reason a rollback names no revision: a target
    is meaningless without the count it replaces, that count is live state the
    platform holds, and a strategy asserting "six" would be asserting the
    deployment is running three - a fact no evidence in front of it carries, and
    one that stops being true the moment anybody scales. The tier that performs
    the action reads what is running, derives the target, and reports both.

    It carries **no undo descriptor, and no field for one**, which is the
    rollback's shape and for the rollback's reason: what it leaves behind - the
    count that was running, and whether the platform was reconciling the
    application itself - is known only to the tier that did the work. What says a
    row with no descriptor against it is a change nobody accounted for is the
    kind, through `leaves_something_to_put_back`.

    There is no matching action for reducing capacity, and there should not be.
    Being wrong about adding it costs money; being wrong about removing it costs
    an outage.
    """

    action_type: Literal["scale-out"] = "scale-out"
    application: str


class PinAutoscaler(BaseModel):
    """Holding a deployment's size still by raising its autoscaler's floor.

    The fifth generic mitigation, and the first that stops something rather than
    adding or restoring something. The criterion is unchanged by that, as it was
    unchanged by a mitigation that adds: what admits an action unasked is
    membership of the declared set (spec §13), never what kind of change it makes.

    It answers a control loop rather than a change or a state, which is what
    separates it from every action above. A flag was moved once, a revision shipped
    once, a heap filled and load arrived; an autoscaler goes on deciding, and the
    count Argus sets through the deployment is re-derived within a sync period. So
    this is aimed at the controller - raising the floor it may fall to until it
    meets the ceiling it was already allowed to reach - and the deployment's own
    replica count is not written at all.

    The application, and no count, for a stronger version of the reason a
    scale-out carries none. A floor is meaningless without the ceiling it is
    raised to meet, that ceiling is on a live resource only the write tier can
    read, and it is a bound somebody declared for this deployment rather than a
    figure an agent could assert. Which also makes the count not Argus's to choose
    even in principle.

    It carries **no undo descriptor, and no field for one**, which is the
    rollback's and the scale-out's shape and for their reason: what it leaves
    behind - the floor the autoscaler had, and whether the platform was
    reconciling the application itself - is known only to the tier that did the
    work.

    There is no matching action for lowering a floor or a ceiling, and there
    should not be. Either reduces capacity, and the judgement there is the one the
    scale-out already rests on: being wrong about adding capacity costs money and
    being wrong about removing it costs an outage.
    """

    action_type: Literal["pin-autoscaler"] = "pin-autoscaler"
    application: str


class DiscardCacheEntries(BaseModel):
    """Throwing away the copies of something that have stopped agreeing with it.

    The sixth generic mitigation, and the first that removes something rather
    than restoring, adding or stopping something. The criterion is unchanged
    again, and saying so a third time is the point: what admits an action unasked
    is membership of the declared set (spec §13), never the kind of change it
    makes - and this is the member most likely to be mistaken for a weakening,
    because removing data sounds heavier than putting a value back and is not.

    Nothing is lost. What is discarded was derived from a store this never
    touches, the service recomputes from that store on the next read, and what is
    gone cannot be stale. So there is no undo descriptor and no field for one -
    not because the tier knows what to put back, as with a rollback, but because
    writing the stale figures back would be recreating the incident.

    `keys` are addresses and arrive from the evidence that named them. Argus
    composes none: a key's format belongs to whoever wrote the store, so a
    constant here would be this agent holding one service's internals, and
    nothing downstream could tell a derived key from a real one. At least one,
    because an action that would reach a store and remove nothing comes back with
    a count of zero - and a zero is indistinguishable from entries somebody else
    had already discarded, so the attempt would be confirmed by a receipt saying
    nothing happened.

    A tuple, and order is kept, for the reason the alert carries them that way:
    one call names all of them, and a collection that sorted or collapsed them
    would be a different set of entries wearing the same count.

    `service` is what it is addressed to and what its identity is taken from. The
    keys are deliberately not part of that identity - the entries a check finds
    stale differ between one run and the next, so an identity carrying them would
    make every attempt a new one and the cap on repeating a mitigation would
    never be reached.
    """

    action_type: Literal["discard-cache-entries"] = "discard-cache-entries"
    service: str
    keys: tuple[str, ...] = Field(min_length=1)


class PinToAccelerator(BaseModel):
    """Holding a deployment's pods to one kind of accelerator.

    The seventh generic mitigation, and a drain in Google SRE's sense: traffic is
    moved off a class of hardware without anything deployed changing. It is
    admitted on that ground, which is the set's own (spec §13), and not because
    it can be put back - though it can.

    It answers a placement rather than a change Argus could return. A replica
    landed on a card whose arithmetic answers differently, with no revision
    behind it, so there is nothing for a rollback to return to; what puts the
    service back is the deployment held to the card its replicas ran on before.

    `accelerator` is that card, worked out from the placement the Investigator
    recorded against the onset and never read at the moment of acting - what a
    platform says once the incident is under way is the very thing in question.
    It is not part of the action's identity, for the reason a discard's keys are
    not: an identity carrying it would let one deployment be pinned once per card
    under a cap meant to stop the same thing being done over and over.

    Like the scale-out and the autoscaler's pin, it carries **no undo
    descriptor**: what it replaces - the selector the deployment had, and whether
    the platform was reconciling it - is known only to the tier that did the
    work.
    """

    action_type: Literal["pin-to-accelerator"] = "pin-to-accelerator"
    application: str
    accelerator: str


# `action_type` is Argus's own word for what was done - it is a column on the
# `action` table and a field on the event a reader sees - so it tags the union,
# where the descriptor's `tool` is the write tier's wire vocabulary and does
# not.
type Action = Annotated[
    RevertFeatureFlag | RestartService | RollBackDeployment | ScaleOut
    | PinAutoscaler | DiscardCacheEntries | PinToAccelerator,
    Field(discriminator="action_type")
]

# What any action calls itself. Named separately from the union because the
# things that render or store an action carry the tag alone: the event says
# what was done without carrying the proposal, and the row keeps a column.
type ActionType = Literal[
    "revert-feature-flag", "restart-service", "roll-back-deployment", "scale-out",
    "pin-autoscaler", "discard-cache-entries", "pin-to-accelerator"
]

# The tags as values, for the row and the event that carry them without
# carrying the action. Here beside the type rather than in the agent that
# proposes one: the column, the published event and the model would otherwise
# be three spellings of one word, and only two of them would fail to compile if
# they disagreed.
#
# Declared as bare `Final` rather than `Final[ActionType]`, so each infers the
# single `Literal` it is rather than the union. The wider annotation is what a
# reader expects and is the worse one: a comparison against a value typed as
# the whole union narrows nothing, so a match over the kinds cannot be checked
# for exhaustiveness and `assert_never` on its last branch is a type error
# instead of a guarantee.
REVERT_FEATURE_FLAG: Final = "revert-feature-flag"
RESTART_SERVICE: Final = "restart-service"
ROLL_BACK_DEPLOYMENT: Final = "roll-back-deployment"
SCALE_OUT: Final = "scale-out"
PIN_AUTOSCALER: Final = "pin-autoscaler"
DISCARD_CACHE_ENTRIES: Final = "discard-cache-entries"
PIN_TO_ACCELERATOR: Final = "pin-to-accelerator"


# What an action reaches the estate through. A role rather than a vendor, for
# the reason the read tier's Argo CD adapter is a `deploy` source and not an
# `argocd` one: nothing above the retrieval boundary learns which product
# answered, and a walk that narrowed itself by the word "argo" would have to be
# rewritten by whoever replaces it.
type Platform = Literal["deployment-platform", "flag-provider", "cache"]

DEPLOYMENT_PLATFORM: Final = "deployment-platform"
FLAG_PROVIDER: Final = "flag-provider"
# The store a service keeps its derived copies in, reached over that store's own
# protocol rather than through anything that manages the service. A third role
# because no control plane offers this write: a platform's built-in actions reach
# a workload's lifecycle and its size, and none of them reaches what a cache
# holds. Filing it under the deployment platform for tidiness would mean a walk
# that lost that platform passed over a discard, abandoning it over an outage
# that never touched the store it acts on.
CACHE: Final = "cache"


class RestartedService(BaseModel):
    """What a restart did, as the tier that performed it saw it.

    The new process start time is read back rather than assumed, and it is the
    whole reason this is a value and not a bare acknowledgement: a restart that
    was accepted and never happened is indistinguishable, from the symptoms
    alone, from one that happened and did not help. Only the start time moving
    separates them, and only the tier that performed the restart is in a
    position to wait for it.
    """

    service: str
    process_start_time_seconds: float


class CacheEntriesDiscarded(BaseModel):
    """What a discard removed, as the store itself reported it.

    The one action whose own answer is evidence rather than an acknowledgement.
    Every other result in this module records something the tier had to go and
    look at afterwards - a process's start time, a revision put back - because a
    platform accepting a request says nothing about whether the request took
    effect. A store answering "these many of the keys you named existed and are
    now gone" is a statement about the world, made by the only thing that could
    make it.

    Which is why the figure is carried rather than derived. The number of keys
    asked for is already known to whoever asked, and reporting that instead would
    report a discard that removed nothing as a discard that removed everything -
    then the attempt would be confirmed on the strength of a number this tier
    made up.

    Fewer than were named is not a failure and the figure says so honestly: an
    entry something else had already discarded is an entry absent, which is what
    the incident needed. The count is read out in the account of the incident, so
    it has to be what actually went.
    """

    discarded: int


class DeploymentRestored(BaseModel):
    """Which of the two things a rollback changed were put back.

    Two flags rather than one answer, because a restore can half-succeed and
    the half that fails is the quiet one. A deployment whose revision is back
    looks right from every angle a reader has - and is silently receiving
    nothing anybody ships to it, because the reconciliation Argus suspended is
    still suspended.

    Here beside `RestartedService` rather than inside the agent that reads it,
    for the reason every contract in this package is here: the tier that
    performs the restore answers with it and the agent that asked names it, so
    a copy kept inside either one is a copy the other has to install an agent
    to read.

    Both fields are named for what they claim rather than for what they are
    about. A `bool` called `automated_sync` beside a descriptor's
    `was_syncing_itself` reads as a second opinion on the same state, and the
    two say different things: one is how Argus found the platform, and this is
    whether Argus managed to leave it that way.
    """

    revision_put_back: bool
    automated_sync_put_back: bool


class CapacityRestored(BaseModel):
    """Which of the two things a scale-out changed were put back.

    `DeploymentRestored`'s shape for the other action that changes live state
    under a GitOps controller, and two flags rather than one answer for the same
    reason: a restore can half-succeed and the half that fails is the quiet one. A
    deployment back at its declared size looks right from every angle a reader
    has, and is silently receiving nothing anybody ships to it, because the
    reconciliation Argus suspended is still suspended.

    A type of its own rather than that one reused, because the first field is a
    different claim: a revision put back and a replica count put back are not the
    same fact, and a reader of `revision_put_back` on a resize would be told
    something nobody established.
    """

    count_put_back: bool
    automated_sync_put_back: bool


class AcceleratorPinRestored(BaseModel):
    """Which of the two things a pin to an accelerator changed were put back.

    `AutoscalingRestored`'s shape for the fourth action that changes live state
    under a GitOps controller, and two flags for that one's reason: a deployment
    back on the selector it had looks right from every angle a reader has, and is
    silently receiving nothing anybody ships to it while the reconciliation Argus
    suspended is still suspended.
    """

    pin_put_back: bool
    automated_sync_put_back: bool


class AutoscalingRestored(BaseModel):
    """Which of the two things an autoscaler pin changed were put back.

    `CapacityRestored`'s shape for the next action that changes live state under
    a GitOps controller, and two flags rather than one for the reason that one has
    two: a restore can half-succeed and the half that fails is the quiet one. An
    autoscaler back at the floor it was declared with looks right from every angle
    a reader has, and is silently receiving nothing anybody ships to it, because
    the reconciliation Argus suspended is still suspended.

    A type of its own rather than that one reused, because the first field is a
    different claim - a replica count put back and an autoscaler's floor put back
    are not the same fact, for the reason their descriptors are two descriptors.
    """

    floor_put_back: bool
    automated_sync_put_back: bool


# The kinds of action that leave a change behind somebody could put back. A
# frozen set rather than a `match` over the union, because the question is
# asked of the *tag* - the row records a kind, and the walk that reads it back
# hours later has the column and not the action it came from.
_LEAVE_SOMETHING_TO_PUT_BACK: Final[frozenset[ActionType]] = frozenset(
    {
        REVERT_FEATURE_FLAG, ROLL_BACK_DEPLOYMENT, SCALE_OUT, PIN_AUTOSCALER,
        PIN_TO_ACCELERATOR
    }
)

# The kinds of action that change something outliving the action itself. Every
# kind but the restart: a process that came back up carries nothing forward,
# and every other kind leaves the estate or a store different afterwards.
#
# A superset of the one above, and the gap between them is the whole reason
# both exist. The four there changed something *and* it can be put back. The
# discard is the one kind that changed something and cannot - what it removed
# was derived from records it never touched, so writing those figures back
# would recreate the incident rather than undo it. A row with no descriptor
# against it therefore means one of three things, and it takes both predicates
# to say which: a change nobody accounted for, figures that were never owed
# back, or an action that left nothing behind at all.
#
# Derived from that set rather than listed beside it, which is what makes the
# relation between them unbreakable rather than merely true. "Leaves something
# to put back" and "changes nothing that outlives it" is a contradiction - a
# kind entered that way would be reported as both unaccounted for and inert -
# and two literals maintained by hand is exactly how one gets entered. There is
# no assertion anywhere that the one is a superset of the other, because the
# union below is the only way either set can be written.
_CHANGE_SOMETHING_PERSISTENT: Final[frozenset[ActionType]] = frozenset(
    _LEAVE_SOMETHING_TO_PUT_BACK | {DISCARD_CACHE_ENTRIES}
)


class ActionIdentity(BaseModel, frozen=True):
    """What an action *is*, for the purpose of asking whether it was done before.

    The kind and the thing it was done to, together and as one value. Two
    readers ask that question at two timescales - the gate asks it within one
    incident, to bound how often a repeatable mitigation may be applied, and
    long-term memory asks it across incidents, to demote a candidate somebody
    already tried and refuted (spec §11.2, §13). They are one question, so they
    compare one type.

    Both halves, because either alone answers something else. The subject alone
    cannot tell a flag put back from a service restarted, and those are
    different evidence about the same cause. The kind alone says nothing about
    blast radius: restarting one service is no licence to restart another.

    Frozen, so it can be a key. Both askers hold a collection of these and ask
    whether one is in it, and a value that could be edited after it was filed
    under itself would be found under a name it no longer has.

    Said as a class argument rather than in a `model_config`, which is the same
    thing at runtime and not the same thing to a reader's editor: a type checker
    reads `frozen` where the class is declared and synthesises the `__hash__`
    that follows from it, where a configuration assigned in the body is a dict it
    does not interpret. Spelled the other way, every file that uses one of these
    as a key is underlined as using an unhashable key - correct code, reported as
    broken, in the one place the design says to look.

    Its existence is the point as much as its shape. While this was two loose
    strings, memory compared the subject half of a pair the gate compared
    whole, and a model's prose about a symptom was stored where the name of a
    service belonged - both of which type it as `str` and neither of which any
    checker could see.
    """

    action_type: ActionType
    subject: str


def the_identity_of(action: Action) -> ActionIdentity:
    """The pair this action is known by, wherever one is compared to another.

    Built from the action rather than assembled at each caller, for the reason
    `the_subject_of` is: the two fields are only an identity together, and a
    caller free to build one from a subject it had lying around is a caller
    free to build one from the wrong subject.
    """
    return ActionIdentity(
        action_type=action.action_type, subject=the_subject_of(action)
    )


def the_identity_recorded(action_type: str, subject: str) -> ActionIdentity | None:
    """The pair a stored row is known by, or `None` where this version cannot
    read it.

    The other way an identity is built, and the one that starts from text. A
    row's kind is a column, so what comes back out of the table is a `str` -
    including, on an incident old enough, a kind some version since removed.
    Such a row is history and still has to come out of the table, so it is
    passed over here rather than refused, exactly as an outcome nobody can
    spell is: a kind this version has no strategy for is a kind no later
    candidate could be matched against anyway.

    Validated rather than matched against a list of spellings. The tag is
    already a `Literal` this model checks on the way in, and a second list of
    the same words is a second place to forget one.
    """
    try:
        return ActionIdentity.model_validate(
            {"action_type": action_type, "subject": subject}
        )
    except ValidationError:
        return None


def the_subject_of(action: Action) -> str:
    """What the action acts on, whatever kind of thing that is.

    Here rather than at each caller because the readers that ask are several -
    the row the claim writes, the event a reader sees, and the identity above -
    and a union unpacked in that many places is that many places that grow a
    branch when a fourth kind arrives, most of which will be found by a bug.
    """
    match action:
        case RevertFeatureFlag():
            return action.flag
        case RestartService():
            return action.service
        case (
            RollBackDeployment() | ScaleOut() | PinAutoscaler() | PinToAccelerator()
        ):
            # The application rather than the card, for a pin to an accelerator:
            # see `PinToAccelerator`.
            return action.application
        case DiscardCacheEntries():
            # The service rather than the keys, and the keys are the reason to
            # say so. A subject is what an action is known by across attempts,
            # and the entries a check finds stale differ between one run and the
            # next - so a subject carrying them would make every discard a
            # different action and the cap on repeating one unreachable.
            return action.service
        case _:
            assert_never(action)


def the_service_addressed_by(action: Action) -> str | None:
    """Which service this action acts on, or `None` where it acts on none.

    Not `the_subject_of`, and the difference is what this exists for. A subject
    is whatever an action acts on, of whatever kind; this is an *address*, and
    only some of the things Argus acts on have one. A feature flag is a switch
    in Argus's own provider: nobody owns it but Argus, and treating its name as
    an address compares a flag against a list of service names and gets a
    confident wrong answer. A rollback's application is a service under the
    platform's word for it, so that one has an address like a restart does.

    `None` rather than the alerting service's name, because they are not the
    same claim. One says this action is aimed at nothing anybody owns; the other
    would say it is aimed at the service that alerted - which is false, and
    false in a way that reads correctly in every account of the incident
    afterwards.

    In the kernel because two modules ask it and neither could own it. The gate
    asks whether the address is within the estate Argus may touch; the walk asks
    whether the action went somewhere the incident was not about, so the account
    can say why Argus was allowed to. Kept inside either of them, it would be
    the other installing an agent to read a `match` over three classes - and a
    second copy of that `match` is the thing this module exists to prevent.

    Exhaustive on purpose. A fourth kind of action stops this type-checking
    rather than quietly acquiring an address of `None` and the authority that
    comes with it.
    """
    match action:
        case RevertFeatureFlag():
            return None
        case RestartService():
            return action.service
        case (
            RollBackDeployment() | ScaleOut() | PinAutoscaler() | PinToAccelerator()
        ):
            return action.application
        case DiscardCacheEntries():
            # An address like a restart's, not a flag's. The store holds one
            # service's derived copies, so the discard is aimed at that service
            # - which is what lets the gate ask whether it is within the estate
            # Argus may touch, and the account say why Argus was allowed to.
            return action.service
        case _:
            assert_never(action)


def the_direction_of(action: Action) -> bool | None:
    """Which way a two-state action moved its subject, or `None` for an action
    that has no direction to move in.

    A flag is set on or off, and which of those happened is the half of the
    sentence a reader can act on. A restart has no such half: there is one
    thing it does, and reporting it as having been moved to `true` would be a
    field invented to keep a shape.
    """
    match action:
        case RevertFeatureFlag():
            return action.enabled
        case (
            RestartService() | RollBackDeployment() | ScaleOut() | PinAutoscaler()
            | DiscardCacheEntries() | PinToAccelerator()
        ):
            return None
        case _:
            assert_never(action)


def the_accelerator_of(action: Action) -> str | None:
    """The card a pin held its deployment to, or `None` for an action that pins
    nothing to a card.

    Asked of the action rather than read off its subject, because the subject of
    a pin is the application: that a deployment was held to a card is half of
    what was done, and which card is the half a reader checks against the
    placement recorded at the onset.
    """
    match action:
        case PinToAccelerator():
            return action.accelerator
        case (
            RevertFeatureFlag() | RestartService() | RollBackDeployment() | ScaleOut()
            | PinAutoscaler() | DiscardCacheEntries()
        ):
            return None
        case _:
            assert_never(action)


def leaves_something_to_put_back(action_type: ActionType) -> bool:
    """Whether an action of this kind changes state somebody could restore.

    Not what admits an action - that is membership of the set of generic
    mitigations, and lives with the agent that holds it (spec §13). This is the
    narrower question the record has to answer afterwards: a row with no undo
    descriptor against it means one of two very different things, and only the
    kind can say which. An action of a kind that leaves nothing behind has
    nothing to put back; one of a kind that does, and carries no descriptor, is
    a change nobody has accounted for.
    """
    return action_type in _LEAVE_SOMETHING_TO_PUT_BACK


def changes_something_persistent(action_type: ActionType) -> bool:
    """Whether an action of this kind leaves the world different afterwards.

    The question `leaves_something_to_put_back` cannot answer, and the one that
    separates the two silences a row with no undo descriptor can mean. A
    restart changed nothing that outlives it, so there is nothing to put back
    and nothing was lost by not trying; a discard changed something real and
    still owes nothing back. Both are false for the older predicate, and told
    apart they want opposite sentences - "there was nothing to put back"
    against "no undo was owed". Said the wrong way round, a reader deciding
    whether to go and look at the store is told Argus was never in it.

    Named for the restart, because the restart is the only kind that makes it
    false. Spelled as owing an undo it would be the neighbouring set with the
    restart flipped - a synonym for the predicate beside it, whose one
    distinguishing answer would be the wrong one.
    """
    return action_type in _CHANGE_SOMETHING_PERSISTENT


def the_platform_of(action_type: ActionType) -> Platform:
    """What an action of this kind reaches the estate through.

    Asked of kinds that have not been attempted, which is what decides
    everything about its shape. A platform that did not answer one action has
    taken every action through it away at once, and a walk finding that out
    has to say which of its remaining candidates are still worth reaching for -
    so this has to be answerable about an action nobody has performed, and
    cannot be derived by watching one fail.

    A `match` rather than a mapping, and the difference is the whole reason this
    is a function. A `dict` answers a sixth kind with a `KeyError` at walk time
    or, worse, with a default that quietly files it under the platform that
    happens to be commonest - and the walk would then pass over a candidate that
    was never on the failed platform at all. Here `assert_never` makes a kind
    nobody has placed a type error, before anything runs.

    Matched on the literals rather than on the constants above, which is not the
    duplication it looks like: `case REVERT_FEATURE_FLAG` is a capture pattern
    and would match everything. The literals are what mypy checks the union
    against, so a misspelling here fails the build rather than the walk.
    """
    match action_type:
        case "revert-feature-flag":
            return FLAG_PROVIDER
        case "restart-service" | "roll-back-deployment" | "scale-out" \
                | "pin-autoscaler" | "pin-to-accelerator":
            return DEPLOYMENT_PLATFORM
        case "discard-cache-entries":
            return CACHE

    assert_never(action_type)


# The kinds of action whose own answer states what they changed, rather than that
# a request was accepted. A frozen set over the tag for the reason the set above
# is one: the gate asks this before anything has been performed, so there is no
# answer yet to inspect and the question has to be answerable about a kind nobody
# has called.
#
# What it decides is which confirmation an attempt gets. A count of entries
# removed is the store saying they are gone, and that is the whole of what the
# incident was; a platform's acknowledgement of a restart says a request was
# taken, and whether it helped has to be watched for in the service's own
# window. Where that window never departed there is nothing to watch, so a kind
# that answers for itself is the only kind that can be confirmed at all.
_REPORT_WHAT_THEY_CHANGED: Final[frozenset[ActionType]] = frozenset(
    {DISCARD_CACHE_ENTRIES}
)


def reports_what_it_changed(action_type: ActionType) -> bool:
    """Whether an action of this kind answers with what it did.

    Asked of the tag rather than of a performed action, and asked before the
    action is taken: the gate decides whether a confirmation could ever arrive
    while there is still nothing to inspect.

    Declared beside what admits an action unasked rather than inside the
    mitigation agent, because both are properties of the kind and a reader
    weighing one wants the other in front of them - and because a second copy
    kept where it is used is a second copy that comes to disagree.
    """
    return action_type in _REPORT_WHAT_THEY_CHANGED


def the_actions_through(platform: Platform) -> list[ActionType]:
    """Every kind of action that reaches the estate through `platform`.

    The question `the_platform_of` answers backwards, and it has two askers that
    must agree: the escalation raised when an unreachable platform leaves nothing
    to try, and the line an incident's record is narrated as. Both have to say
    what the platform *took away* rather than only that it is down - a reader
    told a platform's name has to go and look up which of Argus's actions went
    with it, which is the thing saying it at all exists to prevent.

    Derived from the same mapping rather than listed here, which is what makes a
    sixth mitigation safe: the kind has to be placed in `the_platform_of` or the
    type check fails, and once placed it appears here without anybody adding it.
    A second list would be a second thing to forget.

    Ordered as `ActionType` declares them, not as a set, because this is read out
    to a person: a sentence whose actions reorder between two runs of the same
    incident reads as two different facts.
    """
    return [
        action_type for action_type in get_args(ActionType.__value__)
        if the_platform_of(action_type) == platform
    ]


class Outcome(BaseModel):
    """What happened when an action was taken.

    `detail` is for the human reading the timeline, and carries what the
    verdict alone cannot - which flag was changed, and, where a restore failed,
    what the provider said about it. `undo_descriptor` is the one the write
    tier returned, which is the record of what was actually changed rather than
    what was intended; it is absent when nothing was changed at all.

    `measured` is the second fact the verdict cannot carry, and it exists
    because `ESCALATED` arrives from two opposite places. One is a refutation
    whose undo could not be established: the service was watched, it did not
    recover, and only putting the change back went wrong. The other is an action
    whose window ran out without the service being read once. Both escalate,
    both end the walk, and only the first tested anything - so the candidate's
    row is decided on this rather than on a word that means both.

    A field rather than a seventh `Verdict` member because nothing routes on it.
    The status derived from either is the same, the walk ends either way, and
    the only reader is the `tested` argument on the candidate's row. A member
    would put the distinction into a stored vocabulary and give
    `incident_memory` a value to order by, for a difference nobody branches on.

    It defaults to true, which is the ordinary case: an action was taken and the
    service was watched afterwards. Only the paths that know they watched
    nothing say so.
    """

    verdict: Verdict
    detail: str
    undo_descriptor: UndoDescriptor | None = None
    measured: bool = True
