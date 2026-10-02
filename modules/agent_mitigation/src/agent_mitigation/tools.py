from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Protocol, assert_never

from argus_core import SettingsSlice, parse_iso, to_iso, utc_now
from argus_core.mcp_transport import McpClient
from argus_core.models import (
    Action,
    AutoscalerUndo,
    AutoscalingRestored,
    CapacityRestored,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    MetricBucket,
    PinAutoscaler,
    ReplicaUndo,
    RestartedService,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    RolloutProgress,
    ScaleOut,
    UndoDescriptor,
)
from read_mcp_client import get_metrics_summary, get_rollout_progress
from write_mcp_client import (
    get_recent_flag_changes,
    pin_autoscaler,
    restart_service,
    restore_autoscaler_floor,
    restore_deployment,
    restore_replica_count,
    roll_back_deployment,
    scale_out,
    set_feature_flag,
)

from agent_mitigation.attribution import change_by_actor_to, changes_not_made_by


class Arrival(StrEnum):
    """Whether the change an action made has taken effect on the service yet.

    Three answers because the wait has three ways out, and only one of them is a
    duration anybody could have picked. `ARRIVED` says the change is in force and
    the minutes from here describe it. `STILL_ARRIVING` says the platform is
    working on it, so the minutes so far describe the code being replaced and
    judging them would judge the wrong deployment. `WILL_NOT_ARRIVE` says the
    platform has stopped - a rolling update it is holding - so nothing is going to
    change by waiting longer.

    That third answer is what gives the wait an end without a figure. A rollout
    stopped part way satisfies neither count and never will, so a loop holding
    only "arrived or not" would poll until its lease expired and leave the change
    applied for another worker to find. It is the counts that are asked first: a
    rollout stopped *after* it finished has arrived, and the pause says nothing
    about a change already in force on every replica. Paused is a state the platform reports,
    not a length of time somebody judged, which is why it can be read here at all
    - spec §16 keeps the "has this taken too long" judgement away from the channel
    precisely because a replica count and a timestamp cannot support it.

    Not every action has anything to wait for. A flag the provider has
    acknowledged is in force on the next request, a restart answers with the new
    process's start time and so has already happened, and an autoscaler's floor is
    its own spec. Those arrive on acknowledgement, and `an_action_in_force_at_once`
    is what says so.
    """

    ARRIVED = "arrived"
    STILL_ARRIVING = "still-arriving"
    WILL_NOT_ARRIVE = "will-not-arrive"


class HasArrived(Protocol):
    """What the wait needs from whatever can say the change took effect.

    A `Protocol` rather than a `Callable` alias for the reason the other seams
    here are: a test stands one in, and a named port says what it is standing in
    for. Nothing is passed - which change is being waited on was decided when the
    action was performed, and a port that took the action again would let the two
    disagree about what is being waited for.
    """

    def __call__(self) -> Arrival: ...


def an_action_in_force_at_once() -> Arrival:
    """The arrival of a change that is in force as soon as it is acknowledged.

    A flag, a restart and an autoscaler floor are all of this kind, and for three
    different reasons that come to the same thing: the target service reads its
    flags fresh on every request, a restart is answered with the new process's
    start time so the tier that performed it has already waited, and an
    autoscaler's floor is a field on its own object rather than a state something
    has to converge on.

    Named rather than written as a lambda at each call site, because "this action
    has nothing to wait for" is a claim about the action and deserves somewhere a
    reader can find the argument for it.
    """
    return Arrival.ARRIVED


class FlagChangeFetcher(Protocol):
    """What `mitigate` needs from whatever reads recent flag changes.

    A `Protocol` for the reason `ActionTaker` is one, and asking nothing for
    the same reason: how far back the window reaches was decided where the
    process started.
    """

    def __call__(self) -> list[FlagChange]: ...
# The same tool asked for a window that starts where the caller says, rather
# than where configuration says. Only the resumed walk needs that: it is asking
# about one particular moment - when an action was claimed - and the configured
# lookback is about something else entirely.
class FlagChangesSince(Protocol):
    def __call__(self, since: str) -> list[FlagChange]: ...
# The service's own account of itself, and the one way to change what it does.
# `Protocol` rather than a `Callable` alias for both, because a test stands each
# in with `create_autospec` and specing against the function that answers them
# would be specing against the wrong shape: those take the connection they are
# asked over, and neither of these knows a server exists.


