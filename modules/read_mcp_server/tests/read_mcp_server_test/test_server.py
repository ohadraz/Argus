"""Which tools a deployment's read tier actually offers.

Every other file here is about what one tool answers. This is about the list
itself, which is a decision `build_server` makes and no other test reads: a
tool registered in the wrong half of that function is offered by one deployment
and missing from another, and every case about what it answers goes on passing.

The half below the index guard is the one that is allowed to vary. A retrieval
by meaning backed by no index answers nothing for every description, which a
model reads as a fact about the code - so where a deployment keeps no store
the tool is not offered at all. Everything above that line is offered by every
deployment, and the register is one of those: whose a dependency is has nothing
to do with how anybody finds source.

And one tool's answer, because no module beside this one holds it: which flags
are on is the flag provider's port's to say, and the tool that says it is
registration and nothing else.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final
from unittest.mock import Mock, create_autospec

import pytest
from alerting_platform import AlertingPlatform
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    calling,
    one_record_was_logged,
    the_answer_was,
)
from code_host import CodeHostReads
from core import ReadMcpEndpoint
from core.embedding import Embedder
from core.models import CodeSearch
from core.vector_store import VectorSearch
from deployment_platform import DeploymentPlatformReads
from flag_provider import FlagProviderReads, FlagProviderUnavailable
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, Tool
from metrics_source import MetricsSource, SeriesClassifier
from postgres import Connections
from read_mcp_server.meaning import IndexReadSettings
from read_mcp_server.registry import ServiceRegistrySettings
from read_mcp_server.repository import RepositoryReadSettings
from read_mcp_server.retrieval import TargetServiceSettings
from read_mcp_server.server import build_server
from read_mcp_server.window import RetrievalSettings

SEARCHING_BY_GREP_ALONE = CodeSearch.GREP

# What the index a read tier searches is built with: required by the settings,
# and read by nothing here, since no case opens a store.
DONT_CARE_COLLECTION = "dont-care-collection"
DONT_CARE_EMBEDDING_MODEL = "dont-care-model"
DONT_CARE_MAX_LINES = 60
DONT_CARE_OVERLAP = 10
DONT_CARE_SCOPE = "src"

# How the SDK's client is told to open a session by the `initialize` handshake,
# as the tier's own client opens one - its default speaks to a server in the
# same process without one.
LEGACY_HANDSHAKE: Final = "legacy"

THE_REGISTER = "get_service_dependencies"
# The rollout channel's two answers, named because the test below is about both
# being offered. One is read by a model and one by a caller, so a deployment that
# dropped either would still look complete from the other's side.
THE_ROLLOUT_COUNTS = "get_rollout_progress"
THE_ROLLOUT_IN_WORDS = "get_rollout_state"
RETRIEVAL_BY_MEANING = "search_repository_by_meaning"
# Where the rule that paged stands, which is what a mitigation on a series alert
# is judged by.
THE_ALERT_RULE = "get_alert_rule"
# Where each replica runs, which the Investigator reads on every incident before
# its model is asked anything.
THE_PLACEMENT = "get_placements"
# The flags evaluating true now, which is how an agent learns which flag an
# incident is about without Argus's configuration naming it.
THE_ENABLED_FLAGS = "get_enabled_flags"
SOME_FLAG = "monthly-spend-feature"
SOME_OTHER_FLAG = "recommendations-v2"
# Whether the branch Code-Fix reads contains the revision that ran, which Code-Fix
# is told before it reads anything.
THE_BRANCH_CONTAINING = "branch_contains_revision"
THE_FILE_READER = "read_repository_file"
# A file read at a commit, and a revision asked after on a branch.
SOME_PATH = "src/io_shop/spend_summary.py"
SOME_REF = "9abaec7"
SOME_SOURCE = "def average(account): ...\n"
SOME_BRANCH = "release"
SOME_REVISION = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
# How the code a patch does not change uses what it changes, which Code-Fix's
# submission is held to before it is asked anything.
THE_CODE_OUTSIDE_A_PATCH = "get_code_outside_the_patch"

# The tools a model is offered as this tier declares them (MCP, `tools/list`),
# each with the arguments its caller fills in itself rather than asking the
# model for. The search by meaning is one of them, and absent here only because
# the tier these cases build searches by grep alone.
OFFERED_TO_A_MODEL = {
    "get_service_dependencies": {"service"},
    "get_what_a_deployment_changed": {"service"},
    "get_rollout_state": {"service"},
    "search_repository": {"ref"},
    "list_repository_files": {"ref"},
    "read_repository_file": {"ref"}
}

# Anthropic's floor for a tool's description ("Define tools": at least three
# to four sentences, more for a complex tool).
FEWEST_SENTENCES = 3


@pytest.mark.unit
def test_a_deployment_with_no_index_still_offers_the_service_register() -> None:
    # The failure this exists for, and it cost a whole stack run to find: the
    # register was registered below the guard that skips the index tools, so
    # under `grep` the read tier answered "unknown tool" - the walk's own read
    # of the estate failed, the gate found nothing within reach, and a restart
    # aimed at a dependency was refused for a reason nothing in the incident
    # was wrong about.
    #
    # Whose a dependency is has nothing to do with how anybody finds source,
    # which is exactly why putting the two together looked harmless.
    Scenario() \
        .given(a_deployment_that_keeps_no_index := _a_read_tier_searching(
            SEARCHING_BY_GREP_ALONE
        )) \
        .when(lambda: _the_tools_offered_by(a_deployment_that_keeps_no_index)) \
        .then(all_of(
            _the_tools_include(THE_REGISTER),
            _the_tools_exclude(RETRIEVAL_BY_MEANING)))


@pytest.mark.unit
def test_every_deployment_offers_the_rollout_counts_a_mitigation_waits_on() -> None:
    # Above the index guard, like the register and for a related reason. What a
    # deployment keeps no store for is how anybody finds source; whether a
    # rollback has reached every replica is not a search, and a tier that offered
    # it under one search mode and not the other would leave Mitigation unable to
    # tell that its own change had landed - on half the deployments, and only
    # under a mode no unit test exercises.
    #
    # Asserted alongside the prose channel rather than instead of it. Both are
    # offered: `get_rollout_state` answers an Investigator's model in sentences,
    # and this answers a caller in counts, and dropping either to add the other is
    # the mistake the pair exists to prevent.
    Scenario() \
        .given(a_deployment_that_keeps_no_index := _a_read_tier_searching(
            SEARCHING_BY_GREP_ALONE
        )) \
        .when(lambda: _the_tools_offered_by(a_deployment_that_keeps_no_index)) \
        .then(all_of(
            _the_tools_include(THE_ROLLOUT_COUNTS),
            _the_tools_include(THE_ROLLOUT_IN_WORDS)))


@pytest.mark.unit
def test_every_deployment_offers_the_alert_rule_a_mitigation_is_judged_by() -> None:
    # Above the index guard for the rollout counts' reason: whether the rule
    # that paged has stopped firing is not a search, and a tier offering it
    # under one search mode only would leave Mitigation unable to judge its own
    # action on half the deployments.
    Scenario() \
        .given(a_deployment_that_keeps_no_index := _a_read_tier_searching(
            SEARCHING_BY_GREP_ALONE
        )) \
        .when(lambda: _the_tools_offered_by(a_deployment_that_keeps_no_index)) \
        .then(_the_tools_include(THE_ALERT_RULE))


@pytest.mark.unit
def test_every_deployment_offers_where_the_replicas_run() -> None:
    # Above the index guard for the rollout counts' reason: where a pod runs is
    # not a search, and a tier offering it under one mode only would leave the
    # Investigator's every round without the one reading a moved replica shows in.
    Scenario() \
        .given(a_deployment_that_keeps_no_index := _a_read_tier_searching(
            SEARCHING_BY_GREP_ALONE
        )) \
        .when(lambda: _the_tools_offered_by(a_deployment_that_keeps_no_index)) \
        .then(_the_tools_include(THE_PLACEMENT))


@pytest.mark.unit
def test_every_deployment_offers_whether_the_branch_read_contains_what_ran() -> None:
    # Above the index guard for the rollout counts' reason: whether a revision
    # is on the branch Code-Fix reads is not a search, and a tier offering it
    # under one mode only would leave Code-Fix told on half the deployments and
    # silent on the rest.
    Scenario() \
        .given(a_deployment_that_keeps_no_index := _a_read_tier_searching(
            SEARCHING_BY_GREP_ALONE
        )) \
        .when(lambda: _the_tools_offered_by(a_deployment_that_keeps_no_index)) \
        .then(_the_tools_include(THE_BRANCH_CONTAINING))


@pytest.mark.unit
def test_every_deployment_offers_what_the_code_outside_a_patch_does_with_it() -> None:
    # Above the index guard for the rollout counts' reason: what the code a
    # patch does not change does with what it changes is read off the syntax
    # tree, not searched, and Code-Fix is held to it on every deployment.
    Scenario() \
        .given(a_deployment_that_keeps_no_index := _a_read_tier_searching(
            SEARCHING_BY_GREP_ALONE
        )) \
        .when(lambda: _the_tools_offered_by(a_deployment_that_keeps_no_index)) \
        .then(_the_tools_include(THE_CODE_OUTSIDE_A_PATCH))


@pytest.mark.unit
def test_a_deployment_with_no_index_says_so_when_it_starts(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Which of the two read tiers this is decides what Code-Fix is offered, and
    # is otherwise visible only in a tool list nobody reads.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            a_deployment_that_keeps_no_index := _a_read_tier_searching(
                SEARCHING_BY_GREP_ALONE
            )
        ) \
        .when(lambda: _the_tools_offered_by(a_deployment_that_keeps_no_index)) \
        .then(
            one_record_was_logged(caplog, "read_mcp_server.server", logging.INFO,
                                  "search by meaning not offered",
                                  values={"code_search": SEARCHING_BY_GREP_ALONE})
        )


@pytest.mark.unit
@pytest.mark.parametrize("tool", sorted(OFFERED_TO_A_MODEL))
def test_a_tool_a_model_is_offered_describes_each_argument_the_model_is_asked_for(
    tool: str
) -> None:
    # What an argument means, and what it changes, is said beside it rather
    # than in the tool's prose - which is also what keeps the prose from
    # describing an argument the model is never shown.
    Scenario() \
        .when(lambda: _the_tool_listed(SEARCHING_BY_GREP_ALONE, tool)) \
        .then(_every_argument_but(OFFERED_TO_A_MODEL[tool]).is_described())


@pytest.mark.unit
@pytest.mark.parametrize("tool", sorted(OFFERED_TO_A_MODEL))
def test_a_tool_a_model_is_offered_is_described_for_the_model(tool: str) -> None:
    # The description a tool is listed with is the one a model reads. A
    # docstring written for whoever maintains the server - where the behaviour
    # lives, what is not acted on yet - would reach every prompt as it stands,
    # and an argument its caller fills in has no place in it.
    Scenario() \
        .when(lambda: _the_tool_listed(SEARCHING_BY_GREP_ALONE, tool)) \
        .then(all_of(
            _it_is_described_in_at_least(FEWEST_SENTENCES),
            _its_description_does_not_say("registration only"),
            *(_its_description_does_not_say(f"`{argument}`")
              for argument in OFFERED_TO_A_MODEL[tool])))


@pytest.mark.unit
def test_the_file_reader_tells_a_model_to_read_several_files_in_one_turn() -> None:
    # Measured over Code-Fix's recorded corpus rather than supposed: the model
    # asked for exactly one file in 59 of 88 turns, and its widest turn was two
    # in most walks and four in two of them. Nothing in its loop was holding it
    # to one - every parallel call is answered in a single reply - so what did
    # was this tool's own first sentence, "Read one file's entire contents",
    # which reads as a limit where a unit was meant.
    #
    # Worth correcting because turns are what the resend is quadratic in, and
    # said in the tool rather than in a brief, because the sentence that reads
    # as the constraint is the sentence that has to stop reading that way.
    Scenario() \
        .when(lambda: _the_tool_listed(SEARCHING_BY_GREP_ALONE, THE_FILE_READER)) \
        .then(_its_description_says("several files"))


@pytest.mark.unit
def test_the_enabled_flags_are_the_providers_answer_in_its_order() -> None:
    # Registration and nothing else: what is on, and in what order, is the
    # provider's to say through the port this tier is handed.
    flags = _a_flag_provider()
    flags.enabled.return_value = [SOME_OTHER_FLAG, SOME_FLAG]

    Scenario() \
        .given(read_tier := _a_read_tier(SEARCHING_BY_GREP_ALONE, flags)) \
        .when(lambda: _asked(read_tier, THE_ENABLED_FLAGS).structured_content) \
        .then(the_answer_was({"result": [SOME_OTHER_FLAG, SOME_FLAG]}))


@pytest.mark.unit
def test_a_provider_that_could_not_be_asked_is_an_error_rather_than_nothing_enabled() -> None:
    # "Could not ask" and "nothing is on" are opposite facts, and an outage
    # answered as an empty list would look like an environment with no flag to
    # revert at all.
    flags = _a_flag_provider()
    flags.enabled.side_effect = FlagProviderUnavailable("dont-care")

    Scenario() \
        .given(read_tier := _a_read_tier(SEARCHING_BY_GREP_ALONE, flags)) \
        .when(lambda: _asked(read_tier, THE_ENABLED_FLAGS).is_error) \
        .then(the_answer_was(True))


@pytest.mark.unit
def test_a_file_is_read_by_the_code_host_at_the_path_and_ref_asked_for() -> None:
    # Two strings handed on by position: swapped, the host is asked for a file
    # named like a commit at a commit named like a path.
    code = _a_code_host()
    code.file_at.return_value = SOME_SOURCE

    Scenario() \
        .given(read_tier := _a_read_tier(SEARCHING_BY_GREP_ALONE, code=code)) \
        .when(lambda: _asked(read_tier, THE_FILE_READER,
                             path=SOME_PATH, ref=SOME_REF).structured_content) \
        .then(all_of(
            the_answer_was({"result": SOME_SOURCE}),
            lambda _: _the_code_host_was_asked(code.file_at, (SOME_PATH, SOME_REF))
        ))


@pytest.mark.unit
def test_whether_a_branch_holds_a_revision_is_asked_of_the_code_host_as_named() -> None:
    # Swapped, the host is asked whether the revision holds the branch, and
    # Code-Fix is told what ran is not on the branch it reads - or that it is.
    code = _a_code_host()
    code.contains.return_value = True

    Scenario() \
        .given(read_tier := _a_read_tier(SEARCHING_BY_GREP_ALONE, code=code)) \
        .when(lambda: _asked(read_tier, THE_BRANCH_CONTAINING,
                             branch=SOME_BRANCH, revision=SOME_REVISION).structured_content) \
        .then(all_of(
            the_answer_was({"result": True}),
            lambda _: _the_code_host_was_asked(code.contains, (SOME_BRANCH, SOME_REVISION))
        ))


def _a_flag_provider() -> Mock:
    flags: Mock = create_autospec(FlagProviderReads, instance=True)

    return flags


def _a_code_host() -> Mock:
    code: Mock = create_autospec(CodeHostReads, instance=True)

    return code


def _the_code_host_was_asked(asked: Mock, expected: tuple[object, ...]) -> bool:
    made = [each.args for each in asked.call_args_list]

    if made != [expected]:
        raise AssertionError(
            f"Expected the code host asked once with {expected}, and it was asked {made}"
        )

    return True


def _asked(server: MCPServer, tool: str, **arguments: object) -> CallToolResult:
    """One call over a real MCP session held in memory, opened by the handshake
    the tier's own client opens one with."""
    async def over_a_session() -> CallToolResult:
        async with Client(server, mode=LEGACY_HANDSHAKE) as session:
            return await session.call_tool(tool, dict(arguments))

    return asyncio.run(over_a_session())


