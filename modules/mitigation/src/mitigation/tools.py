from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Protocol

from core import SettingsSlice, parse_iso, to_iso, utc_now
from core.anomaly import the_end_of_the_onset
from core.mcp_transport import ActionExhausted, McpClient
from core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    Action,
    AlertRuleStanding,
    AutoscalerUndo,
    AutoscalingRestored,
    CacheEntriesDiscarded,
    CapacityRestored,
    ChangeEvent,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    FlagHistory,
    FlagUndo,
    MetricBucket,
    Planned,
    ReplicaUndo,
    RestartedService,
    RolloutProgress,
    UndoDescriptor,
)
from read_mcp_client import (
    get_alert_rule,
    get_change_events,
    get_metrics_summary,
    get_rollout_progress,
)
from write_mcp_client import (
    discard_cache_entries,
    get_recent_flag_changes,
    pin_autoscaler,
    pin_to_accelerator,
    plan_accelerator_pin,
    plan_autoscaler_pin,
    plan_flag,
    plan_rollback,
    plan_scale_out,
    restart_service,
    restore_accelerator_pin,
    restore_autoscaler_floor,
    restore_deployment,
    restore_replica_count,
    roll_back_deployment,
    scale_out,
    set_feature_flag,
    was_flag_changed_by_argus_since,
    was_flag_changed_by_others_since,
)

from mitigation.attribution import changes_not_made_by

logger = logging.getLogger(__name__)