class MetricsFetcher(Protocol):
    def __call__(self) -> list[MetricBucket]: ...


class FlagSetter(Protocol):
    def __call__(self, flag: str, enabled: bool, /) -> UndoDescriptor: ...


class ServiceRestarter(Protocol):
    """The tier's other write: bringing a service back under a new process.

    It answers with what came up rather than with nothing, because a restart
    that was accepted and never happened is indistinguishable from the symptoms
    alone. No undo descriptor, and no room for one - there is nothing a restart
    leaves behind for anybody to put back.
    """

    def __call__(self, service: str, /) -> RestartedService: ...


class DeploymentRoller(Protocol):
    """The tier's third write: returning a deployment to a revision it already
    ran.

    The application, and nothing else. Which entry to return to is the
    platform's to resolve - the immediately preceding deployment - because
    nothing above this port holds a deployment history to choose from, and a
    commit Argus found in a diff is not necessarily a revision this
    application ever ran.

    It answers with the descriptor recording what it changed, and the
    descriptor records *two* things: the platform refuses a rollback while it
    is reconciling the application itself, so suspending that is part of
    performing this rather than a separate concern - and an undo that restored
    only the revision would leave the deployment silently receiving nothing
    anybody ships to it.
    """

    def __call__(self, application: str, /) -> DeploymentRollbackUndo: ...


class DeploymentScaler(Protocol):
    """The tier's fourth write: giving a deployment more replicas than it has.

    The application, and nothing else. How many is the tier's to resolve - it
    reads what is running, doubles it, and bounds the result by a ceiling of its
    own - because a target count is meaningless without the count it replaces, and
    nothing above the port can read that.

    It answers with the descriptor recording what it changed, and the descriptor
    records *two* things for the reason a rollback's does: a platform reconciling
    the application itself puts a live replica count straight back, so suspending
    that is part of performing this rather than a separate concern.
    """

    def __call__(self, application: str, /) -> ReplicaUndo: ...


class CapacityRestorer(Protocol):
    """Putting a scaled-out deployment back to the size Argus found it at.

    Both of the things the scale-out changed, and it answers with which of them
    it managed rather than with nothing - for the reason the deployment restorer
    below does: a restore that half-succeeded is not a restore, and the caller has
    to be able to say which half is still changed.
    """

    def __call__(self, descriptor: ReplicaUndo, /) -> CapacityRestored: ...


class AutoscalerPinner(Protocol):
    """Stopping a deployment's autoscaler moving its replica count about.

    The application, and nothing else. How high the floor goes is the tier's to
    resolve - it reads the autoscaler's own ceiling and raises the floor to meet
    it, bounded by a ceiling of its own - because a floor is meaningless without
    the ceiling it is raised to, and because that ceiling is a bound somebody
    declared for the deployment rather than a figure an agent may assert.

    It answers with the descriptor recording what it changed, and the descriptor
    records *two* things for the reason a scale-out's does: a platform reconciling
    the application itself re-applies the autoscaler the repository declares, floor
    included, so suspending that is part of performing this rather than a separate
    concern.
    """

    def __call__(self, application: str, /) -> AutoscalerUndo: ...


class AutoscalingRestorer(Protocol):
    """Letting a pinned autoscaler move again, as Argus found it.

    Both of the things the pin changed, and it answers with which of them it
    managed rather than with nothing - for the reason the capacity restorer above
    does: a restore that half-succeeded is not a restore, and the caller has to be
    able to say which half is still changed.
    """

    def __call__(self, descriptor: AutoscalerUndo, /) -> AutoscalingRestored: ...


class DeploymentRestorer(Protocol):
    """Putting a rolled-back deployment back the way Argus found it.

    Both of the things the rollback changed, and it answers with which of them
    it managed rather than with nothing. A restore that half-succeeded is not
    a restore, and the caller has to be able to say which half is still
    changed - "the revision is back and reconciliation is still suspended" is
    a sentence somebody can act on, where "it did not work" is not.
    """

    def __call__(self,
                 descriptor: DeploymentRollbackUndo, /) -> DeploymentRestored: ...


