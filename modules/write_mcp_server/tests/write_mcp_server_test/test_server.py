"""Which of the write tier's tools are changes, which are marked, what each
takes, and what its reads answer.

The one thing about the assembled server its own tools' suites cannot see: a
tool not registered as a change changes the world for any walk at all, a stale
one included, and nothing about the tool itself would say so. And the same of a
platform write not registered as marked: it is made for a call naming no action,
and lands on the platform as nobody's.

Its plans are reads. Each works a change out before it is made and changes
nothing, so it is asked holding no run - the walk plans before it claims - and
what is asserted is that each answers the plan its module worked out, over the
wire, from the port it was handed. The writes then take the plan back whole and
nothing they could work out again: the plan is what the claim recorded, and a
write that re-derived it would compare the estate with something nobody wrote
down.

And the provider's history, and the two questions asked of it about one flag,
which are registration and nothing else - so what is asserted is that each is
answered by the port it was handed, from the moment it was asked about, and
that "nobody can say" crosses the wire as itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock, create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from core import Fence, WriteMcpEndpoint, to_iso
from core.mcp_transport import ACTION_META_KEY, CHANGED_SINCE_MARKER, FENCE_META_KEY
from core.models import (
    AcceleratorPinUndo,
    AutoscalerUndo,
    DeploymentRollbackUndo,
    FlagChange,
    FlagState,
    FlagUndo,
    Planned,
    ReplicaUndo,
    RolloutProgress,
)
from deployment_platform import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentPlatformWrites,
    DeploymentRecord,
    MarkedObject,
    SyncOperations,
)
from flag_provider import FlagProviderUnavailable, FlagProviderWrites
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, TypeAdapter
from write_mcp_server.discarding import DiscardSettings
from write_mcp_server.fencing import FencedFastMCP, HoldForAChange
from write_mcp_server.server import build_server

from write_mcp_server_test.framework.marks import marked_are
from write_mcp_server_test.framework.settings import some_repository_settings

# Every tool that changes something outside the tier: the seven mitigations,
# the four restores that put them back, and the branch and pull request a fix
# is proposed on.
EVERY_CHANGE = {
    "set_feature_flag", "restart_service", "roll_back_deployment", "restore_deployment",
    "scale_out", "restore_replica_count", "pin_autoscaler", "discard_cache_entries",
    "restore_autoscaler_floor", "pin_to_accelerator", "restore_accelerator_pin",
    "commit_to_new_branch", "open_pull_request"
}

# Every change that writes to the deployment platform an object that can carry
# Argus's mark: the four actions and the four restores that put them back. Not
# the restart, whose write is the platform's own action and has nowhere to put
# one; and not the flag, the cache, the branch or the pull request, which are
# not the platform's.
EVERY_MARKED = {
    "roll_back_deployment", "restore_deployment", "scale_out", "restore_replica_count",
    "pin_autoscaler", "restore_autoscaler_floor", "pin_to_accelerator",
    "restore_accelerator_pin"
}

THE_HISTORY = "get_recent_flag_changes"
WHETHER_ARGUS_CHANGED_IT = "was_flag_changed_by_argus_since"
WHETHER_ANYBODY_ELSE_CHANGED_IT = "was_flag_changed_by_others_since"
PLAN_ROLLBACK = "plan_rollback"
PLAN_SCALE_OUT = "plan_scale_out"
PLAN_AUTOSCALER_PIN = "plan_autoscaler_pin"
PLAN_ACCELERATOR_PIN = "plan_accelerator_pin"
PLAN_FLAG = "plan_flag"
# One plan for every write that leaves something to put back.
EVERY_PLAN = {PLAN_ROLLBACK, PLAN_SCALE_OUT, PLAN_AUTOSCALER_PIN, PLAN_ACCELERATOR_PIN,
              PLAN_FLAG}
# The reads, which a stale walk gets nothing wrong by asking.
EVERY_READ = {THE_HISTORY, WHETHER_ARGUS_CHANGED_IT, WHETHER_ANYBODY_ELSE_CHANGED_IT,
              *EVERY_PLAN}

# What each plan is asked with - only what the caller holds and the tier cannot
# work out - and what its write is then asked with: the plan back, whole, and
# for the flag the state asked for.
EVERY_PLANNED_TOOL_AND_WHAT_IT_TAKES = [
    pytest.param(PLAN_ROLLBACK, {"application"}, id="plan_rollback"),
    pytest.param(PLAN_SCALE_OUT, {"application"}, id="plan_scale_out"),
    pytest.param(PLAN_AUTOSCALER_PIN, {"application"}, id="plan_autoscaler_pin"),
    pytest.param(PLAN_ACCELERATOR_PIN, {"application", "accelerator"},
                 id="plan_accelerator_pin"),
    pytest.param(PLAN_FLAG, {"flag", "enabled"}, id="plan_flag"),
    pytest.param("roll_back_deployment", {"planned"}, id="roll_back_deployment"),
    pytest.param("scale_out", {"planned"}, id="scale_out"),
    pytest.param("pin_autoscaler", {"planned"}, id="pin_autoscaler"),
    pytest.param("pin_to_accelerator", {"planned"}, id="pin_to_accelerator"),
    pytest.param("set_feature_flag", {"planned", "enabled"}, id="set_feature_flag")
]

# Every write the platform port has. A plan asks none of them.
EVERY_PLATFORM_WRITE = ["suspend_sync", "resume_sync", "roll_back", "scale", "restart",
                        "set_autoscaler_floor", "pin_to_accelerator"]

SOME_FLAG = "monthly-spend-feature"
SOME_MOMENT = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
SOME_CHANGE = FlagChange(
    flag=SOME_FLAG,
    enabled=False,
    occurred_at=to_iso(SOME_MOMENT),
    actor="admin",
    made_by_argus=False
)

SOME_FENCE = Fence(run_id="6f1c1d2e-0000-4000-8000-000000000001", epoch=3)
SOME_ACTION_ID = "6f1c1d2e-0000-4000-8000-0000000000a1"
SOME_APPLICATION = "io-shop"
SOME_CARD = "Tesla-V100-SXM2-16GB"

# The platform's own clock when a plan reads it - a plan's `since` - and a
# moment either side of it, which is all a history entry's time is compared for.
SOME_PLATFORM_TIME = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
BEFORE_THE_PLAN = SOME_PLATFORM_TIME - timedelta(hours=1)
AFTER_THE_PLAN = SOME_PLATFORM_TIME + timedelta(minutes=1)

# The account Argus signs in to the platform as, and somebody who is not Argus.
SOME_ARGUS_ACCOUNT = "argus"
SOME_PERSON = "alice"
# The history entry a rollback was on, and the one Argus's rollback added.
THE_ENTRY_IT_WAS_ON = 41
THE_ENTRY_THE_ROLLBACK_ADDED = THE_ENTRY_IT_WAS_ON + 1
THE_REVISION_IT_WAS_ON = "0f1e2d3"
THE_REVISION_ROLLED_BACK_TO = "a7b8c9d"
# Two entries of the revision rolled back to, before the one it was on: the
# platform re-synced it, and a plan returns to the second, the last of that run.
THE_FIRST_ENTRY_ROLLED_BACK_TO = THE_ENTRY_IT_WAS_ON - 2
THE_RE_SYNCED_ENTRY = THE_ENTRY_IT_WAS_ON - 1
# Two entries the platform's own sync adds after the plan was read: another
# revision, then the one it was on again. Worked out again from the history then,
# a rollback would return to the first of them - which is what lets a rollback
# show it went where its plan said.
A_REVISION_SYNCED_SINCE = "5c6d7e8"
THE_ENTRY_SYNCED_SINCE = THE_ENTRY_IT_WAS_ON + 1
THE_ENTRY_SYNCED_BACK_SINCE = THE_ENTRY_SYNCED_SINCE + 1
# What the Deployment runs at the revision rolled back to, and what the
# platform renders for it - the same, so the rollback is nobody else's.
THE_IMAGES_ROLLED_BACK_TO = {SOME_APPLICATION: f"{SOME_APPLICATION}:{THE_REVISION_ROLLED_BACK_TO}"}
# A platform with no sync asked of it and none it has run, so the history alone
# says what was deployed.
NO_SYNC_ASKED_OR_RUN = SyncOperations(requested=None, last_run=None)

# A deployment's count and its autoscaler's bounds, with room between the
# floor and the ceiling for a pin, and room under the ceiling for a scale-out.
SOME_COUNT = 3
SOME_AUTOSCALER = Autoscaler(name="io-shop-cpu", namespace="shopping")
SOME_BOUNDS = AutoscalerBounds(floor=2, ceiling=8)


@pytest.mark.unit
def test_every_tool_the_tier_serves_but_its_reads_is_a_change() -> None:
    Scenario() \
        .given(
            server := _a_server()
        ) \
        .when(
            lambda: _what_it_serves(server)
        ) \
        .then(
            _changes_are(server, EVERY_CHANGE, reads=EVERY_READ)
        )


@pytest.mark.unit
def test_every_change_that_writes_to_the_platform_is_marked() -> None:
    # The writes a plan precedes stay marked: a plan is handed to them, and the
    # mark is still what says a landed change was this claim's.
    Scenario() \
        .given(
            server := _a_server()
        ) \
        .when(
            lambda: server.marked
        ) \
        .then(
            marked_are(EVERY_MARKED)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("tool", "takes"), EVERY_PLANNED_TOOL_AND_WHAT_IT_TAKES)
def test_a_plan_takes_what_its_caller_holds_and_its_write_takes_the_plan(
    tool: str, takes: set[str]
) -> None:
    # A plan is asked with what the caller holds and the tier cannot work out;
    # its write is asked with the plan, and with nothing it could work out
    # again - an application beside the plan would be a second statement of the
    # change, free to disagree with the first.
    Scenario() \
        .given(
            server := _a_server()
        ) \
        .when(
            lambda: _the_arguments_of(server, tool)
        ) \
        .then(
            _the_arguments_are(tool, takes)
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool", "arguments", "a_platform_to_plan_over", "planned_as"),
    [
        pytest.param(PLAN_ROLLBACK, {"application": SOME_APPLICATION},
                     lambda: _a_platform_a_rollback_can_be_planned_over(),
                     Planned[DeploymentRollbackUndo], id="rollback"),
        pytest.param(PLAN_SCALE_OUT, {"application": SOME_APPLICATION},
                     lambda: _a_platform_a_scale_out_can_be_planned_over(),
                     Planned[ReplicaUndo], id="scale-out"),
        pytest.param(PLAN_AUTOSCALER_PIN, {"application": SOME_APPLICATION},
                     lambda: _a_platform_an_autoscaler_pin_can_be_planned_over(),
                     Planned[AutoscalerUndo], id="autoscaler-pin"),
        pytest.param(PLAN_ACCELERATOR_PIN,
                     {"application": SOME_APPLICATION, "accelerator": SOME_CARD},
                     lambda: _a_platform_an_accelerator_pin_can_be_planned_over(),
                     Planned[AcceleratorPinUndo], id="accelerator-pin")
    ]
)
def test_a_platform_plan_is_read_holding_no_run_dated_by_the_platform_and_changes_nothing(
    tool: str,
    arguments: dict[str, str],
    a_platform_to_plan_over: Callable[[], Mock],
    planned_as: type[BaseModel]
) -> None:
    # Asked with no run held - the server's hold refuses to be asked - because
    # the walk plans before it claims. What comes back is a plan of the action's
    # own kind, dated by the platform's clock rather than the tier's, and nothing
    # was asked to change.
    platform = a_platform_to_plan_over()

    Scenario() \
        .given(
            server := _a_server(platform=platform)
        ) \
        .when(
            lambda: _the_plan_answered(server, tool, planned_as, **arguments)
        ) \
        .then(all_of(
            _it_is_dated(SOME_PLATFORM_TIME),
            lambda _: _nothing_was_written_to(platform)
        ))


@pytest.mark.unit
def test_a_flag_plan_is_read_holding_no_run_dated_by_the_provider_and_changes_nothing() -> None:
    flags = _a_provider()
    flags.state_of.return_value = FlagState(enabled=True, read_at=SOME_MOMENT)

    Scenario() \
        .given(
            server := _a_server(flags)
        ) \
        .when(
            lambda: _the_plan_answered(server, PLAN_FLAG, Planned[FlagUndo],
                                       flag=SOME_FLAG, enabled=False)
        ) \
        .then(all_of(
            _it_is_dated(SOME_MOMENT),
            lambda _: _the_flag_was_never_set(flags)
        ))


@pytest.mark.unit
def test_a_rollback_goes_to_the_entry_its_plan_named_and_no_other() -> None:
    # The plan crosses the wire whole and is what the write acts on: the
    # platform's own sync has deployed another revision since the plan and then
    # the one it found again, so re-deriving the target from this history would
    # pick the entry that sync passed through.
    platform = _a_platform_its_own_sync_ran_on_since_the_plan()

    Scenario() \
        .given(
            server := _a_server(platform=platform, hold=_a_hold_answering_held)
        ) \
        .when(
            lambda: _asked(server, "roll_back_deployment", _acting_for(SOME_ACTION_ID),
                           planned=_a_rollback_plan().model_dump(mode="json"))
        ) \
        .then(
            _it_rolled_back_to(platform, THE_RE_SYNCED_ENTRY)
        )


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_a_flag_is_set_from_its_plan_to_the_state_asked_for(enabled: bool) -> None:
    # The plan and the state cross the wire, and the provider is asked for the
    # flag the plan names in the state the call asked for.
    flags = _a_provider_nobody_changed_anything_on()

    Scenario() \
        .given(
            server := _a_server(flags, hold=_a_hold_answering_held)
        ) \
        .when(
            lambda: _asked(server, "set_feature_flag", _acting_for(SOME_ACTION_ID),
                           planned=_a_flag_plan(was_enabled=not enabled).model_dump(mode="json"),
                           enabled=enabled)
        ) \
        .then(
            _the_flag_was_set(flags, SOME_FLAG, enabled)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("newest_by", "changed_since"), [
    pytest.param(SOME_ARGUS_ACCOUNT, False, id="argus-s-own-account"),
    pytest.param(SOME_PERSON, True, id="somebody-else-s")
])
def test_a_rollback_is_answered_as_made_only_where_the_account_it_was_handed_made_the_newest_entry(
    newest_by: str, changed_since: bool
) -> None:
    # The rollback asked again after its answer was lost. The account Argus
    # signs in as is the server's to hand the write, as it is the restore's:
    # nothing in the call names it, and a write told any other name would take
    # Argus's own landed rollback for a person's - or a person's for Argus's,
    # and judge the service against a mitigation nobody here made. Either way
    # nothing is written.
    platform = _a_platform_a_rollback_since_the_plan_stands_on(by=newest_by)

    Scenario() \
        .given(
            server := _a_server(platform=platform, hold=_a_hold_answering_held,
                                argus_account=SOME_ARGUS_ACCOUNT)
        ) \
        .when(
            lambda: _asked(server, "roll_back_deployment", _acting_for(SOME_ACTION_ID),
                           planned=_a_rollback_plan().model_dump(mode="json"))
        ) \
        .then(all_of(
            _it_was_refused_as_changed_since(changed_since),
            lambda _: _nothing_was_written_to(platform)
        ))


@pytest.mark.unit
def test_a_marked_tool_writes_under_the_action_its_call_named() -> None:
    # The tool's half of the mark: the action id travels in the call's `_meta`,
    # and has to reach the port's write. A restore stands for the eight, over a
    # platform where the rollback is still Argus's, so it does write.
    platform = _a_platform_argus_s_rollback_still_stands_on(by=SOME_ARGUS_ACCOUNT)

    Scenario() \
        .given(
            server := _a_server(platform=platform, hold=_a_hold_answering_held)
        ) \
        .when(
            lambda: _asked(server, "restore_deployment", _acting_for(SOME_ACTION_ID),
                           descriptor=_a_rollback_descriptor().model_dump(mode="json"))
        ) \
        .then(
            _every_write_was_for(platform.resume_sync, SOME_ACTION_ID)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("newest_by", "resumed"), [
    pytest.param(SOME_ARGUS_ACCOUNT, True, id="argus-s-own-account"),
    pytest.param(SOME_PERSON, False, id="somebody-else-s")
])
def test_a_rollback_is_put_back_only_where_the_account_it_was_handed_made_the_newest_entry(
    newest_by: str, resumed: bool
) -> None:
    # The account Argus signs in to the platform as is the server's to hand the
    # restore: nothing in the call names it, and a restore told any other name
    # would leave Argus's own rollback standing as a person's - or put back a
    # person's as Argus's.
    platform = _a_platform_argus_s_rollback_still_stands_on(by=newest_by)

    Scenario() \
        .given(
            server := _a_server(platform=platform, hold=_a_hold_answering_held,
                                argus_account=SOME_ARGUS_ACCOUNT)
        ) \
        .when(
            lambda: _asked(server, "restore_deployment", _acting_for(SOME_ACTION_ID),
                           descriptor=_a_rollback_descriptor().model_dump(mode="json"))
        ) \
        .then(
            lambda _: _it_was_resumed(platform, resumed)
        )


@pytest.mark.unit
def test_the_history_is_the_providers_from_the_moment_asked() -> None:
    flags = _a_provider()
    flags.changes_since.return_value = [SOME_CHANGE]

    Scenario() \
        .given(server := _a_server(flags)) \
        .when(lambda: [
            FlagChange.model_validate(each)
            for each in _the_answer_to(server, THE_HISTORY, since=to_iso(SOME_MOMENT))
        ]) \
        .then(all_of(
            the_answer_was([SOME_CHANGE]),
            lambda _: _the_provider_was_asked(flags.changes_since, (SOME_MOMENT,))
        ))


@pytest.mark.unit
def test_a_history_the_provider_could_not_give_is_an_error_rather_than_empty() -> None:
    # "Nothing changed" is a conclusion Mitigation escalates on.
    flags = _a_provider()
    flags.changes_since.side_effect = FlagProviderUnavailable("dont-care")

    Scenario() \
        .given(server := _a_server(flags)) \
        .when(lambda: _asked(server, THE_HISTORY, None, since=to_iso(SOME_MOMENT)).isError) \
        .then(the_answer_was(True))


@pytest.mark.unit
@pytest.mark.parametrize("answer", [True, False, None], ids=["yes", "no", "nobody can say"])
def test_whether_argus_changed_a_flag_is_the_providers_answer(answer: bool | None) -> None:
    # `None` crossing the wire as itself is the case that matters: a resumed walk
    # told `False` instead acts again on something that may already have been done.
    flags = _a_provider()
    flags.argus_changed_since.return_value = answer

    Scenario() \
        .given(server := _a_server(flags)) \
        .when(lambda: _the_answer_to(server, WHETHER_ARGUS_CHANGED_IT,
                                     flag=SOME_FLAG, since=to_iso(SOME_MOMENT))) \
        .then(all_of(
            _it_answered(answer),
            lambda _: _the_provider_was_asked(flags.argus_changed_since,
                                              (SOME_FLAG, SOME_MOMENT))
        ))


@pytest.mark.unit
@pytest.mark.parametrize("answer", [True, False, None], ids=["yes", "no", "nobody can say"])
def test_whether_anybody_else_changed_a_flag_is_the_providers_answer(
    answer: bool | None
) -> None:
    # And here `None` told as `False` is an undo overwriting a person's change.
    flags = _a_provider()
    flags.others_changed_since.return_value = answer

    Scenario() \
        .given(server := _a_server(flags)) \
        .when(lambda: _the_answer_to(server, WHETHER_ANYBODY_ELSE_CHANGED_IT,
                                     flag=SOME_FLAG, since=to_iso(SOME_MOMENT))) \
        .then(all_of(
            _it_answered(answer),
            lambda _: _the_provider_was_asked(flags.others_changed_since,
                                              (SOME_FLAG, SOME_MOMENT))
        ))


def _a_provider() -> Mock:
    flags: Mock = create_autospec(FlagProviderWrites, instance=True)

    return flags


def _a_provider_nobody_changed_anything_on() -> Mock:
    """A provider whose history since any plan holds no change to any flag,
    asked either way it can be."""
    flags = _a_provider()
    flags.changes_since.return_value = []
    flags.set.return_value = FlagUndo(flag=SOME_FLAG, was_enabled=True)

    return flags


def _a_flag_plan(was_enabled: bool) -> Planned[FlagUndo]:
    return Planned[FlagUndo](descriptor=FlagUndo(flag=SOME_FLAG, was_enabled=was_enabled),
                             since=SOME_MOMENT)


def _a_rollback_descriptor() -> DeploymentRollbackUndo:
    """A rollback that suspended reconciliation, so its restore writes twice."""
    return DeploymentRollbackUndo(
        application=SOME_APPLICATION,
        was_on_history_id=THE_ENTRY_IT_WAS_ON,
        was_on_revision=THE_REVISION_IT_WAS_ON,
        rolled_back_to_revision=THE_REVISION_ROLLED_BACK_TO,
        was_syncing_itself=True
    )


def _a_rollback_plan() -> Planned[DeploymentRollbackUndo]:
    """A rollback planned from a platform syncing itself, over
    `_the_history_a_rollback_is_planned_from` - to the last entry of the run
    before the one it was on - read at the platform's `SOME_PLATFORM_TIME`."""
    return Planned[DeploymentRollbackUndo](
        descriptor=_a_rollback_descriptor().model_copy(
            update={"rolled_back_to_history_id": THE_RE_SYNCED_ENTRY}
        ),
        since=SOME_PLATFORM_TIME
    )


