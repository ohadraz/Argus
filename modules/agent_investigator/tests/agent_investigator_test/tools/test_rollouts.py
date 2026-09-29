"""The channel that says whether the deployment finished arriving.

The Investigator's sixth, and the third that is not a window over time. Whether
a rollout converged is a fact about the deployment running now, so there is
nothing to date, nothing to widen and no reading to record - and, like the
register, nothing for a model to name: the service is the incident's.

Its silence is not evidence, so it reports rather than raises, and here that
matters more than anywhere else in the tier. The answer this channel gives most
often is that the deployment converged, which *rules a mode out* - so a failure
that arrived looking like an empty answer would not merely be a gap, it would be
read as the finding that sends a walk back to blame the revision.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_investigator.retrieval import RolloutFetcher
from agent_investigator.tools.rollouts import ROLLOUT_TOOL, read_the_rollout
from argus_core.mcp_transport import McpToolError
from argus_core.models import ToolCall
from argus_testkit import Assertion, Scenario, all_of

SOME_SERVICE = "io-shop"
SOME_CALL = ToolCall(id="call-1", name=ROLLOUT_TOOL, arguments={})

A_SPLIT_FLEET = (
    "Deployment of io-shop has not converged: 3 of 6 replicas are running "
    "revision [9c1f0ab], and 3 are still running revision [544cef3]."
)
IT_IS_PAUSED = (
    "Its rolling update is paused, so the platform is not converging it on its "
    "own."
)
A_CONVERGED_FLEET = (
    "Deployment of io-shop has converged: all 6 replicas are running revision "
    "[9c1f0ab], deployed at 2026-08-20T11:05:00Z."
)


@pytest.mark.unit
def test_the_answer_carries_what_the_platform_said_about_the_rollout() -> None:
    # Passed through rather than summarised. What separates this mode from a bad
    # deployment is a replica count and a pause, and a channel that condensed
    # them into a verdict would be making the reading it exists to enable.
    platform = a_platform_reporting(A_SPLIT_FLEET, IT_IS_PAUSED)

    Scenario() \
        .given(platform) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform)) \
        .then(all_of(
            _the_answer_mentions("not converged"),
            _the_answer_mentions("paused"),
            _it_was_served()
        ))


@pytest.mark.unit
def test_a_converged_deployment_is_served_as_the_evidence_it_is() -> None:
    # The ordinary answer, and not a blank. A reader weighing a deploy at the
    # onset has been told the deploy is not half-applied, which rules this mode
    # out and leaves the revision itself as the subject.
    platform = a_platform_reporting(A_CONVERGED_FLEET)

    Scenario() \
        .given(platform) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform)) \
        .then(all_of(
            _the_answer_mentions("converged"),
            _it_was_served()
        ))


@pytest.mark.unit
def test_a_platform_nobody_can_reach_is_reported_rather_than_ending_the_walk() -> None:
    # The register's case rather than the change channel's: a rollout nobody
    # could read supports no conclusion either way, and the model can still
    # answer - at a lower confidence, or by naming the distinction it could not
    # draw. Ending the investigation over it would throw away everything already
    # retrieved to avoid a gap the model is able to report.
    platform = create_autospec(RolloutFetcher, instance=True)
    platform.side_effect = McpToolError("nobody answered")

    Scenario() \
        .given(platform) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform)) \
        .then(all_of(
            _it_was_not_served(),
            _the_answer_mentions("rollout")
        ))


@pytest.mark.unit
def test_an_empty_answer_is_said_as_unread_and_never_as_converged() -> None:
    # The failure worth a test of its own. Everywhere else an empty answer is a
    # gap; here the answer a reader most expects is "it converged", so emptiness
    # left to speak for itself is not a missing finding but the wrong one - and
    # the wrong one sends a walk to blame a revision that is not at fault.
    platform = a_platform_reporting()

    Scenario() \
        .given(platform) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform)) \
        .then(all_of(
            _the_answer_mentions("unread"),
            _the_answer_says_nothing_about_having_converged()
        ))


@pytest.mark.unit
def test_the_channel_records_no_reading() -> None:
    # Every windowed channel records one, and a reading is what says which
    # minutes are already in front of the model. There are no minutes here, so a
    # reading would put a windowed retrieval in the record for a question that
    # has no window.
    platform = a_platform_reporting(A_CONVERGED_FLEET)

    Scenario() \
        .given(platform) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform)) \
        .then(_nothing_was_recorded_as_read())


def a_platform_reporting(*lines: str) -> Any:
    platform = create_autospec(RolloutFetcher, instance=True)
    platform.return_value = list(lines)

    return platform


def _the_answer_mentions(expected: str) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if expected not in answer.result.content:
            raise AssertionError(
                f"Expected the answer to mention [{expected}], and what the "
                f"model is shown is: {answer.result.content}"
            )

        return True

    return assertion


def _the_answer_says_nothing_about_having_converged() -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if "converged" in answer.result.content:
            raise AssertionError(
                f"An answer the read tier gave nothing for says something about "
                f"convergence, which is the one thing it cannot know and the one "
                f"reading that rules this mode out: {answer.result.content}"
            )

        return True

    return assertion


def _it_was_served() -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer.result.failed:
            raise AssertionError(
                f"Expected the call to be served as evidence, and it came back "
                f"marked failed: {answer.result.content}"
            )

        return True

    return assertion


def _it_was_not_served() -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if not answer.result.failed:
            raise AssertionError(
                "A rollout that could not be read was served as evidence about "
                "the incident, so the model cannot tell a deployment it has been "
                "told about from one nobody could ask about."
            )

        return True

    return assertion


def _nothing_was_recorded_as_read() -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer.reading is not None:
            raise AssertionError(
                f"Expected no reading for a channel with no window, and one was "
                f"recorded: {answer.reading}."
            )

        return True

    return assertion
