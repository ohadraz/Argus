from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Any, NamedTuple
from unittest.mock import create_autospec

import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting, calling
from core import Fence, Holding, RunLost, WriteMcpEndpoint, get_settings, parse_iso, to_iso
from core.mcp_transport import (
    Asking,
    ChangedSince,
    McpClient,
    McpToolError,
    PlatformUnreachable,
)
from core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    AutoscalerUndo,
    ChangeFound,
    DeploymentRestored,
    DeploymentRollbackUndo,
    FlagChange,
    FlagUndo,
    Made,
    NotMade,
    Planned,
    ReplicaUndo,
    RestartedService,
    UndoDescriptor,
)
from deployment_platform.argocd import AUTOMATED, ENABLED
from write_mcp_client import (
    accelerator_pin_still_argus_s,
    autoscaler_pin_still_argus_s,
    commit_to_new_branch,
    discard_cache_entries,
    flag_still_argus_s,
    get_recent_flag_changes,
    open_pull_request,
    pin_autoscaler,
    pin_to_accelerator,
    plan_accelerator_pin,
    plan_autoscaler_pin,
    plan_flag,
    plan_rollback,
    plan_scale_out,
    restart_service,
    restore_accelerator_pin,
    restore_autoscaler_floor,
    restore_deployment,
    restore_replica_count,
    roll_back_deployment,
    rollback_still_argus_s,
    scale_out,
    scale_out_still_argus_s,
    set_feature_flag,
    was_flag_changed_by_others_since,
    whether_accelerator_pin_was_made,
    whether_autoscaler_pin_was_made,
    whether_flag_was_made,
    whether_rollback_was_made,
    whether_scale_out_was_made,
    write_mcp,
)

from write_mcp_client_test.a_write_server_holding_one_run import THE_RUN_HELD
from write_mcp_client_test.fake_deployment_platform import (
    THE_AUTOSCALER_CEILING,
    THE_AUTOSCALER_FLOOR,
    THE_COUNT_RUNNING,
    THE_HISTORY_BEFORE_IT,
    THE_HISTORY_RUNNING_NOW,
    THE_PLATFORM_S_TIME,
    THE_REVISION_BEFORE_IT,
    THE_REVISION_RUNNING_NOW,
    FakeDeploymentPlatformHandler,
    a_running_platform,
)
from write_mcp_client_test.fake_feature_flag_provider import (
    THE_ARGUS_ACTOR,
    THE_ENVIRONMENT,
    THE_PROVIDER_S_TIME,
    FakeUnleashHandler,
    a_running_write_mcp,
)

SINCE = "2026-08-20T11:00:00Z"
INSIDE_THE_WINDOW = "2026-08-20T11:04:38.033Z"
DONT_CARE_ACTOR = "dont-care-actor"
SOME_HUMAN = "admin"
SOME_APPLICATION = "io-shop"
SOME_CARD = "Tesla-V100-SXM2-16GB"
SOME_FLAG = "monthly-spend-feature"
# The action row a walk's platform writes are made for.
SOME_ACTION_ID = "6f1c1d2e-0000-4000-8000-0000000000a1"
# Where the mark lands on what the platform was asked to write. Spelled out
# rather than imported: the wire shape is the adapter's suite's to pin, and this
# one asserts the action travelled the whole way to it.
THE_ACTION_ANNOTATION = "argus/action"

# Somebody who deployed after Argus rolled back, and the revision they deployed.
SOME_PERSON_DEPLOYING = "alice"
A_REVISION_SOMEBODY_DEPLOYED = "9b2c4e1f0a7d8c6b5e4f3a2d1c0b9a8f7e6d5c4b"

# A moment after each party's clock stands, which is where a change somebody
# made since a plan is recorded.
AFTER_THE_PLATFORM_S_PLAN = THE_PLATFORM_S_TIME + timedelta(minutes=30)
AFTER_THE_PROVIDER_S_PLAN = THE_PROVIDER_S_TIME + timedelta(minutes=1)

# The rollback the platform's history plans: from the entry running back to the
# one before it, from a platform reconciling the application itself.
THE_ROLLBACK_PLANNED = DeploymentRollbackUndo(
    application=SOME_APPLICATION,
    was_on_history_id=THE_HISTORY_RUNNING_NOW,
    was_on_revision=THE_REVISION_RUNNING_NOW,
    rolled_back_to_revision=THE_REVISION_BEFORE_IT,
    rolled_back_to_history_id=THE_HISTORY_BEFORE_IT,
    was_syncing_itself=True
)
# Twice the count running, under the most replicas Argus may ask for.
THE_SCALE_OUT_PLANNED = ReplicaUndo(
    application=SOME_APPLICATION,
    was_replicas=THE_COUNT_RUNNING,
    replicas_asked_for=2 * THE_COUNT_RUNNING,
    was_syncing_itself=True
)
# The floor raised to the ceiling, which is under the most Argus may ask for.
THE_AUTOSCALER_PIN_PLANNED = AutoscalerUndo(
    application=SOME_APPLICATION,
    was_min_replicas=THE_AUTOSCALER_FLOOR,
    min_replicas_asked_for=THE_AUTOSCALER_CEILING,
    was_syncing_itself=True
)
# From a Deployment held to no card.
THE_ACCELERATOR_PIN_PLANNED = AcceleratorPinUndo(
    application=SOME_APPLICATION,
    was_pinned_to=None,
    pinned_to=SOME_CARD,
    was_syncing_itself=True
)

# Every plan the platform answers, what it is asked with, whether the case needs
# an autoscaler staged beside the Deployment, and the change it plans.
EVERY_PLATFORM_PLAN = [
    pytest.param(lambda client: plan_rollback(SOME_APPLICATION, client=client),
                 False, THE_ROLLBACK_PLANNED, id="rollback"),
    pytest.param(lambda client: plan_scale_out(SOME_APPLICATION, client=client),
                 False, THE_SCALE_OUT_PLANNED, id="scale-out"),
    pytest.param(lambda client: plan_autoscaler_pin(SOME_APPLICATION, client=client),
                 True, THE_AUTOSCALER_PIN_PLANNED, id="autoscaler-pin"),
    pytest.param(lambda client: plan_accelerator_pin(SOME_APPLICATION, SOME_CARD, client=client),
                 False, THE_ACCELERATOR_PIN_PLANNED, id="accelerator-pin")
]

# A claim of the server's run from before it was last taken back.
A_CLAIM_THE_RUN_MOVED_PAST = Fence(run_id=THE_RUN_HELD.run_id, epoch=THE_RUN_HELD.epoch - 1)

# A plan and a descriptor nothing in a case reads, for the cases about how a
# write is asked rather than what it writes.
DONT_CARE_PLANNED_FLAG = Planned(descriptor=FlagUndo(flag=SOME_FLAG, was_enabled=True),
                                 since=THE_PROVIDER_S_TIME)
DONT_CARE_SERVICE = "dont-care-service"
DONT_CARE_CACHE_KEY = "dont-care:cache:key"
DONT_CARE_BRANCH = "argus/dont-care"
DONT_CARE_BASE = "main"
DONT_CARE_TEXT = "dont care"

# Where a write tier is, waiting for its answers a bound that is not the one
# the settings default to - so a client built waiting it waited for what its
# endpoint said, and not for a figure of its own.
SOME_ANSWER_BOUND = 690.0
DONT_CARE_HOST = "dont-care-host"
DONT_CARE_PORT = 8199
DONT_CARE_URL = "http://dont-care-host:8199"
AN_ENDPOINT_WAITING_SOME_BOUND = WriteMcpEndpoint(
    write_mcp_host=DONT_CARE_HOST,
    write_mcp_port=DONT_CARE_PORT,
    write_mcp_url=DONT_CARE_URL,
    write_mcp_answered_within_seconds=SOME_ANSWER_BOUND
)

# A flag switched off from on, as the provider records it once it has the
# change under the name Argus writes as: after the plan's read.
THE_FLAG_SET_AND_ASKED_AGAIN = FlagUndo(flag=SOME_FLAG, was_enabled=True,
                                        written_at=AFTER_THE_PROVIDER_S_PLAN)