def _a_deployment(history_id: int,
                  revision: str,
                  by: str | None,
                  deployed_at: datetime = BEFORE_THE_PLAN) -> DeploymentRecord:
    return DeploymentRecord(history_id=history_id, revision=revision,
                            deployed_at=deployed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            repo_url=None, path=None, initiated_by=by)


def _the_history_a_rollback_is_planned_from() -> list[DeploymentRecord]:
    """The revision rolled back to, synced twice, then the revision it was on."""
    return [
        _a_deployment(THE_FIRST_ENTRY_ROLLED_BACK_TO, THE_REVISION_ROLLED_BACK_TO, by=None),
        _a_deployment(THE_RE_SYNCED_ENTRY, THE_REVISION_ROLLED_BACK_TO, by=None),
        _a_deployment(THE_ENTRY_IT_WAS_ON, THE_REVISION_IT_WAS_ON, by=None)
    ]


def _a_platform_read_at(time: datetime) -> Mock:
    """A platform whose clock answers `time`, no object of which carries any
    action's mark, and with no sync asked of it or run."""
    platform: Mock = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.now.return_value = time
    platform.mark_on.return_value = None
    platform.sync_operations_of.return_value = NO_SYNC_ASKED_OR_RUN

    return platform


def _a_platform_a_rollback_can_be_planned_over() -> Mock:
    """Running the revision it was on, syncing itself, and nothing marked."""
    platform = _a_platform_read_at(SOME_PLATFORM_TIME)
    platform.deployments_of.return_value = _the_history_a_rollback_is_planned_from()
    platform.is_syncing_itself.return_value = True

    return platform


