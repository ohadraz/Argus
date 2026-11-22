"""The read tier's root: `argus-read-mcp` (spec §12.1, §13).

`python -m apps.read_mcp`. Which tools there are and what each answers is
`read_mcp_server`'s; this decides what they read through - every platform's
adapter, each holding a read credential alone, the metrics source and the store
passages are searched in - and serves them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from alerting_platform.grafana import Grafana, GrafanaSettings
from code_host.github import GitHubReads, GitHubReadSettings
from core import (
    DatabaseSettings,
    ReadMcpEndpoint,
    TelemetrySettings,
    get_settings,
    open_pool,
)
from core.models import MetricBucket, RuleSeries
from deployment_platform.argocd import ArgoCd, ArgoCdSettings
from embedding_fastembed import an_embedder
from flag_provider.unleash import UnleashFrontend, UnleashFrontendSettings
from metrics_source import MetricsSource
from metrics_source.prometheus_adapter import buckets_between, what_the_series_is
from metrics_source.prometheus_settings import PrometheusSettings
from read_mcp_server.meaning import IndexReadSettings
from read_mcp_server.registry import ServiceRegistrySettings
from read_mcp_server.repository import RepositoryReadSettings
from read_mcp_server.retrieval import TargetServiceSettings
from read_mcp_server.server import build_server
from read_mcp_server.window import RetrievalSettings
from telemetry import start_telemetry
from telemetry.langfuse import LangfuseSettings, to_langfuse
from vector_store_qdrant import SearchOpenedOnFirstUse
from vector_store_qdrant.settings import QdrantSettings

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-read-mcp"


def the_minutes_at(settings: PrometheusSettings) -> MetricsSource:
    """The metrics port, bound to the one vendor this deployment reads metrics
    from, so that what the tool is handed names a window and nothing else."""
    def minutes(started_at: datetime,
                ended_at: datetime,
                rule_series: RuleSeries | None = None) -> list[MetricBucket]:
        return buckets_between(started_at, ended_at, settings, rule_series=rule_series)

    return minutes


def main() -> None:
    """The process: the environment read where it starts, then serve until killed.

    The only place in this tier that reads the environment - the kernel's
    settings and each vendor's, every adapter's from its own. Everything below is
    handed the part of the answer it reads, which is what makes the tier a
    property of the types rather than of what the deployment happened to put in
    the environment.

    A pool rather than a connection, and held open for the life of the process:
    the index's watermark is read on every search by meaning, and a handshake
    per question is one a model waits through. It reads one row and writes
    none - a database arriving in the read tier does not make the read tier
    capable of writing (§13).

    Its telemetry is started first and closed last, so what it collected in its
    final seconds is on disk.
    """
    settings = get_settings()

    with (
        start_telemetry(TelemetrySettings.of(settings), _SERVICE,
                        also=to_langfuse(LangfuseSettings())),
        open_pool(DatabaseSettings.of(settings)) as pool
    ):
        index = IndexReadSettings.of(settings)

        build_server(
            ReadMcpEndpoint.of(settings),
            RetrievalSettings.of(settings),
            TargetServiceSettings.of(settings),
            the_minutes_at(PrometheusSettings()),
            # The flag provider's adapter, built here for the same reason and
            # handed on as its reads port - holding the evaluation credential
            # alone, since its settings have nowhere to put another.
            UnleashFrontend(UnleashFrontendSettings()),
            # The adapter is built here and nowhere else in this tier, and handed
            # on typed as the reads port: a write typed anywhere below does not
            # type-check, which is the tier split held in the code this process
            # runs as well as in the process boundary.
            ArgoCd(ArgoCdSettings()),
            # The code host's adapter, built here for the same reason and handed
            # on as its reads port - holding the read credential alone, since
            # its settings have nowhere to put the one that pushes.
            GitHubReads(GitHubReadSettings()),
            ServiceRegistrySettings.of(settings),
            RepositoryReadSettings.of(settings),
            index,
            # The store's reading side, handed on as the port, which can only
            # search. It opens on first use, so a tier that never searches by
            # meaning - or offers no such tool - reaches no store.
            SearchOpenedOnFirstUse(QdrantSettings().qdrant_url,
                                   index.repository_index_collection),
            # The model a question is embedded with, handed on as the port - the
            # one the index was built with. It loads on first use, so a tier that
            # never searches by meaning loads no model.
            an_embedder(settings.repository_index_embedding_model),
            # The alerting platform's adapter, built here for the same reason and
            # handed on as its port, and the metrics adapter's account of what a
            # rule's series measures beside it - the one adapter that may read a
            # query.
            Grafana(GrafanaSettings()),
            what_the_series_is,
            pool.connection
        ).serve()


if __name__ == "__main__":
    main()