@dataclass(frozen=True)
class PerformingWrites:
    """The writes that perform a mitigation - one per kind of action there is.

    A bundle because the alternative grows by one parameter per action kind at
    every caller, and because in production these are assembled from one
    connection and then taken apart again at the call site: each member is
    `*_over(client)`, so passing them separately is a value disassembled for the
    journey and reassembled by the callee's `match`.

    Named for the role and not for the tier. A tier-shaped name would invite
    `changed_from_outside` in, which is a *read*, and the restorers with it - and
    those belong to putting a change back rather than to making one, which is a
    different moment with a different caller. What performs an action and what
    undoes one are two collaborations, and `undo_change` holds the second.
    """

    set_state: FlagSetter
    restart: ServiceRestarter
    roll_back: DeploymentRoller
    scale_out: DeploymentScaler
    pin: AutoscalerPinner


Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
# Whether the walk waiting on an action is still one anybody wants. Takes
# nothing: which incident this is belongs to the caller, and an agent that had
# to be told would be an agent that could look it up - which is a database this
# module has no business holding an opinion about.
StillWanted = Callable[[], bool]
# Whether somebody other than Argus changed a flag since a given moment, or
# `None` where nobody can say. What an undo consults before it writes: a change
# made after Argus's own is somebody's deliberate decision, and putting the flag
# back would replace it with a state nobody chose.
ChangedFromOutside = Callable[[str, datetime], bool | None]


class MitigationSettings(SettingsSlice):
    """How Mitigation behaves against the provider and the service.

    How far back a window of recent flag changes reaches, whose changes Argus
    recognises as its own, and how long it waits while nothing has been measured.
    Not how long the service is watched for: that is measured off the window the
    service answers with.

    `unleash_actor` is empty where Argus and its operators share one
    credential. That is a real deployment and not a misconfiguration - the
    attribution rules answer `None` there rather than guessing.
    """

    flag_change_lookback_minutes: int
    unleash_actor: str
    mitigation_verification_timeout_seconds: float
    mitigation_attempts_per_subject: int


def flag_changes_over(client: McpClient) -> FlagChangesSince:
    """The provider's flag history, asked over one connection to the write tier.

    The tier is the write tier because the provider serves its audit log to
    admin credentials only, and `argus-read-mcp` holds none by design. Reading
    history is strictly less than the write tier can already do.
    """
    return partial(_flag_changes_since, client=client)


def recent_metrics_over(client: McpClient) -> MetricsFetcher:
    """The service's metrics, asked over one connection to the read tier."""
    return partial(fetch_recent_metrics, client=client)


# Which arrival a given action has to wait for. A seam of its own because the
# choice depends on the action and the binding does not: a walk binds this once
# over its read connection, and the kind is only known when an action is taken.
ArrivalFor = Callable[[Action], HasArrived]


def nothing_to_wait_for(action: Action) -> HasArrived:
    """Every kind of action in force as soon as it is acknowledged.

    The default, and what every caller that has no read connection gets. Named
    rather than written as a lambda at the signature, because "this caller is not
    waiting for anything" is a claim worth being able to find.
    """
    return an_action_in_force_at_once


def how_a_change_arrives(action: Action, *, client: McpClient) -> HasArrived:
    """Which arrival this action has to wait for, chosen by what it changes.

    Three of the five kinds have nothing to wait for, and for three reasons that
    come to the same thing: the target service reads its flags fresh on every
    request, a restart is answered with the new process's start time so the tier
    that performed it has already waited, and an autoscaler's floor is a field on
    its own object rather than a state anything converges on. Those are
    `an_action_in_force_at_once`.

    The two that change a Deployment wait on different counts - the revision
    reaching every replica, and the replicas asked for existing - which is why this
    dispatches rather than handing one check to all five. A single check would
    either make three actions wait for a rollout nobody started, or let the two
    that matter be judged on minutes their change was not in force for.

    Here rather than at the caller that assembles the walk, because the caller
    holds a bound `take_action` and not the action - the kind is only known at the
    moment one is taken. `assert_never` on the remaining branch, so a further kind
    of action is a type error here rather than an action silently judged as though
    it had arrived.
    """
    match action:
        case RollBackDeployment():
            return a_rollback_arriving_over(client, action.application)
        case ScaleOut():
            return added_capacity_arriving_over(client, action.application)
        case RevertFeatureFlag() | RestartService() | PinAutoscaler():
            return an_action_in_force_at_once
        case _:
            assert_never(action)


def a_rollback_arriving_over(client: McpClient, service: str) -> HasArrived:
    """Whether the revision a rollback returned to has reached every replica,
    asked over one connection to the read tier.

    The read tier because this is a read, which is the same reason the metrics are
    asked there. The two clients are interchangeable at the type level, so a seam
    bound to the wrong one fails at the moment the walk has already changed
    production and the incident is still happening.
    """
    return partial(_how_the_revision_is_arriving, client=client, service=service)


