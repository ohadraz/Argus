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

And the provider's history, and the one question asked of it about one flag,
which are registration and nothing else - so what is asserted is that each is
answered by the port it was handed, from the moment it was asked about, and
that "nobody can say" crosses the wire as itself.

And the checks a resumed walk asks before it watches a change an earlier
worker made: whether each kind's change is still as Argus left it. Reads, so a
walk asks them holding no run; each is handed the change the row recorded and
nothing it could work out again, and the three whose change carries a claim's
mark are handed the claim the call's `_meta` names - the claim is the whole of
whose a mark is, and a call naming none has no claim to compare with.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from unittest.mock import Mock, create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from code_host import CodeHostWrites
from core import Fence, WriteMcpEndpoint, to_iso
from core.models import (
    AcceleratorPinUndo,
    AutoscalerUndo,
    ChangeFound,
    DeploymentRollbackUndo,
    FlagChange,
    FlagState,
    FlagUndo,
    OpenedPullRequest,
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
from mcp.client import Client
from mcp.types import CallToolResult, RequestParamsMeta, TextContent
from mcp_transport import ACTION_META_KEY, CHANGED_SINCE_MARKER, FENCE_META_KEY
from pydantic import BaseModel, TypeAdapter
from write_mcp_server.discarding import DiscardSettings
from write_mcp_server.fencing import FencedMCPServer, HoldForAChange
from write_mcp_server.server import build_server

from write_mcp_server_test.framework.marks import (
    ANOTHER_CLAIM,
    THE_MOMENT_A_MARK_SAYS,
    a_mark_found,
    marked_are,
)

# How the SDK's client is told to open a session by the `initialize` handshake,
# as the tier's own client opens one - its default speaks to a server in the
# same process without one.
LEGACY_HANDSHAKE: Final = "legacy"
# A call's `_meta` as the SDK types it, built from the map a case writes, as the
# transport builds it: validated rather than cast.
_AS_REQUEST_META: Final = TypeAdapter(RequestParamsMeta)

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
WHETHER_ANYBODY_ELSE_CHANGED_IT = "was_flag_changed_by_others_since"
PLAN_ROLLBACK = "plan_rollback"
PLAN_SCALE_OUT = "plan_scale_out"
PLAN_AUTOSCALER_PIN = "plan_autoscaler_pin"
PLAN_ACCELERATOR_PIN = "plan_accelerator_pin"
PLAN_FLAG = "plan_flag"
# One plan for every write that leaves something to put back.
EVERY_PLAN = {PLAN_ROLLBACK, PLAN_SCALE_OUT, PLAN_AUTOSCALER_PIN, PLAN_ACCELERATOR_PIN,
              PLAN_FLAG}
# One check for every write that leaves something to put back: whether its
# change is still as Argus left it.
FLAG_STILL_ARGUS_S = "flag_still_argus_s"
ROLLBACK_STILL_ARGUS_S = "rollback_still_argus_s"
SCALE_OUT_STILL_ARGUS_S = "scale_out_still_argus_s"
AUTOSCALER_PIN_STILL_ARGUS_S = "autoscaler_pin_still_argus_s"
ACCELERATOR_PIN_STILL_ARGUS_S = "accelerator_pin_still_argus_s"
EVERY_STILL_ARGUS_S = {FLAG_STILL_ARGUS_S, ROLLBACK_STILL_ARGUS_S, SCALE_OUT_STILL_ARGUS_S,
                       AUTOSCALER_PIN_STILL_ARGUS_S, ACCELERATOR_PIN_STILL_ARGUS_S}
# And one read for each of the same five: whether a claim's change was made.
WHETHER_FLAG_WAS_MADE = "whether_flag_was_made"
WHETHER_ROLLBACK_WAS_MADE = "whether_rollback_was_made"
WHETHER_SCALE_OUT_WAS_MADE = "whether_scale_out_was_made"
WHETHER_AUTOSCALER_PIN_WAS_MADE = "whether_autoscaler_pin_was_made"
WHETHER_ACCELERATOR_PIN_WAS_MADE = "whether_accelerator_pin_was_made"
EVERY_WHETHER_IT_WAS_MADE = {WHETHER_FLAG_WAS_MADE, WHETHER_ROLLBACK_WAS_MADE,
                             WHETHER_SCALE_OUT_WAS_MADE, WHETHER_AUTOSCALER_PIN_WAS_MADE,
                             WHETHER_ACCELERATOR_PIN_WAS_MADE}

# The reads, which a stale walk gets nothing wrong by asking.
EVERY_READ = {THE_HISTORY, WHETHER_ANYBODY_ELSE_CHANGED_IT, *EVERY_PLAN,
              *EVERY_STILL_ARGUS_S, *EVERY_WHETHER_IT_WAS_MADE}

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
# Who the provider says made a change to a flag: somebody, and Argus.
SOME_FLAG_ACTOR = "admin"
SOME_ARGUS_FLAG_ACTOR = "argus"
SOME_CHANGE = FlagChange(
    flag=SOME_FLAG,
    enabled=False,
    occurred_at=to_iso(SOME_MOMENT),
    actor=SOME_FLAG_ACTOR,
    made_by_argus=False
)
# What the provider says when it cannot give its history: whatever it says, the
# read answers an error.
DONT_CARE_PROVIDER_WORDS = "the provider did not answer"
# When the provider dated its answer to Argus's flip of `SOME_FLAG`, by its own
# clock - after `SOME_MOMENT`, the plan's read, which the flip's history is read
# from.
THE_MOMENT_THE_FLIP_WAS_ANSWERED = SOME_MOMENT + timedelta(seconds=2)
# Argus's flip of `SOME_FLAG`, as the row records it - what puts it back - and as
# the provider's history records it.
ARGUS_S_FLIP = FlagUndo(flag=SOME_FLAG, was_enabled=True,
                        written_at=THE_MOMENT_THE_FLIP_WAS_ANSWERED)
ARGUS_S_FLIP_IN_THE_HISTORY = FlagChange(
    flag=SOME_FLAG,
    enabled=not ARGUS_S_FLIP.was_enabled,
    occurred_at=to_iso(THE_MOMENT_THE_FLIP_WAS_ANSWERED),
    actor=SOME_ARGUS_FLAG_ACTOR,
    made_by_argus=True
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

# A fix as Code-Fix proposes it: the branch it is put on, the branch it is cut
# from and proposed onto, each file's whole new content, and its words.
SOME_FIX_BRANCH = "argus/fix-monthly-spend"
SOME_BASE_BRANCH = "main"
SOME_PATCH = {"src/io_shop/spend_summary.py": "def average(account): ...\n"}
SOME_MESSAGE = "Average spend over the items bought this month"
SOME_BODY = "The month's items, not the account's."
SOME_PROPOSAL = OpenedPullRequest(number=7, url="https://code.invalid/pulls/7",
                                  branch=SOME_FIX_BRANCH)


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
def test_a_fix_is_put_on_its_branch_by_the_code_host_as_the_call_named_it() -> None:
    # Positional on the port, so the order is the whole of which branch is
    # written and which is the base: swapped, a fix would be cut from a branch
    # that does not exist yet and written over the one that is deployed.
    code = create_autospec(CodeHostWrites, instance=True)
    code.commit_to_new_branch.return_value = SOME_FIX_BRANCH

    Scenario() \
        .given(server := _a_server(code=code, hold=_a_hold_answering_held)) \
        .when(lambda: _asked(server, "commit_to_new_branch", _acting_for(SOME_ACTION_ID),
                             branch=SOME_FIX_BRANCH, base_branch=SOME_BASE_BRANCH,
                             files=SOME_PATCH, message=SOME_MESSAGE).structured_content) \
        .then(all_of(
            the_answer_was({"result": SOME_FIX_BRANCH}),
            lambda _: _the_code_host_was_asked(
                code.commit_to_new_branch,
                (SOME_FIX_BRANCH, SOME_BASE_BRANCH, SOME_PATCH, SOME_MESSAGE)
            )
        ))


@pytest.mark.unit
def test_a_fix_is_proposed_by_the_code_host_as_the_call_named_it() -> None:
    code = create_autospec(CodeHostWrites, instance=True)
    code.propose.return_value = SOME_PROPOSAL

    Scenario() \
        .given(server := _a_server(code=code, hold=_a_hold_answering_held)) \
        .when(lambda: OpenedPullRequest.model_validate(
            _asked(server, "open_pull_request", _acting_for(SOME_ACTION_ID),
                   head_branch=SOME_FIX_BRANCH, base_branch=SOME_BASE_BRANCH,
                   title=SOME_MESSAGE, body=SOME_BODY).structured_content
        )) \
        .then(all_of(
            the_answer_was(SOME_PROPOSAL),
            lambda _: _the_code_host_was_asked(
                code.propose, (SOME_FIX_BRANCH, SOME_BASE_BRANCH, SOME_MESSAGE, SOME_BODY)
            )
        ))


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
    flags.changes_since.side_effect = FlagProviderUnavailable(DONT_CARE_PROVIDER_WORDS)

    Scenario() \
        .given(server := _a_server(flags)) \
        .when(lambda: _asked(server, THE_HISTORY, None, since=to_iso(SOME_MOMENT)).is_error) \
        .then(the_answer_was(True))


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
    """Whose it is said as the platform's adapter says it, of the account the
    server here is built with."""
    return DeploymentRecord(history_id=history_id, revision=revision,
                            deployed_at=deployed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            repo_url=None, path=None, initiated_by=by,
                            made_by_argus=None if by is None else by == SOME_ARGUS_ACCOUNT)


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
    again, both since the plan; and answering a rollback asked of it after the
    plan, by its own clock."""
    platform = _a_platform_a_rollback_can_be_planned_over()
    platform.deployments_of.return_value = [
        *_the_history_a_rollback_is_planned_from(),
        _a_deployment(THE_ENTRY_SYNCED_SINCE, A_REVISION_SYNCED_SINCE, by=None,
                      deployed_at=AFTER_THE_PLAN),
        _a_deployment(THE_ENTRY_SYNCED_BACK_SINCE, THE_REVISION_IT_WAS_ON, by=None,
                      deployed_at=AFTER_THE_PLAN)
    ]
    platform.roll_back.return_value = AFTER_THE_PLAN

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


def _a_platform_a_rollback_since_the_plan_stands_on(by: str,
                                                    marked_by: str = SOME_ACTION_ID) -> Mock:
    """A platform `_a_rollback_plan`'s rollback has been made on since the plan
    was read: its newest entry, of the revision rolled back to, made by `by`
    after the plan; sync off, under the mark of the action `marked_by` names -
    this action's own, unless a case names another."""
    platform = _a_platform_read_at(SOME_PLATFORM_TIME)
    platform.deployments_of.return_value = [
        *_the_history_a_rollback_is_planned_from(),
        _a_deployment(THE_ENTRY_THE_ROLLBACK_ADDED, THE_REVISION_ROLLED_BACK_TO, by=by,
                      deployed_at=AFTER_THE_PLAN)
    ]
    platform.is_syncing_itself.return_value = False
    platform.mark_on.side_effect = (
        lambda dont_care_application, kind: a_mark_found(marked_by)
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
              argus_account: str = SOME_ARGUS_ACCOUNT,
              code: Mock | None = None) -> FencedMCPServer:
    return build_server(
        WriteMcpEndpoint(write_mcp_host="127.0.0.1", write_mcp_port=8199,
                         write_mcp_url="http://127.0.0.1:8199"),
        flags if flags is not None else _a_provider(),
        code if code is not None else create_autospec(CodeHostWrites, instance=True),
        platform if platform is not None else create_autospec(DeploymentPlatformWrites,
                                                              instance=True),
        DiscardSettings(cache_url="redis://cache.invalid:6379"),
        hold if hold is not None else _a_hold_never_asked,
        argus_account=argus_account
    )


def _acting_for(action_id: str) -> dict[str, Any]:
    """The `_meta` of a call a walk makes holding `SOME_FENCE`, for `action_id`."""
    return {FENCE_META_KEY: SOME_FENCE.spoken(), ACTION_META_KEY: action_id}


def _the_code_host_was_asked(asked: Mock, expected: tuple[object, ...]) -> bool:
    made = [each.args for each in asked.call_args_list]

    if made != [expected]:
        raise AssertionError(
            f"Expected the code host asked once with {expected}, and it was asked {made}."
        )

    return True


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


def _what_it_serves(server: FencedMCPServer) -> set[str]:
    return {tool.name for tool in asyncio.run(server.list_tools())}


def _the_arguments_of(server: FencedMCPServer, tool: str) -> set[str] | None:
    """The arguments `tool` declares to a caller, or `None` where it is not
    served at all."""
    declared = {each.name: each for each in asyncio.run(server.list_tools())}

    if tool not in declared:
        return None

    return set(declared[tool].input_schema.get("properties", {}))


def _asked(server: FencedMCPServer,
           tool: str,
           meta: dict[str, Any] | None,
           **arguments: object) -> CallToolResult:
    """One call over a real MCP session held in memory, opened by the handshake
    the tier's own client opens one with, carrying `meta` - none, for a read."""
    async def over_a_session() -> CallToolResult:
        async with Client(server, mode=LEGACY_HANDSHAKE) as session:
            return await session.call_tool(
                tool, dict(arguments),
                meta=_AS_REQUEST_META.validate_python(meta) if meta is not None else None
            )

    return asyncio.run(over_a_session())


def _the_answer_to(server: FencedMCPServer, tool: str, **arguments: object) -> Any:
    """What the tool answered, as the transport reads a structured answer."""
    result = _asked(server, tool, None, **arguments)

    if result.is_error or result.structured_content is None:
        raise AssertionError(f"Expected [{tool}] to answer, and it said [{result.content}].")

    return result.structured_content.get("result", result.structured_content)


def _the_plan_answered[P: BaseModel](server: FencedMCPServer,
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
        refused = result.is_error and CHANGED_SINCE_MARKER in _the_words_of(result)

        if expected and not refused:
            raise AssertionError(
                f"Expected the write refused as changed since the plan, and it answered "
                f"is_error=[{result.is_error}] saying [{_the_words_of(result)}]."
            )

        if not expected and result.is_error:
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


def _changes_are(server: FencedMCPServer,
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


# What a scale-out of `SOME_COUNT` asks for: one doubling of it.
TWICE_SOME_COUNT = 2 * SOME_COUNT


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool", "takes"),
    [
        pytest.param(FLAG_STILL_ARGUS_S, {"planned", "descriptor"}, id="flag"),
        pytest.param(ROLLBACK_STILL_ARGUS_S, {"descriptor"}, id="rollback"),
        pytest.param(SCALE_OUT_STILL_ARGUS_S, {"descriptor"}, id="scale-out"),
        pytest.param(AUTOSCALER_PIN_STILL_ARGUS_S, {"descriptor"}, id="autoscaler-pin"),
        pytest.param(ACCELERATOR_PIN_STILL_ARGUS_S, {"descriptor"}, id="accelerator-pin")
    ]
)
def test_a_check_on_a_change_takes_what_the_row_recorded_and_nothing_else(
    tool: str, takes: set[str]
) -> None:
    # The change the row recorded - and, for a flag, the plan the claim carries,
    # whose read the provider's history is asked from, as the write asks it. Not
    # the claim: that travels in `_meta`, which a model is never offered as an
    # argument - and never anything the check could work out from the estate.
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
    ("tool", "a_change_argus_made", "a_platform_as_argus_left_it"),
    [
        pytest.param(ROLLBACK_STILL_ARGUS_S, lambda: _a_rollback_descriptor(),
                     lambda: _a_platform_argus_s_rollback_still_stands_on(
                         by=SOME_ARGUS_ACCOUNT),
                     id="rollback"),
        pytest.param(SCALE_OUT_STILL_ARGUS_S, lambda: _a_scale_out(),
                     lambda: _a_platform_as_the_scale_out_left_it(marked_by=SOME_ACTION_ID),
                     id="scale-out"),
        pytest.param(AUTOSCALER_PIN_STILL_ARGUS_S, lambda: _an_autoscaler_pin(),
                     lambda: _a_platform_as_the_autoscaler_pin_left_it(
                         marked_by=SOME_ACTION_ID),
                     id="autoscaler-pin"),
        pytest.param(ACCELERATOR_PIN_STILL_ARGUS_S, lambda: _an_accelerator_pin(),
                     lambda: _a_platform_as_the_accelerator_pin_left_it(
                         marked_by=SOME_ACTION_ID),
                     id="accelerator-pin")
    ]
)
def test_a_platform_change_as_argus_left_it_is_found_so_holding_no_run_and_writing_nothing(
    tool: str,
    a_change_argus_made: Callable[[], BaseModel],
    a_platform_as_argus_left_it: Callable[[], Mock]
) -> None:
    # Asked with no run held - the server's hold refuses to be asked - because
    # a read gets nothing wrong for a stale walk; and what was found crosses the
    # wire as itself.
    platform = a_platform_as_argus_left_it()

    Scenario() \
        .given(
            server := _a_server(platform=platform, argus_account=SOME_ARGUS_ACCOUNT)
        ) \
        .when(
            lambda: _what_it_found(server, tool, _acting_for(SOME_ACTION_ID),
                                   descriptor=a_change_argus_made().model_dump(mode="json"))
        ) \
        .then(all_of(
            _it_found_it_still_argus_s(True),
            lambda _: _nothing_was_written_to(platform)
        ))


@pytest.mark.unit
def test_a_flag_as_argus_left_it_is_found_so_from_the_plans_read() -> None:
    # The provider's history, from the plan's read - the write's own - with
    # Argus's flip in it, and nobody else's. The plan crosses the wire beside
    # the change.
    flags = _a_provider()
    flags.changes_since.return_value = [ARGUS_S_FLIP_IN_THE_HISTORY]

    Scenario() \
        .given(
            server := _a_server(flags)
        ) \
        .when(
            lambda: _what_it_found(
                server, FLAG_STILL_ARGUS_S, None,
                planned=_a_flag_plan(was_enabled=ARGUS_S_FLIP.was_enabled).model_dump(
                    mode="json"),
                descriptor=ARGUS_S_FLIP.model_dump(mode="json")
            )
        ) \
        .then(all_of(
            _it_found_it_still_argus_s(True),
            lambda _: _the_provider_was_asked(flags.changes_since, (SOME_MOMENT,)),
            lambda _: _the_flag_was_never_set(flags)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool", "a_change_argus_made", "a_platform_marked_by"),
    [
        pytest.param(SCALE_OUT_STILL_ARGUS_S, lambda: _a_scale_out(),
                     lambda claim: _a_platform_as_the_scale_out_left_it(marked_by=claim),
                     id="scale-out"),
        pytest.param(AUTOSCALER_PIN_STILL_ARGUS_S, lambda: _an_autoscaler_pin(),
                     lambda claim: _a_platform_as_the_autoscaler_pin_left_it(marked_by=claim),
                     id="autoscaler-pin"),
        pytest.param(ACCELERATOR_PIN_STILL_ARGUS_S, lambda: _an_accelerator_pin(),
                     lambda claim: _a_platform_as_the_accelerator_pin_left_it(marked_by=claim),
                     id="accelerator-pin")
    ]
)
@pytest.mark.parametrize(
    ("meta", "still_argus_s"),
    [
        pytest.param(_acting_for(SOME_ACTION_ID), True, id="the-claim-that-marked-it"),
        pytest.param(_acting_for(ANOTHER_CLAIM), False, id="another-claim"),
        pytest.param(None, None, id="no-claim")
    ]
)
def test_a_marked_change_is_found_argus_s_only_for_the_claim_its_call_names(
    tool: str,
    a_change_argus_made: Callable[[], BaseModel],
    a_platform_marked_by: Callable[[str], Mock],
    meta: dict[str, Any] | None,
    still_argus_s: bool | None
) -> None:
    # The claim travels in `_meta`, as a marked write's does, and reaches the
    # check: the objects carry `SOME_ACTION_ID`'s mark, so the call naming that
    # claim finds the change its own, one naming another finds somebody's, and
    # one naming none is a question nobody can answer.
    platform = a_platform_marked_by(SOME_ACTION_ID)

    Scenario() \
        .given(
            server := _a_server(platform=platform)
        ) \
        .when(
            lambda: _what_it_found(server, tool, meta,
                                   descriptor=a_change_argus_made().model_dump(mode="json"))
        ) \
        .then(
            _it_found_it_still_argus_s(still_argus_s)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("newest_by", "still_argus_s"), [
    pytest.param(SOME_ARGUS_ACCOUNT, True, id="argus-s-own-account"),
    pytest.param(SOME_PERSON, False, id="somebody-else-s")
])
def test_a_rollback_is_found_argus_s_only_where_the_account_it_was_handed_made_the_newest_entry(
    newest_by: str, still_argus_s: bool
) -> None:
    # The account Argus signs in as is the server's to hand the check, as it is
    # the rollback's and the restore's: a check told any other name would take
    # Argus's own rollback for a person's, or a person's for Argus's.
    platform = _a_platform_argus_s_rollback_still_stands_on(by=newest_by)

    Scenario() \
        .given(
            server := _a_server(platform=platform, argus_account=SOME_ARGUS_ACCOUNT)
        ) \
        .when(
            lambda: _what_it_found(server, ROLLBACK_STILL_ARGUS_S, None,
                                   descriptor=_a_rollback_descriptor().model_dump(mode="json"))
        ) \
        .then(
            _it_found_it_still_argus_s(still_argus_s)
        )



def _a_scale_out() -> ReplicaUndo:
    """A scale-out of `SOME_COUNT` to one doubling of it, that suspended sync."""
    return ReplicaUndo(application=SOME_APPLICATION, was_replicas=SOME_COUNT,
                       replicas_asked_for=TWICE_SOME_COUNT, was_syncing_itself=True)


def _an_autoscaler_pin() -> AutoscalerUndo:
    """A pin of `SOME_BOUNDS`' floor to its ceiling, that suspended sync."""
    return AutoscalerUndo(application=SOME_APPLICATION, was_min_replicas=SOME_BOUNDS.floor,
                          min_replicas_asked_for=SOME_BOUNDS.ceiling, was_syncing_itself=True)


def _an_accelerator_pin() -> AcceleratorPinUndo:
    """A pin to `SOME_CARD` of pods held to none, that suspended sync."""
    return AcceleratorPinUndo(application=SOME_APPLICATION, was_pinned_to=None,
                              pinned_to=SOME_CARD, was_syncing_itself=True)


def _a_platform_marked_by(claim: str, *objects: MarkedObject) -> Mock:
    """A platform not syncing itself, the application and `objects` carrying
    `claim`'s mark."""
    marked = {MarkedObject.APPLICATION, *objects}
    platform = _a_platform_read_at(SOME_PLATFORM_TIME)
    platform.is_syncing_itself.return_value = False
    platform.mark_on.side_effect = (
        lambda dont_care_application, kind: a_mark_found(claim) if kind in marked else None
    )

    return platform


def _a_platform_as_the_scale_out_left_it(marked_by: str) -> Mock:
    """Running the count `_a_scale_out` asked for, with no autoscaler."""
    platform = _a_platform_marked_by(marked_by, MarkedObject.DEPLOYMENT)
    platform.rollout_of.return_value = RolloutProgress(
        replicas_wanted=TWICE_SOME_COUNT, replicas_serving=TWICE_SOME_COUNT,
        replicas_updated=TWICE_SOME_COUNT, is_paused=False, has_failed=False
    )
    platform.autoscaler_of.return_value = None

    return platform


def _a_platform_as_the_autoscaler_pin_left_it(marked_by: str) -> Mock:
    """Its autoscaler's floor raised to its ceiling, as `_an_autoscaler_pin` asked."""
    platform = _a_platform_marked_by(marked_by, MarkedObject.AUTOSCALER)
    platform.autoscaler_of.return_value = SOME_AUTOSCALER
    platform.autoscaler_bounds.return_value = AutoscalerBounds(
        floor=SOME_BOUNDS.ceiling, ceiling=SOME_BOUNDS.ceiling
    )

    return platform


def _a_platform_as_the_accelerator_pin_left_it(marked_by: str) -> Mock:
    """Its pods held to `SOME_CARD`, as `_an_accelerator_pin` asked."""
    platform = _a_platform_marked_by(marked_by, MarkedObject.DEPLOYMENT)
    platform.accelerator_pin_of.return_value = SOME_CARD

    return platform


def _what_it_found(server: FencedMCPServer,
                   tool: str,
                   meta: dict[str, Any] | None,
                   **arguments: object) -> ChangeFound:
    """What a check answered over the wire, carrying `meta`, read as what it
    found."""
    result = _asked(server, tool, meta, **arguments)

    if result.is_error or result.structured_content is None:
        raise AssertionError(f"Expected [{tool}] to answer, and it said [{result.content}].")

    return ChangeFound.model_validate(
        result.structured_content.get("result", result.structured_content)
    )


def _it_found_it_still_argus_s(expected: bool | None) -> Assertion[ChangeFound]:
    """`is` rather than `==`: `None` and `False` are the whole distinction here."""
    def assertion(found: ChangeFound) -> bool:
        if found.still_argus_s is not expected:
            raise AssertionError(
                f"Expected the change found still Argus's [{expected}], got "
                f"[{found.still_argus_s}] finding [{found.found}]."
            )

        return True

    return assertion


# How a call to one of the reads asking whether a claim's change was made comes
# back: made, nothing landed, refused as changed since, or refused with nobody
# able to say.
MADE = "made"
NOTHING_LANDED = "nothing landed"
CHANGED_SINCE = "changed since"
NOBODY_CAN_SAY = "nobody can say"

# Every platform kind, as a plan of it, the platform as the change left it
# under a claim's marks, and the moment that platform says it was made.
EVERY_PLATFORM_KIND_MADE = [
    pytest.param(WHETHER_ROLLBACK_WAS_MADE, lambda: _a_rollback_plan(),
                 lambda claim: _a_platform_a_rollback_since_the_plan_stands_on(
                     by=SOME_ARGUS_ACCOUNT, marked_by=claim),
                 AFTER_THE_PLAN, id="rollback"),
    pytest.param(WHETHER_SCALE_OUT_WAS_MADE,
                 lambda: Planned[ReplicaUndo](descriptor=_a_scale_out(), since=SOME_PLATFORM_TIME),
                 lambda claim: _a_platform_as_the_scale_out_left_it(marked_by=claim),
                 THE_MOMENT_A_MARK_SAYS, id="scale-out"),
    pytest.param(WHETHER_AUTOSCALER_PIN_WAS_MADE,
                 lambda: Planned[AutoscalerUndo](descriptor=_an_autoscaler_pin(),
                                                 since=SOME_PLATFORM_TIME),
                 lambda claim: _a_platform_as_the_autoscaler_pin_left_it(marked_by=claim),
                 THE_MOMENT_A_MARK_SAYS, id="autoscaler-pin"),
    pytest.param(WHETHER_ACCELERATOR_PIN_WAS_MADE,
                 lambda: Planned[AcceleratorPinUndo](descriptor=_an_accelerator_pin(),
                                                     since=SOME_PLATFORM_TIME),
                 lambda claim: _a_platform_as_the_accelerator_pin_left_it(marked_by=claim),
                 THE_MOMENT_A_MARK_SAYS, id="accelerator-pin")
]


@pytest.mark.unit
@pytest.mark.parametrize("tool", sorted(EVERY_WHETHER_IT_WAS_MADE))
def test_whether_a_change_was_made_takes_the_claim_s_plan_and_nothing_else(tool: str) -> None:
    Scenario() \
        .given(
            server := _a_server()
        ) \
        .when(
            lambda: _the_arguments_of(server, tool)
        ) \
        .then(
            _the_arguments_are(tool, {"planned"})
        )


@pytest.mark.unit
@pytest.mark.parametrize(("tool", "a_plan", "a_platform_marked_by", "made_at"),
                         EVERY_PLATFORM_KIND_MADE)
def test_a_platform_change_made_is_found_made_and_dated_holding_no_run_and_writing_nothing(
    tool: str,
    a_plan: Callable[[], BaseModel],
    a_platform_marked_by: Callable[[str], Mock],
    made_at: datetime
) -> None:
    # Asked with no run held - the server's hold refuses to be asked - and the
    # moment it was made crosses the wire as itself.
    platform = a_platform_marked_by(SOME_ACTION_ID)

    Scenario() \
        .given(
            server := _a_server(platform=platform, argus_account=SOME_ARGUS_ACCOUNT)
        ) \
        .when(
            lambda: _asked(server, tool, _acting_for(SOME_ACTION_ID),
                           planned=a_plan().model_dump(mode="json"))
        ) \
        .then(all_of(
            _it_came_back(MADE),
            _it_was_made_at(made_at),
            lambda _: _nothing_was_written_to(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("tool", "a_plan", "a_platform_marked_by", "dont_care_made_at"),
                         EVERY_PLATFORM_KIND_MADE)
@pytest.mark.parametrize(
    ("meta", "came_back", "saying"),
    [
        pytest.param(_acting_for(SOME_ACTION_ID), MADE, None, id="the-claim-that-marked-it"),
        pytest.param(_acting_for(ANOTHER_CLAIM), CHANGED_SINCE, CHANGED_SINCE_MARKER,
                     id="another-claim"),
        pytest.param(None, NOBODY_CAN_SAY, ACTION_META_KEY, id="no-claim")
    ]
)
def test_a_platform_change_is_found_made_only_for_the_claim_its_call_names(
    tool: str,
    a_plan: Callable[[], BaseModel],
    a_platform_marked_by: Callable[[str], Mock],
    dont_care_made_at: datetime,
    meta: dict[str, Any] | None,
    came_back: str,
    saying: str | None
) -> None:
    # The claim travels in `_meta` and reaches the compare: the platform carries
    # `SOME_ACTION_ID`'s marks, so the call naming that claim finds the change
    # made, one naming another finds somebody's switch or change since - as the
    # write would - and one naming none is refused, saying the `_meta` key it
    # found no claim under, as a marked write refused for the same is.
    platform = a_platform_marked_by(SOME_ACTION_ID)

    Scenario() \
        .given(
            server := _a_server(platform=platform, argus_account=SOME_ARGUS_ACCOUNT)
        ) \
        .when(
            lambda: _asked(server, tool, meta, planned=a_plan().model_dump(mode="json"))
        ) \
        .then(
            _it_came_back(came_back, saying=saying)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("newest_by", "came_back"), [
    pytest.param(SOME_ARGUS_ACCOUNT, MADE, id="argus-s-own-account"),
    pytest.param(SOME_PERSON, CHANGED_SINCE, id="somebody-else-s")
])
def test_a_rollback_is_found_made_only_where_the_account_it_was_handed_made_the_entry(
    newest_by: str, came_back: str
) -> None:
    platform = _a_platform_a_rollback_since_the_plan_stands_on(by=newest_by)

    Scenario() \
        .given(
            server := _a_server(platform=platform, argus_account=SOME_ARGUS_ACCOUNT)
        ) \
        .when(
            lambda: _asked(server, WHETHER_ROLLBACK_WAS_MADE, _acting_for(SOME_ACTION_ID),
                           planned=_a_rollback_plan().model_dump(mode="json"))
        ) \
        .then(
            _it_came_back(came_back)
        )


@pytest.mark.unit
def test_a_scale_out_that_never_landed_comes_back_as_nothing_landed() -> None:
    # Nothing crossing the wire as itself: the walk makes the change, as the live
    # walk would.
    platform = _a_platform_a_scale_out_can_be_planned_over()

    Scenario() \
        .given(
            server := _a_server(platform=platform)
        ) \
        .when(
            lambda: _asked(server, WHETHER_SCALE_OUT_WAS_MADE, _acting_for(SOME_ACTION_ID),
                           planned=Planned[ReplicaUndo](descriptor=_a_scale_out(),
                                                        since=SOME_PLATFORM_TIME
                                                        ).model_dump(mode="json"))
        ) \
        .then(all_of(
            _it_came_back(NOTHING_LANDED),
            lambda _: _nothing_was_written_to(platform)
        ))


@pytest.mark.unit
def test_a_scale_out_whose_suspension_alone_landed_carries_it_across_the_wire() -> None:
    # The count where the plan found it, the sync suspended under the claim's
    # mark: nothing landed, carrying the plan whole - what a walk stopped before
    # it writes puts the suspension back with.
    platform = _a_platform_marked_by(SOME_ACTION_ID)
    platform.rollout_of.return_value = RolloutProgress(
        replicas_wanted=SOME_COUNT, replicas_serving=SOME_COUNT, replicas_updated=SOME_COUNT,
        is_paused=False, has_failed=False
    )
    platform.autoscaler_of.return_value = None

    Scenario() \
        .given(
            server := _a_server(platform=platform)
        ) \
        .when(
            lambda: _asked(server, WHETHER_SCALE_OUT_WAS_MADE, _acting_for(SOME_ACTION_ID),
                           planned=Planned[ReplicaUndo](descriptor=_a_scale_out(),
                                                        since=SOME_PLATFORM_TIME
                                                        ).model_dump(mode="json"))
        ) \
        .then(all_of(
            _it_came_back(NOTHING_LANDED),
            _it_left_behind_across_the_wire(_a_scale_out()),
            lambda _: _nothing_was_written_to(platform)
        ))


def _it_left_behind_across_the_wire(expected: ReplicaUndo) -> Assertion[CallToolResult]:
    """Nothing landed, carrying `expected` - read back as the kind it is."""
    def assertion(result: CallToolResult) -> bool:
        answered = (result.structured_content or {}).get("result", result.structured_content)
        carried = answered.get("left_behind") if isinstance(answered, dict) else None
        left = None if carried is None else TypeAdapter(ReplicaUndo).validate_python(carried)

        if left != expected:
            raise AssertionError(
                f"Expected nothing landed carrying {expected!r} across the wire, got "
                f"[{answered}]."
            )

        return True

    return assertion


@pytest.mark.unit
@pytest.mark.parametrize(
    ("history", "came_back"),
    [
        pytest.param([ARGUS_S_FLIP_IN_THE_HISTORY], MADE, id="argus-s-flip"),
        pytest.param([], NOTHING_LANDED, id="nothing"),
        pytest.param([SOME_CHANGE], CHANGED_SINCE, id="somebody-else-s")
    ]
)
def test_whether_a_flip_was_made_is_the_provider_s_history_since_the_plan(
    history: list[FlagChange], came_back: str
) -> None:
    flags = _a_provider()
    flags.changes_since.return_value = history

    Scenario() \
        .given(
            server := _a_server(flags)
        ) \
        .when(
            lambda: _asked(server, WHETHER_FLAG_WAS_MADE, None,
                           planned=_a_flag_plan(
                               was_enabled=ARGUS_S_FLIP.was_enabled).model_dump(mode="json"))
        ) \
        .then(all_of(
            _it_came_back(came_back),
            lambda _: _the_provider_was_asked(flags.changes_since, (SOME_MOMENT,)),
            lambda _: _the_flag_was_never_set(flags)
        ))


def _it_came_back(expected: str, saying: str | None = None) -> Assertion[CallToolResult]:
    """Which of the four ways the read came back - and, for a refusal, in its own
    words: a changed-since refusal carries the marker, and one nobody can answer
    for says why, in `saying`, and carries no marker."""
    def assertion(result: CallToolResult) -> bool:
        words = _the_words_of(result)

        answered = (result.structured_content or {}).get("result", result.structured_content)

        if result.is_error:
            came_back = CHANGED_SINCE if CHANGED_SINCE_MARKER in words else NOBODY_CAN_SAY
        elif isinstance(answered, dict) and "made_at" in answered:
            came_back = MADE
        elif isinstance(answered, dict) and "left_behind" in answered:
            came_back = NOTHING_LANDED
        else:
            came_back = f"neither made nor nothing landed, [{answered}]"

        if came_back != expected:
            raise AssertionError(
                f"Expected the read to come back [{expected}], got [{came_back}] saying "
                f"[{result.content}]."
            )

        if saying is not None and saying not in words:
            raise AssertionError(
                f"Expected the refusal to say [{saying}], got [{words}]."
            )

        return True

    return assertion


def _it_was_made_at(expected: datetime) -> Assertion[CallToolResult]:
    def assertion(result: CallToolResult) -> bool:
        answered = (result.structured_content or {}).get("result", result.structured_content)
        made_at = None if answered is None else answered.get("made_at")

        if made_at is None or datetime.fromisoformat(made_at) != expected:
            raise AssertionError(
                f"Expected the change found made at [{expected}], got [{made_at}]."
            )

        return True

    return assertion
