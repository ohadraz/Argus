from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final

from core import Holding, WriteMcpEndpoint, to_iso
from core.mcp_transport import McpClient
from core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    AutoscalerUndo,
    AutoscalingRestored,
    CacheEntriesDiscarded,
    CapacityRestored,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    FlagUndo,
    OpenedPullRequest,
    Planned,
    ReplicaUndo,
    RestartedService,
    UndoDescriptor,
    parse_undo_descriptor,
)
from pydantic import TypeAdapter

# One tool answers with a list this module has to build; the other answers with
# a descriptor the kernel already knows how to read, and `parse_undo_descriptor`
# is passed as it stands. A union decides which member a stored object is, and
# that decision has one door - reading it a second way here would be a second
# place for it to be decided differently.
_FLAG_CHANGES: Final = TypeAdapter(list[FlagChange])

# Either question about whose a flag change was, answered as a yes, a no, or
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

# The branch a fix was written to, which the server answers with as a bare
# string. Validated rather than cast: what comes back is handed straight to
# `open_pull_request` as the branch to propose, and a tool that answered with
# something else would have that failure surface two calls later.
_A_BRANCH: Final = TypeAdapter(str)

# Where the server's tools are served, under the address the endpoint names.
_MCP_PATH: Final = "/mcp"


def write_mcp(endpoint: WriteMcpEndpoint, holding: Holding | None = None) -> McpClient:
    """A client holding one session to `argus-write-mcp`.

    Built where a process starts, and separate from the read tier's client
    because the servers are separate - two sessions to two addresses. Holding
    one authorizes nothing: what makes the write tier the write tier is the
    credential that server holds and the tools it has (spec §12.1, §13).

    A process that walks runs hands over what it is `holding`, and each call
    says the claim held as it is made: the tier makes a change only for the
    claim that holds its run. A process holding none can still read.
    """
    return McpClient(f"{endpoint.write_mcp_url}{_MCP_PATH}", holding=holding)


def plan_flag(flag: str,
              enabled: bool,
              *,
              client: McpClient) -> Planned[FlagUndo]:
    """Plans setting a feature flag on or off: the state the provider holds it
    in, and the provider's own time for that read.

    A read, asked before the action is claimed, and it changes nothing. What it
    answers is what the claim records and what `set_feature_flag` is handed
    back: the write compares the flag's history since `since` with it, and
    never works it out again.

    Raises `ActionExhausted` where the flag is already as asked - an action
    spent, not a mitigation that happened.
    """
    return client.call(
        "plan_flag",
        _PLANNED_FLAG.validate_python,
        flag=flag,
        enabled=enabled
    )


def set_feature_flag(planned: Planned[FlagUndo],
                     enabled: bool,
                     *,
                     client: McpClient) -> UndoDescriptor:
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
    return client.call(
        "set_feature_flag",
        parse_undo_descriptor,
        planned=planned.model_dump(mode="json"),
        enabled=enabled
    )


def discard_cache_entries(keys: Sequence[str],
                          *,
                          client: McpClient) -> CacheEntriesDiscarded:
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
    """
    return client.call(
        "discard_cache_entries",
        _CACHE_ENTRIES_DISCARDED.validate_python,
        keys=list(keys),
    )


def restart_service(service: str,
                    *,
                    client: McpClient) -> RestartedService:
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
    """
    return client.call(
        "restart_service",
        _RESTARTED_SERVICE.validate_python,
        service=service,
    )


def plan_rollback(application: str,
                  *,
                  client: McpClient) -> Planned[DeploymentRollbackUndo]:
    """Plans returning a deployment to the revision it ran before: the entry it
    is on, the entry it would go back to, and whether the platform reconciles
    it itself, dated by the platform's own clock.

    A read, asked before the action is claimed, and it changes nothing. Which
    revision is not a parameter, because nothing on this side of the port holds
    a deployment history to choose from - the tier works it out, and the plan
    is how it says which.
    """
    return client.call(
        "plan_rollback",
        _PLANNED_ROLLBACK.validate_python,
        application=application
    )


def roll_back_deployment(planned: Planned[DeploymentRollbackUndo],
                         *,
                         client: McpClient) -> DeploymentRollbackUndo:
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
    descriptor = client.call(
        "roll_back_deployment",
        parse_undo_descriptor,
        planned=planned.model_dump(mode="json")
    )

    if not isinstance(descriptor, DeploymentRollbackUndo):
        raise ValueError(
            f"rolling [{planned.descriptor.application}] back answered with a "
            f"[{descriptor.kind}] descriptor, which is not a record of a "
            f"deployment being rolled back"
        )

    return descriptor


