"""The read tier, as typed functions rather than tool names and dictionaries.

`read_mcp` builds the client a process holds to `argus-read-mcp`, and every
function here is asked over one. Where that server is reached is read once, by
whoever builds the client; nothing below this door learns an address.
"""

from read_mcp_client.client import (
    get_alert_rule,
    get_change_events,
    get_enabled_flags,
    get_log_lines,
    get_metrics_summary,
    get_repository_index_freshness,
    get_rollout_progress,
    get_rollout_state,
    get_service_dependencies,
    get_what_a_deployment_changed,
    list_repository_files,
    read_mcp,
    read_repository_file,
    search_repository,
    search_repository_by_meaning,
)

__all__ = [
    "get_alert_rule",
    "get_change_events",
    "get_enabled_flags",
    "get_log_lines",
    "get_metrics_summary",
    "get_repository_index_freshness",
    "get_rollout_progress",
    "get_rollout_state",
    "get_service_dependencies",
    "get_what_a_deployment_changed",
    "list_repository_files",
    "read_mcp",
    "read_repository_file",
    "search_repository",
    "search_repository_by_meaning"
]