# The two writes a second asking would make twice: neither leaves a mark a
# second asking could find. A restart is Argo CD's own resource action, and a
# discard removes what it names.
EVERY_WRITE_NOT_TO_BE_ASKED_TWICE = [
    pytest.param(lambda client: restart_service(DONT_CARE_SERVICE, client=client),
                 id="restart"),
    pytest.param(lambda client: discard_cache_entries([DONT_CARE_CACHE_KEY], client=client),
                 id="discard")
]
# Every other write: each finds its own mark at its target, or what it wrote,
# and answers a second asking as made.
EVERY_WRITE_ASKED_AGAIN_AS_MADE = [
    pytest.param(lambda client: set_feature_flag(
        DONT_CARE_PLANNED_FLAG, not DONT_CARE_PLANNED_FLAG.descriptor.was_enabled, client=client),
                 id="flag"),
    pytest.param(lambda client: roll_back_deployment(
        Planned(descriptor=THE_ROLLBACK_PLANNED, since=THE_PLATFORM_S_TIME), client=client),
                 id="rollback"),
    pytest.param(lambda client: restore_deployment(THE_ROLLBACK_PLANNED, client=client),
                 id="rollback-put-back"),
    pytest.param(lambda client: scale_out(
        Planned(descriptor=THE_SCALE_OUT_PLANNED, since=THE_PLATFORM_S_TIME), client=client),
                 id="scale-out"),
    pytest.param(lambda client: restore_replica_count(THE_SCALE_OUT_PLANNED, client=client),
                 id="scale-out-put-back"),
    pytest.param(lambda client: pin_autoscaler(
        Planned(descriptor=THE_AUTOSCALER_PIN_PLANNED, since=THE_PLATFORM_S_TIME),
        client=client),
                 id="autoscaler-pin"),
    pytest.param(lambda client: restore_autoscaler_floor(THE_AUTOSCALER_PIN_PLANNED,
                                                         client=client),
                 id="autoscaler-pin-put-back"),
    pytest.param(lambda client: pin_to_accelerator(
        Planned(descriptor=THE_ACCELERATOR_PIN_PLANNED, since=THE_PLATFORM_S_TIME),
        client=client),
                 id="accelerator-pin"),
    pytest.param(lambda client: restore_accelerator_pin(THE_ACCELERATOR_PIN_PLANNED,
                                                        client=client),
                 id="accelerator-pin-put-back"),
    pytest.param(lambda client: commit_to_new_branch(
        DONT_CARE_BRANCH, DONT_CARE_BASE, {DONT_CARE_TEXT: DONT_CARE_TEXT}, DONT_CARE_TEXT,
        client=client),
                 id="branch"),
    pytest.param(lambda client: open_pull_request(
        DONT_CARE_BRANCH, DONT_CARE_BASE, DONT_CARE_TEXT, DONT_CARE_TEXT, client=client),
                 id="pull-request")
]

# Every read the write tier serves: the plans, whether a claim's change was
# made, whether a change made is still Argus's, and the flag provider's log.
DONT_CARE_PLANNED_ROLLBACK = Planned(descriptor=THE_ROLLBACK_PLANNED, since=THE_PLATFORM_S_TIME)
DONT_CARE_PLANNED_SCALE_OUT = Planned(descriptor=THE_SCALE_OUT_PLANNED,
                                      since=THE_PLATFORM_S_TIME)
DONT_CARE_PLANNED_AUTOSCALER_PIN = Planned(descriptor=THE_AUTOSCALER_PIN_PLANNED,
                                           since=THE_PLATFORM_S_TIME)
DONT_CARE_PLANNED_ACCELERATOR_PIN = Planned(descriptor=THE_ACCELERATOR_PIN_PLANNED,
                                            since=THE_PLATFORM_S_TIME)
EVERY_READ_OF_THE_WRITE_TIER = [
    pytest.param(lambda client: plan_flag(SOME_FLAG, False, client=client), id="plan-flag"),
    pytest.param(lambda client: plan_rollback(SOME_APPLICATION, client=client),
                 id="plan-rollback"),
    pytest.param(lambda client: plan_scale_out(SOME_APPLICATION, client=client),
                 id="plan-scale-out"),
    pytest.param(lambda client: plan_autoscaler_pin(SOME_APPLICATION, client=client),
                 id="plan-autoscaler-pin"),
    pytest.param(lambda client: plan_accelerator_pin(SOME_APPLICATION, SOME_CARD,
                                                     client=client),
                 id="plan-accelerator-pin"),
    pytest.param(lambda client: whether_flag_was_made(DONT_CARE_PLANNED_FLAG, client=client),
                 id="whether-flag-was-made"),
    pytest.param(lambda client: whether_rollback_was_made(DONT_CARE_PLANNED_ROLLBACK,
                                                          client=client),
                 id="whether-rollback-was-made"),
    pytest.param(lambda client: whether_scale_out_was_made(DONT_CARE_PLANNED_SCALE_OUT,
                                                           client=client),
                 id="whether-scale-out-was-made"),
    pytest.param(lambda client: whether_autoscaler_pin_was_made(
        DONT_CARE_PLANNED_AUTOSCALER_PIN, client=client), id="whether-autoscaler-pin-was-made"),
    pytest.param(lambda client: whether_accelerator_pin_was_made(
        DONT_CARE_PLANNED_ACCELERATOR_PIN, client=client), id="whether-accelerator-pin-was-made"),
    pytest.param(lambda client: flag_still_argus_s(
        DONT_CARE_PLANNED_FLAG, DONT_CARE_PLANNED_FLAG.descriptor, client=client),
                 id="flag-still-argus-s"),
    pytest.param(lambda client: rollback_still_argus_s(THE_ROLLBACK_PLANNED, client=client),
                 id="rollback-still-argus-s"),
    pytest.param(lambda client: scale_out_still_argus_s(THE_SCALE_OUT_PLANNED, client=client),
                 id="scale-out-still-argus-s"),
    pytest.param(lambda client: autoscaler_pin_still_argus_s(THE_AUTOSCALER_PIN_PLANNED,
                                                             client=client),
                 id="autoscaler-pin-still-argus-s"),
    pytest.param(lambda client: accelerator_pin_still_argus_s(THE_ACCELERATOR_PIN_PLANNED,
                                                              client=client),
                 id="accelerator-pin-still-argus-s"),
    pytest.param(lambda client: get_recent_flag_changes(SINCE, client=client),
                 id="recent-flag-changes"),
    pytest.param(lambda client: was_flag_changed_by_others_since(
        SOME_FLAG, THE_PROVIDER_S_TIME, client=client), id="flag-changed-by-others")
]

# Every platform write a second asking answers as made, how it is planned,
# whether the case needs an autoscaler staged beside the Deployment, and the
# change it plans.
EVERY_PLATFORM_WRITE_ASKED_AGAIN = [
    pytest.param(lambda client: plan_rollback(SOME_APPLICATION, client=client),
                 lambda planned, client: roll_back_deployment(planned, client=client),
                 False, THE_ROLLBACK_PLANNED, id="rollback"),
    pytest.param(lambda client: plan_scale_out(SOME_APPLICATION, client=client),
                 lambda planned, client: scale_out(planned, client=client),
                 False, THE_SCALE_OUT_PLANNED, id="scale-out"),
    pytest.param(lambda client: plan_autoscaler_pin(SOME_APPLICATION, client=client),
                 lambda planned, client: pin_autoscaler(planned, client=client),
                 True, THE_AUTOSCALER_PIN_PLANNED, id="autoscaler-pin"),
    pytest.param(lambda client: plan_accelerator_pin(SOME_APPLICATION, SOME_CARD, client=client),
                 lambda planned, client: pin_to_accelerator(planned, client=client),
                 False, THE_ACCELERATOR_PIN_PLANNED, id="accelerator-pin")
]


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
def test_a_flag_s_plan_survives_the_wire_and_changes_nothing(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Asked holding no run, because the walk plans before it claims. What comes
    # back is the plan whole: what the flag was found in, and the provider's own
    # time for the read - a moment a resumed walk later asks the history from.
    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, SOME_FLAG))
        ) \
        .when(
            _asking_the_server_as(None, lambda client: plan_flag(
                SOME_FLAG, enabled=False, client=client
            ))
        ) \
        .then(all_of(
            _the_plan_is(FlagUndo(flag=SOME_FLAG, was_enabled=True), THE_PROVIDER_S_TIME),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
        ))


@pytest.mark.integration
def test_switching_a_flag_off_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The whole path in two calls: the typed client, a real MCP round trip for
    # the plan and another for the change made from it, the tool, the admin
    # adapter, and the provider's own wire shape - with only the provider at the
    # far end faked. And the assertion is on the provider's state, not on what
    # the client said: an action Argus reports taking and did not take is the
    # failure that matters.
    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, SOME_FLAG))
        ) \
        .when(
            _asking_the_server(lambda client: _setting(SOME_FLAG, False, client))
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
    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp))
        ) \
        .when(
            _asking_the_server(lambda client: _setting(SOME_FLAG, True, client))
        ) \
        .then(all_of(
            the_undo_descriptor_says_it_had_been(enabled=False),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG]),
        ))


@pytest.mark.integration
def test_a_flag_somebody_changed_since_its_plan_arrives_as_changed_since_and_is_left_as_set(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Somebody switched it off and back on after the plan read it: the value
    # is what the plan found, and only the history says a person is acting on
    # it. The refusal reaches the walk as its own type - the walk escalates on
    # it rather than act beside them - saying it left nothing, and the flag is
    # as they left it.
    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, SOME_FLAG))
        ) \
        .when(attempting(
            _asking_the_server(lambda client: _planned_and_then_toggled_by_somebody(
                running_write_mcp, client
            ))
        )) \
        .then(all_of(
            an_error_was_raised(ChangedSince),
            _it_left_behind(None),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
        ))


