"""`argus-write-mcp` - the tools that change state (spec §12.1, §13).

A separate process from `argus-read-mcp`, not a separate module inside it. The
split is what makes "read-only" a property of a running process: the read server
holds no credential that could authorize a change, so a compromised or confused
caller cannot mutate anything through it, whatever tools it believes it has.

Every tool here that touches the running service performs a **generic
mitigation** (§13) - one of the closed, pre-authorised set Argus may take
unasked. The rest write to a branch nothing is running, which is how a proposed
fix reaches a human without reaching production. What has no function on this
server at all is anything that would deploy: merging a pull request, applying
infrastructure. That is tier enforcement by absence rather than by a check some
future caller could skip.

Built rather than declared, for the reason the read server is: the process that
reads configuration is the process that starts, and a server assembled at import
would have bound its credentials before anything could say which deployment it
was in.
"""

from __future__ import annotations

from argus_core import WriteMcpEndpoint, get_settings
from argus_core.models import (
    AutoscalerUndo,
    AutoscalingRestored,
    CacheEntriesDiscarded,
    CapacityRestored,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    FlagUndo,
    OpenedPullRequest,
    ReplicaUndo,
    RestartedService,
)
from mcp.server.fastmcp import FastMCP

from write_mcp_server import (
    branching,
    discarding,
    flag_history,
    flag_state,
    pinning,
    pull_requests,
    restarting,
    rolling_back,
    scaling,
)
from write_mcp_server.discarding import DiscardSettings
from write_mcp_server.flag_state import FlagWriteSettings
from write_mcp_server.pinning import PinSettings
from write_mcp_server.pull_requests import RepositoryWriteSettings
from write_mcp_server.restarting import RestartSettings
from write_mcp_server.rolling_back import RollbackSettings
from write_mcp_server.scaling import ScaleSettings


