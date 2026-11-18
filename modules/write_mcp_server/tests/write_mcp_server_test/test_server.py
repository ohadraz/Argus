"""Which of the write tier's tools are changes, which are marked, and what its
reads answer.

The one thing about the assembled server its own tools' suites cannot see: a
tool not registered as a change changes the world for any walk at all, a stale
one included, and nothing about the tool itself would say so. And the same of a
platform write not registered as marked: it is made for a call naming no action,
and lands on the platform as nobody's.

And its three reads, which are registration and nothing else - the provider's
history, and the two questions asked of it about one flag - so what is asserted
is that each is answered by the port it was handed, from the moment it was
asked about, and that "nobody can say" crosses the wire as itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock, create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from core import Fence, WriteMcpEndpoint, to_iso
from core.mcp_transport import ACTION_META_KEY, FENCE_META_KEY
from core.models import DeploymentRollbackUndo, FlagChange
from deployment_platform import DeploymentPlatformWrites
from flag_provider import FlagProviderUnavailable, FlagProviderWrites
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult
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
# The reads, which a stale walk gets nothing wrong by asking.
EVERY_READ = {THE_HISTORY, WHETHER_ARGUS_CHANGED_IT, WHETHER_ANYBODY_ELSE_CHANGED_IT}

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
def test_a_marked_tool_writes_under_the_action_its_call_named() -> None:
    # The tool's half of the mark: the action id travels in the call's `_meta`,
    # and has to reach the port's write. A restore stands for the eight, being
    # the one whose every write is marked whatever the platform answers.
    platform = create_autospec(DeploymentPlatformWrites, instance=True)

    Scenario() \
        .given(
            server := _a_server(platform=platform, hold=_a_hold_answering_held)
        ) \
        .when(
            lambda: _asked(server, "restore_deployment",
                           {FENCE_META_KEY: SOME_FENCE.spoken(),
                            ACTION_META_KEY: SOME_ACTION_ID},
                           descriptor=_a_rollback_descriptor().model_dump(mode="json"))
        ) \
        .then(
            _every_write_was_for(platform.resume_sync, SOME_ACTION_ID)
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


def _a_rollback_descriptor() -> DeploymentRollbackUndo:
    """A rollback that suspended reconciliation, so its restore writes twice."""
    return DeploymentRollbackUndo(
        application=SOME_APPLICATION,
        was_on_history_id=41,
        was_on_revision="0f1e2d3",
        was_syncing_itself=True
    )


def _a_server(flags: Mock | None = None,
              platform: Mock | None = None,
              hold: HoldForAChange | None = None) -> FencedFastMCP:
    return build_server(
        WriteMcpEndpoint(write_mcp_host="127.0.0.1", write_mcp_port=8199,
                         write_mcp_url="http://127.0.0.1:8199"),
        flags if flags is not None else _a_provider(),
        some_repository_settings(),
        platform if platform is not None else create_autospec(DeploymentPlatformWrites,
                                                              instance=True),
        DiscardSettings(cache_url="redis://cache.invalid:6379"),
        hold if hold is not None else _a_hold_never_asked
    )


@contextmanager
def _a_hold_never_asked(dont_care_fence: Fence) -> Generator[bool]:
    raise AssertionError("Expected the run never asked after for a read, and it was.")


@contextmanager
def _a_hold_answering_held(dont_care_fence: Fence) -> Generator[bool]:
    yield True


def _what_it_serves(server: FencedFastMCP) -> set[str]:
    return {tool.name for tool in asyncio.run(server.list_tools())}


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

    return result.structuredContent.get("result")


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