@pytest.mark.integration
def test_reading_flag_changes_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Asked holding no run, because a read changes nothing a stale walk could
    # get wrong, and is answered without asking after any run.
    Scenario() \
        .given(
            calling(the_provider_recorded(
                running_write_mcp,
                [a_disabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW)],
            ))
        ) \
        .when(
            _asking_the_server_as(
                None, lambda client: get_recent_flag_changes(SINCE, client=client)
            )
        ) \
        .then(
            the_changes_are([(SOME_FLAG, False)])
        )


@pytest.mark.integration
def test_asking_whether_others_changed_a_flag_reaches_the_provider_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The question an undo asks before it writes: the typed client, a real MCP
    # round trip, the tool, the provider's own log and the name the server was
    # told Argus writes under. Asked holding no run, as a read is.
    Scenario() \
        .given(
            calling(the_provider_recorded(
                running_write_mcp,
                [a_disabling_of(SOME_FLAG, at=INSIDE_THE_WINDOW, by=SOME_HUMAN)]
            ))
        ) \
        .when(
            _asking_the_server_as(None, lambda client: was_flag_changed_by_others_since(
                SOME_FLAG, parse_iso(SINCE), client=client
            ))
        ) \
        .then(
            _the_answer_is(True)
        )


def _the_answer_is(expected: bool | None) -> Assertion[bool | None]:
    """`is` rather than `==`: `None` and `False` are the whole distinction here."""
    def assertion(answer: bool | None) -> bool:
        if answer is not expected:
            raise AssertionError(f"Expected the answer [{expected}], got [{answer}].")

        return True

    return assertion


@pytest.mark.integration
def test_a_change_the_client_made_can_be_undone_through_the_same_calls(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Undoing a refuted mitigation is the same plan and the same write with the
    # state reversed, which is the only reason one tool serves both directions.
    # If the round trip only worked one way, a refuted action could not be put
    # back.
    #
    # Every call goes over one session, which is how the walk makes them: an
    # action and the undo that follows it are calls by one worker, and a session
    # good for only the first would leave a refuted flag where it was.
    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, SOME_FLAG))
        ) \
        .when(
            _asking_the_server(lambda client: _undoing(
                _setting(SOME_FLAG, False, client), SOME_FLAG, client
            ))
        ) \
        .then(
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
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
@pytest.mark.parametrize(("ask", "with_an_autoscaler", "planned"), EVERY_PLATFORM_PLAN)
def test_a_platform_plan_survives_the_wire_and_changes_nothing(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler],
    ask: Callable[[McpClient], Planned[Any]],
    with_an_autoscaler: bool,
    planned: UndoDescriptor
) -> None:
    # Asked holding no run, because the walk plans before it claims. What comes
    # back is the plan whole - a descriptor of the action's own kind, every
    # field of it - dated by the platform's own clock: the moment a resumed walk
    # later asks whether anything landed after.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            calling(_an_autoscaler_staged_on(handler, with_an_autoscaler))
        ) \
        .when(
            _asking_the_server_as(None, ask)
        ) \
        .then(all_of(
            _the_plan_is(planned, THE_PLATFORM_S_TIME),
            _nothing_was_written_to(handler)
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
            _asking_the_server(_rolling_back)
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
            ),
            _the_descriptor_records_it_went_to(THE_REVISION_BEFORE_IT)
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
                _rolling_back(client), client=client
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


@pytest.mark.integration
def test_a_rollback_somebody_deployed_over_is_left_as_they_set_it_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The whole path of the question a put-back asks before it writes: the
    # history and the images read through the adapter, against the account the
    # server was told Argus signs in as. A person deployed after Argus's
    # rollback, so neither the revision nor the sync is touched, the
    # suspension Argus made is said to stand, and the answer says what was
    # found.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .when(
            _asking_the_server(lambda client: restore_deployment(
                _rolled_back_and_then_deployed_over(handler, client),
                client=client
            ))
        ) \
        .then(all_of(
            _it_was_left_as_somebody_set_it(mentioning=A_REVISION_SOMEBODY_DEPLOYED),
            _the_platform_was_not_rolled_back_again(handler),
            the_platform_stopped_reconciling(handler)
        ))


@pytest.mark.integration
def test_a_rollback_somebody_deployed_over_since_its_plan_arrives_as_changed_since(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # This action's earlier asking suspended the sync and its answer was lost;
    # somebody has deployed since the plan. The rollback is not made over them,
    # and the refusal reaches the walk as its own type carrying the suspension
    # this action's mark shows landed - the one change of Argus's out there,
    # recorded nowhere else - and saying that is all of it.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .when(attempting(
            _asking_the_server(lambda client: _planned_and_then_deployed_over_after_a_suspension(
                handler, client
            ))
        )) \
        .then(all_of(
            an_error_was_raised(ChangedSince),
            _it_left_behind(THE_ROLLBACK_PLANNED),
            _the_platform_was_never_rolled_back(handler)
        ))


@pytest.mark.integration
def test_an_unreachable_platform_arrives_as_its_own_type_through_the_client(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The whole of what the typed client owes this change, which is nothing. The
    # marker is recognised once, where a tool's reported error becomes an
    # exception, so by the time the call returns here the type is already right
    # and the client has only to stay out of the way. A client that re-read the
    # failure to classify it would be a second reading of the same field, and
    # this test fails the day one is added - it catches the type, and a re-wrap
    # into anything else does not satisfy it.
    running_write_mcp_over_a_platform.unavailable = True

    Scenario() \
        .when(
            attempting(
                _asking_the_server(_rolling_back)
            )
        ) \
        .then(all_of(_it_came_back_as_an_unreachable_platform()))


@pytest.mark.integration
def test_scaling_out_from_its_plan_reaches_the_platform_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The count the plan asked for is the count the platform's Deployment now
    # declares, and reconciliation was suspended first - a count left under
    # automated sync is put straight back by the next sync.
    Scenario() \
        .when(
            _asking_the_server(lambda client: scale_out(
                plan_scale_out(SOME_APPLICATION, client=client), client=client
            ))
        ) \
        .then(all_of(
            _the_platform_runs(running_write_mcp_over_a_platform,
                               THE_SCALE_OUT_PLANNED.replicas_asked_for),
            the_platform_stopped_reconciling(running_write_mcp_over_a_platform),
            _it_answered_as(THE_SCALE_OUT_PLANNED)
        ))


@pytest.mark.integration
def test_pinning_an_autoscaler_from_its_plan_reaches_the_platform_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The floor the plan raised to is the floor the platform's autoscaler now
    # declares, and reconciliation was suspended first - a floor left under
    # automated sync is put back by the next sync.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            calling(_an_autoscaler_staged_on(handler, True))
        ) \
        .when(
            _asking_the_server(lambda client: pin_autoscaler(
                plan_autoscaler_pin(SOME_APPLICATION, client=client), client=client
            ))
        ) \
        .then(all_of(
            _the_autoscaler_s_floor_is(handler, THE_AUTOSCALER_PIN_PLANNED.min_replicas_asked_for),
            the_platform_stopped_reconciling(handler),
            _it_answered_as(THE_AUTOSCALER_PIN_PLANNED)
        ))


@pytest.mark.integration
def test_pinning_to_a_card_reaches_the_platform_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The one action whose subject arrives from the caller: which card to hold
    # the pods to was worked out from a placement this tier never saw. So what is
    # asserted is that the card named here is the card the platform now selects,
    # and that reconciliation was suspended first - a pin left under automated
    # sync is taken off by the next sync.
    Scenario() \
        .when(
            _asking_the_server(lambda client: _pinning_to(SOME_CARD, client))
        ) \
        .then(all_of(
            _the_platform_selects(running_write_mcp_over_a_platform, SOME_CARD),
            the_platform_stopped_reconciling(running_write_mcp_over_a_platform),
            _it_answered_as(THE_ACCELERATOR_PIN_PLANNED)
        ))


@pytest.mark.integration
def test_restoring_a_pin_reaches_the_platform_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # Driven from a real pin rather than a descriptor written here, for the
    # rollback's reason. And from a deployment that was held to no card, which
    # is the case that matters: "there was none" crosses the wire as a null,
    # and a restore that read it as "nothing recorded" would leave the pin on.
    Scenario() \
        .when(
            _asking_the_server(lambda client: restore_accelerator_pin(
                _pinning_to(SOME_CARD, client), client=client
            ))
        ) \
        .then(all_of(
            _both_halves_of_the_pin_were_put_back(),
            _the_platform_selects(running_write_mcp_over_a_platform, None),
            the_platform_is_reconciling_itself_again(
                running_write_mcp_over_a_platform
            )
        ))