def restore_deployment(descriptor: DeploymentRollbackUndo,
                       *,
                       client: McpClient) -> DeploymentRestored:
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
    return client.call(
        "restore_deployment",
        _DEPLOYMENT_RESTORED.validate_python,
        descriptor=descriptor.model_dump(mode="json"),
    )


def plan_scale_out(application: str,
                   *,
                   client: McpClient) -> Planned[ReplicaUndo]:
    """Plans giving a deployment more replicas than it is running: the count it
    runs, the count it would be given, and whether the platform reconciles it
    itself, dated by the platform's own clock.

    A read, asked before the action is claimed, and it changes nothing. How many
    is not a parameter, for the reason `scale_out` gives.
    """
    return client.call(
        "plan_scale_out",
        _PLANNED_SCALE_OUT.validate_python,
        application=application
    )


def scale_out(planned: Planned[ReplicaUndo],
              *,
              client: McpClient) -> ReplicaUndo:
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
    descriptor = client.call(
        "scale_out",
        parse_undo_descriptor,
        planned=planned.model_dump(mode="json")
    )

    if not isinstance(descriptor, ReplicaUndo):
        raise ValueError(
            f"scaling [{planned.descriptor.application}] out answered with a "
            f"[{descriptor.kind}] descriptor, which is not a record of a "
            f"deployment being resized"
        )

    return descriptor


def restore_replica_count(descriptor: ReplicaUndo,
                          *,
                          client: McpClient) -> CapacityRestored:
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
    return client.call(
        "restore_replica_count",
        _CAPACITY_RESTORED.validate_python,
        descriptor=descriptor.model_dump(mode="json"),
    )


def plan_autoscaler_pin(application: str,
                        *,
                        client: McpClient) -> Planned[AutoscalerUndo]:
    """Plans stopping a deployment's autoscaler moving the replica count about:
    the floor it has, the floor it would be raised to, and whether the platform
    reconciles it itself, dated by the platform's own clock.

    A read, asked before the action is claimed, and it changes nothing. No
    count, for the reason `pin_autoscaler` gives.
    """
    return client.call(
        "plan_autoscaler_pin",
        _PLANNED_AUTOSCALER_PIN.validate_python,
        application=application
    )


def pin_autoscaler(planned: Planned[AutoscalerUndo],
                   *,
                   client: McpClient) -> AutoscalerUndo:
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
    descriptor = client.call(
        "pin_autoscaler",
        parse_undo_descriptor,
        planned=planned.model_dump(mode="json")
    )

    if not isinstance(descriptor, AutoscalerUndo):
        raise ValueError(
            f"pinning [{planned.descriptor.application}]'s autoscaler answered with a "
            f"[{descriptor.kind}] descriptor, which is not a record of an "
            f"autoscaler being held still"
        )

    return descriptor


def restore_autoscaler_floor(descriptor: AutoscalerUndo,
                             *,
                             client: McpClient) -> AutoscalingRestored:
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
    return client.call(
        "restore_autoscaler_floor",
        _AUTOSCALING_RESTORED.validate_python,
        descriptor=descriptor.model_dump(mode="json"),
    )


def plan_accelerator_pin(application: str,
                         accelerator: str,
                         *,
                         client: McpClient) -> Planned[AcceleratorPinUndo]:
    """Plans holding a deployment's pods to one accelerator card: the card they
    are held to now, the card they would be held to, and whether the platform
    reconciles the application itself, dated by the platform's own clock.

    A read, asked before the action is claimed, and it changes nothing. The
    caller names the card as well as the application, because the card is the
    one thing the tier cannot work out: which card is good comes from where the
    replicas started before the onset, which the caller recorded and the write
    tier never saw.
    """
    return client.call(
        "plan_accelerator_pin",
        _PLANNED_ACCELERATOR_PIN.validate_python,
        application=application,
        accelerator=accelerator
    )


