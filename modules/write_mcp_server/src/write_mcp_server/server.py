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
    ConfigRollbackUndo,
    ConfigurationRestored,
    FlagChange,
    FlagUndo,
    OpenedPullRequest,
    RestartedService,
)
from mcp.server.fastmcp import FastMCP

from write_mcp_server import (
    branching,
    flag_history,
    flag_state,
    pull_requests,
    restarting,
    rolling_back,
)
from write_mcp_server.flag_state import FlagWriteSettings
from write_mcp_server.pull_requests import RepositoryWriteSettings
from write_mcp_server.restarting import RestartSettings
from write_mcp_server.rolling_back import RollbackSettings


def build_server(endpoint: WriteMcpEndpoint,
                 flag_settings: FlagWriteSettings,
                 repository_settings: RepositoryWriteSettings,
                 restart_settings: RestartSettings,
                 rollback_settings: RollbackSettings) -> FastMCP:
    """Registers the write tools against one deployment's configuration.

    Four slices, not one. The flag tools speak to the provider, the code tool
    speaks to the repository, and the restart and the rollback each speak to
    the deployment platform - separately, because they are different routes
    under different paths and a single slice would make one tool's
    misconfiguration look like the other's. Every credential named belongs to
    this tier, and none of them belongs in another's calls. What keeps the *tiers* apart is that
    the read server is handed a slice with no field any of these could arrive
    in - not a check made here.

    The tool bodies stay registration only; the behaviour, and the seams a
    decorated function cannot carry, live in `flag_state`, `flag_history` and
    `pull_requests`.
    """
    mcp = FastMCP(
        "argus-write-mcp",
        host=endpoint.write_mcp_host,
        port=endpoint.write_mcp_port,
    )

    def confirm_the_change_landed() -> list[str]:
        return flag_state.evaluated_flags(flag_settings)

    confirm_a_new_process_is_serving = restarting.the_process_start_time(
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
    def roll_back_configuration(application: str) -> ConfigRollbackUndo:
        """Returns a deployment to the configuration revision it ran before,
        and reports what that cost.

        A generic mitigation (§13), admissible unasked for one specific
        reason: the revision it applies was reviewed and ran before, so this
        replays somebody's change rather than authoring one. It writes nothing
        to the configuration repository, and must not - that would be an
        infrastructure change requiring approval.

        Which revision is not a parameter. The platform resolves it as
        `argocd app rollback APPNAME` does with its history id omitted - the
        immediately preceding deployment - because nothing above this port
        holds a deployment history to choose from.

        Mitigates without resolving. The repository still holds the change
        that caused the incident, and the platform's own reconciliation has
        been suspended so that it is not re-applied; both are recorded in the
        descriptor returned, and both are what a withdrawal puts back. The
        behavior lives in `rolling_back.roll_back_configuration`; this is
        registration only."""
        return rolling_back.roll_back_configuration(application, rollback_settings)

    @mcp.tool()
    def restore_configuration(
        descriptor: ConfigRollbackUndo
    ) -> ConfigurationRestored:
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
        `rolling_back.restore_configuration`; this is registration only."""
        return rolling_back.restore_configuration(descriptor, rollback_settings)

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
        RollbackSettings.of(settings)
    ).run(transport="streamable-http")


if __name__ == "__main__":
    main()