def _the_tool_listed(mode: CodeSearch, name: str) -> Tool:
    """One tool as one deployment's read tier lists it."""
    found = [tool for tool in asyncio.run(_a_read_tier(mode).list_tools())
             if tool.name == name]

    if len(found) != 1:
        raise AssertionError(f"Expected one tool listed as [{name}], got {len(found)}.")

    return found[0]


def _every_argument_but(bound: set[str]) -> _Arguments:
    return _Arguments(bound)


class _Arguments:
    """The arguments of a listed tool its caller does not fill in."""

    def __init__(self, bound: set[str]) -> None:
        self._bound = bound

    def is_described(self) -> Assertion[Tool]:
        def assertion(tool: Tool) -> bool:
            undescribed = [
                argument
                for argument, schema in tool.input_schema.get("properties", {}).items()
                if argument not in self._bound and not schema.get("description")
            ]

            if undescribed:
                raise AssertionError(
                    f"Expected every argument [{tool.name}] asks a model for to be "
                    f"described, and {undescribed} are not."
                )

            return True

        return assertion


def _it_is_described_in_at_least(sentences: int) -> Assertion[Tool]:
    def assertion(tool: Tool) -> bool:
        said = (tool.description or "").strip()
        counted = said.count(". ") + (1 if said.endswith(".") else 0)

        if counted < sentences:
            raise AssertionError(
                f"Expected [{tool.name}] described in at least {sentences} sentences, "
                f"and it is described in {counted}: [{said}]."
            )

        return True

    return assertion