@pytest.mark.integration
def test_a_platform_write_carries_the_action_it_was_made_for_to_the_platform(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The whole path the mark travels: the action the walk acts for, into the
    # call's `_meta` by the client, out of it by the tool, and onto the object
    # the platform was asked to write. Read off the suspension, which is the
    # rollback's own merge patch and so what the platform keeps.
    Scenario() \
        .when(
            _asking_the_server(_rolling_back)
        ) \
        .then(
            _every_sync_patch_was_for(running_write_mcp_over_a_platform, SOME_ACTION_ID)
        )


@pytest.mark.integration
def test_a_platform_write_made_while_no_action_is_taken_is_refused_and_changes_nothing(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # Made, it would be a write on the platform nobody could tell from a
    # person's. Refused as an ordinary refusal - the run is still held, so not a
    # lost one - and before anything was asked to change. The plan before it is
    # a read, and is answered.
    Scenario() \
        .when(attempting(
            _asking_the_server_as(THE_RUN_HELD, _rolling_back)
        )) \
        .then(all_of(
            an_error_was_raised(McpToolError),
            _it_did_not_come_back_as(RunLost),
            _it_did_not_come_back_as(ChangedSince),
            _the_sync_policy_was_never_patched(running_write_mcp_over_a_platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("asking", EVERY_WRITE_NOT_TO_BE_ASKED_TWICE)
def test_a_write_a_second_asking_would_make_twice_is_asked_not_to_be_asked_again(
    asking: Callable[[McpClient], object]
) -> None:
    # The transport asks a call once more over a new session where the first
    # got no answer. For a restart, that is a second restart: so this write
    # says it is not to be asked again, and a lost answer reaches the walk as
    # lost rather than as a service restarted twice.
    Scenario() \
        .given(
            client := _a_client_answering_anything()
        ) \
        .when(
            attempting(lambda: asking(client))
        ) \
        .then(
            _it_was_asked(client, kind=Asking.CHANGE_ASKED_ONCE)
        )


@pytest.mark.unit
@pytest.mark.parametrize("asking", EVERY_WRITE_ASKED_AGAIN_AS_MADE)
def test_a_write_a_second_asking_answers_as_made_is_left_to_be_asked_again(
    asking: Callable[[McpClient], object]
) -> None:
    # The other half: a write whose second asking finds what the first made is
    # how a lost answer is recovered, and marking it not to be asked again
    # would hand an incident to a person over a change that is known.
    Scenario() \
        .given(
            client := _a_client_answering_anything()
        ) \
        .when(
            attempting(lambda: asking(client))
        ) \
        .then(
            _it_was_asked(client, kind=Asking.CHANGE)
        )


@pytest.mark.unit
@pytest.mark.parametrize("asking", EVERY_READ_OF_THE_WRITE_TIER)
def test_a_read_of_the_write_tier_is_asked_as_a_read(
    asking: Callable[[McpClient], object]
) -> None:
    # A plan, whether a claim's change was made, whether a change is still
    # Argus's: none changes anything, so a lost answer is no change nobody can
    # account for - asked again, and failing as that asking failed.
    Scenario() \
        .given(
            client := _a_client_answering_anything()
        ) \
        .when(
            attempting(lambda: asking(client))
        ) \
        .then(
            _it_was_asked(client, kind=Asking.READ)
        )


@pytest.mark.unit
def test_a_write_client_waits_for_an_answer_as_long_as_its_endpoint_says() -> None:
    # Above the slowest tool this tier serves, a restart: waited for less, a
    # restart still being made is handed to a person as lost. The figure is the
    # endpoint's, which the settings give it, and not one the client keeps.
    Scenario() \
        .given(
            builds := create_autospec(McpClient)
        ) \
        .when(
            lambda: write_mcp(AN_ENDPOINT_WAITING_SOME_BOUND, builds_client=builds)
        ) \
        .then(
            _it_was_built_waiting(builds, SOME_ANSWER_BOUND)
        )


@pytest.mark.integration
@pytest.mark.parametrize(("plan", "write", "with_an_autoscaler", "planned"),
                         EVERY_PLATFORM_WRITE_ASKED_AGAIN)
def test_a_platform_write_asked_again_for_the_same_action_is_answered_as_made_and_writes_nothing(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler],
    plan: Callable[[McpClient], Planned[Any]],
    write: Callable[[Planned[Any], McpClient], UndoDescriptor],
    with_an_autoscaler: bool,
    planned: UndoDescriptor
) -> None:
    # What the transport's second asking of a write is, as the tier hears it:
    # the same tool, the same plan, under the same action. The first asking
    # landed; the second finds the change at its target under this action's
    # mark and answers as made, writing nothing - so asking again is how a lost
    # answer is recovered, never how a change is made twice.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            calling(_an_autoscaler_staged_on(handler, with_an_autoscaler))
        ) \
        .when(
            _asking_the_server(_asked_twice(handler, plan, write))
        ) \
        .then(all_of(
            _answered_again_as(planned),
            _the_second_asking_wrote_nothing()
        ))


@pytest.mark.integration
def test_a_flag_set_asked_again_for_the_same_action_is_answered_as_made(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The flag's second asking, once the provider has recorded the first under
    # the name Argus writes as - which the stand-in leaves the case to stage, as
    # a real provider records it. Answered as made, dated by that record rather
    # than by a write of its own: the provider's clock stands still at the
    # moment a write would be dated.
    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, SOME_FLAG))
        ) \
        .when(
            _asking_the_server(lambda client: _set_and_asked_again(
                running_write_mcp, THE_FLAG_SET_AND_ASKED_AGAIN, client
            ))
        ) \
        .then(all_of(
            _answered_as_exactly(THE_FLAG_SET_AND_ASKED_AGAIN),
            the_provider_now_reports_enabled(running_write_mcp, [])
        ))


def _it_came_back_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, PlatformUnreachable):
            raise AssertionError(
                f"Expected the call to raise an unreachable platform, and what "
                f"was raised was {raised!r}."
            )

        return True

    return assertion


@pytest.mark.integration
def test_a_change_for_a_claim_the_run_moved_past_arrives_as_a_lost_run_and_changes_nothing(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The walk that made it stops writing on `RunLost`, so the tier's refusal
    # has to reach it as that and not as a tool that broke - and the flag has to
    # be where it was, or a second walk changed the world for somebody else's
    # incident. The plan is a read, and is answered whoever asks.
    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, SOME_FLAG))
        ) \
        .when(attempting(
            _asking_the_server_as(A_CLAIM_THE_RUN_MOVED_PAST,
                                  lambda client: _setting(SOME_FLAG, False, client))
        )) \
        .then(all_of(
            an_error_was_raised(RunLost),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
        ))