class Arrival(StrEnum):
    """Whether the change an action made has taken effect on the service yet.

    Three answers because the wait has three ways out, and only one of them is a
    duration anybody could have picked. `ARRIVED` says the change is in force and
    the minutes from here describe it. `STILL_ARRIVING` says the platform is
    working on it, so the minutes so far describe the code being replaced and
    judging them would judge the wrong deployment. `WILL_NOT_ARRIVE` says the
    platform has stopped - a rolling update it is holding, or a Deployment it
    reports failed - so nothing is going to change by waiting longer.

    That third answer is what gives the wait an end without a figure. A rollout
    stopped part way never converges, so a loop holding only "arrived or not"
    would poll until its lease expired and leave the change applied for another
    worker to find. A failed Deployment ends either wait; a pause ends only a
    rollback's, because the platform goes on scaling a paused Deployment. It is
    the counts that are asked first: a rollout stopped *after* it finished has
    arrived, and neither state says anything about a change already in force on
    every replica. Both are states the platform reports, not lengths of time
    somebody judged, which is why they can be read here at all - spec §16 keeps
    the "has this taken too long" judgement away from the channel precisely
    because a replica count and a timestamp cannot support it.

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


# The flag history asked from a moment the caller says, rather than one
# configuration says: `fetch_recent_flag_changes` works the start out from the
# lookback and, where one was stated, the onset.
class FlagChangesSince(Protocol):
    def __call__(self, since: str) -> list[FlagChange]: ...


class DeploymentsBetween(Protocol):
    """What Mitigation needs from whatever reads a service's deploy history.

    A window rather than a moment, unlike the flag history above, because that
    is how the platform is asked: a history entry belongs to an application, and
    the read tier answers for a span of it.
    """

    def __call__(self,
                 *,
                 service: str,
                 window_start: str,
                 window_end: str) -> list[ChangeEvent]: ...
# The service's own account of itself, and the one way to change what it does.
# `Protocol` rather than a `Callable` alias for both, because a test stands each
# in with `create_autospec` and specing against the function that answers them
# would be specing against the wrong shape: those take the connection they are
# asked over, and neither of these knows a server exists.


class MetricsFetcher(Protocol):
    """The service's metrics, read for the rule that paged.

    The rule rather than the series it watches: what that series is called in
    the metrics backend's own language is the read tier's to work out, and
    nothing on this side of the port speaks it. `None` for an alert naming no
    rule, which is read for the five fixed series alone.
    """

    def __call__(self, rule: str | None, /) -> list[MetricBucket]: ...


class RuleReader(Protocol):
    """Where an alert rule stands, by the reference the alert carried.

    What an action on an incident paged by a series alert is judged by: the
    rule defines what is acceptable for the service.
    """

    def __call__(self, rule: str, /) -> AlertRuleStanding: ...


class FlagSetter(Protocol):
    """Setting a flag to a state with nothing planned for it - what puts a
    flag back, which plans and writes in one breath because the check that
    guards it was asked a moment before. A flag already in the state asked for
    is answered as put there, with nothing written (`set_flag`)."""

    def __call__(self, flag: str, enabled: bool, /) -> UndoDescriptor: ...


class FlagPlanner(Protocol):
    """Working out a flag change before it is claimed: the state the provider
    holds the flag in, and the provider's own time for that read.

    The flag and the state asked for, and nothing else - which state the flag
    is in is the tier's to read, through the admin credential only it holds. A
    read: it changes nothing, and refuses as spent a flag already as asked.
    """

    def __call__(self, flag: str, enabled: bool, /) -> Planned[FlagUndo]: ...


class PlannedFlagSetter(Protocol):
    """The first of the writes: setting the planned flag to a state.

    Handed the plan the claim carries rather than the flag's name, because the
    write compares the provider's history since the plan's read with it before
    it changes anything, and a write handed the name alone would have nothing to
    compare with. Refuses with `ChangedSince` where somebody else has changed
    the flag since.
    """

    def __call__(self, planned: Planned[FlagUndo], enabled: bool, /) -> UndoDescriptor: ...


class RollbackPlanner(Protocol):
    """Working out a rollback before it is claimed: the entry the deployment is
    on, the one it would go back to, and whether the platform reconciles it
    itself, dated by the platform's clock.

    The application, and nothing else, for the reason `DeploymentRoller` once
    took nothing else: which entry to return to is the platform's history to
    resolve, and nothing above this port holds it.
    """

    def __call__(self, application: str, /) -> Planned[DeploymentRollbackUndo]: ...


class ScaleOutPlanner(Protocol):
    """Working out a scale-out before it is claimed: the count running, the count
    it would be given, and whether the platform reconciles it itself.

    No count goes with it: what to scale to is the tier's to resolve from what
    is running, and a figure named here would be this layer asserting a fact
    about live state it cannot read. Refuses as spent a deployment already as
    large as Argus may make it.
    """

    def __call__(self, application: str, /) -> Planned[ReplicaUndo]: ...


class AutoscalerPinPlanner(Protocol):
    """Working out an autoscaler pin before it is claimed: the floor it has, the
    floor it would be raised to, and whether the platform reconciles it itself.

    The application alone, for `ScaleOutPlanner`'s reason: the floor is worked
    out from the autoscaler's own ceiling, which only the tier reads.
    """

    def __call__(self, application: str, /) -> Planned[AutoscalerUndo]: ...


class AcceleratorPinPlanner(Protocol):
    """Working out a pin to a card before it is claimed: the card the pods are
    held to now, the card they would be held to, and whether the platform
    reconciles the application itself.

    The application and the card. Which card is worked out from where the
    replicas started before the onset, a reading the tier never saw - so the
    tier is told it here, once, and the write holds the pods to the card the
    claim recorded.
    """

    def __call__(self, application: str, accelerator: str, /) -> Planned[AcceleratorPinUndo]: ...


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

    The plan, and nothing else. Which entry to return to was the platform's to
    resolve when the rollback was planned - nothing above this port holds a
    deployment history to choose from, and a commit Argus found in a diff is not
    necessarily a revision this application ever ran - and the write returns to
    the entry the claim recorded rather than working it out again from a
    history that may have moved since.

    It answers with the descriptor recording what it changed, and the
    descriptor records *two* things: the platform refuses a rollback while it
    is reconciling the application itself, so suspending that is part of
    performing this rather than a separate concern - and an undo that restored
    only the revision would leave the deployment silently receiving nothing
    anybody ships to it.
    """

    def __call__(self,
                 planned: Planned[DeploymentRollbackUndo], /) -> DeploymentRollbackUndo: ...


