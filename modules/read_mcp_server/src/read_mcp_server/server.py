"""`argus-read-mcp` - the tools that only look (spec §12.1, §13).

Built rather than declared. Every tool below needs configuration, and the
process that reads configuration is the process that starts: a server assembled
at import would have bound its windows and its credential before anything could
say which deployment it was in.

What the tools close over is the whole of what this tier may know - four narrow
slices, none of which has a field that could hold a credential capable of
changing anything. That is the read tier stated as a type rather than promised
in a comment.
"""

from __future__ import annotations

from argus_core import ReadMcpEndpoint, get_settings
from argus_core.models import ChangeEvent, MetricBucket
from mcp.server.fastmcp import FastMCP

from read_mcp_server import flags, retrieval
from read_mcp_server.argocd import (
    ArgocdSettings,
    fetch_argocd_application,
    fetch_deploys,
)
from read_mcp_server.change_source import ChangeSource
from read_mcp_server.flags import FlagReadSettings
from read_mcp_server.retrieval import TargetServiceSettings
from read_mcp_server.window import RetrievalSettings


def build_server(endpoint: ReadMcpEndpoint,
                 retrieval_settings: RetrievalSettings,
                 target_service: TargetServiceSettings,
                 flag_settings: FlagReadSettings,
                 argocd_settings: ArgocdSettings) -> FastMCP:
    """Registers every read tool against one deployment's configuration.

    A function rather than module-level code, so that importing this module -
    which the tests do - binds no address and builds no server. The slices
    arrive here and are closed over by the registrations below; nothing beneath
    this module reads configuration for itself.

    The tool bodies stay one-line delegations. What they delegate to is where
    the behaviour lives, and where an injection seam a decorated function
    cannot have - a `Callable`-typed default breaks FastMCP's schema
    generation - is available to a test.
    """
    mcp = FastMCP(
        "argus-read-mcp",
        host=endpoint.read_mcp_host,
        port=endpoint.read_mcp_port,
    )

    fetch_logs = retrieval.target_service_logs(target_service)
    fetch_metrics = retrieval.target_service_metrics(target_service)

    def toggles() -> list[dict[str, object]]:
        return list(flags.fetch_evaluated_toggles(flag_settings))

    def deploys(application: str,
                *,
                window_start: str,
                window_end: str) -> list[ChangeEvent]:
        return fetch_deploys(
            application,
            window_start=window_start,
            window_end=window_end,
            fetch=lambda named: fetch_argocd_application(named, argocd_settings)
        )

    changes: ChangeSource = deploys

    @mcp.tool()
    def get_log_lines(alert_time: str | None = None,
                      window_start: str | None = None,
                      window_end: str | None = None,
                      filters: str | None = None) -> list[str]:
        """Returns the Target Service's log lines for one window of an incident.

        Phase two of the Two-phase retrieval:
        1. call `get_metrics_summary` first, to find the minute the incident
           started,
        2. then ask for a window anchored on that onset - reaching back before
           it, since the cause lands in a minute that still looks healthy.

        `alert_time` is the incident's `T0` and derives the window from
        configured lookback/lookahead;
        `window_start`/`window_end` override it and are clamped to the
        configured maximum span, with a leading notice line when that happens.
        All times are ISO-8601 strings, since an `@mcp.tool()` parameter must be
        JSON-schema-representable. Passing nothing returns the whole log, which
        is what `agent_investigator` still does.
        `filters` matches the tool's eventual shape (§16 field-level filtering)
        but isn't acted on yet. The behavior itself - and the `fetch` injection
        seam a `Callable` default cannot have on a decorated function - lives in
        `retrieval.get_log_lines`; this is registration only."""
        return retrieval.get_log_lines(
            alert_time,
            window_start,
            window_end,
            filters,
            settings=retrieval_settings,
            fetch=fetch_logs
        )

    @mcp.tool()
    def get_metrics_summary(alert_time: str | None = None,
                            window_start: str | None = None,
                            window_end: str | None = None) -> list[MetricBucket]:
        """Returns per-minute aggregated metrics for one window of an incident.

        Phase one of Two-phase retrieval: cheap enough to read whole, it shows
        the incident's shape - which minutes are anomalous, and whether error
        rate or latency moved - so a caller can locate the onset and anchor a
        log window on it.
        Windowing works exactly as in `get_log_lines`; the behavior lives in
        `retrieval.get_metrics_summary`."""
        return retrieval.get_metrics_summary(
            alert_time,
            window_start,
            window_end,
            settings=retrieval_settings,
            fetch=fetch_metrics
        )

    @mcp.tool()
    def get_change_events(service: str,
                          window_start: str,
                          window_end: str) -> list[ChangeEvent]:
        """Returns what changed on a service within one window.

        The third retrieval channel. Metrics locate the minute an incident
        started and logs say what the service said about it; this answers "what
        changed" - which is what a cause is. Ask over a window far wider than
        any log window: a change can precede the symptoms it causes by an
        unbounded lag, and changes are sparse where log lines are not.

        The window is explicit and required - unlike the other two tools, there
        is no alert-time default, because how far back a cause may lie is the
        caller's judgement and not retrieval's.

        Raises rather than returning nothing when the change source cannot be
        reached: "nothing changed" is a conclusion, and an outage is not
        evidence for it. The behavior, and the source injection seam, live in
        `retrieval.get_change_events`; this is registration only."""
        return retrieval.get_change_events(
            service, window_start, window_end, source=changes
        )

    @mcp.tool()
    def get_enabled_flags() -> list[str]:
        """Returns the feature flags currently evaluating true.

        Evaluated at the moment of the call, not from a cached copy, so a flag
        somebody turned off a second ago is already absent. The environment is
        the read credential's own - a caller cannot ask about one this tier was
        not given access to.

        This is how an agent learns *which* flag an incident is about without
        that flag being named in Argus's configuration. Reverting it is a
        different tier's tool on a different process: the credential behind this
        call cannot change a flag's state (§13).

        Raises rather than returning an empty list when the provider cannot be
        reached, for the reason `get_change_events` does: "nothing is enabled"
        is a conclusion, and an outage is not evidence for it. The behavior and
        its injection seam live in `flags.enabled_flags`; this is registration
        only."""
        return flags.enabled_flags(toggles)

    return mcp


def main() -> None:
    """The process: one read of the environment, then serve until killed.

    The only place in this server that calls `get_settings`. Everything below
    is handed the part of the answer it reads, which is what makes the tier a
    property of the types rather than of what the deployment happened to put in
    the environment.
    """
    settings = get_settings()

    build_server(
        ReadMcpEndpoint.of(settings),
        RetrievalSettings.of(settings),
        TargetServiceSettings.of(settings),
        FlagReadSettings.of(settings),
        ArgocdSettings.of(settings)
    ).run(transport="streamable-http")


if __name__ == "__main__":
    main()
