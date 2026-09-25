from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from argus_core import WriteMcpEndpoint, get_settings
from argus_core.mcp_transport import McpClient
from argus_core.models import (
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    FlagUndo,
    RestartedService,
    UndoDescriptor,
)
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario, calling
from write_mcp_client import (
    get_recent_flag_changes,
    restart_service,
    restore_deployment,
    roll_back_deployment,
    set_feature_flag,
    write_mcp,
)

from write_mcp_client_test.fake_deployment_platform import (
    THE_HISTORY_BEFORE_IT,
    THE_HISTORY_RUNNING_NOW,
    THE_REVISION_RUNNING_NOW,
    FakeDeploymentPlatformHandler,
    a_running_platform,
)
from write_mcp_client_test.fake_feature_flag_provider import FakeUnleashHandler, a_running_write_mcp

SINCE = "2026-08-20T11:00:00Z"
INSIDE_THE_WINDOW = "2026-08-20T11:04:38.033Z"
DONT_CARE_ACTOR = "dont-care-actor"
SOME_APPLICATION = "io-shop"


@pytest.fixture
def running_write_mcp_over_a_platform() -> Iterator[type[FakeDeploymentPlatformHandler]]:
    """The same real server, with a fake deployment platform behind it too.

    Nested in this order because the write server reads its settings once, at
    start-up, from the environment it was launched with - so the platform has
    to have said where it is listening before the subprocess exists.
    """
    with a_running_platform() as platform, a_running_write_mcp():
        yield platform


@pytest.fixture
def running_write_mcp() -> Iterator[type[FakeUnleashHandler]]:
    """A fake flag provider and a real `write_mcp_server` process in front of
    it, for the length of one test."""
    with a_running_write_mcp() as provider:
        yield provider


@pytest.mark.integration
def test_switching_a_flag_off_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The whole path in one call: the typed client, a real MCP round trip, the
    # tool, the admin adapter, and the provider's own wire shape - with only the
    # provider at the far end faked. And the assertion is on the provider's
    # state, not on what the client said: an action Argus reports taking and did
    # not take is the failure that matters.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, some_flag))
        ) \
        .when(
            _asking_the_server(lambda client: set_feature_flag(
                some_flag, enabled=False, client=client
            ))
        ) \
        .then(all_of(
            the_undo_descriptor_says_it_had_been(enabled=True),
            the_provider_now_reports_enabled(running_write_mcp, []),
        ))


@pytest.mark.integration
def test_switching_a_flag_on_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The direction a revert-only write tier could not perform, and the one an
    # incident caused by a flag being switched off needs.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp))
        ) \
        .when(
            _asking_the_server(lambda client: set_feature_flag(
                some_flag, enabled=True, client=client
            ))
        ) \
        .then(all_of(
            the_undo_descriptor_says_it_had_been(enabled=False),
            the_provider_now_reports_enabled(running_write_mcp, [some_flag]),
        ))


@pytest.mark.integration
def test_reading_flag_changes_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            calling(the_provider_recorded(
                running_write_mcp,
                [a_disabling_of(some_flag, at=INSIDE_THE_WINDOW)],
            ))
        ) \
        .when(
            _asking_the_server(
                lambda client: get_recent_flag_changes(SINCE, client=client)
            )
        ) \
        .then(
            the_changes_are([(some_flag, False)])
        )


@pytest.mark.integration
def test_a_change_the_client_made_can_be_undone_through_the_same_call(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Undoing a refuted mitigation is this same tool with the state reversed,
    # which is the only reason one tool serves both directions. If the round
    # trip only worked one way, a refuted action could not be put back.
    #
    # Both writes go over one session, which is how the walk makes them: an
    # action and the undo that follows it are two calls by one worker, and a
    # session good for only the first would leave a refuted flag where it was.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, some_flag))
        ) \
        .when(
            _asking_the_server(lambda client: _undoing(
                set_feature_flag(some_flag, enabled=False, client=client),
                some_flag,
                client
            ))
        ) \
        .then(
            the_provider_now_reports_enabled(running_write_mcp, [some_flag])
        )


