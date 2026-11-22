from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from types import TracebackType
from typing import Final, Self

from core import Holding, WriteMcpEndpoint, to_iso
from core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    AutoscalerUndo,
    AutoscalingRestored,
    CacheEntriesDiscarded,
    CapacityRestored,
    ChangeFound,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    FlagUndo,
    Made,
    NotMade,
    OpenedPullRequest,
    Planned,
    ReplicaUndo,
    RestartedService,
    UndoDescriptor,
    parse_undo_descriptor,
)
from mcp_transport import Asking, McpClient
from pydantic import TypeAdapter

# One tool answers with a list this module has to build; the other answers with
# a descriptor the kernel already knows how to read, and `parse_undo_descriptor`
# is passed as it stands. A union decides which member a stored object is, and
# that decision has one door - reading it a second way here would be a second
# place for it to be decided differently.
_FLAG_CHANGES: Final = TypeAdapter(list[FlagChange])

# Whether anybody else changed a flag, answered as a yes, a no, or
# nobody-can-say - validated rather than cast, so `None` crosses as itself and
# anything else the tier said is refused here rather than read as an answer.
_AN_ANSWER_OR_NONE: Final[TypeAdapter[bool | None]] = TypeAdapter(bool | None)

_OPENED_PULL_REQUEST: Final = TypeAdapter(OpenedPullRequest)

_RESTARTED_SERVICE: Final = TypeAdapter(RestartedService)

_DEPLOYMENT_RESTORED: Final = TypeAdapter(DeploymentRestored)

_CAPACITY_RESTORED: Final = TypeAdapter(CapacityRestored)
_CACHE_ENTRIES_DISCARDED: Final = TypeAdapter(CacheEntriesDiscarded)

_AUTOSCALING_RESTORED: Final = TypeAdapter(AutoscalingRestored)

_ACCELERATOR_PIN_RESTORED: Final = TypeAdapter(AcceleratorPinRestored)

# Each plan, read as the plan of the kind its action makes. The kind is the
# tool's, not the answer's to choose, so a plan of any other kind is refused
# here rather than read through the union: there is nothing to decide.
_PLANNED_FLAG: Final = TypeAdapter(Planned[FlagUndo])
_PLANNED_ROLLBACK: Final = TypeAdapter(Planned[DeploymentRollbackUndo])
_PLANNED_SCALE_OUT: Final = TypeAdapter(Planned[ReplicaUndo])
_PLANNED_AUTOSCALER_PIN: Final = TypeAdapter(Planned[AutoscalerUndo])
_PLANNED_ACCELERATOR_PIN: Final = TypeAdapter(Planned[AcceleratorPinUndo])

# What a resumed walk's two reads answer: a claim's change found made or not
# made - what of the claim's is out there all the same carried on the second -
# read as the kind the tool asks after; and a performed change found still
# Argus's, changed since, or nobody's to say. The two answers share no field
# and `NotMade` refuses extra ones, so neither is read as the other.
_MADE_FLAG: Final[TypeAdapter[Made[FlagUndo] | NotMade[FlagUndo]]] = TypeAdapter(
    Made[FlagUndo] | NotMade[FlagUndo]
)
_MADE_ROLLBACK: Final[
    TypeAdapter[Made[DeploymentRollbackUndo] | NotMade[DeploymentRollbackUndo]]
] = TypeAdapter(Made[DeploymentRollbackUndo] | NotMade[DeploymentRollbackUndo])
_MADE_SCALE_OUT: Final[TypeAdapter[Made[ReplicaUndo] | NotMade[ReplicaUndo]]] = TypeAdapter(
    Made[ReplicaUndo] | NotMade[ReplicaUndo]
)
_MADE_AUTOSCALER_PIN: Final[
    TypeAdapter[Made[AutoscalerUndo] | NotMade[AutoscalerUndo]]
] = TypeAdapter(Made[AutoscalerUndo] | NotMade[AutoscalerUndo])
_MADE_ACCELERATOR_PIN: Final[
    TypeAdapter[Made[AcceleratorPinUndo] | NotMade[AcceleratorPinUndo]]
] = TypeAdapter(Made[AcceleratorPinUndo] | NotMade[AcceleratorPinUndo])
_CHANGE_FOUND: Final = TypeAdapter(ChangeFound)