def _a_platform_its_own_sync_ran_on_since_the_plan() -> Mock:
    """`_a_platform_a_rollback_can_be_planned_over`, after the platform's own
    sync - naming nobody - deployed another revision and then the one it was on
    again, both since the plan."""
    platform = _a_platform_a_rollback_can_be_planned_over()
    platform.deployments_of.return_value = [
        *_the_history_a_rollback_is_planned_from(),
        _a_deployment(THE_ENTRY_SYNCED_SINCE, A_REVISION_SYNCED_SINCE, by=None,
                      deployed_at=AFTER_THE_PLAN),
        _a_deployment(THE_ENTRY_SYNCED_BACK_SINCE, THE_REVISION_IT_WAS_ON, by=None,
                      deployed_at=AFTER_THE_PLAN)
    ]

    return platform


def _a_platform_a_scale_out_can_be_planned_over() -> Mock:
    """Running `SOME_COUNT` with no autoscaler, syncing itself."""
    platform = _a_platform_read_at(SOME_PLATFORM_TIME)
    platform.rollout_of.return_value = RolloutProgress(
        replicas_wanted=SOME_COUNT, replicas_serving=SOME_COUNT, replicas_updated=SOME_COUNT,
        is_paused=False, has_failed=False
    )
    platform.autoscaler_of.return_value = None
    platform.is_syncing_itself.return_value = True

    return platform