def added_capacity_arriving_over(client: McpClient, service: str) -> HasArrived:
    """Whether the replicas a scale-out asked for are running, asked over one
    connection to the read tier.

    A different question from the rollback's and not a spelling of it. Every
    replica that exists can be on the right revision while half the replicas asked
    for have yet to start, so one answer would be wrong for one of the two actions
    - see `RolloutProgress`.
    """
    return partial(_how_the_capacity_is_arriving, client=client, service=service)


def _how_the_revision_is_arriving(*, client: McpClient, service: str) -> Arrival:
    progress = get_rollout_progress(service, client=client)

    return _the_arrival_of(progress, progress.has_converged)


def _how_the_capacity_is_arriving(*, client: McpClient, service: str) -> Arrival:
    progress = get_rollout_progress(service, client=client)

    return _the_arrival_of(progress, progress.has_every_replica_it_asked_for)


def _the_arrival_of(progress: RolloutProgress, it_has_landed: bool) -> Arrival:
    """One rollout's counts read as a state of arrival.

    Stated once because both questions above are read the same way once their own
    count has been chosen, and two spellings of this would let the two actions come
    to disagree about what a paused platform means.

    Landed is asked first, and the order is the whole of it. A rolling update can
    be stopped after it has finished - every replica already on the new revision,
    nothing left to converge - and a pause read ahead of the counts would answer
    that such a change will never arrive, so Mitigation would report a mitigation
    that is in force on every replica as one that never applied, and wake somebody
    about it.

    The pause answers for a fleet that has *not* finished, which is the case it is
    read for. A rolling update nobody is advancing satisfies no count it has not
    already satisfied, so a caller told only "not yet" would wait for a
    convergence that is not coming - until its lease expired, leaving the change
    applied for another worker to find. Reported as a state rather than judged as a
    duration, which is what makes it readable here at all rather than a judgement
    §16 keeps out of this side.
    """
    if it_has_landed:
        return Arrival.ARRIVED

    return Arrival.WILL_NOT_ARRIVE if progress.is_paused else Arrival.STILL_ARRIVING


def flag_setter_over(client: McpClient) -> FlagSetter:
    """The first of the writes Argus makes, over one connection to the write
    tier."""
    return partial(set_flag, client=client)


def service_restarter_over(client: McpClient) -> ServiceRestarter:
    """The second, over the same connection."""
    return partial(restart_a_service, client=client)


def deployment_roller_over(client: McpClient) -> DeploymentRoller:
    """The third, over the same connection."""
    return partial(roll_back_a_deployment, client=client)


def deployment_scaler_over(client: McpClient) -> DeploymentScaler:
    """The fourth, over the same connection."""
    return partial(scale_out_a_deployment, client=client)


def capacity_restorer_over(client: McpClient) -> CapacityRestorer:
    """Putting the fourth back, which is a tool of its own for the reason the
    third's is: two pieces of prior state and a platform that refuses one order of
    them, so the tier performs it as its own operation and answers with which
    halves it managed."""
    return partial(restore_a_replica_count, client=client)


def performing_writes_over(client: McpClient) -> PerformingWrites:
    """Every write that performs a mitigation, over one connection.

    Here rather than at the one caller that assembles it, because the bundle and
    the connection are the same fact said twice: a caller building three of these
    over one client and the fourth over another would be a caller nothing stopped.
    """
    return PerformingWrites(
        set_state=flag_setter_over(client),
        restart=service_restarter_over(client),
        roll_back=deployment_roller_over(client),
        scale_out=deployment_scaler_over(client),
        pin=autoscaler_pinner_over(client)
    )


def autoscaler_pinner_over(client: McpClient) -> AutoscalerPinner:
    """The fifth write, over one connection."""
    return partial(pin_an_autoscaler, client=client)


def autoscaling_restorer_over(client: McpClient) -> AutoscalingRestorer:
    """Putting the fifth back, which is a tool of its own for the reason the
    fourth's is: two pieces of prior state and a platform that refuses one order of
    them, so the tier performs it as its own operation and answers with which
    halves it managed."""
    return partial(restore_an_autoscaler, client=client)