@pytest.mark.integration
def test_a_change_made_while_no_run_is_held_is_refused_and_changes_nothing(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # A caller that forgot to say which claim it acts for is a bug, not a walk
    # that lost its run - so it is an ordinary refusal that says it left nothing.
    Scenario() \
        .given(
            calling(the_provider_has_enabled(running_write_mcp, SOME_FLAG))
        ) \
        .when(attempting(
            _asking_the_server_as(None, lambda client: _setting(SOME_FLAG, False, client))
        )) \
        .then(all_of(
            an_error_was_raised(McpToolError),
            _it_did_not_come_back_as(RunLost),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
        ))


def _setting(flag: str, enabled: bool, client: McpClient) -> UndoDescriptor:
    """`flag` planned and then set to `enabled` from its plan, as the walk
    makes a change: two calls over one session."""
    return set_feature_flag(plan_flag(flag, enabled, client=client), enabled, client=client)


def _undoing(undo_descriptor: UndoDescriptor,
             flag: str,
             client: McpClient) -> UndoDescriptor:
    assert isinstance(undo_descriptor, FlagUndo)

    return _setting(flag, undo_descriptor.was_enabled, client)


def _planned_and_then_toggled_by_somebody(handler: type[FakeUnleashHandler],
                                          client: McpClient) -> UndoDescriptor:
    """The flag planned to go off, then switched off and back on by somebody
    after the plan's read - the provider's history says so, its state does not
    - then set from the plan."""
    planned = plan_flag(SOME_FLAG, False, client=client)
    handler.events = [
        a_disabling_of(SOME_FLAG, at=to_iso(AFTER_THE_PROVIDER_S_PLAN), by=SOME_HUMAN),
        an_enabling_of(SOME_FLAG, at=to_iso(AFTER_THE_PROVIDER_S_PLAN), by=SOME_HUMAN)
    ]

    return set_feature_flag(planned, False, client=client)


def _rolling_back(client: McpClient) -> DeploymentRollbackUndo:
    """`SOME_APPLICATION` planned and then rolled back from its plan, as the
    walk makes a change: two calls over one session."""
    return roll_back_deployment(plan_rollback(SOME_APPLICATION, client=client), client=client)


def _pinning_to(card: str, client: McpClient) -> AcceleratorPinUndo:
    """`SOME_APPLICATION` planned and then pinned to `card` from its plan."""
    return pin_to_accelerator(plan_accelerator_pin(SOME_APPLICATION, card, client=client),
                              client=client)


def _planned_and_then_deployed_over_after_a_suspension(
    handler: type[FakeDeploymentPlatformHandler], client: McpClient
) -> DeploymentRollbackUndo:
    """The rollback planned; then the sync off under this action's own mark, as
    an earlier asking whose answer was lost left it, and a deployment of
    somebody else's recorded after the plan; then the rollback asked again from
    the plan."""
    planned = plan_rollback(SOME_APPLICATION, client=client)
    handler.sync_policy = {AUTOMATED: {"selfHeal": True, ENABLED: False}}
    handler.syncs_itself = False
    handler.application_annotations = {THE_ACTION_ANNOTATION: SOME_ACTION_ID}
    handler.history = handler.history + [{
        "id": handler.history[-1]["id"] + 1,
        "revision": A_REVISION_SOMEBODY_DEPLOYED,
        "deployedAt": to_iso(AFTER_THE_PLATFORM_S_PLAN),
        "initiatedBy": {"username": SOME_PERSON_DEPLOYING}
    }]

    return roll_back_deployment(planned, client=client)


def _an_autoscaler_staged_on(handler: type[FakeDeploymentPlatformHandler],
                             staged: bool) -> Callable[[], None]:
    """An autoscaler beside the Deployment at its declared floor, where
    `staged` - and none, as the platform starts, where not."""
    def step() -> None:
        handler.autoscaler_floor = THE_AUTOSCALER_FLOOR if staged else None

    return step


def _every_sync_patch_was_for(handler: type[FakeDeploymentPlatformHandler],
                              action_id: str) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        marked = [
            patch.get("metadata", {}).get("annotations", {}).get(THE_ACTION_ANNOTATION)
            for patch in handler.sync_patches_received
        ]

        if not marked or any(each != action_id for each in marked):
            raise AssertionError(
                f"Expected every sync patch marked as made for [{action_id}], got the "
                f"marks {marked}."
            )

        return True

    return assertion


def _the_sync_policy_was_never_patched(
    handler: type[FakeDeploymentPlatformHandler]
) -> Assertion[Exception | None]:
    def assertion(dont_care_error: Exception | None) -> bool:
        if handler.sync_patches_received:
            raise AssertionError(
                f"Expected the sync policy left alone, and it was patched "
                f"{handler.sync_patches_received}."
            )

        return True

    return assertion


def _nothing_was_written_to(handler: type[FakeDeploymentPlatformHandler]) -> Assertion[object]:
    """No patch of the application or of any resource, no rollback and no
    action run: the platform holds what it held."""
    def assertion(dont_care_result: object) -> bool:
        written = {
            "sync patches": handler.sync_patches_received,
            "resource patches": handler.resource_patches_received,
            "rollbacks": handler.rolled_back_to,
            "actions": handler.actions_run
        }

        if any(written.values()):
            raise AssertionError(f"Expected nothing written to the platform, and it got {written}")

        return True

    return assertion


def _the_platform_was_never_rolled_back(
    handler: type[FakeDeploymentPlatformHandler]
) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if handler.rolled_back_to:
            raise AssertionError(
                f"Expected the platform never rolled back, and it was rolled back to "
                f"{handler.rolled_back_to}."
            )

        return True

    return assertion


def _it_did_not_come_back_as(excluded: type[Exception]) -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if isinstance(raised, excluded):
            raise AssertionError(
                f"Expected the call not to raise {excluded.__name__}, and it did: "
                f"{raised!r}."
            )

        return True

    return assertion


def _it_left_behind(expected: UndoDescriptor | None) -> Assertion[Exception | None]:
    """The refusal says the whole of what it left behind, and it is `expected` -
    every field of it but the moment it was written, which is the tier's to
    stamp."""
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, McpToolError):
            raise AssertionError(f"Expected a refusal of the tool's, and {raised!r} was raised.")

        if not raised.left_behind_known:
            raise AssertionError(
                f"Expected the refusal to say the whole of what it left behind, and it did "
                f"not: {raised!r}."
            )

        if _without_its_moment(raised.undo_descriptor) != _without_its_moment(expected):
            raise AssertionError(
                f"Expected the refusal to have left behind [{expected!r}], and it carried "
                f"[{raised.undo_descriptor!r}]."
            )

        return True

    return assertion


def _without_its_moment(descriptor: UndoDescriptor | None) -> dict[str, Any] | None:
    if descriptor is None:
        return None

    return descriptor.model_dump(exclude={"written_at"})


def _the_plan_is(descriptor: UndoDescriptor, since: datetime) -> Assertion[Planned[Any]]:
    """The plan came back whole: the change it describes, every field of it,
    and the moment the state it was worked out from was read."""
    def assertion(planned: Planned[Any]) -> bool:
        wrong = {
            field: (expected, got)
            for field, expected, got in [("descriptor", descriptor, planned.descriptor),
                                         ("since", since, planned.since)]
            if expected != got
        }

        if wrong:
            raise AssertionError(
                f"Expected the plan to describe {descriptor!r} read at [{since}], and "
                f"{wrong} differed (expected, got)."
            )

        return True

    return assertion


def _it_answered_as(planned: UndoDescriptor) -> Assertion[UndoDescriptor]:
    """What the write answered is the change its plan described, every field of
    it but the moment it was written, which the write stamps."""
    def assertion(answered: UndoDescriptor) -> bool:
        if _without_its_moment(answered) != _without_its_moment(planned):
            raise AssertionError(
                f"Expected the write to answer with the change planned, {planned!r}, and "
                f"it answered {answered!r}."
            )

        return True

    return assertion


def _a_client_answering_anything() -> Any:
    """A client whose every call is answered, with something no write reads -
    for the cases about how a write is asked rather than what comes back."""
    return create_autospec(McpClient, instance=True)