class DeploymentScaler(Protocol):
    """The tier's fourth write: giving a deployment more replicas than it has.

    The plan, and nothing else. How many was the tier's to resolve when it
    planned - it read what was running and doubled it - and the write bounds the
    result by a ceiling of its own, because a target count is meaningless without
    the count it replaces and nothing above the port can read that.

    It answers with the descriptor recording what it changed, and the descriptor
    records *two* things for the reason a rollback's does: a platform reconciling
    the application itself puts a live replica count straight back, so suspending
    that is part of performing this rather than a separate concern. The count it
    records is the one the write found, which an autoscaler may have moved since
    the plan.
    """

    def __call__(self, planned: Planned[ReplicaUndo], /) -> ReplicaUndo: ...


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

    The plan, and nothing else. How high the floor goes was the tier's to
    resolve when it planned - it read the autoscaler's own ceiling and raised the
    floor to meet it, bounded by a ceiling of its own - because a floor is
    meaningless without the ceiling it is raised to, and because that ceiling is
    a bound somebody declared for the deployment rather than a figure an agent
    may assert.

    It answers with the descriptor recording what it changed, and the descriptor
    records *two* things for the reason a scale-out's does: a platform reconciling
    the application itself re-applies the autoscaler the repository declares, floor
    included, so suspending that is part of performing this rather than a separate
    concern.
    """

    def __call__(self, planned: Planned[AutoscalerUndo], /) -> AutoscalerUndo: ...


class CacheEntryDiscarder(Protocol):
    """Throwing away the copies a check found disagreeing with their records.

    The keys and nothing else. They are addresses rather than descriptions, and
    they come from the evidence that named them: a key's format belongs to
    whoever wrote the store, so nothing above this composes one, and a parameter
    that could match a key it was not given - a pattern, a prefix, a service -
    would be a blast radius its caller could not state.

    It answers with how many of those keys existed and are now gone, which makes
    this the one write in the bundle whose own answer is evidence rather than an
    acknowledgement. Everything else here reports that a request was accepted and
    leaves whether it helped to be watched for; a store saying how many copies it
    removed has stated the thing the incident was about.

    So the figure is the store's and never the caller's. Fewer than were named is
    not a failure - something else may already have discarded them, and an entry
    absent is what the incident needed - but it has to be reported honestly,
    because that figure is what an attempt is confirmed from and what the account
    of the incident reads out.
    """

    def __call__(self, keys: Sequence[str], /) -> CacheEntriesDiscarded: ...


class AutoscalingRestorer(Protocol):
    """Letting a pinned autoscaler move again, as Argus found it.

    Both of the things the pin changed, and it answers with which of them it
    managed rather than with nothing - for the reason the capacity restorer above
    does: a restore that half-succeeded is not a restore, and the caller has to be
    able to say which half is still changed.
    """

    def __call__(self, descriptor: AutoscalerUndo, /) -> AutoscalingRestored: ...


class AcceleratorPinner(Protocol):
    """Holding a deployment's pods to one accelerator card.

    The plan, which carries the card: the tier was told it when the pin was
    planned, and holds the pods to the card the claim recorded rather than one
    it is told a second time.

    It answers with the descriptor recording what it changed, and the descriptor
    records *two* things for the reason the autoscaler pin's does: a platform
    reconciling the application re-applies the declared pod template, selector
    included, so suspending that is part of performing this.
    """

    def __call__(self, planned: Planned[AcceleratorPinUndo], /) -> AcceleratorPinUndo: ...


class AcceleratorPinRestorer(Protocol):
    """Letting a deployment's pods off the card Argus held them to, as Argus
    found them.

    Both of the things the pin changed, answered with which it managed, for the
    reason every restorer here answers that way.
    """

    def __call__(self, descriptor: AcceleratorPinUndo, /) -> AcceleratorPinRestored: ...


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
    undoes one are two collaborations, and `PuttingBack` holds the second.

    The planners are here, though each is a read, because a plan is asked of the
    tier that writes from it: it is what that write compares the estate with,
    read through the same port the compare reads through - and a flag's plan
    needs the admin credential only the write tier holds.
    """

    set_state: PlannedFlagSetter
    restart: ServiceRestarter
    roll_back: DeploymentRoller
    scale_out: DeploymentScaler
    pin: AutoscalerPinner
    discard: CacheEntryDiscarder
    pin_to_accelerator: AcceleratorPinner
    plan_flag: FlagPlanner
    plan_rollback: RollbackPlanner
    plan_scale_out: ScaleOutPlanner
    plan_autoscaler_pin: AutoscalerPinPlanner
    plan_accelerator_pin: AcceleratorPinPlanner


