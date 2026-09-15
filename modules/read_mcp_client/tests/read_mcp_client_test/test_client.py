from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import NamedTuple

import pytest
from argus_core import ReadMcpEndpoint, get_settings, parse_iso
from argus_core.mcp_transport import McpClient
from argus_core.models import ChangeEvent, MetricBucket
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario, calling
from read_mcp_client import (
    get_change_events,
    get_log_lines,
    get_metrics_summary,
    read_mcp,
)

from read_mcp_client_test.conftest import FakeTargetServiceHandler
from read_mcp_client_test.framework.builders import (
    a_cause_line_at,
    a_failure_line_at,
    a_metric_at,
    an_iso_minute,
)


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
            _asking_the_server(lambda client: get_log_lines(client=client))
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
            _asking_the_server(lambda client: get_change_events(
                "kukibuki-service",
                window_start=an_iso_minute(some_deploy_time - timedelta(hours=1)),
                window_end=an_iso_minute(some_deploy_time + timedelta(hours=1)),
                client=client
            ))
        ) \
        .then(
            _the_changes_reference(some_revision)
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
                metrics=[a_metric_at(datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC))],
                logs=some_logs
            ))
        ) \
        .when(
            _asking_the_server(_every_channel_in_turn)
        ) \
        .then(
            _every_call_was_answered()
        )


class _ThreeAnswers(NamedTuple):
    """What each of three tools said, over one session."""

    lines: list[str]
    buckets: list[MetricBucket]
    changes: list[ChangeEvent]


def _every_channel_in_turn(client: McpClient) -> _ThreeAnswers:
    some_window = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)

    return _ThreeAnswers(
        lines=get_log_lines(client=client),
        buckets=get_metrics_summary(client=client),
        changes=get_change_events(
            "kukibuki-service",
            window_start=an_iso_minute(some_window - timedelta(hours=1)),
            window_end=an_iso_minute(some_window + timedelta(hours=1)),
            client=client
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


def _an_argocd_deploy_at(moment: datetime, revision: str) -> dict[str, object]:
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
        "initiatedBy": {"username": "kuki"}
    }


def _the_changes_reference(*expected_references: str) -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        actual = [change.reference for change in changes]
        assert actual == list(expected_references), (
            f"Expected changes {list(expected_references)}, got {actual}."
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


def _asking_the_server[T](ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """One client to the subprocess the fixture started, held for one `when`.

    Where the subprocess is listening is read through `get_settings` rather than
    named here, because the fixture is what decides the port - it sets the
    environment and clears the cache before yielding, and this is the same
    answer the server itself resolved from.

    Closed on the way out, so a test leaves no session and no thread behind it.
    """
    def step() -> T:
        with read_mcp(ReadMcpEndpoint.of(get_settings())) as client:
            return ask(client)

    return step


def _drilling_down_from_metrics_to_logs(alert_time: str,
                                        into: Callable[[MetricBucket], bool]
) -> Callable[[], _DrillDown]:
    def both_phases(client: McpClient) -> _DrillDown:
        buckets = get_metrics_summary(alert_time=alert_time, client=client)
        anomalous = [bucket for bucket in buckets if into(bucket)]
        onset = anomalous[0].bucket_id if anomalous else None

        if onset is None:
            return _DrillDown(onset=None, lines=[])

        window_start, window_end = _a_window_anchored_on(onset)

        return _DrillDown(
            onset=onset,
            lines=get_log_lines(
                window_start=window_start,
                window_end=window_end,
                client=client
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
