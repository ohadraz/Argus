from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from argus_core import WriteMcpEndpoint
from argus_core.mcp_transport import McpClient
from argus_core.models import (
    ConfigRollbackUndo,
    ConfigurationRestored,
    FlagChange,
    OpenedPullRequest,
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

_OPENED_PULL_REQUEST: Final = TypeAdapter(OpenedPullRequest)

_RESTARTED_SERVICE: Final = TypeAdapter(RestartedService)

_CONFIGURATION_RESTORED: Final = TypeAdapter(ConfigurationRestored)

# The branch a fix was written to, which the server answers with as a bare
# string. Validated rather than cast: what comes back is handed straight to
# `open_pull_request` as the branch to propose, and a tool that answered with
# something else would have that failure surface two calls later.
_A_BRANCH: Final = TypeAdapter(str)

# Where the server's tools are served, under the address the endpoint names.
_MCP_PATH: Final = "/mcp"


def write_mcp(endpoint: WriteMcpEndpoint) -> McpClient:
    """A client holding one session to `argus-write-mcp`.

    Built where a process starts, and separate from the read tier's client
    because the servers are separate - two sessions to two addresses. Holding
    one authorizes nothing: what makes the write tier the write tier is the
    credential that server holds and the tools it has (spec §12.1, §13).
    """
    return McpClient(f"{endpoint.write_mcp_url}{_MCP_PATH}")


def set_feature_flag(flag: str,
                     enabled: bool,
                     *,
                     client: McpClient) -> UndoDescriptor:
    """Sets a feature flag on or off, returning the undo descriptor for the
    change.

    A generic mitigation of spec §7.3: Mitigation's response to a flag-toggle
    cause. It is taken unasked because its kind is in the declared set (§13),
    not because it can be reversed. The descriptor it returns records the state
    that existed before, and is what puts the flag back if the mitigation turns
    out to be refuted.

    `enabled` is the state to leave the flag in, so undoing a change is this
    same call with it reversed. Mitigation needs both directions: a flag that
    was switched off can cause an incident exactly as one switched on can, and
    is undone by switching it back on.

    Raises rather than returning quietly when the flag did not actually reach
    that state. A verdict formed against a service nothing was done to would
    describe an experiment that never ran.
    """
    return client.call(
        "set_feature_flag",
        parse_undo_descriptor,
        flag=flag,
        enabled=enabled,
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


def roll_back_configuration(application: str,
                            *,
                            client: McpClient) -> ConfigRollbackUndo:
    """Returns a deployment to the configuration revision it ran before.

    A generic mitigation of spec §7.3: Mitigation's response to a
    config-induced failure. Taken unasked because its kind is in the declared
    set (§13), and admissible there for one specific reason - the revision it
    applies was reviewed and ran before, so this replays somebody's change
    rather than authoring one. Nothing is written to the configuration
    repository.

    Which revision is not a parameter, because nothing on this side of the
    port holds a deployment history to choose from. The platform resolves it
    the way `argocd app rollback APPNAME` does with its history id omitted.

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
        "roll_back_configuration",
        parse_undo_descriptor,
        application=application,
    )

    if not isinstance(descriptor, ConfigRollbackUndo):
        raise ValueError(
            f"rolling [{application}] back answered with a "
            f"[{descriptor.kind}] descriptor, which is not a record of a "
            f"deployment being rolled back"
        )

    return descriptor


def restore_configuration(descriptor: ConfigRollbackUndo,
                          *,
                          client: McpClient) -> ConfigurationRestored:
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
        "restore_configuration",
        _CONFIGURATION_RESTORED.validate_python,
        descriptor=descriptor.model_dump(mode="json"),
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