@dataclass(frozen=True)
class PuttingBack:
    """The collaborations that put a change back - one restorer per kind that
    leaves one, and the check that guards a flag's.

    Apart from `PerformingWrites` because they happen at a different moment and
    for a different caller: a refuted action puts its own change back after the
    wait, and a withdrawal puts back every change an incident made, long after
    the writes that made them.

    Each member is bound over the tier that serves it. Today all of them are the
    write tier, because the restorers are writes and the provider serves its
    audit log - which `changed_from_outside` reads - to write credentials alone.
    """

    set_state: FlagSetter
    restore_deployment: DeploymentRestorer
    restore_capacity: CapacityRestorer
    restore_autoscaling: AutoscalingRestorer
    restore_accelerator_pin: AcceleratorPinRestorer
    changed_from_outside: ChangedFromOutside


Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
# Whether somebody other than Argus changed a flag since a given moment, or
# `None` where nobody can say. What an undo consults before it writes: a change
# made after Argus's own is somebody's deliberate decision, and putting the flag
# back would replace it with a state nobody chose.
ChangedFromOutside = Callable[[str, datetime], bool | None]


class MitigationSettings(SettingsSlice):
    """How Mitigation behaves against the provider and the service.

    How far back a window of recent changes reaches, which deployments Argus
    recognises as its own, and how long it waits while nothing has been measured.
    Not how long the service is watched for: that is measured off the window the
    service answers with - plus `metrics_reporting_lag_minutes`, how long after a
    minute ends the metrics source reports it, without which the wait ends before
    the minute that decides it can be read.

    `argocd_actor` is empty where Argus and its operators share one credential on
    the platform. That is a real deployment and not a misconfiguration - the
    attribution rules filter nothing there rather than guessing. Whose a flag
    change was is not here: the provider's adapter says so on the change itself.
    """

    mitigation_change_lookback_minutes: int
    argocd_actor: str
    mitigation_verification_timeout_seconds: float
    mitigation_attempts_per_subject: int
    metrics_reporting_lag_minutes: int


def flag_changes_over(client: McpClient) -> FlagChangesSince:
    """The provider's flag history, asked over one connection to the write tier.

    The tier is the write tier because the provider serves its audit log to
    admin credentials only, and `argus-read-mcp` holds none by design. Reading
    history is strictly less than the write tier can already do.
    """
    return partial(_flag_changes_since, client=client)


def deployments_over(client: McpClient) -> DeploymentsBetween:
    """The platform's deploy history, asked over one connection to the read tier.

    The read tier, unlike the flag history's, because the platform's history is
    readable with the read tier's own credential - the Investigator's change
    channel asks it there for the same reason.
    """
    return partial(get_change_events, client=client)


def recent_metrics_over(client: McpClient) -> MetricsFetcher:
    """The service's metrics, asked over one connection to the read tier."""
    return partial(fetch_recent_metrics, client=client)


def rules_read_over(client: McpClient) -> RuleReader:
    """Alert rules, read over one connection to the read tier."""
    return partial(get_alert_rule, client=client)


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


class RolloutReader(Protocol):
    """How far a service's rollout has got, as counts.

    What an action that changes a Deployment waits on: the revision reaching
    every replica, or the replicas asked for existing. Which of the two counts
    answers is the kind's to say; this only reads them.
    """

    def __call__(self, service: str, /) -> RolloutProgress: ...


def rollout_progress_over(client: McpClient) -> RolloutReader:
    """How far a service's rollout has got, asked over one connection to the read
    tier.

    The read tier because this is a read, which is the same reason the metrics are
    asked there. The two clients are interchangeable at the type level, so a seam
    bound to the wrong one fails at the moment the walk has already changed
    production and the incident is still happening.
    """
    return partial(get_rollout_progress, client=client)


def flag_setter_over(client: McpClient) -> FlagSetter:
    """Setting a flag with nothing planned for it, over one connection to the
    write tier - what puts a flag back."""
    return partial(set_flag, client=client)