def _it_was_asked(client: Any, *, kind: Asking) -> Assertion[object]:
    """The one call made said what kind of call it is - a read, a change that
    may be asked again, or a change asked once - and said it outright, rather
    than leaving it to whatever the transport assumes."""
    def assertion(dont_care_result: object) -> bool:
        if not client.call.called:
            raise AssertionError(f"Expected one call asked as [{kind}], and none was made.")

        said = client.call.call_args.kwargs.get("asking", "nothing")

        if said is not kind:
            raise AssertionError(
                f"Expected [{client.call.call_args.args[0]}] asked as [{kind}], and it was "
                f"asked as [{said}]."
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


class _AskedAgain(NamedTuple):
    """What the second asking of a write answered, and what the platform had
    been asked to write after the first asking and after both."""

    answered_again: UndoDescriptor
    written_after_the_first: dict[str, int]
    written_after_both: dict[str, int]


def _written_to(handler: type[FakeDeploymentPlatformHandler]) -> dict[str, int]:
    """How many of each kind of write the platform has been asked for."""
    return {
        "sync patches": len(handler.sync_patches_received),
        "resource patches": len(handler.resource_patches_received),
        "rollbacks": len(handler.rolled_back_to),
        "actions": len(handler.actions_run)
    }


def _asked_twice(handler: type[FakeDeploymentPlatformHandler],
                 plan: Callable[[McpClient], Planned[Any]],
                 write: Callable[[Planned[Any], McpClient], UndoDescriptor]
                 ) -> Callable[[McpClient], _AskedAgain]:
    """Planned once, and written from that plan twice over one session under
    one action - the second asking as the transport makes it."""
    def both_askings(client: McpClient) -> _AskedAgain:
        planned = plan(client)
        write(planned, client)
        written_after_the_first = _written_to(handler)

        return _AskedAgain(answered_again=write(planned, client),
                           written_after_the_first=written_after_the_first,
                           written_after_both=_written_to(handler))

    return both_askings


def _answered_again_as(planned: UndoDescriptor) -> Assertion[_AskedAgain]:
    def assertion(asked: _AskedAgain) -> bool:
        return _it_answered_as(planned)(asked.answered_again)

    return assertion


def _the_second_asking_wrote_nothing() -> Assertion[_AskedAgain]:
    def assertion(asked: _AskedAgain) -> bool:
        if not any(asked.written_after_the_first.values()):
            raise AssertionError(
                f"Expected the first asking to write to the platform, and it wrote "
                f"nothing: {asked.written_after_the_first}."
            )

        if asked.written_after_both != asked.written_after_the_first:
            raise AssertionError(
                f"Expected the second asking to write nothing, and the platform's writes "
                f"went from {asked.written_after_the_first} to {asked.written_after_both}."
            )

        return True

    return assertion


def _set_and_asked_again(handler: type[FakeUnleashHandler],
                         recorded: FlagUndo,
                         client: McpClient) -> UndoDescriptor:
    """`recorded`'s flag planned away from the state it was in and set from
    its plan, the provider recording that under the name Argus writes as at
    `recorded`'s moment, and the same write asked again from the same plan;
    what the second asking answered."""
    assert recorded.written_at is not None

    asked = not recorded.was_enabled
    planned = plan_flag(recorded.flag, asked, client=client)
    set_feature_flag(planned, asked, client=client)
    the_provider_recorded(handler, [
        a_disabling_of(recorded.flag, at=to_iso(recorded.written_at), by=THE_ARGUS_ACTOR)
    ])()

    return set_feature_flag(planned, asked, client=client)


def _answered_as_exactly(expected: UndoDescriptor) -> Assertion[UndoDescriptor]:
    """Every field, the moment it was written included."""
    def assertion(answered: UndoDescriptor) -> bool:
        if answered != expected:
            raise AssertionError(f"Expected the write to answer [{expected!r}], and it "
                                 f"answered [{answered!r}].")

        return True

    return assertion


def _asking_the_server[T](ask: Callable[[McpClient], T]) -> Callable[[], T]:
    """`_asking_the_server_as` the claim that holds the server's run, acting for
    an action, as a walk's worker asks it."""
    return _asking_the_server_as(THE_RUN_HELD, ask, acting_for=SOME_ACTION_ID)


def _asking_the_server_as[T](held: Fence | None,
                             ask: Callable[[McpClient], T],
                             acting_for: str | None = None) -> Callable[[], T]:
    """One client to the subprocess the fixture started, held for one `when`,
    by a process holding `held` - or holding no run, for `None` - and acting for
    the action `acting_for` names, where it names one.

    Where the subprocess is listening is read through `get_settings` rather than
    named here, because the fixture is what decides the port - it sets the
    environment and clears the cache before yielding, and this is the same
    answer the server resolved from.

    Closed on the way out, so a test leaves no session and no thread behind it.
    """
    def step() -> T:
        holding = Holding()

        with (
            write_mcp(WriteMcpEndpoint.of(get_settings()), holding=holding) as client,
            holding.of(held) if held is not None else nullcontext(),
            holding.acting_for(acting_for) if acting_for is not None else nullcontext()
        ):
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


def a_disabling_of(flag: str, at: str, by: str = DONT_CARE_ACTOR) -> dict[str, Any]:
    """One row of the provider's event log, in its own wire shape, recorded in
    the environment the server was told it serves."""
    return {
        "id": 11,
        "type": "feature-environment-disabled",
        "createdBy": by,
        "createdAt": at,
        "featureName": flag,
        "project": "default",
        "environment": THE_ENVIRONMENT
    }


def an_enabling_of(flag: str, at: str, by: str = DONT_CARE_ACTOR) -> dict[str, Any]:
    """The row the provider records for a flag switched on - the row after
    `a_disabling_of`'s, where a case records both."""
    return {
        "id": 12,
        "type": "feature-environment-enabled",
        "createdBy": by,
        "createdAt": at,
        "featureName": flag,
        "project": "default",
        "environment": THE_ENVIRONMENT
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
    """Reconciliation was suspended by switching `automated` off, and the rest
    of the policy is as the operator declared it.

    Argo CD reads `enabled: false` as configured and not syncing, so the
    operator's `automated` object stays where it was, `selfHeal` and all. A
    caller that removed `automated` would suspend sync and lose that with it; one
    that sent a policy to the spec route would replace the whole spec.
    """
    def assertion(dont_care_result: object) -> bool:
        if not handler.sync_patches_received:
            raise AssertionError(
                "Expected the sync policy to have been patched before the "
                "change, and the platform was never asked to change it - so "
                "the change was asked for against an application still "
                "reconciling itself."
            )

        automated = handler.sync_policy.get(AUTOMATED)

        if automated is None or automated.get(ENABLED) is not False:
            raise AssertionError(
                f"Expected reconciliation to be suspended by switching "
                f"`automated` off, and the platform holds "
                f"[{handler.sync_policy}]."
            )

        if automated.get("selfHeal") is not True:
            raise AssertionError(
                f"Expected the operator's `selfHeal` to survive the suspension, "
                f"and the platform holds [{handler.sync_policy}]."
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


def _the_platform_selects(handler: type[FakeDeploymentPlatformHandler],
                          card: str | None) -> Assertion[object]:
    """The card the platform's own Deployment now holds its pods to.

    Read from the platform rather than from what came back, for the reason the
    other writes are: what Argus says it did and what the world received are
    the two things worth keeping apart.
    """
    def assertion(dont_care_result: object) -> bool:
        if handler.accelerator_pin != card:
            raise AssertionError(
                f"Expected the platform's Deployment to be held to [{card}], and "
                f"it is held to [{handler.accelerator_pin}]."
            )

        return True

    return assertion


def _the_platform_runs(handler: type[FakeDeploymentPlatformHandler],
                       replicas: int | None) -> Assertion[object]:
    """The count the platform's own Deployment now declares, read from the
    platform for `_the_platform_selects`'s reason."""
    def assertion(dont_care_result: object) -> bool:
        if handler.replicas != replicas:
            raise AssertionError(
                f"Expected the platform's Deployment to declare [{replicas}] replicas, "
                f"and it declares [{handler.replicas}]."
            )

        return True

    return assertion


def _the_autoscaler_s_floor_is(handler: type[FakeDeploymentPlatformHandler],
                               floor: int) -> Assertion[object]:
    """The floor the platform's own autoscaler now declares, read from the
    platform for `_the_platform_selects`'s reason."""
    def assertion(dont_care_result: object) -> bool:
        if handler.autoscaler_floor != floor:
            raise AssertionError(
                f"Expected the platform's autoscaler to declare the floor [{floor}], "
                f"and it declares [{handler.autoscaler_floor}]."
            )

        return True

    return assertion


def _both_halves_of_the_pin_were_put_back() -> Assertion[AcceleratorPinRestored]:
    def assertion(restored: AcceleratorPinRestored) -> bool:
        if not (restored.pin_put_back and restored.automated_sync_put_back):
            raise AssertionError(
                f"Expected both the pin and the sync policy to be put back, and "
                f"the tier reported pin_put_back=[{restored.pin_put_back}] "
                f"automated_sync_put_back=[{restored.automated_sync_put_back}]."
            )

        return True

    return assertion


def _rolled_back_and_then_deployed_over(handler: type[FakeDeploymentPlatformHandler],
                                        client: McpClient) -> DeploymentRollbackUndo:
    """A real rollback through the server, and then a deployment of somebody
    else's recorded after it - the descriptor the rollback answered with, to
    put back."""
    rolled_back = _rolling_back(client)
    handler.history = handler.history + [{
        "id": handler.history[-1]["id"] + 1,
        "revision": A_REVISION_SOMEBODY_DEPLOYED,
        "deployedAt": to_iso(AFTER_THE_PLATFORM_S_PLAN),
        "initiatedBy": {"username": SOME_PERSON_DEPLOYING}
    }]

    return rolled_back


def _the_descriptor_records_it_went_to(revision: str) -> Assertion[DeploymentRollbackUndo]:
    """The revision rolled back to, carried back through the round trip - what
    a withdrawal hours later compares the platform with."""
    def assertion(descriptor: DeploymentRollbackUndo) -> bool:
        if descriptor.rolled_back_to_revision != revision:
            raise AssertionError(
                f"Expected the descriptor to record rolling back to [{revision}], and "
                f"it records [{descriptor.rolled_back_to_revision}]."
            )

        return True

    return assertion


def _it_was_left_as_somebody_set_it(mentioning: str) -> Assertion[DeploymentRestored]:
    def assertion(restored: DeploymentRestored) -> bool:
        if restored.left_because is None or mentioning not in restored.left_because:
            raise AssertionError(
                f"Expected the deployment left as somebody set it, naming "
                f"[{mentioning}], and the tier reported {restored!r}."
            )

        if not restored.sync_still_suspended:
            raise AssertionError(
                f"Expected the sync Argus suspended said to be still suspended, and "
                f"the tier reported {restored!r}."
            )

        return True

    return assertion


def _the_platform_was_not_rolled_back_again(
    handler: type[FakeDeploymentPlatformHandler]
) -> Assertion[object]:
    """One rollback - Argus's own - and none after it: the put-back wrote
    nothing over the deployment somebody made since."""
    def assertion(dont_care_result: object) -> bool:
        if handler.rolled_back_to != [THE_HISTORY_BEFORE_IT]:
            raise AssertionError(
                f"Expected only Argus's rollback to entry [{THE_HISTORY_BEFORE_IT}], "
                f"and the platform was asked for {handler.rolled_back_to}."
            )

        return True

    return assertion


# When the provider recorded a change Argus made from a plan: after the plan's
# read, as a real change lands. And when somebody changed the flag after that.
WHEN_ARGUS_S_CHANGE_WAS_RECORDED = AFTER_THE_PROVIDER_S_PLAN
WHEN_SOMEBODY_CHANGED_IT_AFTER = WHEN_ARGUS_S_CHANGE_WAS_RECORDED + timedelta(minutes=1)


@pytest.mark.integration
def test_a_flag_still_as_argus_left_it_is_said_so_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The whole path of the question a resumed walk asks before it watches a
    # flag it did not set: the typed client, a real MCP round trip, the tool,
    # the provider's own log from the plan's read and the name the server was
    # told Argus writes under. A read - the flag is where it was.
    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _a_flag_switched_off_by_argus(
                running_write_mcp, WHEN_ARGUS_S_CHANGE_WAS_RECORDED, client
            ))()
        ) \
        .when(
            _asking_the_server(lambda client: flag_still_argus_s(
                the_plan, _as_recorded_at(the_plan, WHEN_ARGUS_S_CHANGE_WAS_RECORDED),
                client=client
            ))
        ) \
        .then(all_of(
            _it_was_found(still_argus_s=True),
            the_provider_now_reports_enabled(running_write_mcp, [])
        ))


@pytest.mark.integration
def test_a_flag_somebody_changed_since_argus_set_it_is_said_so_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Changed since crosses the wire as itself, with what was found - not as
    # nobody-can-say, and not as a refusal: it is an answer, and the walk
    # escalates on it rather than watch somebody's flag as Argus's.
    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _a_flag_switched_off_by_argus(
                running_write_mcp, WHEN_ARGUS_S_CHANGE_WAS_RECORDED, client
            ))(),
            calling(the_provider_has_enabled(running_write_mcp, SOME_FLAG)),
            calling(the_provider_recorded(running_write_mcp, [
                a_disabling_of(SOME_FLAG, at=to_iso(WHEN_ARGUS_S_CHANGE_WAS_RECORDED),
                               by=THE_ARGUS_ACTOR),
                an_enabling_of(SOME_FLAG, at=to_iso(WHEN_SOMEBODY_CHANGED_IT_AFTER),
                               by=SOME_HUMAN)
            ]))
        ) \
        .when(
            _asking_the_server(lambda client: flag_still_argus_s(
                the_plan, _as_recorded_at(the_plan, WHEN_ARGUS_S_CHANGE_WAS_RECORDED),
                client=client
            ))
        ) \
        .then(all_of(
            _it_was_found(still_argus_s=False),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
        ))