def deployment_restorer_over(client: McpClient) -> DeploymentRestorer:
    """Putting the third back, which is a tool of its own rather than the same
    call reversed.

    A flag's undo is `set_state` with the state the descriptor recorded, and one
    seam serves both directions. A rollback's is not: it has two pieces of prior
    state to restore and a platform that refuses one order of them, so the tier
    performs it as its own operation and answers with which halves it managed.
    """
    return partial(restore_a_deployment, client=client)


def _flag_changes_since(since: str, *, client: McpClient) -> list[FlagChange]:
    """The write tier's flag history, asked from one moment onwards.

    A named function rather than `get_recent_flag_changes` itself, because the
    agent needs exactly one of that tool's calling shapes and a seam is only
    useful if a test can spec against the shape the caller actually uses.
    """
    return get_recent_flag_changes(since, client=client)


def fetch_recent_flag_changes(
    settings: MitigationSettings,
    fetch: FlagChangesSince,
    now: Clock = utc_now,
    onset: datetime | None = None,
) -> list[FlagChange]:
    """The flag toggles recorded over the configured lookback, oldest first -
    excluding the ones Argus itself made.

    A named function rather than `get_recent_flag_changes` passed directly,
    because the agent needs exactly one of that tool's calling shapes - a
    window ending now - and a seam is only useful if a test can spec against
    the shape the caller actually uses. Deciding the window here also keeps
    `propose_action` free of both configuration and I/O.

    `fetch` is not defaulted, here or in the two questions below. It is the
    provider reached over a connection somebody opened, and a default would be
    this module deciding where that provider is - which belongs to whoever
    started the process. The clock still is: a clock is not an address.

    Argus's own changes are dropped here rather than by the caller, because
    every caller wants the same thing: what somebody *else* did. Once Argus can
    act more than once on an incident, its own revert lands in this window, and
    a window carrying it makes the unambiguous case - one flag changed, so that
    is the one to put back - report two flags and refuse to act.

    `onset` moves the window back to end where the incident began, and is left
    out by almost every caller. Ending it at the present asks what somebody
    *just* changed, which is the right question about an incident happening now
    and the wrong one about an incident a check found long afterwards: there the
    flag moved a week ago, a window ending now does not reach it, and the agent
    proposes nothing about a flag that is still on.

    Anchored rather than widened, and the difference matters. The lookback is
    short on purpose - a wide window makes "two flags changed, so no action" the
    common case - so it stays the width it was and only moves. The upper bound
    is applied here because the provider is asked from a moment and answers to
    the present: without it, a window anchored a week back carries a week. What
    it drops is changes made after the incident began, which did not cause it,
    and that is the rule the Investigator's own default window already applies.
    """
    lookback = timedelta(minutes=settings.flag_change_lookback_minutes)
    window_ends_at = onset if onset is not None else now()

    changes = changes_not_made_by(
        settings.unleash_actor,
        fetch(since=to_iso(window_ends_at - lookback)),
    )

    return [
        change for change in changes
        if parse_iso(change.occurred_at) <= window_ends_at
    ]


def argus_changed_flag_since(
    flag: str,
    since: datetime,
    settings: MitigationSettings,
    fetch: FlagChangesSince,
) -> bool | None:
    """Whether Argus's own change to `flag` reached the provider after `since`.

    The question a walk asks when it is resumed inside the mitigation node and
    finds an action claimed with nothing recorded against it: the worker that
    claimed it died, and only the provider knows whether the change it was
    making landed. The provider's event log is where that is written down, and
    it is already what tells Argus's changes from a human's - asked here in the
    one direction the rest of Argus never asks it.

    `None` means the provider could not say - it could not be reached, or it
    attributes nothing to Argus because operator and agent share a credential.
    A caller must not read that as "no change was made": the difference between
    an unmade change and an unanswerable question is the difference between
    acting again and escalating.
    """
    try:
        changes = fetch(since=to_iso(since))
    except Exception:
        # Every way the provider can fail to answer arrives here, and they all
        # mean the same thing to the caller: nobody can say. Narrowing this to
        # the transport's own exception would let a change in the client's
        # vocabulary turn "could not ask" into a crash inside a resumed walk.
        return None

    return change_by_actor_to(flag, settings.unleash_actor, changes)