def planned_flag_setter_over(client: McpClient) -> PlannedFlagSetter:
    """The first of the writes Argus makes, from its plan, over one connection
    to the write tier."""
    return partial(set_a_planned_flag, client=client)


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
        set_state=planned_flag_setter_over(client),
        restart=service_restarter_over(client),
        roll_back=deployment_roller_over(client),
        scale_out=deployment_scaler_over(client),
        pin=autoscaler_pinner_over(client),
        discard=cache_entry_discarder_over(client),
        pin_to_accelerator=accelerator_pinner_over(client),
        plan_flag=partial(plan_a_flag, client=client),
        plan_rollback=partial(plan_a_rollback, client=client),
        plan_scale_out=partial(plan_a_scale_out, client=client),
        plan_autoscaler_pin=partial(plan_an_autoscaler_pin, client=client),
        plan_accelerator_pin=partial(plan_a_pin_to_a_card, client=client)
    )


def putting_back_over(client: McpClient) -> PuttingBack:
    """Everything that puts a change back, over one connection to the write tier.

    Here rather than at the one caller that binds it, for the reason
    `performing_writes_over` is: the bundle and the connection are the same fact
    said twice.
    """
    return PuttingBack(
        set_state=flag_setter_over(client),
        restore_deployment=deployment_restorer_over(client),
        restore_capacity=capacity_restorer_over(client),
        restore_autoscaling=autoscaling_restorer_over(client),
        restore_accelerator_pin=accelerator_pin_restorer_over(client),
        changed_from_outside=partial(somebody_else_changed_flag_since, client=client)
    )


def autoscaler_pinner_over(client: McpClient) -> AutoscalerPinner:
    """The fifth write, over one connection."""
    return partial(pin_an_autoscaler, client=client)


def cache_entry_discarder_over(client: McpClient) -> CacheEntryDiscarder:
    """The sixth write, over one connection - and the only one not aimed at a
    control plane."""
    return partial(discard_the_cache_entries, client=client)


def accelerator_pinner_over(client: McpClient) -> AcceleratorPinner:
    """The seventh write, over one connection."""
    return partial(pin_a_deployment_to_a_card, client=client)