def _its_description_says(wanted: str) -> Assertion[Tool]:
    def assertion(tool: Tool) -> bool:
        said = tool.description or ""

        if wanted not in said:
            raise AssertionError(
                f"Expected [{tool.name}]'s description to say [{wanted}], and it says "
                f"[{said}]."
            )

        return True

    return assertion


def _its_description_does_not_say(unwanted: str) -> Assertion[Tool]:
    def assertion(tool: Tool) -> bool:
        said = tool.description or ""

        if unwanted in said:
            raise AssertionError(
                f"Expected [{tool.name}]'s description not to say [{unwanted}], and it "
                f"says [{said}]."
            )

        return True

    return assertion


def _the_tools_offered_by(mode: CodeSearch) -> list[str]:
    """Every tool one deployment's read tier registers, by name.

    Built rather than asserted against a list written here. What the server
    offers is the thing under test, and a second copy of the list would be a
    second place to forget a tool.
    """
    # `asyncio.run` rather than an async test. Listing what a server offers is
    # the only asynchronous thing this file touches, nothing else in the
    # workspace is an async test, and `asyncio_mode` is unconfigured - so a
    # coroutine here would be a new convention bought for one call.
    return [tool.name for tool in asyncio.run(_a_read_tier(mode).list_tools())]


def _a_read_tier(mode: CodeSearch,
                 flags: Mock | None = None,
                 code: Mock | None = None) -> MCPServer:
    """One deployment's read tier, reaching nothing - its flags answered by
    `flags` and its repository by `code` where a case gives them."""
    return build_server(
        ReadMcpEndpoint(read_mcp_host="127.0.0.1",
                        read_mcp_port=8090,
                        read_mcp_url="http://127.0.0.1:8090/mcp"),
        RetrievalSettings(log_initial_lookback_minutes=5,
                          log_initial_lookahead_minutes=5,
                          log_max_window_minutes=60,
                          metrics_window_minutes=60),
        TargetServiceSettings(target_service_url="http://target.invalid"),
        create_autospec(MetricsSource, instance=True),
        flags if flags is not None else _a_flag_provider(),
        create_autospec(DeploymentPlatformReads, instance=True),
        code if code is not None else _a_code_host(),
        ServiceRegistrySettings(
            service_registry_base_url="http://registry.invalid",
            service_registry_service_path="/registry/services/{service}"
        ),
        RepositoryReadSettings(service_source_paths="src"),
        IndexReadSettings(repository_index_collection=DONT_CARE_COLLECTION,
                          repository_index_embedding_model=DONT_CARE_EMBEDDING_MODEL,
                          repository_index_max_lines=DONT_CARE_MAX_LINES,
                          repository_index_chunk_overlap=DONT_CARE_OVERLAP,
                          service_source_paths=DONT_CARE_SCOPE,
                          code_search=mode),
        create_autospec(VectorSearch, instance=True),
        create_autospec(Embedder, instance=True),
        create_autospec(AlertingPlatform, instance=True),
        create_autospec(SeriesClassifier, instance=True),
        create_autospec(Connections, instance=True)
    )


def _a_read_tier_searching(mode: CodeSearch) -> CodeSearch:
    return mode


def _the_tools_include(expected: str) -> Assertion[list[str]]:
    def assertion(offered: list[str]) -> bool:
        if expected not in offered:
            raise AssertionError(
                f"Expected [{expected}] to be offered, and this deployment "
                f"offers {sorted(offered)}."
            )

        return True

    return assertion


def _the_tools_exclude(unwanted: str) -> Assertion[list[str]]:
    def assertion(offered: list[str]) -> bool:
        if unwanted in offered:
            raise AssertionError(
                f"Expected [{unwanted}] not to be offered where there is no "
                f"index, and this deployment offers {sorted(offered)} - a tool "
                f"that is offered will be called, and one backed by no index "
                f"answers nothing for every description."
            )

        return True

    return assertion