def _a_platform_an_autoscaler_pin_can_be_planned_over() -> Mock:
    """An autoscaler with room between its bounds, syncing itself."""
    platform = _a_platform_read_at(SOME_PLATFORM_TIME)
    platform.autoscaler_of.return_value = SOME_AUTOSCALER
    platform.autoscaler_bounds.return_value = SOME_BOUNDS
    platform.is_syncing_itself.return_value = True

    return platform


def _a_platform_an_accelerator_pin_can_be_planned_over() -> Mock:
    """Held to no card, syncing itself."""
    platform = _a_platform_read_at(SOME_PLATFORM_TIME)
    platform.accelerator_pin_of.return_value = None
    platform.is_syncing_itself.return_value = True

    return platform


def _a_platform_a_rollback_since_the_plan_stands_on(by: str) -> Mock:
    """A platform `_a_rollback_plan`'s rollback has been made on since the plan
    was read: its newest entry, of the revision rolled back to, made by `by`
    after the plan; sync off, under this action's own mark."""
    platform = _a_platform_read_at(SOME_PLATFORM_TIME)
    platform.deployments_of.return_value = [
        *_the_history_a_rollback_is_planned_from(),
        _a_deployment(THE_ENTRY_THE_ROLLBACK_ADDED, THE_REVISION_ROLLED_BACK_TO, by=by,
                      deployed_at=AFTER_THE_PLAN)
    ]
    platform.is_syncing_itself.return_value = False
    platform.mark_on.side_effect = (
        lambda dont_care_application, kind: SOME_ACTION_ID
            if kind == MarkedObject.APPLICATION else None
    )
    platform.images_running.return_value = THE_IMAGES_ROLLED_BACK_TO
    platform.images_at.return_value = THE_IMAGES_ROLLED_BACK_TO

    return platform


