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
from typing import Any, Final

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
    RolloutProgress,
    ServiceDependency,
)
from argus_telemetry import start_telemetry
from code_index.embedding import an_embedder
from deployment_platform import DeploymentPlatformReads
from deployment_platform.argocd import ArgoCd, ArgoCdSettings
from metrics_source import MetricsSettings, MetricsSource, RuleSeries
from metrics_source.prometheus_adapter import buckets_between

from read_mcp_server import (
    alert_rules,
    deployments,
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

    @mcp.tool()
    def get_what_a_deployment_changed(service: str, revision: str) -> list[str]:
        """Returns what one deployment of a service changed - the files that
        differ from the revision deployed before it, and the change made to each.

        The channel that tells a bad deployment from a broken configuration, and
        the only one that can. Both arrive as a deployment, both move the same
        signals, and both are put right by returning the deployment - what
        separates them is whether the commit that landed touched source code or
        the values it shipped with, and that is inside the commit.

        Nothing else answers it. A deploy's summary names the path the
        application syncs from, which is the directory its manifests live in and
        is the same directory whatever the commit changed - so it is constant
        across exactly the distinction it looks like it would settle. The logs
        report a symptom and the metrics its shape.

        `revision` is the deploy's own reference as `get_change_events` reported
        it. What it is compared against is not asked for: the revision deployed
        before it is in the deployment history, which you cannot see, so naming
        it would be naming a guess - and a diff against a guessed base describes
        the wrong change in the shape a right one has.

        Worth calling whenever a deployment precedes the onset and you are about
        to say which of the two causes it was. Read the paths first: a change
        confined to configuration is not new code, whatever else is true, and a
        change to a source file is not a values mistake.

        No path is labelled code or configuration, deliberately - which
        directories hold configuration is that repository's business, and this
        answers with what changed so you can see for yourself. The answer is
        bounded and says so wherever it was: a deployment can be a repository-wide
        sweep, and an answer shortened in silence would read as the whole change.

        Three answers are facts rather than failures and are worth acting on
        differently: a revision no deployment has (which is what a feature flag's
        name looks like here), a deployment with nothing before it, and a
        deployment that changed nothing at all. A repository that could not be
        compared raises instead, because that last answer rules a deployment out
        and an outage is not evidence for it. The behavior lives in
        `deployments.what_a_deployment_changed`; this is registration only."""
        return deployments.what_a_deployment_changed(
            service, revision, repository_settings, platform=platform
        )

    @mcp.tool()
    def get_rollout_progress(service: str) -> RolloutProgress:
        """Returns how many of a service's replicas have reached the revision
        being rolled out, and how many have not, as counts rather than prose.

        The same read as `get_rollout_state` and a different reader. That one
        answers in sentences, for a model weighing whether a deployment is the
        fault; this answers in numbers, for a caller that has just changed
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
        how often it is evaluated, and how long it keeps firing once its
        condition stops holding.

        Read by Mitigation, which judges an action on a series alert by the rule
        that paged: the rule defines what is acceptable for the service. Not
        offered to a model. A rule that cannot be read raises rather than
        answering normal, which is the answer that would confirm whatever was
        just done. The behavior lives in `alert_rules.how_the_rule_stands`; this
        is registration only."""
        return alert_rules.how_the_rule_stands(rule, fetch=from_grafana)

    @mcp.tool()
    def get_rollout_state(service: str) -> list[str]:
        """Returns whether the deployment a service is running has finished
        arriving - how many replicas are on the revision being rolled out, how
        many are still on the one before it, and whether the rolling update is
        paused.

        The channel that tells a bad deployment from two revisions serving at
        once, and the only one that can. `get_change_events` reports that a
        revision was deployed, which both look like; what it cannot report is
        whether that revision reached every replica, because a deploy history
        records syncs that completed and a rollout is a stretch rather than an
        instant.

        Worth calling whenever a deployment precedes the onset - before saying
        the revision is at fault, and before proposing to return it. A deployment
        that has converged rules the split out and leaves the revision itself as
        the subject, which is an answer worth having either way.

        A split fleet is not a verdict. Every deployment is part way through for
        a minute or two, so the answer says what the platform reports and when
        the state began, and whether that is too long is yours to judge against
        an onset this channel has never seen. What makes it a fault rather than a
        rollout in progress is failures that only requests crossing the two
        versions could produce.

        A platform that could not be reached raises rather than answering that
        the deployment converged. The behavior lives in
        `rollouts.how_the_rollout_is_going`; this is registration only."""
        return rollouts.how_the_rollout_is_going(
            service, platform=platform
        )

    @mcp.tool()
    def get_service_dependencies(service: str) -> list[ServiceDependency]:
        """Returns what a service calls, and whose each of those is.

        The channel nobody reads until an incident, and the one that answers a
        question no other channel can. Metrics, logs and the deploy history all
        describe this service; when the time a request spends is spent waiting on
        something else, what decides the response is whether that something else
        belongs to the same organisation. A neighbour's process can be
        restarted. Another company's outage can only be escalated to whoever can
        telephone them.

        Worth calling whenever a log line, a failure or a latency figure points
        at a host this service does not run. The host name will not answer it -
        an internal-looking name is internal-looking because somebody chose the
        spelling, and a third party on a private link reads the same.

        Each entry says what it is for as well as whose it is, because an
        incident is diagnosed from what the dependency was doing on the request
        path. An `ownership` this system does not recognise is reported as
        written and is treated as not ours, which is a reason to say so rather
        than to act. A service the register holds no entry for depends on nothing
        as far as anybody here knows; a register that could not be reached raises
        rather than answering that. The behavior lives in
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