def somebody_else_changed_flag_since(
    flag: str,
    since: datetime,
    settings: MitigationSettings,
    fetch: FlagChangesSince,
) -> bool | None:
    """Whether anybody but Argus changed `flag` after `since`.

    What an undo consults before it writes, and the mirror of the question
    above: not "did my change land" but "has anybody been in here since it
    did". The provider's event log answers it, and nothing else can - current
    state cannot, because a flag somebody switched and switched back reads
    exactly like one nobody touched, and the provider serves current state from
    a cache that lags the change that matters most.

    `None` means nobody can say: the provider could not be reached. A caller
    must not read it as "nobody has been in here" - the two are the difference
    between putting a change back and overwriting a person.

    A deployment that attributes nothing - operator and agent sharing one
    credential - answers `True`, because `changes_not_made_by` filters nothing
    there and Argus's own write is then indistinguishable from somebody else's.
    That is the safe direction: a flag left as found can be put back by hand,
    and a human's deliberate change overwritten cannot be recovered at all.
    """
    try:
        changes = fetch(since=to_iso(since))
    except Exception:
        return None

    return any(
        change.flag == flag
        for change in changes_not_made_by(settings.unleash_actor, changes)
    )


def fetch_recent_metrics(*, client: McpClient) -> list[MetricBucket]:
    """The service's metric buckets, over the retention the read tier holds.

    Unanchored deliberately. The verdict asks whether the minutes since the
    action sit at the service's baseline, and the baseline is the incident's
    own quiet stretch - a window narrowed to post-action minutes alone would
    have no departure to contrast with, and would read any steady rate as
    healthy however elevated it was.
    """
    return get_metrics_summary(client=client)


def restart_a_service(service: str, *, client: McpClient) -> RestartedService:
    """Restarts a service, answering with the process that came up.

    A named function rather than `restart_service` itself, for the reason
    `_flag_changes_since` is one: the agent needs one of that tool's calling
    shapes, and a seam is only useful if a test can spec against the shape the
    caller actually uses.
    """
    return restart_service(service, client=client)


def roll_back_a_deployment(application: str,
                           *,
                           client: McpClient) -> DeploymentRollbackUndo:
    """Returns a deployment to the revision it ran before, answering with what
    that cost.

    A named function rather than `roll_back_deployment` itself, for the
    reason `restart_a_service` is one: the agent needs one of that tool's
    calling shapes, and a seam is only useful if a test can spec against the
    shape the caller actually uses.
    """
    return roll_back_deployment(application, client=client)


def restore_a_deployment(descriptor: DeploymentRollbackUndo,
                         *,
                         client: McpClient) -> DeploymentRestored:
    """Puts back both of the things a rollback changed, reporting which it
    managed."""
    return restore_deployment(descriptor, client=client)


def scale_out_a_deployment(application: str,
                           *,
                           client: McpClient) -> ReplicaUndo:
    """Gives a deployment more replicas than it is running, answering with what
    that cost.

    A named function rather than `scale_out` itself, for the reason
    `restart_a_service` is one: the agent needs one of that tool's calling shapes,
    and a seam is only useful if a test can spec against the shape the caller
    actually uses.
    """
    return scale_out(application, client=client)


def restore_a_replica_count(descriptor: ReplicaUndo,
                            *,
                            client: McpClient) -> CapacityRestored:
    """Puts back both of the things a scale-out changed, reporting which it
    managed."""
    return restore_replica_count(descriptor, client=client)


def pin_an_autoscaler(application: str,
                      *,
                      client: McpClient) -> AutoscalerUndo:
    """Stops a deployment's autoscaler scaling it back down, answering with what
    that changed.

    A named function rather than `pin_autoscaler` itself, for the reason
    `scale_out_a_deployment` is one: the agent needs one of that tool's calling
    shapes, and a seam is only useful if a test can spec against the shape the
    caller actually uses.
    """
    return pin_autoscaler(application, client=client)


def restore_an_autoscaler(descriptor: AutoscalerUndo,
                          *,
                          client: McpClient) -> AutoscalingRestored:
    """Puts back both of the things a pin changed, reporting which it managed."""
    return restore_autoscaler_floor(descriptor, client=client)


def set_flag(flag: str, enabled: bool, *, client: McpClient) -> UndoDescriptor:
    """Sets a flag to a state, returning the undo descriptor for the change.

    One seam for both taking an action and undoing it: undoing is the same call
    with the state reversed. That is not a convenience - it is what lets a
    refuted mitigation be put back in whichever direction it went.
    """
    return set_feature_flag(flag, enabled, client=client)
