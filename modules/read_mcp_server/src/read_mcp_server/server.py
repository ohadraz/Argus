"""`argus-read-mcp` - the tools that only look (spec §12.1, §13).

Built rather than declared. Every tool below needs configuration, and the
process that reads configuration is the process that starts: a server assembled
at import would have bound its windows and its credential before anything could
say which deployment it was in.

What the tools close over is the whole of what this tier may know - a handful of
narrow slices, none of which has a field that could hold a credential capable of
changing anything. That is the read tier stated as a type rather than promised
in a comment.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import partial
from typing import Annotated, Any, Final

from argus_core import (
    Connections,
    DatabaseSettings,
    ReadMcpEndpoint,
    TelemetrySettings,
    get_settings,
    open_pool,
)
from argus_core.mcp_transport import TracedFastMCP
from argus_core.models import (
    AlertRuleStanding,
    ChangeEvent,
    MetricBucket,
    PodPlacement,
    RolloutAccount,
    RolloutProgress,
    ServiceDependency,
)
from argus_telemetry import start_telemetry
from code_index.embedding import an_embedder
from deployment_platform import DeploymentPlatformReads
from deployment_platform.argocd import ArgoCd, ArgoCdSettings
from metrics_source import MetricsSettings, MetricsSource, RuleSeries
from metrics_source.prometheus_adapter import buckets_between
from pydantic import Field
from repository_source import the_branch_contains, the_head_of

from read_mcp_server import (
    alert_rules,
    deployments,
    descriptions,
    flags,
    meaning,
    placements,
    repository,
    retrieval,
    rollouts,
)
from read_mcp_server.alert_rules import AlertRuleReadSettings
from read_mcp_server.change_source import ChangeSource
from read_mcp_server.deploy_history import fetch_deploys
from read_mcp_server.flags import FlagReadSettings
from read_mcp_server.meaning import IndexReadSettings
from read_mcp_server.registry import (
    ServiceRegistrySettings,
    fetch_registered_service,
    what_a_service_depends_on,
)
from read_mcp_server.repository import RepositoryReadSettings
from read_mcp_server.retrieval import TargetServiceSettings
from read_mcp_server.window import RetrievalSettings

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-read-mcp"

logger = logging.getLogger(__name__)


def build_server(endpoint: ReadMcpEndpoint,
                 retrieval_settings: RetrievalSettings,
                 target_service: TargetServiceSettings,
                 metrics_settings: MetricsSettings,
                 flag_settings: FlagReadSettings,
                 platform: DeploymentPlatformReads,
                 registry_settings: ServiceRegistrySettings,
                 repository_settings: RepositoryReadSettings,
                 index_settings: IndexReadSettings,
                 alert_rule_settings: AlertRuleReadSettings,
                 connections: Connections) -> TracedFastMCP:
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
    mcp = TracedFastMCP(
        "argus-read-mcp",
        host=endpoint.read_mcp_host,
        port=endpoint.read_mcp_port,
    )

    fetch_logs = retrieval.target_service_logs(target_service)

    # The port bound to the one vendor this deployment reads metrics from, so
    # that what the tool is handed names a window and nothing else.
    def metrics(started_at: datetime,
                ended_at: datetime,
                rule_series: RuleSeries | None = None) -> list[MetricBucket]:
        return buckets_between(
            started_at, ended_at, metrics_settings, rule_series=rule_series
        )

    metrics_source: MetricsSource = metrics

    def toggles() -> list[dict[str, object]]:
        return list(flags.fetch_evaluated_toggles(flag_settings))

    # The deploy history for a window, as the change channel asks for it. The
    # deployment channel and the rollout channel are handed the platform itself,
    # so one object decides where the platform is for all three.
    def deploys(application: str,
                *,
                window_start: str,
                window_end: str) -> list[ChangeEvent]:
        return fetch_deploys(
            application,
            window_start=window_start,
            window_end=window_end,
            platform=platform
        )

    changes: ChangeSource = deploys

    def from_grafana(path: str) -> dict[str, Any]:
        return alert_rules.fetch_from_grafana(path, alert_rule_settings)

    # Which series a rule watches, read off its definition in the same Grafana
    # the rule's standing is read from.
    def series_the_rule_watches(rule: str) -> RuleSeries | None:
        return alert_rules.the_series_the_rule_watches(rule, fetch=from_grafana)

    def registered(service: str) -> dict[str, object]:
        return fetch_registered_service(service, registry_settings)

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
                            window_end: str | None = None,
                            rule: str | None = None) -> list[MetricBucket]:
        """Returns per-minute aggregated metrics for one window of an incident.

        Phase one of Two-phase retrieval: cheap enough to read whole, it shows
        the incident's shape - which minutes are anomalous, and whether error
        rate or latency moved - so a caller can locate the onset and anchor a
        log window on it.
        Windowing works exactly as in `get_log_lines`. `rule` is the uid of the
        alert rule that paged: its own series is read beside the fixed ones and
        carried on each minute as `rule_reading`, with the direction the rule
        fires in. The behavior lives in `retrieval.get_metrics_summary`."""
        return retrieval.get_metrics_summary(
            alert_time,
            window_start,
            window_end,
            rule,
            settings=retrieval_settings,
            source=metrics_source,
            series_of=series_the_rule_watches
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

    @mcp.tool(description=descriptions.SEARCH_REPOSITORY)
    def search_repository(
        query: Annotated[str, Field(description=descriptions.SEARCH_REPOSITORY_QUERY)],
        ref: Annotated[str, Field(description=descriptions.THE_REF)]
    ) -> list[str]:
        """Returns every line in the Target Service's repository at `ref` that
        contains `query` - a substring, not a pattern - as `path:line: text`.

        Raises rather than answering emptily when the source could not be read:
        "no matches" and "could not look" must not arrive looking alike. What a
        model is told of it is `descriptions.SEARCH_REPOSITORY`. The behavior
        lives in `repository.search_repository`; this is registration only."""
        return repository.search_repository(query, ref, repository_settings)

    @mcp.tool(description=descriptions.LIST_REPOSITORY_FILES)
    def list_repository_files(
        ref: Annotated[str, Field(description=descriptions.THE_REF)]
    ) -> list[str]:
        """Returns every file in the Target Service's repository at `ref`, as
        paths from its root - directories left out.

        Raises rather than returning a short list when the repository could not
        be listed in full, the API truncating its own answer included: a
        listing missing files reads as a repository without them. What a model
        is told of it is `descriptions.LIST_REPOSITORY_FILES`. The behavior
        lives in `repository.list_repository_files`; this is registration
        only."""
        return repository.list_repository_files(ref, repository_settings)

    @mcp.tool(description=descriptions.READ_REPOSITORY_FILE)
    def read_repository_file(
        path: Annotated[str, Field(description=descriptions.READ_REPOSITORY_FILE_PATH)],
        ref: Annotated[str, Field(description=descriptions.THE_REF)]
    ) -> str:
        """Returns what one file in the Target Service's repository says, as
        text, at `ref`.

        Reading is all it does: this process holds no credential that could
        change what it reads (§13). Raises for a path that is not there rather
        than answering emptily - an empty file is a real thing. What a model is
        told of it is `descriptions.READ_REPOSITORY_FILE`. The behavior lives
        in `repository.read_repository_file`; this is registration only."""
        return repository.read_repository_file(path, ref, repository_settings)

    @mcp.tool(description=descriptions.WHAT_A_DEPLOYMENT_CHANGED)
    def get_what_a_deployment_changed(
        service: Annotated[str, Field(description=descriptions.THE_SERVICE)],
        revision: Annotated[
            str, Field(description=descriptions.WHAT_A_DEPLOYMENT_CHANGED_REVISION)
        ]
    ) -> list[str]:
        """Returns what one deployment of a service changed - the files that
        differ from the revision deployed before it, and the change made to each.

        `revision` is the deploy's own reference; the base is read from the
        deployment history rather than asked for, since a caller naming it
        would be naming a guess. No path is labelled code or configuration -
        that is the repository's business. The answer is bounded and says so
        where it was.

        Three answers are facts rather than failures: a revision no deployment
        has, a deployment with nothing before it, and one that changed nothing.
        A repository that could not be compared raises instead, because that
        last answer rules a deployment out. What a model is told of it is
        `descriptions.WHAT_A_DEPLOYMENT_CHANGED`. The behavior lives in
        `deployments.what_a_deployment_changed`; this is registration only."""
        return deployments.what_a_deployment_changed(
            service, revision, repository_settings, platform=platform
        )

    @mcp.tool()
    def get_rollout_progress(service: str) -> RolloutProgress:
        """Returns how many of a service's replicas have reached the revision
        being rolled out, and how many have not, as counts.

        The same read as `get_rollout_state` and a different reader. That one
        names the revisions too, for whoever weighs whether a deployment is the
        fault; this answers in numbers alone, for a caller that has just changed
        something and needs to know the change has arrived before it measures
        anything. Mitigation is that caller: until every replica is on the
        revision a rollback returned to, a minute of metrics is a minute the old
        code was still serving, and a recovery measured across those minutes is a
        recovery measured of the wrong deployment.

        Converged is not the same question as *stuck*. How many replicas have
        arrived is a count reaching its target; whether it has taken too long is a
        judgement on a timing this tier cannot know, and it is not made here or
        anywhere the counts are read.

        A platform that could not be reached raises rather than answering that
        the rollout arrived. The behavior lives in
        `rollouts.how_far_the_rollout_has_got`; this is registration only."""
        return rollouts.how_far_the_rollout_has_got(
            service, platform=platform
        )

    @mcp.tool()
    def get_alert_rule(rule: str) -> AlertRuleStanding:
        """Returns whether an alert rule has stopped firing, as of its last
        evaluation, and how the rule reads its service - how far back it looks,
        how often it is evaluated, how long it keeps firing once its condition
        stops holding, and how long that condition must hold before it fires.

        Read by Mitigation, which judges an action on a series alert by the rule
        that paged: the rule defines what is acceptable for the service. And by
        the postmortem, for how long the rule waits before it fires. Not offered
        to a model. A rule that cannot be read raises rather than
        answering normal, which is the answer that would confirm whatever was
        just done. The behavior lives in `alert_rules.how_the_rule_stands`; this
        is registration only."""
        return alert_rules.how_the_rule_stands(rule, fetch=from_grafana)

    @mcp.tool(description=descriptions.ROLLOUT_STATE)
    def get_rollout_state(
        service: Annotated[str, Field(description=descriptions.THE_SERVICE)]
    ) -> RolloutAccount:
        """Returns whether the deployment a service is running has finished
        arriving - how many replicas are on the revision being rolled out, how
        many are still on the one before it, and whether the rolling update is
        paused.

        Answered as a value - the counts, the revision going out and the one
        before it, each with when it was deployed - and said by whoever reads
        it. A split fleet is not a verdict: whether it has lasted too long is a
        judgement against an onset this tier never sees.

        A platform that could not be reached raises rather than answering that
        the deployment converged. What a model is told of it is
        `descriptions.ROLLOUT_STATE`. The behavior lives in
        `rollouts.how_the_rollout_is_going`; this is registration only."""
        return rollouts.how_the_rollout_is_going(
            service, platform=platform
        )

    @mcp.tool(description=descriptions.SERVICE_DEPENDENCIES)
    def get_service_dependencies(
        service: Annotated[str, Field(description=descriptions.THE_SERVICE)]
    ) -> list[ServiceDependency]:
        """Returns what a service calls, what each of those is for, and whose
        each is.

        An `ownership` this system does not recognise is reported as written
        and treated as not ours. A service the register holds no entry for
        depends on nothing as far as anybody here knows; a register that could
        not be reached raises rather than answering that. What a model is told
        of it is `descriptions.SERVICE_DEPENDENCIES`. The behavior lives in
        `registry.what_a_service_depends_on`; this is registration only."""
        return what_a_service_depends_on(service, fetch=registered)

    @mcp.tool()
    def get_placements(service: str) -> list[PodPlacement]:
        """Returns where each of a service's replicas runs - the pod, its node,
        the accelerator card that node carries, and when the pod started.

        The channel that reads what no other one holds. A replica the platform
        moved onto another card, with nothing deployed, is in no deployment
        history, no diff and no flag log; it is only in where the pods are, and
        when each began running there.

        Read by the Investigator on every incident, after the onset is found and
        before its model is asked anything - so not offered to a model. A pod
        whose node or start the platform does not say is left out, and a node
        whose card it does not say has none, never a guess at either.

        A platform that could not be reached raises rather than answering that
        the service runs nowhere. The behavior lives in
        `placements.where_the_service_runs`; this is registration only."""
        return placements.where_the_service_runs(service, platform=platform)

    @mcp.tool()
    def branch_contains_revision(branch: str, revision: str) -> bool:
        """Returns whether `revision` is in `branch`'s history.

        What Code-Fix is told before it reads anything: it reads one branch,
        and the revision running when the alert fired may have been deployed
        from another that was never merged - so the files it opens are not the
        files that ran. Asked by code, never offered to a model.

        A repository that could not be reached raises rather than answering
        that the branch does not contain it. The behavior lives in
        `repository_source.the_branch_contains`; this is registration only."""
        return the_branch_contains(
            branch, revision, repository.the_source_settings(repository_settings)
        )

    # Everything below this line exists only where the deployment keeps an
    # index. Not a tool that answers "no" when asked: a tool that is offered
    # will be called, and one backed by an index nobody builds answers nothing
    # for every description - which a model reads as a fact about the code.
    # Skipping the registration also skips the store client and the model.
    if not index_settings.searches_by_meaning:
        logger.info("search by meaning not offered",
                    extra={"code_search": index_settings.code_search})

        return mcp

    # Bound once, like the fetchers above. The embedder is the odd one: it
    # loads a model on first use rather than here, so a server that is started
    # and never asked to search by meaning never pays for it.
    embed = an_embedder()
    find_passages = meaning.the_index_at(index_settings)
    indexed_sha = meaning.the_commit_indexed_for(
        repository_settings.github_repository, connections
    )
    head_of = partial(the_head_of, settings=repository.the_source_settings(repository_settings))

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
        return meaning.the_index_notice(ref=ref, head_of=head_of, indexed_sha=indexed_sha)

    @mcp.tool(description=descriptions.SEARCH_REPOSITORY_BY_MEANING)
    def search_repository_by_meaning(
        description: Annotated[
            str, Field(description=descriptions.SEARCH_REPOSITORY_BY_MEANING_DESCRIPTION)
        ],
        ref: Annotated[str, Field(description=descriptions.THE_REF)]
    ) -> list[str]:
        """Returns the passages of the Target Service's source nearest a
        description of what the code does, as `path:start-end` and the source
        itself.

        An answer may open with a `note:` line saying the index describes an
        older commit than the one asked about, in which case code that changed
        in between may not be findable here yet. Nothing found is a real answer;
        an index nobody has built yet says so; and a store that could not be
        reached raises rather than answering emptily. What a model is told of
        it is `descriptions.SEARCH_REPOSITORY_BY_MEANING`. The behavior lives in
        `meaning.search_repository_by_meaning`; this is registration only."""
        return meaning.search_repository_by_meaning(
            description,
            ref,
            settings=repository_settings,
            embed=embed,
            find=find_passages,
            head_of=head_of,
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

    Its telemetry is started first and closed last, so what it collected in its
    final seconds is on disk.
    """
    settings = get_settings()

    with (
        start_telemetry(TelemetrySettings.of(settings), _SERVICE),
        open_pool(DatabaseSettings.of(settings)) as pool,
    ):
        build_server(
            ReadMcpEndpoint.of(settings),
            RetrievalSettings.of(settings),
            TargetServiceSettings.of(settings),
            MetricsSettings.of(settings),
            FlagReadSettings.of(settings),
            # The adapter is built here and nowhere else in this tier, and handed
            # on typed as the reads port: a write typed anywhere below does not
            # type-check, which is the tier split held in the code this process
            # runs as well as in the process boundary.
            ArgoCd(ArgoCdSettings.of(settings)),
            ServiceRegistrySettings.of(settings),
            RepositoryReadSettings.of(settings),
            IndexReadSettings.of(settings),
            AlertRuleReadSettings.of(settings),
            pool.connection
        ).serve()


if __name__ == "__main__":
    main()