def pin_to_accelerator(planned: Planned[AcceleratorPinUndo],
                       *,
                       client: McpClient) -> AcceleratorPinUndo:
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
    descriptor = client.call(
        "pin_to_accelerator",
        parse_undo_descriptor,
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


def restore_accelerator_pin(descriptor: AcceleratorPinUndo,
                            *,
                            client: McpClient) -> AcceleratorPinRestored:
    """Puts back both of the things a pin to a card changed.

    What a withdrawal does to a pin, and what a refuted one does to itself. The
    descriptor goes back over the wire whole, for the reason every other one
    does: it is one record of one change, and a caller assembling it from fields
    could assemble one that never happened.

    Answers with which halves were managed rather than raising, because a
    restore can half-succeed and the half that fails is the quiet one.
    """
    return client.call(
        "restore_accelerator_pin",
        _ACCELERATOR_PIN_RESTORED.validate_python,
        descriptor=descriptor.model_dump(mode="json")
    )


def get_recent_flag_changes(since: str,
                            *,
                            client: McpClient) -> list[FlagChange]:
    """Reads the flag toggles the provider recorded since `since`, oldest first.

    How Mitigation learns which flag an incident is about, and in which
    direction it moved - neither of which current flag state can answer, since
    a flag switched off into an incident evaluates exactly like one that has
    been off for a year.

    On the write client rather than the read client because the provider serves
    its history to admin credentials only, and `argus-read-mcp` holds none by
    design. Reading is less than the write tier can already do; the tier split
    is the claim that the *read* process cannot mutate.

    Raises rather than returning an empty list when the provider cannot be
    reached: "nothing changed" is a conclusion the caller escalates on.
    """
    return client.call(
        "get_recent_flag_changes",
        _FLAG_CHANGES.validate_python,
        since=since,
    )


def was_flag_changed_by_argus_since(flag: str,
                                    since: datetime,
                                    *,
                                    client: McpClient) -> bool | None:
    """Whether Argus's own change to `flag` was recorded at or after `since`,
    or `None` where nobody can say.

    The question a walk resumed after its worker died asks: did the change it
    was claiming land? Only the provider's history knows, and the provider's
    adapter decides whose each change in it was - this carries the answer and
    adds nothing, least of all a `False` where the tier said nobody can say.
    """
    return client.call(
        "was_flag_changed_by_argus_since",
        _AN_ANSWER_OR_NONE.validate_python,
        flag=flag,
        since=to_iso(since)
    )


def was_flag_changed_by_others_since(flag: str,
                                     since: datetime,
                                     *,
                                     client: McpClient) -> bool | None:
    """Whether anybody but Argus changed `flag` at or after `since`, or `None`
    where nobody can say.

    What an undo asks before it writes. `None` is never "nobody": the two are
    the difference between putting a change back and overwriting a person.
    """
    return client.call(
        "was_flag_changed_by_others_since",
        _AN_ANSWER_OR_NONE.validate_python,
        flag=flag,
        since=to_iso(since)
    )


def commit_to_new_branch(branch: str,
                         base_branch: str,
                         files: Mapping[str, str],
                         message: str,
                         *,
                         client: McpClient) -> str:
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
    return client.call(
        "commit_to_new_branch",
        _A_BRANCH.validate_python,
        branch=branch,
        base_branch=base_branch,
        files=dict(files),
        message=message,
    )


def open_pull_request(head_branch: str,
                      base_branch: str,
                      title: str,
                      body: str,
                      *,
                      client: McpClient) -> OpenedPullRequest:
    """Opens a draft pull request proposing a code fix, and returns where a
    human can read it.

    Code-Fix's one outward act (spec §7.4). Everything before it - the
    retrieval, the patch, the branch - is Argus working; this is Argus handing
    the work to somebody, which is why what comes back is an address rather than
    an outcome.

    **There is no `merge_pull_request` beside this, and there is not going to
    be.** Merging is a deploy, and no deploy is among the mitigations Argus may
    take unasked (§13), so the binding this module gives an agent has no
    function for it at all - tier enforcement by absence, which no caller can
    skip and no prompt can talk its way around. The draft is not a parameter
    here either, for the same reason it is not one on the server.

    Raises rather than returning quietly when no pull request was opened: a fix
    reported as proposed but never opened closes an incident on a link to
    nothing.
    """
    return client.call(
        "open_pull_request",
        _OPENED_PULL_REQUEST.validate_python,
        head_branch=head_branch,
        base_branch=base_branch,
        title=title,
        body=body,
    )
