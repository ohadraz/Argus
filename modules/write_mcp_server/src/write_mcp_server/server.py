"""`argus-write-mcp` - the tools that change state (spec §12.1, §13).

A separate process from `argus-read-mcp`, not a separate module inside it. The
split is what makes "read-only" a property of a running process: the read server
holds no credential that could authorize a change, so a compromised or confused
caller cannot mutate anything through it, whatever tools it believes it has.

Everything registered here is **reversible tier** (§13). Nothing irreversible -
merging a pull request, applying infrastructure - has a function on this server
at all, which is tier enforcement by absence rather than by a check some future
caller could skip.

Built rather than declared, for the reason the read server is: the process that
reads configuration is the process that starts, and a server assembled at import
would have bound its credentials before anything could say which deployment it
was in.
"""

from __future__ import annotations

from argus_core import WriteMcpEndpoint, get_settings
from argus_core.models import FlagChange, FlagUndo, OpenedPullRequest
from mcp.server.fastmcp import FastMCP

from write_mcp_server import branching, flag_history, flag_state, pull_requests
from write_mcp_server.flag_state import FlagWriteSettings
from write_mcp_server.pull_requests import RepositoryWriteSettings


def build_server(endpoint: WriteMcpEndpoint,
                 flag_settings: FlagWriteSettings,
                 repository_settings: RepositoryWriteSettings) -> FastMCP:
    """Registers the write tools against one deployment's configuration.

    Two slices, not one, and not five. The flag tools speak to the provider and
    the code tool speaks to the repository; every credential named belongs to
    this tier, and none of them belongs in the other's calls. What keeps the
    *tiers* apart is that the read server is handed a slice with no field any
    of these could arrive in - not a check made here.

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

    @mcp.tool()
    def set_feature_flag(flag: str, enabled: bool) -> FlagUndo:
        """Sets a feature flag on or off in the configured environment.

        A reversible action (§13): it changes production state, and the state
        it changed is recorded in the undo descriptor returned with it, so the
        change can be put back by whoever holds this record - which is what
        makes it autonomous rather than something requiring approval.

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

        It will not write the test that grades the fix (§15.1), and refuses the
        whole patch rather than the offending file: half a patch on a branch
        reads like a change somebody meant to make. The behavior lives in
        `branching.commit_to_new_branch`; this is registration only."""
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

        The reversible end of an irreversible act (§13). Opening a proposal
        changes nothing about the running service and can be undone by closing
        it; *merging* one is a deploy, and there is no tool here that does it -
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
        RepositoryWriteSettings.of(settings)
    ).run(transport="streamable-http")


if __name__ == "__main__":
    main()