# The branch a fix was written to, which the server answers with as a bare
# string. Validated rather than cast: what comes back is handed straight to
# `open_pull_request` as the branch to propose, and a tool that answered with
# something else would have that failure surface two calls later.
_A_BRANCH: Final = TypeAdapter(str)

# Where the server's tools are served, under the address the endpoint names.
_MCP_PATH: Final = "/mcp"


def write_mcp(endpoint: WriteMcpEndpoint,
              holding: Holding | None = None,
              builds_client: Callable[..., McpClient] = McpClient) -> WriteTier:
    """The write tier, over one session held to `argus-write-mcp`.

    Built where a process starts, and separate from the read tier because the
    servers are separate - two sessions to two addresses.

    A process that walks runs hands over what it is `holding`, and each call
    says the claim held as it is made: the tier makes a change only for the
    claim that holds its run. A process holding none can still read.

    Each call waits as long as the endpoint says for its answer: above the
    slowest tool this tier serves, which is `restart_service` - two requests,
    then up to sixty looks at the platform a second apart, each under its
    ten-second timeout, about eleven and a half minutes, after up to five
    seconds' wait for its run to be free. `builds_client` builds the session,
    and is a parameter so that what it was built with can be asserted without
    building one.
    """
    return WriteTier(builds_client(f"{endpoint.write_mcp_url}{_MCP_PATH}",
                                   answered_within=endpoint.write_mcp_answered_within_seconds,
                                   holding=holding))