@pytest.mark.integration
def test_restarting_a_service_reaches_the_platform_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The second write, over the same path as the first: the typed client, a
    # real MCP round trip, the tool, the platform adapter, and Argo CD's own
    # resource-action shape - with only the platform at the far end faked.
    #
    # It is also the only test that proves the wait is real end to end. The
    # fake moves its own gauge when the action runs, so a server that returned
    # on the POST alone would answer with the process that was serving before,
    # and the assertion on what is serving now would catch it.
    some_service = "kuki-service"

    Scenario() \
        .when(
            _asking_the_server(lambda client: restart_service(
                some_service, client=client
            ))
        ) \
        .then(all_of(
            the_platform_was_asked_to_restart(
                running_write_mcp_over_a_platform, some_service
            ),
            the_process_reported_is_the_one_now_serving(
                running_write_mcp_over_a_platform
            )
        ))


@pytest.mark.integration
def test_rolling_a_configuration_back_reaches_the_platform_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The third write, and the first that is more than one request. The fake
    # refuses a rollback while it still reports syncing itself, so a caller that
    # asked for the rollback without suspending reconciliation first would be
    # refused by the fake exactly as a real server refuses it - which is what
    # makes the order of the three requests something this test can witness
    # rather than assume.
    Scenario() \
        .when(
            _asking_the_server(lambda client: roll_back_deployment(
                SOME_APPLICATION, client=client
            ))
        ) \
        .then(all_of(
            the_platform_stopped_reconciling(running_write_mcp_over_a_platform),
            the_platform_was_rolled_back_to(
                running_write_mcp_over_a_platform, THE_HISTORY_BEFORE_IT
            ),
            the_descriptor_records_what_it_came_from(
                history_id=THE_HISTORY_RUNNING_NOW,
                revision=THE_REVISION_RUNNING_NOW,
                was_syncing_itself=True
            )
        ))


@pytest.mark.integration
def test_restoring_a_configuration_reaches_the_platform_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # What a withdrawal does to a rollback, over the same path. Both halves have
    # to arrive: a deployment whose revision is back while the reconciliation
    # Argus suspended is still suspended looks right from every angle a reader
    # has, and silently receives nothing anybody ships to it.
    #
    # Driven from a real rollback rather than from a descriptor written here,
    # because a descriptor a test invented is one nothing proves the tier would
    # ever produce - and the entry it names is the whole of what the restore
    # acts on.
    Scenario() \
        .when(
            _asking_the_server(lambda client: restore_deployment(
                roll_back_deployment(SOME_APPLICATION, client=client),
                client=client
            ))
        ) \
        .then(all_of(
            both_halves_were_put_back(),
            the_platform_is_reconciling_itself_again(
                running_write_mcp_over_a_platform
            ),
            the_platform_was_rolled_back_to(
                running_write_mcp_over_a_platform, THE_HISTORY_RUNNING_NOW
            )
        ))


def _undoing(undo_descriptor: UndoDescriptor,
             flag: str,
             client: McpClient) -> UndoDescriptor:
    assert isinstance(undo_descriptor, FlagUndo)

    return set_feature_flag(
        flag, enabled=undo_descriptor.was_enabled, client=client
    )


