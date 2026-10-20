"""The read tier's tools as it declares them, for a suite that offers them to a
model with no read tier running.

An agent offers the read tier's reads as the server lists them (MCP,
`tools/list`), so a suite that drives an agent needs that list - and a copy
written here would be a second definition of every tool, the thing the server
owning them exists to end. So the server is built in-process and asked: listing
calls no tool, and nothing it is configured to reach is reached.

Built for one way of finding source, since that decides which repository tools
it serves. The search by meaning is served only where an index is kept, and a
tier built to serve it loads an embedding model to be built at all.
"""

from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping
from unittest.mock import create_autospec

from argus_core import Connections, ReadMcpEndpoint
from argus_core.mcp_transport import McpClient
from argus_core.models import CodeSearch, ToolDefinition
from deployment_platform import DeploymentPlatformReads
from mcp.server.fastmcp import FastMCP
from metrics_source import MetricsSettings
from read_mcp_client import offered
from read_mcp_server.alert_rules import AlertRuleReadSettings
from read_mcp_server.flags import FlagReadSettings
from read_mcp_server.meaning import IndexReadSettings
from read_mcp_server.registry import ServiceRegistrySettings
from read_mcp_server.repository import RepositoryReadSettings
from read_mcp_server.retrieval import TargetServiceSettings
from read_mcp_server.server import build_server
from read_mcp_server.window import RetrievalSettings

SEARCHING_BY_GREP_ALONE = CodeSearch.GREP


def what_the_read_tier_offers(held: Mapping[str, Collection[str]],
                              mode: CodeSearch = SEARCHING_BY_GREP_ALONE
                              ) -> list[ToolDefinition]:
    """The tools `held` names, as one deployment's read tier declares them -
    offered as an agent offers them, by the read client's own `offered`."""
    # `asyncio.run` rather than an async helper: listing is the only
    # asynchronous thing here, and no suite in the workspace is async.
    listed = asyncio.run(_a_read_tier(mode).list_tools())
    the_read_tier = create_autospec(McpClient, instance=True)
    the_read_tier.list_tools.return_value = listed

    return offered(held, client=the_read_tier)


def _a_read_tier(mode: CodeSearch) -> FastMCP:
    """One deployment's read tier, reaching nothing."""
    return build_server(
        ReadMcpEndpoint(read_mcp_host="127.0.0.1",
                        read_mcp_port=8090,
                        read_mcp_url="http://127.0.0.1:8090/mcp"),
        RetrievalSettings(log_initial_lookback_minutes=5,
                          log_initial_lookahead_minutes=5,
                          log_max_window_minutes=60,
                          metrics_window_minutes=60),
        TargetServiceSettings(target_service_url="http://target.invalid"),
        MetricsSettings(prometheus_base_url="http://prometheus.invalid"),
        FlagReadSettings(unleash_base_url="http://flags.invalid",
                         unleash_frontend_token="dont-care-token"),
        create_autospec(DeploymentPlatformReads, instance=True),
        ServiceRegistrySettings(
            service_registry_base_url="http://registry.invalid",
            service_registry_service_path="/registry/services/{service}"
        ),
        RepositoryReadSettings(github_api_url="http://github.invalid",
                               github_repository="dont-care/repository",
                               github_read_token="dont-care-token",
                               github_source_paths="src"),
        IndexReadSettings(qdrant_url="http://qdrant.invalid",
                          code_index_collection="dont-care-collection",
                          code_search=mode),
        AlertRuleReadSettings(grafana_base_url="http://grafana.invalid",
                              grafana_auth_token="dont-care-token"),
        create_autospec(Connections, instance=True)
    )