def _a_platform_argus_s_rollback_still_stands_on(by: str) -> Mock:
    """A platform `_a_rollback_descriptor`'s rollback has been through, its
    newest entry - of the revision rolled back to - made by `by`, running the
    images that revision renders, sync still suspended, and no sync asked of it
    or run since."""
    platform: Mock = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.sync_operations_of.return_value = NO_SYNC_ASKED_OR_RUN
    platform.deployments_of.return_value = [
        _a_deployment(THE_ENTRY_IT_WAS_ON, THE_REVISION_IT_WAS_ON, by=None),
        _a_deployment(THE_ENTRY_THE_ROLLBACK_ADDED, THE_REVISION_ROLLED_BACK_TO, by=by)
    ]
    platform.images_running.return_value = THE_IMAGES_ROLLED_BACK_TO
    platform.images_at.return_value = THE_IMAGES_ROLLED_BACK_TO
    platform.is_syncing_itself.return_value = False

    return platform


def _a_server(flags: Mock | None = None,
              platform: Mock | None = None,
              hold: HoldForAChange | None = None,
              argus_account: str = SOME_ARGUS_ACCOUNT) -> FencedFastMCP:
    return build_server(
        WriteMcpEndpoint(write_mcp_host="127.0.0.1", write_mcp_port=8199,
                         write_mcp_url="http://127.0.0.1:8199"),
        flags if flags is not None else _a_provider(),
        some_repository_settings(),
        platform if platform is not None else create_autospec(DeploymentPlatformWrites,
                                                              instance=True),
        DiscardSettings(cache_url="redis://cache.invalid:6379"),
        hold if hold is not None else _a_hold_never_asked,
        argus_account=argus_account
    )


