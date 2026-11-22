"""The write tier's root: `argus-write-mcp` (spec §12.1, §13).

`python -m apps.write_mcp`. Which tools there are and what each may change is
`write_mcp_server`'s; this decides what they change it through - the flag
provider, the code host and the deployment platform's adapters, each holding
this tier's credential - and serves them.
"""

from __future__ import annotations

from typing import Final

from code_host.github import GitHub, GitHubSettings
from core import DatabaseSettings, TelemetrySettings, WriteMcpEndpoint, get_settings
from deployment_platform.argocd import ArgoCd, ArgoCdSettings
from flag_provider.unleash import Unleash, UnleashSettings
from telemetry import start_telemetry
from write_mcp_server.discarding import DiscardSettings
from write_mcp_server.fencing import OpensHolds, holds_in_the_database
from write_mcp_server.server import build_server

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-write-mcp"


def main(holds: OpensHolds = holds_in_the_database) -> None:
    """The process: one read of the environment, then serve until killed.

    The only place in this tier that calls `get_settings`, and the one that
    starts its telemetry - closed on the way out, so what it collected last is
    on disk. So are the holds a change is made under, which are the database's
    own runs: `holds` defaults to them, and a suite that serves the real tools
    over a run it stands in for hands its own.
    """
    settings = get_settings()

    with (
        start_telemetry(TelemetrySettings.of(settings), _SERVICE),
        holds(DatabaseSettings.of(settings)) as hold_for_a_change
    ):
        build_server(
            WriteMcpEndpoint.of(settings),
            # The flag provider's adapter, built here and nowhere else in this
            # tier and handed on as the writes port, for the platform's reason.
            Unleash(UnleashSettings()),
            # The code host's adapter, built here for the same reason and handed
            # on as the writes port: it holds the credential that pushes, and no
            # tool names a route.
            GitHub(GitHubSettings.of(settings)),
            # The adapter is built here and nowhere else in this tier, and handed
            # on as the writes port: no action names a route.
            ArgoCd(ArgoCdSettings.of(settings)),
            DiscardSettings.of(settings),
            hold_for_a_change,
            settings.argocd_actor
        ).serve()


if __name__ == "__main__":
    main()