def accelerator_pin_restorer_over(client: McpClient) -> AcceleratorPinRestorer:
    """Putting the seventh back, which is a tool of its own for the autoscaler
    pin's reason: two pieces of prior state and a platform that refuses one order
    of them."""
    return partial(restore_a_card_pin, client=client)


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
    Mitigator needs exactly one of that tool's calling shapes and a seam is only
    useful if a test can spec against the shape the caller actually uses.
    """
    return get_recent_flag_changes(since, client=client)


def fetch_recent_flag_changes(
    settings: MitigationSettings,
    fetch: FlagChangesSince,
    now: Clock = utc_now,
    onset: datetime | None = None,
) -> FlagHistory:
    """The flag toggles recorded over the configured lookback, oldest first -
    excluding the ones Argus itself made - and the window they were read over.

    The window is the one the changes were kept from, its end computed once and
    used for the question and the cut alike, so that what is said of the read
    is exactly what the list covers.

    A named function rather than `get_recent_flag_changes` passed directly,
    because the Mitigator needs exactly one of that tool's calling shapes - a
    window ending now - and a seam is only useful if a test can spec against
    the shape the caller actually uses. Deciding the window here also keeps
    `propose_action` free of both configuration and I/O.

    `fetch` is not defaulted. It is the provider reached over a connection
    somebody opened, and a default would be this module deciding where that
    provider is - which belongs to whoever started the process. The clock still
    is: a clock is not an address.

    Argus's own changes are dropped here rather than by the caller, because
    every caller wants the same thing: what somebody *else* did. Once Argus can
    act more than once on an incident, its own revert lands in this window, and
    a window carrying it makes the unambiguous case - one flag changed, so that
    is the one to revert - report two flags and refuse to act. Whose a change
    was is the provider's adapter's to say (`FlagChange.made_by_argus`); a
    change nobody can say of is kept, because the costly mistake is discarding a
    human's change - the real evidence - rather than keeping one of Argus's.

    `onset` moves the window back to end where the incident began, and is left
    out by almost every caller. Ending it at the present asks what somebody
    *just* changed, which is the right question about an incident happening now
    and the wrong one about an incident a check found long afterwards: there the
    flag moved a week ago, a window ending now does not reach it, and the Mitigator
    proposes nothing about a flag that is still on.

    Anchored rather than widened, and the difference matters. The lookback is
    short on purpose - a wide window makes "two flags changed, so no action" the
    common case - so it keeps its lookback and ends with the onset. The upper bound
    is applied here because the provider is asked from a moment and answers to
    the present: without it, a window anchored a week back carries a week. What
    it drops is changes made after the incident began, which did not cause it,
    and that is the rule the Investigator's own default window already applies:
    it ends with the onset (`the_end_of_the_onset`), so a flag switched on a
    few seconds into the minute it broke is read by both.
    """
    lookback = timedelta(minutes=settings.mitigation_change_lookback_minutes)
    anchored_at = onset if onset is not None else now()
    window_starts_at = anchored_at - lookback
    window_ends_at = the_end_of_the_onset(onset) if onset is not None else anchored_at

    changes = fetch(since=to_iso(window_starts_at))

    return FlagHistory(
        changes=[change for change in changes
                 if change.made_by_argus is not True
                 and parse_iso(change.occurred_at) <= window_ends_at],
        since=window_starts_at,
        until=window_ends_at
    )


def fetch_recent_deployments(
    settings: MitigationSettings,
    fetch: DeploymentsBetween,
    service: str,
    now: Clock = utc_now,
    onset: datetime | None = None
) -> list[ChangeEvent]:
    """The deployments of `service` recorded over the configured lookback,
    oldest first.

    The flag history's window, asked of the other change a service has: the
    same lookback, ending in the same place - with the onset where the alert stated
    one, now where it did not. Not a lookback of its own, because the question
    is the same one: what somebody changed just before this began. A mode that
    names the damage rather than the change is answered by undoing whichever of
    the two the record holds there, and the two records have to be read over
    one span or the answer depends on which of them reached further.

    Argus's own rollbacks are dropped, as its flag reverts are and for the same
    reason: where no onset was stated the window ends now, and a round after
    Argus rolled back would read its rollback as the newest deployment - and
    propose rolling that back.
    """
    lookback = timedelta(minutes=settings.mitigation_change_lookback_minutes)
    anchored_at = onset if onset is not None else now()
    window_ends_at = the_end_of_the_onset(onset) if onset is not None else anchored_at

    return changes_not_made_by(
        settings.argocd_actor,
        fetch(
            service=service,
            window_start=to_iso(anchored_at - lookback),
            window_end=to_iso(window_ends_at)
        )
    )


def argus_changed_flag_since(flag: str,
                             since: datetime,
                             *,
                             client: McpClient) -> bool | None:
    """Whether Argus's own change to `flag` reached the provider after `since`.

    The question a walk asks when it is resumed inside the mitigation node and
    finds an action claimed with nothing recorded against it: the worker that
    claimed it died, and only the provider knows whether the change it was
    making landed. The provider's event log is where that is written down, and
    the write tier asks it - the log is served to that tier's credential alone,
    and the provider's adapter there is what tells Argus's changes from a
    human's.

    `None` means nobody could say - the write tier could not be reached, the
    provider's history could not be read, or it attributes nothing to Argus
    because operator and Argus share a credential. A caller must not read that
    as "no change was made": the difference between an unmade change and an
    unanswerable question is the difference between acting again and
    escalating.
    """
    try:
        return was_flag_changed_by_argus_since(flag, since, client=client)
    except Exception:
        # Every way the tier can fail to answer arrives here, and they all mean
        # the same thing to the caller: nobody can say. Narrowing this to the
        # transport's own exception would let a change in the client's
        # vocabulary turn "could not ask" into a crash inside a resumed walk.
        logger.warning("flag history could not be read", exc_info=True, extra={"flag": flag})

        return None


def somebody_else_changed_flag_since(flag: str,
                                     since: datetime,
                                     *,
                                     client: McpClient) -> bool | None:
    """Whether anybody but Argus changed `flag` after `since`.

    What an undo consults before it writes, and the mirror of the question
    above: not "did my change land" but "has anybody been in here since it
    did". The provider's event log answers it, and nothing else can - current
    state cannot, because a flag somebody switched and switched back reads
    exactly like one nobody touched, and the provider serves current state from
    a cache that lags the change that matters most.

    `None` means nobody can say, for the reasons the question above gives. A
    caller must not read it as "nobody has been in here" - the two are the
    difference between putting a change back and overwriting a person.
    """
    try:
        return was_flag_changed_by_others_since(flag, since, client=client)
    except Exception:
        logger.warning("flag history could not be read", exc_info=True, extra={"flag": flag})

        return None


def fetch_recent_metrics(rule: str | None, *, client: McpClient) -> list[MetricBucket]:
    """The service's metric buckets, over the retention the read tier holds.

    Unanchored deliberately. The verdict asks whether the minutes since the
    action sit at the service's baseline, and the baseline is the incident's
    own quiet stretch - a window narrowed to post-action minutes alone would
    have no departure to contrast with, and would read any steady rate as
    healthy however elevated it was.

    Read for the rule that paged, so each minute carries that rule's own series
    beside the five - and the recovery is dated on the series that paged rather
    than on five that may never have moved.
    """
    return get_metrics_summary(rule=rule, client=client)


def restart_a_service(service: str, *, client: McpClient) -> RestartedService:
    """Restarts a service, answering with the process that came up.

    A named function rather than `restart_service` itself, for the reason
    `_flag_changes_since` is one: the Mitigator needs one of that tool's calling
    shapes, and a seam is only useful if a test can spec against the shape the
    caller actually uses.
    """
    return restart_service(service, client=client)


def plan_a_rollback(application: str,
                    *,
                    client: McpClient) -> Planned[DeploymentRollbackUndo]:
    """Works out returning a deployment to the revision it ran before, changing
    nothing.

    A named function rather than `plan_rollback` itself, for the reason
    `restart_a_service` is one: a seam is only useful if a test can spec against
    the shape the caller actually uses.
    """
    return plan_rollback(application, client=client)


def roll_back_a_deployment(planned: Planned[DeploymentRollbackUndo],
                           *,
                           client: McpClient) -> DeploymentRollbackUndo:
    """Returns a deployment to the entry its plan named, answering with what
    that cost.

    A named function rather than `roll_back_deployment` itself, for the
    reason `restart_a_service` is one: the Mitigator needs one of that tool's
    calling shapes, and a seam is only useful if a test can spec against the
    shape the caller actually uses.
    """
    return roll_back_deployment(planned, client=client)


def restore_a_deployment(descriptor: DeploymentRollbackUndo,
                         *,
                         client: McpClient) -> DeploymentRestored:
    """Puts back both of the things a rollback changed, reporting which it
    managed."""
    return restore_deployment(descriptor, client=client)


def plan_a_scale_out(application: str,
                     *,
                     client: McpClient) -> Planned[ReplicaUndo]:
    """Works out giving a deployment more replicas than it is running, changing
    nothing. Named for `plan_a_rollback`'s reason."""
    return plan_scale_out(application, client=client)