def _acting_for(action_id: str) -> dict[str, Any]:
    """The `_meta` of a call a walk makes holding `SOME_FENCE`, for `action_id`."""
    return {FENCE_META_KEY: SOME_FENCE.spoken(), ACTION_META_KEY: action_id}


def _it_was_resumed(platform: Mock, expected: bool) -> bool:
    if platform.resume_sync.called is not expected:
        raise AssertionError(
            f"Expected the sync Argus suspended resumed [{expected}], and the platform "
            f"was asked {platform.method_calls}."
        )

    return True


@contextmanager
def _a_hold_never_asked(dont_care_fence: Fence) -> Generator[bool]:
    raise AssertionError("Expected the run never asked after for a read, and it was.")


@contextmanager
def _a_hold_answering_held(dont_care_fence: Fence) -> Generator[bool]:
    yield True


def _what_it_serves(server: FencedFastMCP) -> set[str]:
    return {tool.name for tool in asyncio.run(server.list_tools())}


def _the_arguments_of(server: FencedFastMCP, tool: str) -> set[str] | None:
    """The arguments `tool` declares to a caller, or `None` where it is not
    served at all."""
    declared = {each.name: each for each in asyncio.run(server.list_tools())}

    if tool not in declared:
        return None

    return set(declared[tool].inputSchema.get("properties", {}))