@pytest.mark.integration
def test_a_flag_whose_history_shows_no_change_since_its_plan_is_said_to_be_nobody_s_to_say(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The row says Argus changed the flag, and the provider's history since the
    # plan holds no change at all: the two contradict each other, and the
    # answer crosses the wire as nobody-can-say rather than either of the others.
    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _a_flag_planned_off(
                running_write_mcp, client
            ))()
        ) \
        .when(
            _asking_the_server(lambda client: flag_still_argus_s(
                the_plan, _as_recorded_at(the_plan, WHEN_ARGUS_S_CHANGE_WAS_RECORDED),
                client=client
            ))
        ) \
        .then(all_of(
            _it_was_found(still_argus_s=None),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
        ))


@pytest.mark.integration
def test_a_rollback_still_argus_s_is_said_so_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # Driven from a real rollback, for the restore's reason: a descriptor a test
    # invented is one nothing proves the tier would produce. The history and
    # the images read through the adapter, against the account the server was
    # told Argus signs in as - the restore's own check, asked on its own.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_rollback_made := _asking_the_server(_rolling_back)(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: rollback_still_argus_s(
                the_rollback_made, client=client
            ))
        ) \
        .then(all_of(
            _it_was_found(still_argus_s=True),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


@pytest.mark.integration
def test_a_rollback_somebody_deployed_over_is_said_so_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # A person deployed after Argus's rollback: the answer says what was found,
    # in the words the restore leaves a rollback standing with.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_rollback_made := _asking_the_server(
                lambda client: _rolled_back_and_then_deployed_over(handler, client)
            )(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: rollback_still_argus_s(
                the_rollback_made, client=client
            ))
        ) \
        .then(all_of(
            _it_was_found(still_argus_s=False, mentioning=A_REVISION_SOMEBODY_DEPLOYED),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


@pytest.mark.integration
def test_a_scale_out_still_argus_s_is_said_so_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # Asked acting for the action that made it, as a resumed walk asks it: the
    # count is the one asked for, and the Deployment carries this action's mark,
    # which travels to the tier in the call's `_meta` as a write's does.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_scale_out_made := _asking_the_server(lambda client: scale_out(
                plan_scale_out(SOME_APPLICATION, client=client), client=client
            ))(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: scale_out_still_argus_s(
                the_scale_out_made, client=client
            ))
        ) \
        .then(all_of(
            _it_was_found(still_argus_s=True),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


@pytest.mark.integration
def test_an_autoscaler_pin_still_argus_s_is_said_so_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # The autoscaler is staged inside the step that pins it: a `calling` step
    # runs after every value in `given` is built, and the pin is one of them.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_pin_made := _asking_the_server(
                lambda client: _an_autoscaler_pinned_on(handler, client)
            )(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: autoscaler_pin_still_argus_s(
                the_pin_made, client=client
            ))
        ) \
        .then(all_of(
            _it_was_found(still_argus_s=True),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


@pytest.mark.integration
def test_a_pin_to_a_card_still_argus_s_is_said_so_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_pin_made := _asking_the_server(lambda client: _pinning_to(SOME_CARD, client))(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: accelerator_pin_still_argus_s(
                the_pin_made, client=client
            ))
        ) \
        .then(all_of(
            _it_was_found(still_argus_s=True),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


def _an_autoscaler_pinned_on(handler: type[FakeDeploymentPlatformHandler],
                             client: McpClient) -> AutoscalerUndo:
    """An autoscaler staged beside the Deployment, then pinned from its plan, as
    the walk makes a change: two calls over one session."""
    _an_autoscaler_staged_on(handler, True)()

    return pin_autoscaler(plan_autoscaler_pin(SOME_APPLICATION, client=client), client=client)


def _it_was_found(still_argus_s: bool | None,
                  mentioning: str | None = None) -> Assertion[ChangeFound]:
    """The answer crossed the wire as itself - `is` rather than `==`, since
    `None` and `False` are the whole distinction - saying what was found, where
    a case names something it must mention."""
    def assertion(found: ChangeFound) -> bool:
        if found.still_argus_s is not still_argus_s:
            raise AssertionError(
                f"Expected the change found still Argus's [{still_argus_s}], got {found!r}."
            )

        if mentioning is not None and (found.found is None or mentioning not in found.found):
            raise AssertionError(
                f"Expected what was found to name [{mentioning}], got [{found.found}]."
            )

        return True

    return assertion


def _what_was_written_to(handler: type[FakeDeploymentPlatformHandler]) -> dict[str, list[Any]]:
    """Every write the platform has been asked for so far, by route."""
    return {
        "sync patches": list(handler.sync_patches_received),
        "resource patches": list(handler.resource_patches_received),
        "rollbacks": list(handler.rolled_back_to),
        "actions": list(handler.actions_run)
    }


def _nothing_more_was_written_to(handler: type[FakeDeploymentPlatformHandler],
                                 written_by_then: dict[str, list[Any]]) -> Assertion[object]:
    """The platform was asked for no write beyond `written_by_then`: the check
    read, and changed nothing."""
    def assertion(dont_care_result: object) -> bool:
        written_now = _what_was_written_to(handler)

        if written_now != written_by_then:
            raise AssertionError(
                f"Expected nothing more written to the platform than {written_by_then}, "
                f"got {written_now}."
            )

        return True

    return assertion


# The flag change a claim plans: the flag found on, to be switched off.
THE_FLAG_CHANGE_PLANNED = FlagUndo(flag=SOME_FLAG, was_enabled=True)


@pytest.mark.integration
def test_a_flag_change_argus_made_from_its_plan_is_found_made_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # The whole path of the first question a resumed walk asks of a claim: the
    # change made through the real server from its plan, the provider recording
    # it under the name Argus writes as, then the read on the same plan. Made,
    # with the plan's change and when the provider recorded it - the moment the
    # walk dates the change by - and the flag left as the change left it.
    the_change_recorded_at = AFTER_THE_PROVIDER_S_PLAN

    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _a_flag_switched_off_by_argus(
                running_write_mcp, the_change_recorded_at, client
            ))()
        ) \
        .when(
            _asking_the_server(lambda client: whether_flag_was_made(the_plan, client=client))
        ) \
        .then(all_of(
            _it_was_made_as(THE_FLAG_CHANGE_PLANNED),
            _it_was_made_at(the_change_recorded_at),
            the_provider_now_reports_enabled(running_write_mcp, [])
        ))


@pytest.mark.integration
def test_a_flag_change_nothing_landed_of_is_found_not_made_through_the_real_write_server(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Planned and never written: nothing in the history since the plan, so
    # nothing landed - not made across the wire, not a refusal, carrying nothing,
    # since a flag has no suspension before it - and the flag where the plan
    # found it.
    nothing_left = None

    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _a_flag_planned_off(
                running_write_mcp, client
            ))()
        ) \
        .when(
            _asking_the_server(lambda client: whether_flag_was_made(the_plan, client=client))
        ) \
        .then(all_of(
            _nothing_landed(left_behind=nothing_left),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
        ))


@pytest.mark.integration
def test_a_flag_somebody_changed_since_its_plan_arrives_as_changed_since_through_the_read(
    running_write_mcp: type[FakeUnleashHandler]
) -> None:
    # Somebody switched it off and back on after the plan read it: the read
    # refuses as the write refuses, with the write's own type, saying it left
    # nothing - and the flag is as they left it.
    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _a_flag_planned_off(
                running_write_mcp, client
            ))(),
            calling(the_provider_recorded(running_write_mcp, [
                a_disabling_of(SOME_FLAG, at=to_iso(AFTER_THE_PROVIDER_S_PLAN), by=SOME_HUMAN),
                an_enabling_of(SOME_FLAG, at=to_iso(AFTER_THE_PROVIDER_S_PLAN), by=SOME_HUMAN)
            ]))
        ) \
        .when(attempting(
            _asking_the_server(lambda client: whether_flag_was_made(the_plan, client=client))
        )) \
        .then(all_of(
            an_error_was_raised(ChangedSince),
            _it_left_behind(None),
            the_provider_now_reports_enabled(running_write_mcp, [SOME_FLAG])
        ))


