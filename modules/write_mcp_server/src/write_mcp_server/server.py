"""`argus-write-mcp` - the tools that change state (spec §12.1, §13).

A separate process from `argus-read-mcp`, not a separate module inside it. The
split is what makes "read-only" a property of a running process: the read server
holds no credential that could authorize a change, so a compromised or confused
caller cannot mutate anything through it, whatever tools it believes it has.

Everything registered here is **reversible tier** (§13). Nothing irreversible -
merging a pull request, applying infrastructure - has a function on this server
at all, which is tier enforcement by absence rather than by a check some future
caller could skip.
"""

from __future__ import annotations

from typing import Any

from argus_core.config import get_settings
from argus_core.models.flag_change import FlagChange
from mcp.server.fastmcp import FastMCP

from write_mcp_server import flag_history, flag_state

settings = get_settings()
mcp = FastMCP(
    "argus-write-mcp",
    host=settings.write_mcp_host,
    port=settings.write_mcp_port,
)


@mcp.tool()
def set_feature_flag(flag: str, enabled: bool) -> dict[str, Any]:
    """Sets a feature flag on or off in the configured environment.

    A reversible action (§13): it changes production state, and the state it
    changed is recorded in the undo descriptor returned with it, so the change
    can be put back by whoever holds this record - which is what makes it
    autonomous rather than something requiring approval.

    Both directions, one tool. A flag causes an incident by changing, and the
    damaging direction is not always "on" - undoing a flag that was switched
    off means switching it back on, and undoing this call is this call with
    the state reversed.

    Returns only once the change is visible to evaluation, and raises rather
    than reporting an unchanged flag as changed: a caller about to judge
    whether the service recovered has to know the service was actually
    changed. The behavior lives in `flag_state.set_flag`; this is registration
    only."""
    return flag_state.set_flag(flag, enabled)


@mcp.tool()
def get_recent_flag_changes(since: str) -> list[FlagChange]:
    """Returns the flag toggles the provider recorded since `since`, oldest
    first - for each, the flag, the state it was changed to, when, and who by.

    A read on the write server, which is where the credential to make it lives:
    the provider serves its history to admin tokens only, and an admin token can
    also change a flag. Issuing the read server one would defeat the tier split;
    reading from a process that can already write does not.

    It answers the question current state cannot - which flag changed, and in
    which direction - so that a flag switched *off* into an incident is
    distinguishable from one that was off all along. The behavior lives in
    `flag_history.recent_flag_changes`; this is registration only."""
    return flag_history.recent_flag_changes(since)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
