from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, NamedTuple
from unittest.mock import create_autospec

import pytest
from alerting_platform.grafana import (
    CONDITION,
    CONDITIONS,
    DATA,
    DATASOURCE_UID,
    EVALUATOR,
    EXPR,
    EXPRESSION,
    EXPRESSION_DATASOURCE,
    LT,
    MODEL,
    PARAMS,
    REDUCE,
    REF_ID,
    THRESHOLD,
    TYPE,
)
from argus_testkit.assertions import Assertion, all_of, the_answer_was
from argus_testkit.scenario import Scenario, attempting, calling
from core import ReadMcpEndpoint, get_settings, parse_iso
from core.mcp_transport import Asking, McpClient
from core.models import (
    ChangeEvent,
    CodeOutsideThePatch,
    CodeUse,
    MetricBucket,
    PodPlacement,
    RuleLine,
    RuleReading,
)
from mcp.types import Tool
from read_mcp_client import ReadTier, read_mcp

from read_mcp_client_test.conftest import ARGUS_S_ACCOUNT, FakeTargetServiceHandler
from read_mcp_client_test.framework.assertions import the_tools_offered_are
from read_mcp_client_test.framework.builders import (
    a_cause_line_at,
    a_failure_line_at,
    a_metric_at,
    an_iso_minute,
)

SOME_BRANCH = "main"
SOME_REVISION = "53f02e9f6cb774f7f5869637bcc879941dcbc82d"

# Where a read tier is, waiting for its answers a bound that is not the one the
# settings default to - so a client built waiting it waited for what its
# endpoint said, and not for a figure of its own.
SOME_ANSWER_BOUND = 90.0
DONT_CARE_HOST = "dont-care-host"
DONT_CARE_PORT = 8199
DONT_CARE_URL = "http://dont-care-host:8199"
AN_ENDPOINT_WAITING_SOME_BOUND = ReadMcpEndpoint(
    read_mcp_host=DONT_CARE_HOST,
    read_mcp_port=DONT_CARE_PORT,
    read_mcp_url=DONT_CARE_URL,
    read_mcp_answered_within_seconds=SOME_ANSWER_BOUND
)

# What every read is asked about, where nothing in a case reads it.
DONT_CARE_SERVICE = "dont-care-service"
DONT_CARE_RULE = "dont-care-rule"
DONT_CARE_TEXT = "dont care"
DONT_CARE_PATH = "src/dont_care.py"

# Every read the read tier serves, asked as a caller asks it.
EVERY_READ = [
    pytest.param(lambda read: read.get_log_lines(), id="log-lines"),
    pytest.param(lambda read: read.get_metrics_summary(), id="metrics-summary"),
    pytest.param(lambda read: read.get_change_events(DONT_CARE_SERVICE, DONT_CARE_TEXT,
                                                     DONT_CARE_TEXT),
                 id="change-events"),
    pytest.param(lambda read: read.get_what_a_deployment_changed(DONT_CARE_SERVICE,
                                                                 SOME_REVISION),
                 id="what-a-deployment-changed"),
    pytest.param(lambda read: read.get_rollout_state(DONT_CARE_SERVICE),
                 id="rollout-state"),
    pytest.param(lambda read: read.get_rollout_progress(DONT_CARE_SERVICE),
                 id="rollout-progress"),
    pytest.param(lambda read: read.get_alert_rule(DONT_CARE_RULE), id="alert-rule"),
    pytest.param(lambda read: read.get_placements(DONT_CARE_SERVICE),
                 id="placements"),
    pytest.param(lambda read: read.branch_contains_revision(SOME_BRANCH, SOME_REVISION),
                 id="branch-contains-revision"),
    pytest.param(lambda read: read.get_enabled_flags(), id="enabled-flags"),
    pytest.param(lambda read: read.get_service_dependencies(DONT_CARE_SERVICE),
                 id="service-dependencies"),
    pytest.param(lambda read: read.search_repository(DONT_CARE_TEXT, SOME_BRANCH),
                 id="search-repository"),
    pytest.param(lambda read: read.get_repository_index_freshness(SOME_BRANCH),
                 id="index-freshness"),
    pytest.param(lambda read: read.search_repository_by_meaning(DONT_CARE_TEXT, SOME_BRANCH),
                 id="search-by-meaning"),
    pytest.param(lambda read: read.get_code_outside_the_patch({DONT_CARE_PATH: DONT_CARE_TEXT},
                                                              SOME_BRANCH),
                 id="code-outside-the-patch"),
    pytest.param(lambda read: read.list_repository_files(SOME_BRANCH),
                 id="list-files"),
    pytest.param(lambda read: read.read_repository_file(DONT_CARE_PATH, SOME_BRANCH),
                 id="read-file")
]


