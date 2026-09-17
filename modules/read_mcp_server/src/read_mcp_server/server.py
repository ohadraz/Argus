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

from argus_core import (
    Connections,
    DatabaseSettings,
    ReadMcpEndpoint,
    get_settings,
    open_pool,
)
from argus_core.models import ChangeEvent, MetricBucket
from code_index.embedding import an_embedder
from mcp.server.fastmcp import FastMCP

from read_mcp_server import flags, meaning, repository, retrieval
from read_mcp_server.argocd import (
    ArgocdSettings,
    fetch_argocd_application,
    fetch_deploys,
)
from read_mcp_server.change_source import ChangeSource
from read_mcp_server.flags import FlagReadSettings
from read_mcp_server.meaning import IndexReadSettings
from read_mcp_server.repository import RepositoryReadSettings
from read_mcp_server.retrieval import TargetServiceSettings
from read_mcp_server.window import RetrievalSettings


def build_server(endpoint: ReadMcpEndpoint,
                 retrieval_settings: RetrievalSettings,
                 target_service: TargetServiceSettings,
                 flag_settings: FlagReadSettings,
                 argocd_settings: ArgocdSettings,
                 repository_settings: RepositoryReadSettings,
                 index_settings: IndexReadSettings,
                 connections: Connections) -> FastMCP:
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

    @mcp.tool()
    def search_repository(query: str, ref: str) -> list[str]:
        """Returns every line in the Target Service's repository at `ref` that
        contains `query`, as `path:line: text`.

        How a fault actually gets localized. The investigation names a cause - a
        flag, a function, a message out of a log line - and this is what turns
        that name into a place to look. Search for it before listing anything:
        a listing is forty paths to guess between, and this is the file.

        Substring, not a regular expression: what matches nothing is a fact
        about the repository, where a pattern that will not compile is a fact
        about the query. Raises rather than answering emptily when the source
        could not be read at all - "no matches" and "could not look" are
        opposite things and must not arrive looking alike. The behavior lives in
        `repository.search_repository`; this is registration only."""
        return repository.search_repository(query, ref, repository_settings)

    @mcp.tool()
    def list_repository_files(ref: str) -> list[str]:
        """Returns every file in the Target Service's repository at `ref`, as
        paths from its root - directories left out.

        How a fault gets localized: read the paths, recognise the module the
        evidence points at, then `read_repository_file` it. Cheap enough to call
        first, since one call names the whole repository.

        Raises rather than returning a short list when the repository could not
        be listed in full - including when the API truncated its own answer. A
        listing that is missing files is indistinguishable from a repository
        that does not have them, and a fix would be written for the wrong file.
        The behavior lives in `repository.list_repository_files`; this is
        registration only."""
        return repository.list_repository_files(ref, repository_settings)

    @mcp.tool()
    def read_repository_file(path: str, ref: str) -> str:
        """Returns what one file in the Target Service's repository says, as
        text, at `ref`.

        The other half of localizing a fault. Reading is all it does: this
        process holds no credential that could change what it reads, so a
        repository arriving in the read tier does not make the read tier capable
        of writing (§13). Proposing a change is a different tool on a different
        server.

        Raises for a path that is not there rather than answering emptily - a
        file that exists and says nothing is a real thing, and the two must not
        arrive looking alike. The behavior lives in
        `repository.read_repository_file`; this is registration only."""
        return repository.read_repository_file(path, ref, repository_settings)

    # Everything below this line exists only where the deployment keeps an
    # index. Not a tool that answers "no" when asked: a tool that is offered
    # will be called, and one backed by an index nobody builds answers nothing
    # for every description - which a model reads as a fact about the code.
    # Skipping the registration also skips the store client and the model.
    if not index_settings.searches_by_meaning:
        return mcp

    # Bound once, like the fetchers above. The embedder is the odd one: it
    # loads a model on first use rather than here, so a server that is started
    # and never asked to search by meaning never pays for it.
    embed = an_embedder()
    find_passages = meaning.the_index_at(index_settings)
    indexed_sha = meaning.the_commit_indexed_for(
        repository_settings.github_repository, connections
    )

    @mcp.tool()
    def get_repository_index_freshness(ref: str) -> str:
        """Returns what has to be said about the index of the Target Service's
        source before anything it answers is acted on, or an empty string when
        there is nothing to say.

        For whoever is assembling a prompt rather than for a model mid-task:
        the same fact `search_repository_by_meaning` prefixes onto its answers,
        available before the first one is asked for. An index is built off any
        incident's path, so it can describe an older commit than the one being
        fixed - and a model that learns that from a result it has already acted
        on has learned it a turn too late.

        The behavior lives in `meaning.the_index_notice`; this is registration
        only."""
        return meaning.the_index_notice(ref=ref, indexed_sha=indexed_sha)

    @mcp.tool()
    def search_repository_by_meaning(description: str, ref: str) -> list[str]:
        """Returns the passages of the Target Service's source nearest a
        description of what the code does, as `path:start-end` and the source
        itself.

        The tool for a cause that has no name to search for. An investigation
        concluding "the discount is divided by a count that can be zero" gives
        `search_repository` nothing to match on - the repository may not say
        `discount` anywhere - and this finds the code that behaves that way.
        Describe the behaviour, not the identifier: this matches meaning, where
        `search_repository` matches characters, and the two are worth using
        together.

        Passages, not files. What comes back is source with the lines it spans,
        ready to read - and `read_repository_file` on the path it names is how
        to see the rest of it.

        An answer may open with a `note:` line saying the index describes an
        older commit than the one asked about, in which case code that changed
        in between may not be findable here yet. Nothing found is a real answer;
        an index nobody has built yet says so; and a store that could not be
        reached raises rather than answering emptily. The behavior lives in
        `meaning.search_repository_by_meaning`; this is registration only."""
        return meaning.search_repository_by_meaning(
            description,
            ref,
            settings=repository_settings,
            embed=embed,
            find=find_passages,
            indexed_sha=indexed_sha
        )

    return mcp


def main() -> None:
    """The process: one read of the environment, then serve until killed.

    The only place in this server that calls `get_settings`. Everything below
    is handed the part of the answer it reads, which is what makes the tier a
    property of the types rather than of what the deployment happened to put in
    the environment.

    A pool rather than a connection, and held open for the life of the process:
    the index's watermark is read on every search by meaning, and a handshake
    per question is one a model waits through. It reads one row and writes
    none - a database arriving in the read tier does not make the read tier
    capable of writing (§13).
    """
    settings = get_settings()

    with open_pool(DatabaseSettings.of(settings)) as pool:
        build_server(
            ReadMcpEndpoint.of(settings),
            RetrievalSettings.of(settings),
            TargetServiceSettings.of(settings),
            FlagReadSettings.of(settings),
            ArgocdSettings.of(settings),
            RepositoryReadSettings.of(settings),
            IndexReadSettings.of(settings),
            pool.connection
        ).run(transport="streamable-http")


if __name__ == "__main__":
    main()