def _asked(server: FencedFastMCP,
           tool: str,
           meta: dict[str, Any] | None,
           **arguments: object) -> CallToolResult:
    """One call over a real MCP session held in memory, carrying `meta` - none,
    for a read."""
    async def over_a_session() -> CallToolResult:
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool(tool, dict(arguments), meta=meta)

    return asyncio.run(over_a_session())


def _the_answer_to(server: FencedFastMCP, tool: str, **arguments: object) -> Any:
    """What the tool answered, as the transport reads a structured answer."""
    result = _asked(server, tool, None, **arguments)

    if result.isError or result.structuredContent is None:
        raise AssertionError(f"Expected [{tool}] to answer, and it said [{result.content}].")

    return result.structuredContent.get("result", result.structuredContent)


def _the_plan_answered[P: BaseModel](server: FencedFastMCP,
                                    tool: str,
                                    planned_as: type[P],
                                    **arguments: object) -> P:
    """What a plan answered, read as the plan of the kind its action makes -
    which refuses a plan of any other kind."""
    return TypeAdapter(planned_as).validate_python(_the_answer_to(server, tool, **arguments))


def _the_words_of(result: CallToolResult) -> str:
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


def _it_was_refused_as_changed_since(expected: bool) -> Assertion[CallToolResult]:
    """Refused as a change made since the plan, or answered - `expected` says
    which."""
    def assertion(result: CallToolResult) -> bool:
        refused = result.isError and CHANGED_SINCE_MARKER in _the_words_of(result)

        if expected and not refused:
            raise AssertionError(
                f"Expected the write refused as changed since the plan, and it answered "
                f"isError=[{result.isError}] saying [{_the_words_of(result)}]."
            )

        if not expected and result.isError:
            raise AssertionError(
                f"Expected the write answered as made, and it was refused saying "
                f"[{_the_words_of(result)}]."
            )

        return True

    return assertion