def build_server(endpoint: WriteMcpEndpoint,
                 flag_settings: FlagWriteSettings,
                 repository_settings: RepositoryWriteSettings,
                 restart_settings: RestartSettings,
                 rollback_settings: RollbackSettings,
                 scale_settings: ScaleSettings,
                 pin_settings: PinSettings,
                 discard_settings: DiscardSettings) -> FastMCP:
    """Registers the write tools against one deployment's configuration.

    Seven slices, not one. The flag tools speak to the provider, the code tool
    speaks to the repository, the discard speaks to the store a service keeps its
    derived copies in, and the restart, the rollback, the scale-out and the pin
    each speak to the deployment platform - separately, because they are
    different routes under different paths and a single slice would make one
    tool's misconfiguration look like another's. Every credential named belongs to
    this tier, and none of them belongs in another's calls. What keeps the *tiers*
    apart is that the read server is handed a slice with no field any of these
    could arrive in - not a check made here.

    The tool bodies stay registration only; the behaviour, and the seams a
    decorated function cannot carry, live in a module per route beside this one.
    """
    mcp = FastMCP(
        "argus-write-mcp",
        host=endpoint.write_mcp_host,
        port=endpoint.write_mcp_port,
    )

    def confirm_the_change_landed() -> list[str]:
        return flag_state.evaluated_flags(flag_settings)

    confirm_a_new_process_is_serving = restarting.the_pod_start_time(
        restart_settings
    )

    @mcp.tool()
    def set_feature_flag(flag: str, enabled: bool) -> FlagUndo:
        """Sets a feature flag on or off in the configured environment.

        A generic mitigation (§13): it is taken unasked because its kind is
        in the declared set, not because it can be undone. It does leave
        something behind, and the state it changed is recorded in the undo
        descriptor returned with it, so whoever holds that record can put the
        change back if the mitigation turns out to be refuted.

        Both directions, one tool. A flag causes an incident by changing, and
        the damaging direction is not always "on" - undoing a flag that was
        switched off means switching it back on, and undoing this call is this
        call with the state reversed.

        Returns only once the change is visible to evaluation, and raises
        rather than reporting an unchanged flag as changed: a caller about to
        judge whether the service recovered has to know the service was
        actually changed. The behavior lives in `flag_state.set_flag`; this is
        registration only."""
        return flag_state.set_flag(
            flag, enabled, flag_settings, evaluate=confirm_the_change_landed
        )

    @mcp.tool()
    def restart_service(service: str) -> RestartedService:
        """Restarts a service and returns the start time of the process now
        serving it.

        A generic mitigation (§13): the industry's most common first response
        to a resource leak, taken unasked because it is in the declared set of
        routine responses - not because it can be undone, which it cannot. It
        changes no persistent state, so it returns no undo descriptor and
        there is nothing for a withdrawal to put back.

        Returns only once a new process is actually serving, and raises rather
        than reporting an unrestarted service as restarted: a caller about to
        judge whether the leak was reclaimed has to know the process it is
        judging is a new one. The behavior lives in
        `restarting.restart_service`; this is registration only."""
        return restarting.restart_service(
            service,
            restart_settings,
            observe=confirm_a_new_process_is_serving
        )

    @mcp.tool()
    def roll_back_deployment(application: str) -> DeploymentRollbackUndo:
        """Returns a deployment to the revision it ran before, and reports
        what that cost.

        A generic mitigation (§13), admissible unasked for one specific
        reason: the revision it applies was reviewed and ran before, so this
        replays somebody's change rather than authoring one. It writes nothing
        to the repository, and must not - that would be an infrastructure
        change requiring approval.

        Which revision is not a parameter. The platform resolves it as
        `argocd app rollback APPNAME` does with its history id omitted - the
        immediately preceding deployment - because nothing above this port
        holds a deployment history to choose from.

        Mitigates without resolving. The repository still holds the change
        that caused the incident, and the platform's own reconciliation has
        been suspended so that it is not re-applied; both are recorded in the
        descriptor returned, and both are what a withdrawal puts back. The
        behavior lives in `rolling_back.roll_back_deployment`; this is
        registration only."""
        return rolling_back.roll_back_deployment(application, rollback_settings)

    @mcp.tool()
    def restore_deployment(
        descriptor: DeploymentRollbackUndo
    ) -> DeploymentRestored:
        """Puts back both of the things a rollback changed, and reports which
        of them it managed.

        The revision the deployment was running, and the reconciliation that
        had to be suspended to leave it. Both, or it is not undone: a
        deployment whose revision is back while the platform is still not
        reconciling it looks correct from every angle a reader has, and
        silently receives nothing anybody ships to it.

        Answers with which halves it managed rather than raising, because a
        restore can half-succeed and the caller has to be able to say which
        half is still changed - "the revision is back and reconciliation is
        still suspended" is a sentence somebody can act on, where "it did not
        work" is not.

        The order is the platform's to dictate: automated sync refuses a
        rollback, so the revision is put back before reconciliation is
        re-enabled. The behavior lives in
        `rolling_back.restore_deployment`; this is registration only."""
        return rolling_back.restore_deployment(descriptor, rollback_settings)

    @mcp.tool()
    def scale_out(application: str) -> ReplicaUndo:
        """Gives a deployment more replicas than it is running, and reports
        what that cost.

        A generic mitigation (§13), and the only one that adds capacity rather
        than restoring state - which changes nothing about what admits it: an
        action is taken unasked because its kind is in the declared set, never
        because it can be put back. Google SRE's own list of generic mitigations
        names adding capacity beside draining, rolling back and restarting.

        How many is not a parameter. The platform is asked what the deployment
        is running, that count is doubled, and the result is bounded by a
        ceiling this tier holds - because a target is meaningless without the
        count it replaces, and nothing above this port can read that count. What
        the repository asks for is a different number as soon as anybody has
        scaled. Both figures are reported back.

        There is no tool for the reverse, and there should not be. Being wrong
        about adding capacity costs money; being wrong about removing it costs an
        outage.

        Mitigates without resolving. The repository still asks for the size that
        was too small, the platform's own reconciliation has been suspended so
        that nothing re-applies it, and the traffic that outgrew the deployment
        is still arriving; the first two are recorded in the descriptor returned
        and are what a withdrawal puts back. The behavior lives in
        `scaling.scale_out`; this is registration only."""
        return scaling.scale_out(application, scale_settings)

    @mcp.tool()
    def restore_replica_count(descriptor: ReplicaUndo) -> CapacityRestored:
        """Puts back both of the things a scale-out changed, and reports which
        of them it managed.

        The count the deployment was running, and the reconciliation that had to
        be suspended to leave it. Both, or it is not undone: a deployment back at
        its declared size while the platform is still not reconciling it looks
        correct from every angle a reader has, and silently receives nothing
        anybody ships to it.

        Answers with which halves it managed rather than raising, for the reason
        the rollback's restore does: a restore can half-succeed, and the caller
        has to be able to say which half is still changed.

        The count is put back before reconciliation is re-enabled. The other
        order would have the platform set the count itself, unverifiably, at a
        moment nothing here chose. The behavior lives in
        `scaling.restore_replica_count`; this is registration only."""
        return scaling.restore_replica_count(descriptor, scale_settings)

    @mcp.tool()
    def pin_autoscaler(application: str) -> AutoscalerUndo:
        """Stops a deployment's autoscaler moving the replica count about, and
        reports the floor it had.

        A generic mitigation (§13), and the first that stops something rather
        than adding or restoring something - which changes nothing about what
        admits it: an action is taken unasked because its kind is in the declared
        set, never because of the kind of change it makes.

        What it stops is a control loop, and it stops it by raising the floor to
        the ceiling: the controller is left running with nowhere left to scale
        down to. Nothing is removed and the ceiling is never moved, which is what
        makes this reversible - lowering a ceiling would reduce a deployment's
        capacity, and nothing here does that autonomously.

        How high is not a parameter, for a stronger version of the reason a
        scale-out takes no count. There a target is meaningless without the count
        it replaces; here the number is not Argus's to choose even in principle,
        because the ceiling is a bound a human declared.

        Mitigates without resolving. The repository still declares the floor the
        controller was thrashing between, the platform's own reconciliation has
        been suspended so that nothing re-applies it, and whatever the controller
        was reacting to is still there; the first two are recorded in the
        descriptor returned and are what a withdrawal puts back. The behavior
        lives in `pinning.pin_autoscaler`; this is registration only."""
        return pinning.pin_autoscaler(application, pin_settings)

    @mcp.tool()
    def discard_cache_entries(keys: list[str]) -> CacheEntriesDiscarded:
        """Removes the named entries from the service's cache and reports how
        many of them were there.

        A generic mitigation (§13), and the only one that reaches a datastore
        rather than a control plane: no platform offers this write, because a
        platform's own actions reach a workload's lifecycle and its size and
        none of them reaches what a cache holds.

        Takes the keys and nothing that could match a key it was not given - no
        pattern, no prefix, no service. The entries to remove are the ones an
        incident's evidence named; a pattern would be a blast radius its caller
        could not state, and emptying the cache would discard entries nothing
        proved wrong.

        Returns no undo descriptor and there is nothing for a withdrawal to put
        back - not because no state changed, which is the restart's reason, but
        because what was removed was a copy of records this never touched.
        Whatever reads one of those entries next works it out again from those
        records, so putting the old values back would be recreating the
        incident.

        The count is the confirmation. It is the store saying which of the named
        keys existed and are now gone, which is the whole of what the incident
        was - so nothing is read back afterwards. Raises rather than reporting
        zero where the store could not be reached at all: a store that answered
        and held none of them is a divergence something else already cleared,
        and a store that never answered is a mitigation that did not happen.
        The behavior lives in `discarding.discard_cache_entries`; this is
        registration only."""
        return discarding.discard_cache_entries(keys, discard_settings)

    @mcp.tool()
    def restore_autoscaler_floor(
        descriptor: AutoscalerUndo
    ) -> AutoscalingRestored:
        """Puts back both of the things a pin changed, and reports which of them
        it managed.

        The floor the autoscaler had, and the reconciliation that had to be
        suspended to leave it. Both, or it is not undone: an autoscaler back at
        its declared floor while the platform is still not reconciling it looks
        correct from every angle a reader has, and silently receives nothing
        anybody ships to it.

        Answers with which halves it managed rather than raising, for the reason
        the other two restores do: a restore can half-succeed, and the caller has
        to be able to say which half is still changed.

        The floor is put back before reconciliation is re-enabled. The other
        order would have the platform re-apply the manifest itself,
        unverifiably, at a moment nothing here chose. The behavior lives in
        `pinning.restore_autoscaler_floor`; this is registration only."""
        return pinning.restore_autoscaler_floor(descriptor, pin_settings)

    @mcp.tool()
    def get_recent_flag_changes(since: str) -> list[FlagChange]:
        """Returns the flag toggles the provider recorded since `since`, oldest
        first - for each, the flag, the state it was changed to, when, and who
        by.

        A read on the write server, which is where the credential to make it
        lives: the provider serves its history to admin tokens only, and an
        admin token can also change a flag. Issuing the read server one would
        defeat the tier split; reading from a process that can already write
        does not.

        It answers the question current state cannot - which flag changed, and
        in which direction - so that a flag switched *off* into an incident is
        distinguishable from one that was off all along. The behavior lives in
        `flag_history.recent_flag_changes`; this is registration only."""
        return flag_history.recent_flag_changes(since, flag_settings)

    @mcp.tool()
    def commit_to_new_branch(branch: str,
                             base_branch: str,
                             files: dict[str, str],
                             message: str) -> str:
        """Puts a proposed fix on a branch of its own, cut from the branch it
        fixes, and returns the branch it wrote.

        `files` maps a repository path to that file's whole new content. A
        branch is the only thing this writes to - never the base - so a wrong
        patch ends up somewhere nobody is running rather than in production.

        Every file the patch names is written, tests included - a fix that
        brings the test exposing the bug is the one a person can trust. The
        behavior lives in `branching.commit_to_new_branch`; this is
        registration only."""
        return branching.commit_to_new_branch(
            branch=branch,
            base_branch=base_branch,
            files=files,
            message=message,
            settings=repository_settings
        )

    @mcp.tool()
    def open_pull_request(head_branch: str,
                          base_branch: str,
                          title: str,
                          body: str) -> OpenedPullRequest:
        """Opens a draft pull request proposing a code fix, from the branch the
        fix sits on onto the branch it fixes.

        The half of a deploy that Argus is trusted with (§13). Opening a
        proposal changes nothing about the running service; *merging* one is
        the deploy itself, and there is no tool here that does it -
        not a guarded one, not an approval-gated one, none. That absence is the
        enforcement, and it is why this returns a place to read rather than an
        outcome: what happens next is a human's to decide.

        There is no draft parameter, because it is not the caller's choice.
        Returns the pull request's number and the address a person can read it
        at. The behavior lives in `pull_requests.open_pull_request`; this is
        registration only."""
        return pull_requests.open_pull_request(
            head_branch=head_branch,
            base_branch=base_branch,
            title=title,
            body=body,
            settings=repository_settings
        )

    return mcp


def main() -> None:
    """The process: one read of the environment, then serve until killed.

    The only place in this server that calls `get_settings`.
    """
    settings = get_settings()

    build_server(
        WriteMcpEndpoint.of(settings),
        FlagWriteSettings.of(settings),
        RepositoryWriteSettings.of(settings),
        RestartSettings.of(settings),
        RollbackSettings.of(settings),
        ScaleSettings.of(settings),
        PinSettings.of(settings),
        DiscardSettings.of(settings)
    ).run(transport="streamable-http")


if __name__ == "__main__":
    main()
