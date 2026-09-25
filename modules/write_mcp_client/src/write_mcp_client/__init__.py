"""The write tier, as typed functions rather than tool names and dictionaries.

`write_mcp` builds the client a process holds to `argus-write-mcp`. Two clients
rather than one, as there are two servers - and holding this one authorizes
nothing: what makes the write tier the write tier is the credential that server
holds and the tools it has (spec §12.1, §13).
"""

from write_mcp_client.client import (
    commit_to_new_branch,
    get_recent_flag_changes,
    open_pull_request,
    restart_service,
    restore_deployment,
    roll_back_deployment,
    set_feature_flag,
    write_mcp,
)

__all__ = [
    "commit_to_new_branch",
    "get_recent_flag_changes",
    "open_pull_request",
    "restart_service",
    "restore_deployment",
    "roll_back_deployment",
    "set_feature_flag",
    "write_mcp",
]