def _it_is_dated(expected: datetime) -> Assertion[Any]:
    def assertion(planned: Any) -> bool:
        if planned.since != expected:
            raise AssertionError(
                f"Expected the plan dated [{expected}], the clock of the port it was read "
                f"through, got [{planned.since}]."
            )

        return True

    return assertion


def _nothing_was_written_to(platform: Mock) -> bool:
    written = [
        (name, call_args) for name, call_args, _ in platform.method_calls
        if name in EVERY_PLATFORM_WRITE
    ]

    if written:
        raise AssertionError(
            f"Expected nothing written to the platform, and it was asked {written}."
        )

    return True


def _it_rolled_back_to(platform: Mock, history_id: int) -> Assertion[CallToolResult]:
    """Read off `call_args` for the reason `_the_provider_was_asked` gives."""
    def assertion(result: CallToolResult) -> bool:
        asked = [call.args[1] for call in platform.roll_back.call_args_list]

        if asked != [history_id]:
            raise AssertionError(
                f"Expected the platform rolled back once to entry [{history_id}], and it "
                f"was asked {asked} (the call answered [{result.content}])."
            )

        return True

    return assertion


def _the_flag_was_never_set(flags: Mock) -> bool:
    written = [call.args for call in flags.set.call_args_list]

    if written:
        raise AssertionError(f"Expected no flag set, and the provider was asked {written}.")

    return True


def _the_flag_was_set(flags: Mock, flag: str, enabled: bool) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        asked = [call.args for call in flags.set.call_args_list]

        if asked != [(flag, enabled)]:
            raise AssertionError(
                f"Expected the provider asked once to set [{flag}] to [{enabled}], and it "
                f"was asked {asked} (the call answered [{result.content}])."
            )

        return True

    return assertion


def _it_answered(expected: bool | None) -> Assertion[Any]:
    """`is` rather than `==`: `None` and `False` are the whole distinction here."""
    def assertion(answered: Any) -> bool:
        if answered is not expected:
            raise AssertionError(f"Expected the answer [{expected}], got [{answered}].")

        return True

    return assertion


def _the_provider_was_asked(question: Mock, expected: tuple[object, ...]) -> bool:
    """Read off `call_args` rather than through `assert_called_with`, which does
    not survive a spec built from a `Protocol`: `self` is left on the signature."""
    asked = [call.args for call in question.call_args_list]

    if asked != [expected]:
        raise AssertionError(f"Expected the provider asked once with {expected}, got {asked}.")

    return True


def _every_write_was_for(write: Mock, action_id: str) -> Assertion[CallToolResult]:
    """`write` was made, and every time under a mark naming `action_id` - the
    moment it carries being the tier's own clock's, which no test can name."""
    def assertion(result: CallToolResult) -> bool:
        marks = [call.args[-1] for call in write.call_args_list]
        named = [getattr(mark, "action_id", None) for mark in marks]

        if not named or any(each != action_id for each in named):
            raise AssertionError(
                f"Expected every write made under the action [{action_id}], got the "
                f"marks {marks} (the call answered [{result.content}])."
            )

        return True

    return assertion


def _the_arguments_are(tool: str, expected: set[str]) -> Assertion[set[str] | None]:
    def assertion(declared: set[str] | None) -> bool:
        if declared is None:
            raise AssertionError(
                f"Expected [{tool}] served taking {sorted(expected)}, and it is not served."
            )

        if declared != expected:
            raise AssertionError(
                f"Expected [{tool}] to take {sorted(expected)}, and it takes {sorted(declared)}."
            )

        return True

    return assertion


def _changes_are(server: FencedFastMCP,
                 expected: set[str],
                 reads: set[str]) -> Assertion[set[str]]:
    def assertion(served: set[str]) -> bool:
        if set(server.changes) != expected or served - set(server.changes) != reads:
            raise AssertionError(
                f"Expected {sorted(expected)} registered as changes and only "
                f"{sorted(reads)} served as reads; the changes were "
                f"{sorted(server.changes)} and the rest {sorted(served - set(server.changes))}."
            )

        return True

    return assertion