class WriteTier:
    """`argus-write-mcp`, one method per tool it serves.

    A type of its own rather than the session it is asked over, for the reason
    the read tier's is: held as a bare client, the two tiers were
    interchangeable to the type checker, and a write bound to the read tier -
    or a read bound here - failed only when it was asked. The read tier's
    class has none of these methods and this one has none of its, so binding
    either to the wrong tier is a type error.

    Holding one authorizes nothing: what makes the write tier the write tier is
    the credential that server holds and the tools it has (spec §12.1, §13).
    Each method is the tool's own calling shape, so a bound method is what a
    seam is bound to - `write.plan_rollback` where the Mitigator plans one.
    """

    def __init__(self, session: McpClient) -> None:
        self._session = session

    def __enter__(self) -> Self:
        return self

    def __exit__(self,
                 exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self._session.close()

    def plan_flag(self, flag: str, enabled: bool) -> Planned[FlagUndo]:
        """Plans setting a feature flag on or off: the state the provider holds it
        in, and the provider's own time for that read.

        A read, asked before the action is claimed, and it changes nothing. What it
        answers is what the claim records and what `set_feature_flag` is handed
        back: the write compares the flag's history since `since` with it, and
        never works it out again.

        Raises `ActionExhausted` where the flag is already as asked - an action
        spent, not a mitigation that happened.
        """
        return self._session.call(
            "plan_flag",
            _PLANNED_FLAG.validate_python,
            asking=Asking.READ,
            flag=flag,
            enabled=enabled
        )

    def set_feature_flag(self, planned: Planned[FlagUndo], enabled: bool) -> UndoDescriptor:
        """Sets the planned feature flag on or off, returning the undo descriptor
        for the change.

        A generic mitigation of spec §7.3: Mitigation's response to a flag-toggle
        cause. It is taken unasked because its kind is in the declared set (§13),
        not because it can be reversed. The descriptor it returns records the state
        that existed before, and is what puts the flag back if the mitigation turns
        out to be refuted.

        `enabled` is the state to leave the flag in, so undoing a change is a plan
        and this same call with it reversed. Mitigation needs both directions: a
        flag that was switched off can cause an incident exactly as one switched on
        can, and is undone by switching it back on.

        The plan goes over the wire whole, for the reason a descriptor does: it is
        one record, and a caller assembling it from fields could assemble one nobody
        planned. Raises `ChangedSince` where somebody else changed the flag since
        the plan, and raises rather than returning quietly when the flag did not
        actually reach that state. A verdict formed against a service nothing was
        done to would describe an experiment that never ran.
        """
        return self._session.call(
            "set_feature_flag",
            parse_undo_descriptor,
            asking=Asking.CHANGE,
            planned=planned.model_dump(mode="json"),
            enabled=enabled
        )

    def discard_cache_entries(self, keys: Sequence[str]) -> CacheEntriesDiscarded:
        """Discards the named cache entries, returning how many of them were there.

        A generic mitigation of spec §7.3: Mitigation's response to a store holding
        copies that have stopped agreeing with the records they came from. Taken
        unasked because its kind is in the declared set (§13), and the only one of
        that set which reaches a datastore rather than a control plane.

        The keys come from the incident's own evidence and are passed through
        untouched. Nothing here composes one: a key's format belongs to whoever wrote
        the store, and a template on this side would be Argus holding one service's
        internals.

        No undo descriptor, and for neither of the reasons the other actions give.
        A restart returns none because it changed nothing persistent; a rollback
        returns one because what it replaced is worth putting back. This changed
        something persistent and there is nothing to put back: the entries were a
        copy of records it never touched, and writing the old figures back would be
        recreating the incident.

        The count is what makes the discard checkable, and it is the only action here
        whose own answer does that. A store reporting how many of the named keys
        existed and are now gone has stated the thing the incident was about, so
        nothing afterwards has to be watched for.

        Not asked again where its answer was lost: a second asking finds nothing
        of the first to answer by, and discards whatever was written under the
        keys since. Such a call is `LostAfterSending`, and a walk told so cannot
        say whether the entries went.
        """
        return self._session.call(
            "discard_cache_entries",
            _CACHE_ENTRIES_DISCARDED.validate_python,
            asking=Asking.CHANGE_ASKED_ONCE,
            keys=list(keys)
        )

    def restart_service(self, service: str) -> RestartedService:
        """Restarts a service, returning the start time of the process now serving.

        A generic mitigation of spec §7.3: Mitigation's response to a resource
        leak. It is taken unasked because its kind is in the declared set (§13),
        not because it can be reversed - it cannot, and it returns no undo
        descriptor, because it changed no persistent state for one to describe.

        The start time is what makes the restart checkable. Memory falling is
        ambiguous on its own - the process restarted, or the traffic dropped - and
        only a start time that moved says which happened.

        Raises rather than returning quietly when no new process came up. A verdict
        formed against a service nothing was done to would describe an experiment
        that never ran, and would read a leak still climbing as evidence that
        restarting a leaking service does not work.

        Not asked again where its answer was lost: a restart is the platform's own
        resource action and carries no mark a second asking could find, so a
        second asking is a second restart. Such a call is `LostAfterSending`, and a
        walk told so cannot say whether the service was restarted.
        """
        return self._session.call(
            "restart_service",
            _RESTARTED_SERVICE.validate_python,
            asking=Asking.CHANGE_ASKED_ONCE,
            service=service
        )

    def plan_rollback(self, application: str) -> Planned[DeploymentRollbackUndo]:
        """Plans returning a deployment to the revision it ran before: the entry it
        is on, the entry it would go back to, and whether the platform reconciles
        it itself, dated by the platform's own clock.

        A read, asked before the action is claimed, and it changes nothing. Which
        revision is not a parameter, because nothing on this side of the port holds
        a deployment history to choose from - the tier works it out, and the plan
        is how it says which.
        """
        return self._session.call(
            "plan_rollback",
            _PLANNED_ROLLBACK.validate_python,
            asking=Asking.READ,
            application=application
        )

    def roll_back_deployment(self,
                             planned: Planned[DeploymentRollbackUndo]) -> DeploymentRollbackUndo:
        """Returns a deployment to the entry its plan named.

        A generic mitigation of spec §7.3: Mitigation's response to a bad
        deployment and to a config-induced failure alike, since a revision carries
        the code and the configuration it shipped with. Taken unasked because its
        kind is in the declared set (§13), and admissible there for one specific
        reason - the revision it applies was reviewed and ran before, so this
        replays somebody's change rather than authoring one. Nothing is written to
        the repository.

        The plan goes over the wire whole, and is what the tier compares the
        platform with before it writes: `ChangedSince` where somebody else moved
        the deployment since, carrying what this action's earlier asking left.

        The descriptor is the point of the return value, and it records *two*
        things: the entry that was running, and whether the platform was
        reconciling the application itself - which a rollback has to suspend,
        because a real server refuses one while it is on. Both are what a
        withdrawal puts back, and only the tier that did the work ever knew
        either.

        Parsed through `parse_undo_descriptor` rather than a local adapter, for
        the reason `set_feature_flag` is: the union decides which member a stored
        object is, and that decision has one door.
        """
        descriptor = self._session.call(
            "roll_back_deployment",
            parse_undo_descriptor,
            asking=Asking.CHANGE,
            planned=planned.model_dump(mode="json")
        )

        if not isinstance(descriptor, DeploymentRollbackUndo):
            raise ValueError(
                f"rolling [{planned.descriptor.application}] back answered with a "
                f"[{descriptor.kind}] descriptor, which is not a record of a "
                f"deployment being rolled back"
            )

        return descriptor

    def restore_deployment(self, descriptor: DeploymentRollbackUndo) -> DeploymentRestored:
        """Puts back both of the things a rollback changed.

        What a withdrawal does to a rollback, and what a refuted one does to
        itself. The descriptor goes back over the wire whole rather than as its
        parts, because it is one record of one change and a caller assembling it
        from fields could assemble one that never happened.

        Answers with which halves were managed rather than raising, for the reason
        the tier reports it that way: a restore can half-succeed, and the half that
        fails is the quiet one - a deployment whose revision is back while
        reconciliation is still suspended looks right and receives nothing.
        """
        return self._session.call(
            "restore_deployment",
            _DEPLOYMENT_RESTORED.validate_python,
            asking=Asking.CHANGE,
            descriptor=descriptor.model_dump(mode="json")
        )

    def plan_scale_out(self, application: str) -> Planned[ReplicaUndo]:
        """Plans giving a deployment more replicas than it is running: the count it
        runs, the count it would be given, and whether the platform reconciles it
        itself, dated by the platform's own clock.

        A read, asked before the action is claimed, and it changes nothing. How many
        is not a parameter, for the reason `scale_out` gives.
        """
        return self._session.call(
            "plan_scale_out",
            _PLANNED_SCALE_OUT.validate_python,
            asking=Asking.READ,
            application=application
        )

    def scale_out(self, planned: Planned[ReplicaUndo]) -> ReplicaUndo:
        """Gives a deployment the replicas its plan asked for.

        A generic mitigation of spec §7.3: Mitigation's response to demand
        saturation, and the only one that adds capacity rather than restoring state.
        Taken unasked because its kind is in the declared set (§13) - what admits an
        action is membership, never whether the change can be put back, though this
        one can be.

        How many is not a parameter, for a stronger version of the reason a rollback
        names no revision: a target count is meaningless without the count it
        replaces, and nothing on this side of the port can read what the deployment
        is running. The tier's plan read it and doubled it, and the write bounds the
        result by a ceiling of its own. The plan goes over the wire whole, and is
        compared with the platform before anything is written, as a rollback's is.

        The descriptor records *two* things, as a rollback's does: the count that was
        running, and whether the platform was reconciling the application itself -
        which a scale-out has to suspend, because a reconciling platform puts a live
        count straight back. Both are what a withdrawal puts back, and only the tier
        that did the work ever knew either.

        Parsed through `parse_undo_descriptor` rather than a local adapter, for the
        reason the two above are: the union decides which member a stored object is,
        and that decision has one door.
        """
        descriptor = self._session.call(
            "scale_out",
            parse_undo_descriptor,
            asking=Asking.CHANGE,
            planned=planned.model_dump(mode="json")
        )

        if not isinstance(descriptor, ReplicaUndo):
            raise ValueError(
                f"scaling [{planned.descriptor.application}] out answered with a "
                f"[{descriptor.kind}] descriptor, which is not a record of a "
                f"deployment being resized"
            )

        return descriptor

    def restore_replica_count(self, descriptor: ReplicaUndo) -> CapacityRestored:
        """Puts back both of the things a scale-out changed.

        What a withdrawal does to a scale-out, and what a refuted one does to
        itself. The descriptor goes back over the wire whole rather than as its
        parts, for the reason a rollback's does: it is one record of one change, and
        a caller assembling it from fields could assemble one that never happened.

        Answers with which halves were managed rather than raising, because a restore
        can half-succeed and the half that fails is the quiet one - a deployment back
        at its declared size while reconciliation is still suspended looks right and
        receives nothing.
        """
        return self._session.call(
            "restore_replica_count",
            _CAPACITY_RESTORED.validate_python,
            asking=Asking.CHANGE,
            descriptor=descriptor.model_dump(mode="json")
        )

    def plan_autoscaler_pin(self, application: str) -> Planned[AutoscalerUndo]:
        """Plans stopping a deployment's autoscaler moving the replica count about:
        the floor it has, the floor it would be raised to, and whether the platform
        reconciles it itself, dated by the platform's own clock.

        A read, asked before the action is claimed, and it changes nothing. No
        count, for the reason `pin_autoscaler` gives.
        """
        return self._session.call(
            "plan_autoscaler_pin",
            _PLANNED_AUTOSCALER_PIN.validate_python,
            asking=Asking.READ,
            application=application
        )

    def pin_autoscaler(self, planned: Planned[AutoscalerUndo]) -> AutoscalerUndo:
        """Stops a deployment's autoscaler moving the replica count about, as its
        plan said.

        A generic mitigation of spec §7.3: Mitigation's response to an autoscaling
        pathology, and the first that stops something rather than adding or restoring
        something. What admits it is membership of the declared set (§13), which is
        unchanged by the kind of change it makes.

        No count, for a stronger version of the reason a scale-out carries none. There
        a target is meaningless without the count it replaces; here the count is not
        Argus's to choose even in principle, because the ceiling is a bound a human
        declared and the floor is raised to meet it. What is being chosen is that the
        count should stop moving.

        The descriptor records *two* things, as a scale-out's does: the floor the
        autoscaler had, and whether the platform was reconciling the application itself
        - which a pin has to suspend, because a reconciling platform re-applies the
        autoscaler's manifest, floor included. Both are what a withdrawal puts back,
        and only the tier that did the work ever knew either.

        Parsed through `parse_undo_descriptor` rather than a local adapter, for the
        reason every descriptor here is: the union decides which member a stored object
        is, and that decision has one door.
        """
        descriptor = self._session.call(
            "pin_autoscaler",
            parse_undo_descriptor,
            asking=Asking.CHANGE,
            planned=planned.model_dump(mode="json")
        )

        if not isinstance(descriptor, AutoscalerUndo):
            raise ValueError(
                f"pinning [{planned.descriptor.application}]'s autoscaler answered with a "
                f"[{descriptor.kind}] descriptor, which is not a record of an "
                f"autoscaler being held still"
            )

        return descriptor

    def restore_autoscaler_floor(self, descriptor: AutoscalerUndo) -> AutoscalingRestored:
        """Puts back both of the things a pin changed.

        What a withdrawal does to a pin, and what a refuted one does to itself. The
        descriptor goes back over the wire whole rather than as its parts, for the
        reason a scale-out's does: it is one record of one change, and a caller
        assembling it from fields could assemble one that never happened.

        Answers with which halves were managed rather than raising, because a restore
        can half-succeed and the half that fails is the quiet one - an autoscaler back
        at its declared floor while reconciliation is still suspended looks right and
        receives nothing.
        """
        return self._session.call(
            "restore_autoscaler_floor",
            _AUTOSCALING_RESTORED.validate_python,
            asking=Asking.CHANGE,
            descriptor=descriptor.model_dump(mode="json")
        )

    def plan_accelerator_pin(self,
                             application: str,
                             accelerator: str) -> Planned[AcceleratorPinUndo]:
        """Plans holding a deployment's pods to one accelerator card: the card they
        are held to now, the card they would be held to, and whether the platform
        reconciles the application itself, dated by the platform's own clock.

        A read, asked before the action is claimed, and it changes nothing. The
        caller names the card as well as the application, because the card is the
        one thing the tier cannot work out: which card is good comes from where the
        replicas started before the onset, which the caller recorded and the write
        tier never saw.
        """
        return self._session.call(
            "plan_accelerator_pin",
            _PLANNED_ACCELERATOR_PIN.validate_python,
            asking=Asking.READ,
            application=application,
            accelerator=accelerator
        )

    def pin_to_accelerator(self, planned: Planned[AcceleratorPinUndo]) -> AcceleratorPinUndo:
        """Holds a deployment's pods to the card its plan named.

        A generic mitigation of spec §7.3: Mitigation's response to accelerator
        heterogeneity, and a drain - the pods move off a class of hardware and
        nothing deployed changes. What admits it is membership of the declared set
        (§13). The plan goes over the wire whole, and is compared with the platform
        before anything is written, as a rollback's is.

        The descriptor records *two* things, as a scale-out's does: the card the
        deployment was held to before, `None` included, and whether the platform
        was reconciling the application itself - which a pin has to suspend, because
        a reconciling platform re-applies the pod template, selector and all.

        Parsed through `parse_undo_descriptor` rather than a local adapter, for the
        reason every descriptor here is: the union decides which member a stored
        object is, and that decision has one door.
        """
        descriptor = self._session.call(
            "pin_to_accelerator",
            parse_undo_descriptor,
            asking=Asking.CHANGE,
            planned=planned.model_dump(mode="json")
        )

        if not isinstance(descriptor, AcceleratorPinUndo):
            raise ValueError(
                f"pinning [{planned.descriptor.application}] to "
                f"[{planned.descriptor.pinned_to}] answered with a "
                f"[{descriptor.kind}] descriptor, which is not a record of a "
                f"deployment being held to a card"
            )

        return descriptor

    def restore_accelerator_pin(self, descriptor: AcceleratorPinUndo) -> AcceleratorPinRestored:
        """Puts back both of the things a pin to a card changed.

        What a withdrawal does to a pin, and what a refuted one does to itself. The
        descriptor goes back over the wire whole, for the reason every other one
        does: it is one record of one change, and a caller assembling it from fields
        could assemble one that never happened.

        Answers with which halves were managed rather than raising, because a
        restore can half-succeed and the half that fails is the quiet one.
        """
        return self._session.call(
            "restore_accelerator_pin",
            _ACCELERATOR_PIN_RESTORED.validate_python,
            asking=Asking.CHANGE,
            descriptor=descriptor.model_dump(mode="json")
        )

    def get_recent_flag_changes(self, since: str) -> list[FlagChange]:
        """Reads the flag toggles the provider recorded since `since`, oldest first.

        How Mitigation learns which flag an incident is about, and in which
        direction it moved - neither of which current flag state can answer, since
        a flag switched off into an incident evaluates exactly like one that has
        been off for a year.

        On the write tier rather than the read tier because the provider serves
        its history to admin credentials only, and `argus-read-mcp` holds none by
        design. Reading is less than the write tier can already do; the tier split
        is the claim that the *read* process cannot mutate.

        Raises rather than returning an empty list when the provider cannot be
        reached: "nothing changed" is a conclusion the caller escalates on.
        """
        return self._session.call(
            "get_recent_flag_changes",
            _FLAG_CHANGES.validate_python,
            asking=Asking.READ,
            since=since
        )

    def whether_flag_was_made(self,
                              planned: Planned[FlagUndo]) -> Made[FlagUndo] | NotMade[FlagUndo]:
        """Whether the flag change a claim planned was made: made, with what puts it
        back and when the provider recorded it; not made, leaving nothing behind,
        where nothing landed.

        The first question a walk resumed after its worker died asks of a claim -
        the write's own rule on the claim's plan, with the write left out. So it
        refuses where `set_feature_flag` would: `ChangedSince` where somebody else
        changed the flag since the plan, carrying what of the claim's landed, and a
        plain refusal where nobody can say.
        """
        return self._session.call(
            "whether_flag_was_made",
            _MADE_FLAG.validate_python,
            asking=Asking.READ,
            planned=planned.model_dump(mode="json")
        )

    def flag_still_argus_s(self, planned: Planned[FlagUndo], descriptor: FlagUndo) -> ChangeFound:
        """Whether a flag change Argus made from `planned` is still as Argus left
        it - or somebody changed it since, saying what was found, or nobody can say,
        saying why.

        What a walk resumed after its worker died asks before it watches a change
        an earlier worker made. A read; the plan and the descriptor go over the wire
        whole, as the claim stored them - the history is read from the plan's.
        """
        return self._session.call(
            "flag_still_argus_s",
            _CHANGE_FOUND.validate_python,
            asking=Asking.READ,
            planned=planned.model_dump(mode="json"),
            descriptor=descriptor.model_dump(mode="json")
        )

    def whether_rollback_was_made(
        self, planned: Planned[DeploymentRollbackUndo]
    ) -> Made[DeploymentRollbackUndo] | NotMade[DeploymentRollbackUndo]:
        """Whether the rollback a claim planned was made: made, with when the
        platform says it was - `None` for a rollback taken and not yet started -
        or not made where nothing landed, carrying the plan where the claim's
        suspension of the sync stands. Refuses where `roll_back_deployment` would,
        `ChangedSince` among it, since the read is the write's own compare."""
        return self._session.call(
            "whether_rollback_was_made",
            _MADE_ROLLBACK.validate_python,
            asking=Asking.READ,
            planned=planned.model_dump(mode="json")
        )

    def rollback_still_argus_s(self, descriptor: DeploymentRollbackUndo) -> ChangeFound:
        """Whether a rollback Argus made is still as Argus left it - the restore's
        own check, asked on its own - or somebody's change since, or nobody can
        say."""
        return self._session.call(
            "rollback_still_argus_s",
            _CHANGE_FOUND.validate_python,
            asking=Asking.READ,
            descriptor=descriptor.model_dump(mode="json")
        )

    def whether_scale_out_was_made(self,
                                   planned: Planned[ReplicaUndo]
                                   ) -> Made[ReplicaUndo] | NotMade[ReplicaUndo]:
        """Whether the scale-out a claim planned was made under the claim the call
        is made for: made, with when its mark says it was written, or not made
        where nothing landed, carrying the plan where the claim's suspension of the
        sync stands. Refuses where `scale_out` would."""
        return self._session.call(
            "whether_scale_out_was_made",
            _MADE_SCALE_OUT.validate_python,
            asking=Asking.READ,
            planned=planned.model_dump(mode="json")
        )

    def scale_out_still_argus_s(self, descriptor: ReplicaUndo) -> ChangeFound:
        """Whether a scale-out Argus made is still as Argus left it under the claim
        the call is made for, or somebody's change since, or nobody can say."""
        return self._session.call(
            "scale_out_still_argus_s",
            _CHANGE_FOUND.validate_python,
            asking=Asking.READ,
            descriptor=descriptor.model_dump(mode="json")
        )

    def whether_autoscaler_pin_was_made(self,
                                        planned: Planned[AutoscalerUndo]
                                        ) -> Made[AutoscalerUndo] | NotMade[AutoscalerUndo]:
        """Whether the autoscaler pin a claim planned was made under the claim the
        call is made for: made, with when its mark says it was written, or not made
        where nothing landed, carrying the plan where the claim's suspension of the
        sync stands. Refuses where `pin_autoscaler` would."""
        return self._session.call(
            "whether_autoscaler_pin_was_made",
            _MADE_AUTOSCALER_PIN.validate_python,
            asking=Asking.READ,
            planned=planned.model_dump(mode="json")
        )

    def autoscaler_pin_still_argus_s(self, descriptor: AutoscalerUndo) -> ChangeFound:
        """Whether an autoscaler pin Argus made is still as Argus left it under the
        claim the call is made for, or somebody's change since, or nobody can
        say."""
        return self._session.call(
            "autoscaler_pin_still_argus_s",
            _CHANGE_FOUND.validate_python,
            asking=Asking.READ,
            descriptor=descriptor.model_dump(mode="json")
        )

    def whether_accelerator_pin_was_made(
        self, planned: Planned[AcceleratorPinUndo]
    ) -> Made[AcceleratorPinUndo] | NotMade[AcceleratorPinUndo]:
        """Whether the pin to a card a claim planned was made under the claim the
        call is made for: made, with when its mark says it was written, or not made
        where nothing landed, carrying the plan where the claim's suspension of the
        sync stands. Refuses where `pin_to_accelerator` would."""
        return self._session.call(
            "whether_accelerator_pin_was_made",
            _MADE_ACCELERATOR_PIN.validate_python,
            asking=Asking.READ,
            planned=planned.model_dump(mode="json")
        )

    def accelerator_pin_still_argus_s(self, descriptor: AcceleratorPinUndo) -> ChangeFound:
        """Whether a pin to a card Argus made is still as Argus left it under the
        claim the call is made for, or somebody's change since, or nobody can
        say."""
        return self._session.call(
            "accelerator_pin_still_argus_s",
            _CHANGE_FOUND.validate_python,
            asking=Asking.READ,
            descriptor=descriptor.model_dump(mode="json")
        )

    def was_flag_changed_by_others_since(self, flag: str, since: datetime) -> bool | None:
        """Whether anybody but Argus changed `flag` at or after `since`, or `None`
        where nobody can say.

        What an undo asks before it writes. `None` is never "nobody": the two are
        the difference between putting a change back and overwriting a person.
        """
        return self._session.call(
            "was_flag_changed_by_others_since",
            _AN_ANSWER_OR_NONE.validate_python,
            asking=Asking.READ,
            flag=flag,
            since=to_iso(since)
        )

    def commit_to_new_branch(self,
                             branch: str,
                             base_branch: str,
                             files: Mapping[str, str],
                             message: str) -> str:
        """Puts a proposed fix on a branch of its own and returns that branch.

        The first half of Code-Fix's outward act (spec §7.4), and the half that
        touches code. `files` maps a repository path to that file's whole new
        content - a patch, already applied by whoever wrote it, rather than a diff
        for something downstream to apply.

        Only ever a branch. The base is never written, so the worst a wrong fix can
        do is sit somewhere unrun until a person looks at it, and the pull request
        that follows is a proposal rather than a change.

        Raises rather than returning quietly when any part of the patch did not
        land. A branch reported as written but only half there would be proposed as
        a whole fix, and read by a human as one.
        """
        return self._session.call(
            "commit_to_new_branch",
            _A_BRANCH.validate_python,
            asking=Asking.CHANGE,
            branch=branch,
            base_branch=base_branch,
            files=dict(files),
            message=message
        )

    def open_pull_request(self,
                          head_branch: str,
                          base_branch: str,
                          title: str,
                          body: str) -> OpenedPullRequest:
        """Opens a draft pull request proposing a code fix, and returns where a
        human can read it.

        Code-Fix's one outward act (spec §7.4). Everything before it - the
        retrieval, the patch, the branch - is Argus working; this is Argus handing
        the work to somebody, which is why what comes back is an address rather than
        an outcome.

        **There is no `merge_pull_request` beside this, and there is not going to
        be.** Merging is a deploy, and no deploy is among the mitigations Argus may
        take unasked (§13), so the tier this module gives an agent has no method
        for it at all - tier enforcement by absence, which no caller can skip and
        no prompt can talk its way around. The draft is not a parameter
        here either, for the same reason it is not one on the server.

        Raises rather than returning quietly when no pull request was opened: a fix
        reported as proposed but never opened closes an incident on a link to
        nothing.
        """
        return self._session.call(
            "open_pull_request",
            _OPENED_PULL_REQUEST.validate_python,
            asking=Asking.CHANGE,
            head_branch=head_branch,
            base_branch=base_branch,
            title=title,
            body=body
        )