@pytest.mark.integration
def test_get_log_lines_reaches_the_real_read_mcp_server(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    some_logs = ["INFO some line", "ERROR another line"]
    the_target_service_has_logs = partial(_the_target_service_has, running_read_mcp)

    Scenario() \
        .given(
            calling(the_target_service_has_logs(some_logs))
        ) \
        .when(
            _asking_the_server(lambda read: read.get_log_lines())
        ) \
        .then(
            _the_returned_lines_are(some_logs)
        )


@pytest.mark.integration
def test_both_retrieval_phases_drive_each_other_through_the_client(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    some_time_the_cause_happened = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)
    some_time_the_error_appeared = some_time_the_cause_happened + timedelta(minutes=1)
    some_alert_time = _an_alert_time_within_window_after(some_time_the_error_appeared)
    some_error_rate_threshold = 0.1
    some_anomalous_error_rate = 0.41
    the_target_service_has = partial(_the_target_service_has, running_read_mcp)

    Scenario() \
        .given(
            calling(the_target_service_has(
                metrics=[
                    a_metric_at(some_time_the_cause_happened),
                    a_metric_at(
                        some_time_the_error_appeared, error_rate=some_anomalous_error_rate
                    )
                ],
                logs=[
                    a_cause_line_at(some_time_the_cause_happened),
                    a_failure_line_at(some_time_the_error_appeared)
                ]
            ))
        ) \
        .when(
            _drilling_down_from_metrics_to_logs(
                some_alert_time, into=_error_rate_above(some_error_rate_threshold)
            )
        ) \
        .then(all_of(
            _the_onset_is(an_iso_minute(some_time_the_error_appeared)),
            # The cause line sits in a minute the summary called healthy. A
            # window anchored on onset reaches back past it; scoping to the
            # anomalous minutes never could.
            _the_retrieved_lines_are([
                a_cause_line_at(some_time_the_cause_happened),
                a_failure_line_at(some_time_the_error_appeared)
            ])
        ))


@pytest.mark.integration
def test_get_change_events_reaches_the_real_read_mcp_server(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    # The whole path, in one call: the typed client, a real MCP round trip, the
    # tool, the port, the Argo CD adapter, and an HTTP response in Argo CD's own
    # shape - with only the server at the far end faked.
    some_deploy_time = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)
    some_revision = "9f4c1e7b2a3d5c8e"
    the_target_service_has_deploys = partial(_the_target_service_has_deploys, running_read_mcp)

    Scenario() \
        .given(
            calling(the_target_service_has_deploys(
                [_an_argocd_deploy_at(some_deploy_time, revision=some_revision)]
            ))
        ) \
        .when(
            _asking_the_server(lambda read: read.get_change_events(
                "kukibuki-service",
                window_start=an_iso_minute(some_deploy_time - timedelta(hours=1)),
                window_end=an_iso_minute(some_deploy_time + timedelta(hours=1))
            ))
        ) \
        .then(
            _the_changes_reference(some_revision)
        )


@pytest.mark.integration
def test_argus_s_own_deployments_are_left_out_over_the_real_read_mcp_server(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    # The whole of how Mitigation stops reading its own rollback as somebody
    # else's change: the client asks, the tier passes the question on, and the
    # Argo CD adapter is what knows which account is Argus's.
    some_deploy_time = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)
    argus_s_rollback = "a1a1a1a1"
    somebody_else_s = "b2b2b2b2"
    the_target_service_has_deploys = partial(_the_target_service_has_deploys, running_read_mcp)

    Scenario() \
        .given(
            calling(the_target_service_has_deploys([
                _an_argocd_deploy_at(some_deploy_time, revision=argus_s_rollback,
                                     started_by=ARGUS_S_ACCOUNT),
                _an_argocd_deploy_at(some_deploy_time, revision=somebody_else_s)
            ]))
        ) \
        .when(
            _asking_the_server(lambda read: read.get_change_events(
                "kukibuki-service",
                window_start=an_iso_minute(some_deploy_time - timedelta(hours=1)),
                window_end=an_iso_minute(some_deploy_time + timedelta(hours=1)),
                excluding_argus_s_own=True
            ))
        ) \
        .then(
            _the_changes_reference(somebody_else_s)
        )


@pytest.mark.integration
def test_one_session_serves_every_call_made_over_it(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    """Three tools over one client, which is the whole point of holding one.

    Asserted as three answers rather than by counting connections, because what
    a caller is promised is that a client is good for more than one question -
    and a session that had silently been rebuilt between them would answer these
    identically. What it rules out is the failure that matters: a second call
    over a held session raising rather than answering.
    """
    some_logs = ["INFO some line"]
    the_target_service_has = partial(_the_target_service_has, running_read_mcp)

    Scenario() \
        .given(
            calling(the_target_service_has(
                metrics=[a_metric_at(
                    datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=5))],
                logs=some_logs
            ))
        ) \
        .when(
            _asking_the_server(_every_channel_in_turn)
        ) \
        .then(
            _every_call_was_answered()
        )


@pytest.mark.integration
def test_the_paging_rules_series_reaches_the_caller_through_the_client(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    # The rule's uid crosses the protocol one way and its readings cross it
    # back, direction and all - which is the half no unit test reaches: a
    # nested reading that did not survive the round trip would arrive as no
    # reading, and a window with none disproves nothing.
    some_minute = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)
    some_rule = "some-rule"
    some_rule_query = "avg(some_confident_ratio)"

    Scenario() \
        .given(
            calling(_the_target_service_watches(
                running_read_mcp, some_rule, some_rule_query,
                metrics=[{**a_metric_at(some_minute), "some_confident_ratio": 0.41}]
            ))
        ) \
        .when(
            _asking_the_server(lambda read: read.get_metrics_summary(
                window_start=an_iso_minute(some_minute),
                window_end=an_iso_minute(some_minute + timedelta(minutes=1)),
                rule=some_rule
            ))
        ) \
        .then(
            _every_bucket_carried(RuleReading(value=0.41, worse_when="below",
                                              line=RuleLine(at=0.8, fires_on_it=False)))
        )


@pytest.mark.integration
def test_where_the_replicas_run_reaches_the_caller_through_the_client(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    # A start time crosses the protocol as text and has to come back the moment
    # it was, zone and all: a placement whose start arrived naive could not be
    # put either side of an onset, and that comparison is all it is read for.
    Scenario() \
        .given(
            calling(_the_platform_places(running_read_mcp, {
                "nodes": [{
                    "kind": "Pod",
                    "name": "io-shop-a",
                    "namespace": "production",
                    "createdAt": "2026-10-07T21:40:30Z",
                    "info": [{"name": "Node", "value": "gpu-a100-0"}]
                }],
                "hosts": [{
                    "name": "gpu-a100-0",
                    "labels": {"nvidia.com/gpu.product": "NVIDIA-A100-SXM4-40GB"}
                }]
            }))
        ) \
        .when(
            _asking_the_server(lambda read: read.get_placements(
                "io-shop"
            ))
        ) \
        .then(
            _the_placements_are([PodPlacement(
                pod="io-shop-a",
                node="gpu-a100-0",
                accelerator="NVIDIA-A100-SXM4-40GB",
                started_at=datetime(2026, 10, 7, 21, 40, 30, tzinfo=UTC)
            )])
        )


@pytest.mark.integration
def test_whether_the_branch_contains_a_revision_reaches_the_caller_through_the_client(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    # Held, rather than the `False` a lost answer would read as: Code-Fix is
    # told the files it reads are not the files that ran only when they are not.
    Scenario() \
        .given(
            calling(_github_compares(running_read_mcp, {
                f"{SOME_REVISION}...{SOME_BRANCH}": "ahead"
            }))
        ) \
        .when(
            _asking_the_server(lambda read: read.branch_contains_revision(
                SOME_BRANCH, SOME_REVISION
            ))
        ) \
        .then(
            _the_branch_contains_it()
        )


@pytest.mark.integration
def test_the_code_outside_a_patch_reaches_the_caller_through_the_client(
    running_read_mcp: type[FakeTargetServiceHandler]
) -> None:
    # The patch crosses the protocol one way, whole files keyed by path, and the
    # rows and the map of names to files cross it back - the half no unit test
    # reaches: a row lost on the way is a use of what changed that nobody hears of.
    some_ledger = "src/io_shop/ledger.py"
    some_summary = "src/io_shop/summary.py"

    Scenario() \
        .given(
            calling(_github_archives(running_read_mcp, {
                some_ledger: "def record(account, price):\n"
                             "    return replace(account, total=account.total + price)\n",
                some_summary: "def average(account, count):\n"
                              "    return account.month // count\n"
            }))
        ) \
        .when(
            _asking_the_server(lambda read: read.get_code_outside_the_patch(
                {some_ledger: "def record(account, price):\n"
                              "    return replace(account, total=account.total + price, "
                              "month=account.month + price)\n"},
                SOME_BRANCH
            ))
        ) \
        .then(
            the_answer_was(CodeOutsideThePatch(
                uses=[CodeUse(name="month", path=some_summary, line=2, function="average",
                              does="divides with it: account.month // count")],
                defined={"average": [some_summary]}
            ))
        )


@pytest.mark.unit
def test_a_read_client_waits_for_an_answer_as_long_as_its_endpoint_says() -> None:
    # Above the slowest tool this tier serves, a read of a whole repository's
    # archive: waited for less, that read is asked again and lost again. The
    # figure is the endpoint's, which the settings give it, and not one the
    # client keeps.
    Scenario() \
        .given(
            builds := create_autospec(McpClient)
        ) \
        .when(
            lambda: read_mcp(AN_ENDPOINT_WAITING_SOME_BOUND, builds_client=builds)
        ) \
        .then(
            _it_was_built_waiting(builds, SOME_ANSWER_BOUND)
        )


@pytest.mark.unit
@pytest.mark.parametrize("asking", EVERY_READ)
def test_every_read_is_asked_as_a_read(asking: Callable[[ReadTier], object]) -> None:
    # A read changes nothing, so one whose answer was lost is asked again and
    # fails as that asking failed - never as a change nobody can account for.
    # Said outright on every call, rather than left to whatever the transport
    # assumes.
    Scenario() \
        .given(
            client := create_autospec(McpClient, instance=True)
        ) \
        .when(
            attempting(lambda: asking(ReadTier(client)))
        ) \
        .then(
            _it_was_asked_as_a_read(client)
        )


@pytest.mark.unit
def test_the_tier_offers_what_its_own_session_lists() -> None:
    # The offer is read off the tier the agent will ask, never a listing kept
    # anywhere else: that would be a second definition of every tool.
    some_tool = "get_rollout_state"

    Scenario() \
        .given(
            session := _a_session_listing(some_tool)
        ) \
        .when(
            lambda: ReadTier(session).offered({some_tool: frozenset()})
        ) \
        .then(
            the_tools_offered_are([some_tool])
        )


@pytest.mark.unit
def test_leaving_the_tier_closes_its_session() -> None:
    # A process holds the tier for its life and leaves it on the way out; a
    # session left open is a thread and a socket nobody owns.
    Scenario() \
        .given(
            session := create_autospec(McpClient, instance=True)
        ) \
        .when(
            lambda: _held_and_left(ReadTier(session))
        ) \
        .then(
            _the_session_was_closed(session)
        )


def _a_session_listing(*names: str) -> Any:
    """A session to a read tier listing these tools, each taking nothing."""
    session = create_autospec(McpClient, instance=True)
    session.list_tools.return_value = [
        Tool(name=name, description="dont care what it does",
             inputSchema={"type": "object", "properties": {}, "required": []})
        for name in names
    ]

    return session


def _held_and_left(tier: ReadTier) -> None:
    with tier:
        pass


def _the_session_was_closed(session: Any) -> Assertion[None]:
    def assertion(dont_care_left: None) -> bool:
        if session.close.call_count != 1:
            raise AssertionError(
                f"Expected leaving the tier to close its session once, and it was closed "
                f"{session.close.call_count} time(s)."
            )

        return True

    return assertion


def _it_was_asked_as_a_read(client: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if not client.call.called:
            raise AssertionError("Expected one call asked as a read, and none was made.")

        said = client.call.call_args.kwargs.get("asking", "nothing")

        if said is not Asking.READ:
            raise AssertionError(
                f"Expected [{client.call.call_args.args[0]}] asked as [{Asking.READ}], and it "
                f"was asked as [{said}]."
            )

        return True

    return assertion


def _it_was_built_waiting(builds: Any, seconds: float) -> Assertion[object]:
    """The one client built was told to wait `seconds` for each answer."""
    def assertion(dont_care_client: object) -> bool:
        if builds.call_args is None:
            raise AssertionError(
                f"Expected a client built waiting [{seconds}]s for an answer, and none was "
                f"built."
            )

        waits = builds.call_args.kwargs.get("answered_within")

        if waits != seconds:
            raise AssertionError(
                f"Expected the client built waiting [{seconds}]s for an answer, and it "
                f"was built waiting [{waits}]s."
            )

        return True

    return assertion


def _github_archives(handler: type[FakeTargetServiceHandler],
                     files: dict[str, str]) -> Callable[[], None]:
    def step() -> None:
        handler.archive = files

    return step


def _github_compares(handler: type[FakeTargetServiceHandler],
                     comparisons: dict[str, str]) -> Callable[[], None]:
    def step() -> None:
        handler.comparisons = comparisons

    return step


def _the_branch_contains_it() -> Assertion[bool]:
    def assertion(contained: bool) -> bool:
        if contained is not True:
            raise AssertionError(
                f"Expected the branch to contain the revision, and the caller got {contained}."
            )

        return True

    return assertion


def _the_platform_places(handler: type[FakeTargetServiceHandler],
                         tree: dict[str, object]) -> Callable[[], None]:
    def step() -> None:
        handler.tree = tree

    return step


def _the_placements_are(expected: list[PodPlacement]) -> Assertion[list[PodPlacement]]:
    def assertion(placements: list[PodPlacement]) -> bool:
        if placements != expected:
            raise AssertionError(
                f"Expected the placements {expected}, and the caller got "
                f"{placements}."
            )

        return True

    return assertion


class _ThreeAnswers(NamedTuple):
    """What each of three tools said, over one session."""

    lines: list[str]
    buckets: list[MetricBucket]
    changes: list[ChangeEvent]


def _every_channel_in_turn(read: ReadTier) -> _ThreeAnswers:
    some_window = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)

    return _ThreeAnswers(
        lines=read.get_log_lines(),
        buckets=read.get_metrics_summary(),
        changes=read.get_change_events(
            "kukibuki-service",
            window_start=an_iso_minute(some_window - timedelta(hours=1)),
            window_end=an_iso_minute(some_window + timedelta(hours=1))
        )
    )


def _every_call_was_answered() -> Assertion[_ThreeAnswers]:
    def assertion(answers: _ThreeAnswers) -> bool:
        if not answers.lines:
            raise AssertionError(
                f"Expected the first call over the session to return lines, "
                f"got {answers.lines}."
            )

        if not answers.buckets:
            raise AssertionError(
                f"Expected the second call over the session to return buckets, "
                f"got {answers.buckets}."
            )

        return True

    return assertion


def _the_target_service_has_deploys(
    handler: type[FakeTargetServiceHandler], deploys: list[dict[str, object]]
) -> Callable[[], None]:
    def step() -> None:
        handler.deploys = deploys

    return step


def _an_argocd_deploy_at(moment: datetime,
                         revision: str,
                         started_by: str = "kuki") -> dict[str, object]:
    return {
        "id": 12,
        "revision": revision,
        "deployedAt": an_iso_minute(moment),
        "deployStartedAt": an_iso_minute(moment - timedelta(minutes=1)),
        "source": {
            "repoURL": "https://github.com/kuki/k8s-configs",
            "path": "apps/target-service/production",
            "targetRevision": "main"
        },
        "initiatedBy": {"username": started_by}
    }


def _the_changes_reference(*expected_references: str) -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        actual = [change.reference for change in changes]
        assert actual == list(expected_references), (
            f"Expected changes {list(expected_references)}, got {actual}."
        )
        return True

    return assertion


def _the_target_service_watches(handler: type[FakeTargetServiceHandler],
                                rule: str,
                                query: str,
                                metrics: list[dict[str, object]]) -> Callable[[], None]:
    """A service whose rule fires below its line on `query`, which is answered
    from each row's `some_confident_ratio`."""
    def step() -> None:
        handler.metrics = metrics
        handler.rules = {rule: _a_rule_firing_below_its_line_on(query)}
        handler.rule_queries = {query: "some_confident_ratio"}

    return step


def _a_rule_firing_below_its_line_on(query: str) -> dict[str, object]:
    """A rule in Grafana's provisioning shape: a query, a reduce, a threshold."""
    return {
        CONDITION: "C",
        DATA: [
            {REF_ID: "A", DATASOURCE_UID: "some-prometheus",
             MODEL: {REF_ID: "A", EXPR: query}},
            {REF_ID: "B", DATASOURCE_UID: EXPRESSION_DATASOURCE,
             MODEL: {REF_ID: "B", TYPE: REDUCE, EXPRESSION: "A"}},
            {REF_ID: "C", DATASOURCE_UID: EXPRESSION_DATASOURCE,
             MODEL: {REF_ID: "C", TYPE: THRESHOLD, EXPRESSION: "B",
                     CONDITIONS: [{EVALUATOR: {TYPE: LT, PARAMS: [0.8]}}]}}
        ]
    }


def _every_bucket_carried(expected: RuleReading) -> Assertion[list[MetricBucket]]:
    def assertion(buckets: list[MetricBucket]) -> bool:
        carried = [bucket.rule_reading for bucket in buckets]

        if not buckets or any(reading != expected for reading in carried):
            raise AssertionError(
                f"Expected every bucket to carry the rule reading [{expected}], "
                f"and they carried {carried}."
            )

        return True

    return assertion


class _DrillDown(NamedTuple):
    """Both phases' output, so `then` can assert on each.

    Phase one's onset is as much the behavior under test as the lines phase
    two returns - asserting only on the lines would pass even if the summary
    had flagged the wrong minute.
    """

    onset: str | None
    lines: list[str]


def _asking_the_server[T](ask: Callable[[ReadTier], T]) -> Callable[[], T]:
    """The read tier the fixture started, held for one `when`.

    Where the subprocess is listening is read through `get_settings` rather than
    named here, because the fixture is what decides the port - it sets the
    environment and clears the cache before yielding, and this is the same
    answer the server itself resolved from.

    Closed on the way out, so a test leaves no session and no thread behind it.
    """
    def step() -> T:
        with read_mcp(ReadMcpEndpoint.of(get_settings())) as read:
            return ask(read)

    return step


def _drilling_down_from_metrics_to_logs(alert_time: str,
                                        into: Callable[[MetricBucket], bool]
) -> Callable[[], _DrillDown]:
    def both_phases(read: ReadTier) -> _DrillDown:
        buckets = read.get_metrics_summary(alert_time=alert_time)
        anomalous = [bucket for bucket in buckets if into(bucket)]
        onset = anomalous[0].bucket_id if anomalous else None

        if onset is None:
            return _DrillDown(onset=None, lines=[])

        window_start, window_end = _a_window_anchored_on(onset)

        return _DrillDown(
            onset=onset,
            lines=read.get_log_lines(
                window_start=window_start,
                window_end=window_end
            )
        )

    return _asking_the_server(both_phases)


def _a_window_anchored_on(onset: str) -> tuple[str, str]:
    """The log window §16 anchors on onset rather than on the alert time.

    Back by the configured lookback, which is what has to contain the cause;
    forward by the lookahead, which contains the symptoms already seen.
    """
    settings = get_settings()
    onset_minute = parse_iso(onset)

    return (
        an_iso_minute(onset_minute - timedelta(minutes=settings.log_initial_lookback_minutes)),
        an_iso_minute(onset_minute + timedelta(minutes=settings.log_initial_lookahead_minutes))
    )


def _error_rate_above(threshold: float) -> Callable[[MetricBucket], bool]:
    def is_anomalous(bucket: MetricBucket) -> bool:
        return bucket.error_rate > threshold

    return is_anomalous


def _an_alert_time_within_window_after(onset: datetime) -> str:
    settings = get_settings()

    return an_iso_minute(onset + timedelta(minutes=settings.log_initial_lookback_minutes // 2))


def _the_target_service_has(handler: type[FakeTargetServiceHandler],
                            logs: list[str],
                            metrics: list[dict[str, object]] | None = None) -> Callable[[], None]:
    def step() -> None:
        handler.logs = logs
        handler.metrics = metrics or []

    return step


def _the_onset_is(expected: str) -> Assertion[_DrillDown]:
    def assertion(drill_down: _DrillDown) -> bool:
        if drill_down.onset != expected:
            raise AssertionError(f"Expected onset {expected}, got {drill_down.onset}.")

        return True

    return assertion


def _the_returned_lines_are(expected: list[str]) -> Assertion[list[str]]:
    def assertion(lines: list[str]) -> bool:
        return _lines_match(lines, expected)

    return assertion


def _the_retrieved_lines_are(expected: list[str]) -> Assertion[_DrillDown]:
    def assertion(drill_down: _DrillDown) -> bool:
        return _lines_match(drill_down.lines, expected)

    return assertion


def _lines_match(actual: list[str], expected: list[str]) -> bool:
    if actual != expected:
        raise AssertionError(f"Expected lines {expected}, got {actual}.")

    return True