def scale_out_a_deployment(planned: Planned[ReplicaUndo],
                           *,
                           client: McpClient) -> ReplicaUndo:
    """Gives a deployment the replicas its plan asked for, answering with what
    that cost.

    A named function rather than `scale_out` itself, for the reason
    `restart_a_service` is one: the Mitigator needs one of that tool's calling shapes,
    and a seam is only useful if a test can spec against the shape the caller
    actually uses.
    """
    return scale_out(planned, client=client)


def restore_a_replica_count(descriptor: ReplicaUndo,
                            *,
                            client: McpClient) -> CapacityRestored:
    """Puts back both of the things a scale-out changed, reporting which it
    managed."""
    return restore_replica_count(descriptor, client=client)


def plan_an_autoscaler_pin(application: str,
                           *,
                           client: McpClient) -> Planned[AutoscalerUndo]:
    """Works out stopping a deployment's autoscaler scaling it back down,
    changing nothing. Named for `plan_a_rollback`'s reason."""
    return plan_autoscaler_pin(application, client=client)


def pin_an_autoscaler(planned: Planned[AutoscalerUndo],
                      *,
                      client: McpClient) -> AutoscalerUndo:
    """Stops a deployment's autoscaler scaling it back down as its plan said,
    answering with what that changed.

    A named function rather than `pin_autoscaler` itself, for the reason
    `scale_out_a_deployment` is one: the Mitigator needs one of that tool's calling
    shapes, and a seam is only useful if a test can spec against the shape the
    caller actually uses.
    """
    return pin_autoscaler(planned, client=client)