def _asking_the_server[T](ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """One client to the subprocess the fixture started, held for one `when`.

    Where the subprocess is listening is read through `get_settings` rather than
    named here, because the fixture is what decides the port - it sets the
    environment and clears the cache before yielding, and this is the same
    answer the server resolved from.

    Closed on the way out, so a test leaves no session and no thread behind it.
    """
    def step() -> T:
        with write_mcp(WriteMcpEndpoint.of(get_settings())) as client:
            return ask(client)

    return step


def the_provider_has_enabled(handler: type[FakeUnleashHandler],
                             *flags: str) -> Callable[[], None]:
    def step() -> None:
        handler.enabled_flags = set(flags)

    return step


def the_provider_recorded(handler: type[FakeUnleashHandler],
                          events: list[dict[str, Any]]) -> Callable[[], None]:
    def step() -> None:
        handler.events = events

    return step


def a_disabling_of(flag: str, at: str) -> dict[str, Any]:
    """One row of the provider's event log, in its own wire shape."""
    return {
        "id": 11,
        "type": "feature-environment-disabled",
        "createdBy": DONT_CARE_ACTOR,
        "createdAt": at,
        "featureName": flag,
        "project": "default",
        "environment": "production",
    }


def the_undo_descriptor_says_it_had_been(enabled: bool) -> Assertion[UndoDescriptor]:
    def assertion(undo_descriptor: UndoDescriptor) -> bool:
        if not isinstance(undo_descriptor, FlagUndo):
            raise AssertionError(
                f"Expected a flag's descriptor, got a [{undo_descriptor.kind}] one."
            )

        actual = undo_descriptor.was_enabled
        if actual is not enabled:
            raise AssertionError(f"Expected was_enabled {enabled}, got {actual}.")

        return True

    return assertion


def the_provider_now_reports_enabled(handler: type[FakeUnleashHandler],
                                     expected: list[str]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        actual = sorted(handler.enabled_flags)
        if actual != sorted(expected):
            raise AssertionError(f"Expected enabled flags {sorted(expected)}, got {actual}.")

        return True

    return assertion


def the_changes_are(expected: list[tuple[str, bool]]) -> Assertion[list[FlagChange]]:
    def assertion(changes: list[FlagChange]) -> bool:
        actual = [(change.flag, change.enabled) for change in changes]
        if actual != expected:
            raise AssertionError(f"Expected changes {expected}, got {actual}.")

        return True

    return assertion


def the_platform_was_asked_to_restart(
    handler: type[FakeDeploymentPlatformHandler], service: str
) -> Assertion[RestartedService]:
    """The platform's own record of what it was told to do.

    Asserted on the platform rather than on what the client answered, for the
    reason the flag round trips are: an action Argus reports taking and did not
    take is the failure that matters.
    """
    def assertion(dont_care_restarted: RestartedService) -> bool:
        asked_for = [
            action for action in handler.actions_run if service in action["path"]
        ]

        if not asked_for:
            raise AssertionError(
                f"Expected the platform to be asked to restart [{service}], "
                f"and it was asked for {handler.actions_run}."
            )

        if asked_for[-1]["asked_for"].get("action") != "restart":
            raise AssertionError(
                f"Expected the restart action to be run on [{service}], "
                f"and {asked_for[-1]['asked_for']} was."
            )

        return True

    return assertion


def the_process_reported_is_the_one_now_serving(
    handler: type[FakeDeploymentPlatformHandler]
) -> Assertion[RestartedService]:
    """What came back is the process the platform is actually serving with.

    The whole reason the tool answers with a value: a start time carried all
    the way back through the MCP round trip, matching the one the platform now
    reports, is the only evidence a caller has that the restart happened.
    """
    def assertion(restarted: RestartedService) -> bool:
        serving = handler.process_start_time_seconds

        if restarted.process_start_time_seconds != serving:
            raise AssertionError(
                f"Expected the process now serving [{serving}] to be reported, "
                f"and [{restarted.process_start_time_seconds}] was."
            )

        return True

    return assertion


def the_platform_stopped_reconciling(
    handler: type[FakeDeploymentPlatformHandler]
) -> Assertion[object]:
    """Reconciliation was suspended, and suspended by a policy with no
    `automated` in it at all.

    Argo CD spells the arrangement as the presence of a key rather than as a
    boolean, so a caller writing `{"automated": false}` would leave a server
    still syncing while believing it had stopped it - and the fake, reading the
    key the way a real one does, would then refuse the rollback.
    """
    def assertion(dont_care_result: object) -> bool:
        if not handler.sync_policies_written:
            raise AssertionError(
                "Expected the sync policy to have been written before the "
                "rollback, and the platform was never asked to change it - so "
                "the rollback was asked for against an application still "
                "reconciling itself."
            )

        suspending = handler.sync_policies_written[0]

        if "automated" in suspending:
            raise AssertionError(
                f"Expected reconciliation to be suspended by a policy naming no "
                f"`automated` at all, and [{suspending}] was written."
            )

        return True

    return assertion


def the_platform_was_rolled_back_to(
    handler: type[FakeDeploymentPlatformHandler], history_id: int
) -> Assertion[object]:
    """The entry the platform was actually returned to.

    Read from the platform rather than from the descriptor, for the reason the
    restart is: what Argus says it did and what the world received are the two
    things worth keeping apart.
    """
    def assertion(dont_care_result: object) -> bool:
        if history_id not in handler.rolled_back_to:
            raise AssertionError(
                f"Expected the platform to be rolled back to history entry "
                f"[{history_id}], and it was asked for "
                f"{handler.rolled_back_to}."
            )

        return True

    return assertion


def the_descriptor_records_what_it_came_from(
    history_id: int, revision: str, was_syncing_itself: bool
) -> Assertion[DeploymentRollbackUndo]:
    """Both pieces of prior state, carried back through the round trip.

    The descriptor is the only record of what a rollback cost, and it has to
    survive serialisation to be worth anything: a withdrawal reads it back
    hours later, and a field lost in transit is a change nobody can put back.
    """
    def assertion(descriptor: DeploymentRollbackUndo) -> bool:
        if descriptor.was_on_history_id != history_id:
            raise AssertionError(
                f"Expected the descriptor to record coming from history entry "
                f"[{history_id}], and it records "
                f"[{descriptor.was_on_history_id}]."
            )

        if descriptor.was_on_revision != revision:
            raise AssertionError(
                f"Expected the descriptor to record the revision [{revision}], "
                f"and it records [{descriptor.was_on_revision}]."
            )

        if descriptor.was_syncing_itself is not was_syncing_itself:
            raise AssertionError(
                f"Expected the descriptor to record that the platform was "
                f"syncing itself [{was_syncing_itself}], and it records "
                f"[{descriptor.was_syncing_itself}] - so a withdrawal would "
                f"leave reconciliation as Argus left it."
            )

        return True

    return assertion


def both_halves_were_put_back() -> Assertion[DeploymentRestored]:
    """A restore that managed one of the two is not a restore.

    Reported as two flags rather than one answer because the half that fails is
    the quiet one, and a caller has to be able to say which is still changed.
    """
    def assertion(restored: DeploymentRestored) -> bool:
        if not (restored.revision_put_back and restored.automated_sync_put_back):
            raise AssertionError(
                f"Expected both the revision and the sync policy to be put "
                f"back, and the tier reported revision_put_back="
                f"[{restored.revision_put_back}] automated_sync_put_back="
                f"[{restored.automated_sync_put_back}]."
            )

        return True

    return assertion


def the_platform_is_reconciling_itself_again(
    handler: type[FakeDeploymentPlatformHandler]
) -> Assertion[object]:
    """The arrangement Argus found, put back as it found it.

    Asserted on the platform's own state rather than on what was written to it,
    because the thing that matters is that the deployment receives what people
    ship to it again - not that a request was made.
    """
    def assertion(dont_care_result: object) -> bool:
        if not handler.syncs_itself:
            raise AssertionError(
                "Expected the platform to be reconciling the application "
                "itself again, and it is still suspended - so the deployment "
                "silently receives nothing anybody ships to it."
            )

        return True

    return assertion
