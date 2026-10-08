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
"""

from __future__ import annotations

import asyncio
from unittest.mock import create_autospec

import pytest
from argus_core import Connections, ReadMcpEndpoint
from argus_core.models import CodeSearch
from argus_testkit import Assertion, Scenario, all_of
from deployment_platform import DeploymentPlatformReads
from metrics_source import MetricsSettings
from read_mcp_server.alert_rules import AlertRuleReadSettings
from read_mcp_server.flags import FlagReadSettings
from read_mcp_server.meaning import IndexReadSettings
from read_mcp_server.registry import ServiceRegistrySettings
from read_mcp_server.repository import RepositoryReadSettings
from read_mcp_server.retrieval import TargetServiceSettings
from read_mcp_server.server import build_server
from read_mcp_server.window import RetrievalSettings

SEARCHING_BY_GREP_ALONE = CodeSearch.GREP

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


def _the_tools_offered_by(mode: CodeSearch) -> list[str]:
    """Every tool one deployment's read tier registers, by name.

    Built rather than asserted against a list written here. What the server
    offers is the thing under test, and a second copy of the list would be a
    second place to forget a tool.
    """
    server = build_server(
        ReadMcpEndpoint(read_mcp_host="127.0.0.1",
                        read_mcp_port=8090,
                        read_mcp_url="http://127.0.0.1:8090/mcp"),
        RetrievalSettings(log_initial_lookback_minutes=5,
                          log_initial_lookahead_minutes=5,
                          log_max_window_minutes=60,
                          metrics_window_minutes=60),
        TargetServiceSettings(target_service_url="http://target.invalid"),
        MetricsSettings(prometheus_base_url="http://prometheus.invalid"),
        FlagReadSettings(unleash_base_url="http://flags.invalid",
                         unleash_frontend_token="dont-care-token"),
        create_autospec(DeploymentPlatformReads, instance=True),
        ServiceRegistrySettings(
            service_registry_base_url="http://registry.invalid",
            service_registry_service_path="/registry/services/{service}"
        ),
        RepositoryReadSettings(github_api_url="http://github.invalid",
                               github_repository="dont-care/repository",
                               github_read_token="dont-care-token",
                               github_source_paths="src"),
        IndexReadSettings(qdrant_url="http://qdrant.invalid",
                          code_index_collection="dont-care-collection",
                          code_search=mode),
        AlertRuleReadSettings(grafana_base_url="http://grafana.invalid",
                              grafana_auth_token="dont-care-token"),
        create_autospec(Connections, instance=True)
    )

    # `asyncio.run` rather than an async test. Listing what a server offers is
    # the only asynchronous thing this file touches, nothing else in the
    # workspace is an async test, and `asyncio_mode` is unconfigured - so a
    # coroutine here would be a new convention bought for one call.
    return [tool.name for tool in asyncio.run(server.list_tools())]


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