def discard_the_cache_entries(keys: Sequence[str],
                              *,
                              client: McpClient) -> CacheEntriesDiscarded:
    """Throws away the named cache entries, answering with how many were there.

    A named function rather than the tool itself, for the reason
    `pin_an_autoscaler` is one: the Mitigator needs one of that tool's calling shapes,
    and a seam is only useful if a test can spec against the shape the caller
    actually uses.
    """
    return discard_cache_entries(keys, client=client)


def restore_an_autoscaler(descriptor: AutoscalerUndo,
                          *,
                          client: McpClient) -> AutoscalingRestored:
    """Puts back both of the things a pin changed, reporting which it managed."""
    return restore_autoscaler_floor(descriptor, client=client)


def plan_a_pin_to_a_card(application: str,
                         accelerator: str,
                         *,
                         client: McpClient) -> Planned[AcceleratorPinUndo]:
    """Works out holding a deployment's pods to one card, changing nothing.
    Named for `plan_a_rollback`'s reason."""
    return plan_accelerator_pin(application, accelerator, client=client)


def pin_a_deployment_to_a_card(planned: Planned[AcceleratorPinUndo],
                               *,
                               client: McpClient) -> AcceleratorPinUndo:
    """Holds a deployment's pods to the card its plan named, answering with what
    that changed.

    A named function rather than the client's own, for the reason
    `pin_an_autoscaler` is one: a seam is only useful if a test can spec against
    the shape the caller actually uses.
    """
    return pin_to_accelerator(planned, client=client)


def restore_a_card_pin(descriptor: AcceleratorPinUndo,
                       *,
                       client: McpClient) -> AcceleratorPinRestored:
    """Puts back both of the things a pin to a card changed, reporting which it
    managed."""
    return restore_accelerator_pin(descriptor, client=client)


def plan_a_flag(flag: str, enabled: bool, *, client: McpClient) -> Planned[FlagUndo]:
    """Works out setting a flag to a state, changing nothing. Named for
    `plan_a_rollback`'s reason."""
    return plan_flag(flag, enabled, client=client)


def set_a_planned_flag(planned: Planned[FlagUndo],
                       enabled: bool,
                       *,
                       client: McpClient) -> UndoDescriptor:
    """Sets the flag its plan named to a state, returning the undo descriptor
    for the change. Named for `plan_a_rollback`'s reason."""
    return set_feature_flag(planned, enabled, client=client)


def set_flag(flag: str, enabled: bool, *, client: McpClient) -> UndoDescriptor:
    """Sets a flag to a state, planned and written in one breath, returning the
    undo descriptor for the change.

    What puts a flag back. The tier writes a flag only from a plan, and a
    put-back has no claim to have carried one: the check that guards it - has
    anybody but Argus changed the flag since Argus set it - was asked a moment
    before, so the plan is read here, immediately before the write it is for,
    and the write compares the provider's history since that read as it does an
    action's.

    A flag the plan finds already in the state asked for is answered as put
    there, and nothing is written. That check has just established nobody but
    Argus has changed the flag since Argus set it, so a flag already back can
    only be Argus's own put-back having landed - a put-back whose answer was
    lost, asked again. Refusing it as spent would report a change that is back
    where Argus found it as one nobody can account for. The answer is what the
    flag was found in, which is the state asked for.
    """
    try:
        planned = plan_flag(flag, enabled, client=client)
    except ActionExhausted:
        return FlagUndo(flag=flag, was_enabled=enabled)

    return set_feature_flag(planned, enabled, client=client)
