from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Final, Literal, assert_never

from pydantic import BaseModel, ConfigDict, Field, GetCoreSchemaHandler, ValidationError
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
    """

    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    ESCALATED = "escalated"
    WITHDRAWN = "withdrawn"


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


class RollBackConfiguration(BaseModel):
    """Returning a deployment's configuration to the revision it ran before.

    A generic mitigation in the same sense a restart is: applied before the
    cause is fully understood, because what it buys is the service being well
    while somebody works out what to write. It is admissible unasked for one
    specific reason - the revision it applies was reviewed and ran before, so
    Argus is replaying somebody's change rather than authoring one. Writing to
    the configuration repository would be the opposite, and is not this.

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

    action_type: Literal["roll-back-configuration"] = "roll-back-configuration"
    application: str


# `action_type` is Argus's own word for what was done - it is a column on the
# `action` table and a field on the event a reader sees - so it tags the union,
# where the descriptor's `tool` is the write tier's wire vocabulary and does
# not.
type Action = Annotated[
    RevertFeatureFlag | RestartService | RollBackConfiguration,
    Field(discriminator="action_type")
]

# What any action calls itself. Named separately from the union because the
# things that render or store an action carry the tag alone: the event says
# what was done without carrying the proposal, and the row keeps a column.
type ActionType = Literal[
    "revert-feature-flag", "restart-service", "roll-back-configuration"
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
ROLL_BACK_CONFIGURATION: Final = "roll-back-configuration"


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


class ConfigurationRestored(BaseModel):
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
    """

    revision: bool
    automated_sync: bool


# The kinds of action that leave a change behind somebody could put back. A
# frozen set rather than a `match` over the union, because the question is
# asked of the *tag* - the row records a kind, and the walk that reads it back
# hours later has the column and not the action it came from.
_LEAVE_SOMETHING_TO_PUT_BACK: Final[frozenset[ActionType]] = frozenset(
    {REVERT_FEATURE_FLAG, ROLL_BACK_CONFIGURATION}
)


class ActionIdentity(BaseModel):
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

    Its existence is the point as much as its shape. While this was two loose
    strings, memory compared the subject half of a pair the gate compared
    whole, and a model's prose about a symptom was stored where the name of a
    service belonged - both of which type it as `str` and neither of which any
    checker could see.
    """

    model_config = ConfigDict(frozen=True)

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
        case RollBackConfiguration():
            return action.application
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
        case RestartService() | RollBackConfiguration():
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


class Outcome(BaseModel):
    """What happened when an action was taken.

    `detail` is for the human reading the timeline, and carries what the
    verdict alone cannot - which flag was changed, and, where a restore failed,
    what the provider said about it. `undo_descriptor` is the one the write
    tier returned, which is the record of what was actually changed rather than
    what was intended; it is absent when nothing was changed at all.
    """

    verdict: Verdict
    detail: str
    undo_descriptor: UndoDescriptor | None = None