@pytest.mark.integration
def test_a_rollback_argus_made_from_its_plan_is_found_made_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # Made, when the platform's history has this rollback's entry by the account
    # Argus signs in as - dated by that entry, which the platform stamps with its
    # own clock - and nothing more written by asking.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_plan := _asking_the_server(_planned_and_rolled_back)(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: whether_rollback_was_made(the_plan, client=client))
        ) \
        .then(all_of(
            _it_was_made_as(THE_ROLLBACK_PLANNED),
            _it_was_made_at(THE_PLATFORM_S_TIME),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


@pytest.mark.integration
def test_a_scale_out_argus_made_from_its_plan_is_found_made_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    # Asked acting for the action that made it, as a resumed walk asks it: the
    # count the plan asked for under this action's mark, which travels to the
    # tier in the call's `_meta`. Dated by the mark - when the write tier wrote
    # it, on the tier's own clock, which nothing here holds - so said only to be
    # dated.
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _planned_and_made(
                plan_scale_out(SOME_APPLICATION, client=client),
                lambda planned: scale_out(planned, client=client)
            ))(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: whether_scale_out_was_made(the_plan, client=client))
        ) \
        .then(all_of(
            _it_was_made_as(THE_SCALE_OUT_PLANNED),
            _it_was_dated(),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


@pytest.mark.integration
def test_an_autoscaler_pin_argus_made_from_its_plan_is_found_made_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _planned_and_made(
                _an_autoscaler_planned_on(handler, client),
                lambda planned: pin_autoscaler(planned, client=client)
            ))(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: whether_autoscaler_pin_was_made(
                the_plan, client=client
            ))
        ) \
        .then(all_of(
            _it_was_made_as(THE_AUTOSCALER_PIN_PLANNED),
            _it_was_dated(),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


@pytest.mark.integration
def test_a_pin_to_a_card_argus_made_from_its_plan_is_found_made_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler]
) -> None:
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_plan := _asking_the_server(lambda client: _planned_and_made(
                plan_accelerator_pin(SOME_APPLICATION, SOME_CARD, client=client),
                lambda planned: pin_to_accelerator(planned, client=client)
            ))(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: whether_accelerator_pin_was_made(
                the_plan, client=client
            ))
        ) \
        .then(all_of(
            _it_was_made_as(THE_ACCELERATOR_PIN_PLANNED),
            _it_was_dated(),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


# Every platform kind's plan, made through the server holding no run, and the
# read of whether a claim's change on that plan was made.
EVERY_PLATFORM_KIND_PLANNED_AND_ASKED_AFTER = [
    pytest.param(lambda handler, client: plan_rollback(SOME_APPLICATION, client=client),
                 lambda planned, client: whether_rollback_was_made(planned, client=client),
                 id="rollback"),
    pytest.param(lambda handler, client: plan_scale_out(SOME_APPLICATION, client=client),
                 lambda planned, client: whether_scale_out_was_made(planned, client=client),
                 id="scale-out"),
    pytest.param(lambda handler, client: _an_autoscaler_planned_on(handler, client),
                 lambda planned, client: whether_autoscaler_pin_was_made(planned, client=client),
                 id="autoscaler-pin"),
    pytest.param(lambda handler, client: plan_accelerator_pin(SOME_APPLICATION, SOME_CARD,
                                                              client=client),
                 lambda planned, client: whether_accelerator_pin_was_made(planned,
                                                                         client=client),
                 id="accelerator-pin")
]


@pytest.mark.integration
@pytest.mark.parametrize(("plan", "ask"), EVERY_PLATFORM_KIND_PLANNED_AND_ASKED_AFTER)
def test_a_platform_change_planned_and_never_made_is_found_not_made_through_the_real_write_server(
    running_write_mcp_over_a_platform: type[FakeDeploymentPlatformHandler],
    plan: Callable[[type[FakeDeploymentPlatformHandler], McpClient], Planned[Any]],
    ask: Callable[[Planned[Any], McpClient], Made[Any] | NotMade[Any]]
) -> None:
    # The claim was written and its worker died before the write: the platform
    # stands as the plan found it, under no mark of this action's, so nothing
    # landed and nothing of the claim's is out there - not made across the wire,
    # not a refusal - and asking wrote nothing.
    no_suspension = None
    handler = running_write_mcp_over_a_platform

    Scenario() \
        .given(
            the_plan := _asking_the_server_as(None, lambda client: plan(handler, client))(),
            written_by_then := _what_was_written_to(handler)
        ) \
        .when(
            _asking_the_server(lambda client: ask(the_plan, client))
        ) \
        .then(all_of(
            _nothing_landed(left_behind=no_suspension),
            _nothing_more_was_written_to(handler, written_by_then)
        ))


def _as_recorded_at(planned: Planned[FlagUndo], written_at: datetime) -> FlagUndo:
    """The plan's change as the row records it once made: dated by when the
    provider recorded the write."""
    return planned.descriptor.model_copy(update={"written_at": written_at})


def _a_flag_planned_off(handler: type[FakeUnleashHandler],
                        client: McpClient) -> Planned[FlagUndo]:
    """`SOME_FLAG` on, as the provider holds it, and its switching off planned -
    nothing written."""
    the_provider_has_enabled(handler, SOME_FLAG)()

    return plan_flag(SOME_FLAG, False, client=client)


def _a_flag_switched_off_by_argus(handler: type[FakeUnleashHandler],
                                  recorded_at: datetime,
                                  client: McpClient) -> Planned[FlagUndo]:
    """`SOME_FLAG` planned off and switched off from its plan through the server,
    and the provider recording the change under the name Argus writes as at
    `recorded_at` - which the stand-in leaves a case to stage. The plan, as the
    claim carries it."""
    planned = _a_flag_planned_off(handler, client)
    set_feature_flag(planned, False, client=client)
    the_provider_recorded(handler, [
        a_disabling_of(SOME_FLAG, at=to_iso(recorded_at), by=THE_ARGUS_ACTOR)
    ])()

    return planned


def _planned_and_rolled_back(client: McpClient) -> Planned[DeploymentRollbackUndo]:
    """`SOME_APPLICATION`'s rollback planned and made from its plan; the plan,
    as the claim carries it."""
    return _planned_and_made(plan_rollback(SOME_APPLICATION, client=client),
                             lambda planned: roll_back_deployment(planned, client=client))


def _planned_and_made[D](planned: Planned[D],
                         make: Callable[[Planned[D]], object]) -> Planned[D]:
    """`planned`, once its change was made from it: the plan, as the claim
    carries it."""
    make(planned)

    return planned


def _an_autoscaler_planned_on(handler: type[FakeDeploymentPlatformHandler],
                              client: McpClient) -> Planned[AutoscalerUndo]:
    """An autoscaler staged beside the Deployment, and its pin planned."""
    _an_autoscaler_staged_on(handler, True)()

    return plan_autoscaler_pin(SOME_APPLICATION, client=client)


def _it_was_made_as(planned: UndoDescriptor) -> Assertion[Made[Any] | NotMade[Any]]:
    """Made, and the change made is the plan's - every field of it but the
    moment it was written, which the tier stamps."""
    def assertion(found: Made[Any] | NotMade[Any]) -> bool:
        if not isinstance(found, Made):
            raise AssertionError(
                f"Expected the change found made as {planned!r}, got [{found!r}]."
            )

        if _without_its_moment(found.descriptor) != _without_its_moment(planned):
            raise AssertionError(
                f"Expected the change found made as {planned!r}, got {found.descriptor!r}."
            )

        return True

    return assertion


def _it_was_made_at(moment: datetime) -> Assertion[Made[Any] | NotMade[Any]]:
    def assertion(found: Made[Any] | NotMade[Any]) -> bool:
        made_at = found.made_at if isinstance(found, Made) else None

        if made_at != moment:
            raise AssertionError(f"Expected the change found made at [{moment}], got [{made_at}].")

        return True

    return assertion


def _it_was_dated() -> Assertion[Made[Any] | NotMade[Any]]:
    def assertion(found: Made[Any] | NotMade[Any]) -> bool:
        if not isinstance(found, Made) or found.made_at is None:
            raise AssertionError(f"Expected the change found made and dated, got [{found!r}].")

        return True

    return assertion


def _nothing_landed(left_behind: UndoDescriptor | None) -> Assertion[Made[Any] | NotMade[Any]]:
    """Not made, arriving as such across the wire - carrying `left_behind`, what
    of the claim's is out there all the same, or `None` where nothing is."""
    def assertion(found: Made[Any] | NotMade[Any]) -> bool:
        if not isinstance(found, NotMade):
            raise AssertionError(
                f"Expected nothing landed, leaving {left_behind!r} behind, got [{found!r}]."
            )

        if found.left_behind != left_behind:
            raise AssertionError(
                f"Expected nothing landed, leaving {left_behind!r} behind, and it left "
                f"{found.left_behind!r}."
            )

        return True

    return assertion
