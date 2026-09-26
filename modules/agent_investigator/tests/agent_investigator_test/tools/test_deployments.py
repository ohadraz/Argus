"""The channel that says what a deployment changed.

The fifth, and the second that is not a window over time. What a deployment
changed is a fact about one commit, so there is nothing to date, nothing to
widen, and no reading to record - but unlike the register it does take an
argument, because which deployment is being asked about is the model's to name
and there is more than one.

It is the one channel that composes with another. The change channel says a
deployment happened and gives its revision; this says what was in it. A model
holding the first answer has everything it needs to ask the second, which is why
the revision is the only argument and why its description names the channel it
comes from.

Its silence is not evidence, so it reports rather than raises. A repository that
could not be compared supports no conclusion about the deployment either way -
where the change channel raises because "nothing changed in this window" is a
conclusion something acts on, and a source never read must not arrive looking
like one read and found empty. Here the model is told, and can answer at a lower
confidence or say which distinction it could not make.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_investigator.retrieval import DeploymentDiffFetcher
from agent_investigator.tools.deployments import (
    DEPLOYMENT_DIFF_TOOL,
    REVISION_ARG,
    deployment_diff_tool,
    read_what_a_deployment_changed,
)
from argus_core.mcp_transport import McpToolError
from argus_core.models import ToolCall
from argus_testkit import Assertion, Scenario, all_of

SOME_SERVICE = "io-shop"

THE_REVISION_DEPLOYED = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_DEPLOYED_BEFORE = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"

THE_CONFIGURATION_FILE = "deploy/values-production.yaml"

WHAT_THE_READ_TIER_SAID = [
    f"Deployment of revision {THE_REVISION_DEPLOYED} to {SOME_SERVICE}, compared "
    f"against {THE_REVISION_DEPLOYED_BEFORE} - the revision deployed before it.",
    f"modified {THE_CONFIGURATION_FILE}",
    "  -  port: 6379",
    "  +  port: 6380"
]


@pytest.mark.unit
def test_the_answer_carries_what_the_deployment_changed() -> None:
    # Every line of it, unedited. What separates a bad deployment from a broken
    # configuration is inside the diff, and a channel that summarised it would be
    # deciding the distinction on the model's behalf.
    the_read_tier = a_deployment_that_changed(WHAT_THE_READ_TIER_SAID)

    Scenario() \
        .given(the_read_tier) \
        .when(
            lambda: read_what_a_deployment_changed(
                a_call_about(THE_REVISION_DEPLOYED), SOME_SERVICE, the_read_tier
            )
        ) \
        .then(all_of(
            _the_answer_mentions(THE_CONFIGURATION_FILE),
            _the_answer_mentions("port: 6380"),
            _it_was_served()
        ))


@pytest.mark.unit
def test_the_deployment_asked_about_is_the_one_the_model_named() -> None:
    # The revision comes out of the call rather than out of anything the loop
    # holds. There is one incident and one service, and there are as many
    # deployments as the history holds - so this is the one channel where the
    # subject is the model's to choose and getting it from elsewhere would answer
    # about a deployment nobody asked about.
    the_read_tier = a_deployment_that_changed(WHAT_THE_READ_TIER_SAID)

    Scenario() \
        .given(the_read_tier) \
        .when(
            lambda: read_what_a_deployment_changed(
                a_call_about(THE_REVISION_DEPLOYED), SOME_SERVICE, the_read_tier
            )
        ) \
        .then(_the_deployment_asked_about_was(
            the_read_tier, SOME_SERVICE, THE_REVISION_DEPLOYED
        ))


@pytest.mark.unit
def test_a_call_naming_no_revision_is_refused_with_the_reason() -> None:
    # A strict schema requires it, so this is not the ordinary case - but a
    # refusal the model can act on costs one turn, where reading the history for
    # a revision of `None` costs a request and answers about nothing.
    the_read_tier = a_deployment_that_changed(WHAT_THE_READ_TIER_SAID)

    Scenario() \
        .given(the_read_tier) \
        .when(
            lambda: read_what_a_deployment_changed(
                ToolCall(id="call-1", name=DEPLOYMENT_DIFF_TOOL, arguments={}),
                SOME_SERVICE,
                the_read_tier
            )
        ) \
        .then(all_of(
            _it_was_not_served(),
            _the_answer_mentions(REVISION_ARG),
            _nothing_was_asked_of(the_read_tier)
        ))


@pytest.mark.unit
def test_a_repository_that_could_not_be_read_is_reported_rather_than_ending_the_walk()\
        -> None:
    # The change channel raises when it cannot be read, because "nothing changed"
    # is a conclusion something acts on. This is the other case: a comparison
    # nobody could make supports no conclusion about the deployment at all, and
    # the model can still answer - at a lower confidence, or by naming the
    # distinction it could not draw. Ending the investigation over it would throw
    # away everything already retrieved to avoid a gap the model can report.
    the_read_tier = create_autospec(DeploymentDiffFetcher, instance=True)
    the_read_tier.side_effect = McpToolError("the repository could not be compared")

    Scenario() \
        .given(the_read_tier) \
        .when(
            lambda: read_what_a_deployment_changed(
                a_call_about(THE_REVISION_DEPLOYED), SOME_SERVICE, the_read_tier
            )
        ) \
        .then(all_of(
            _it_was_not_served(),
            _the_answer_mentions(THE_REVISION_DEPLOYED)
        ))


@pytest.mark.unit
def test_a_deployment_the_read_tier_had_nothing_to_say_about_is_still_answered()\
        -> None:
    # An answer of no lines at all, which the read tier does not produce and
    # which must not reach a model as empty text: empty reads exactly like a tool
    # that failed to say anything, and the model's next move for the two differs.
    the_read_tier = a_deployment_that_changed([])

    Scenario() \
        .given(the_read_tier) \
        .when(
            lambda: read_what_a_deployment_changed(
                a_call_about(THE_REVISION_DEPLOYED), SOME_SERVICE, the_read_tier
            )
        ) \
        .then(_the_answer_is_not_empty())


@pytest.mark.unit
def test_the_channel_records_no_reading() -> None:
    # A reading says which minutes are already in front of the model, and there
    # are no minutes here. One recorded for this would put a windowed retrieval in
    # the record for a question that has no window, and `channels_unread` would
    # begin reporting a channel that cannot be unread in the sense the others are.
    the_read_tier = a_deployment_that_changed(WHAT_THE_READ_TIER_SAID)

    Scenario() \
        .given(the_read_tier) \
        .when(
            lambda: read_what_a_deployment_changed(
                a_call_about(THE_REVISION_DEPLOYED), SOME_SERVICE, the_read_tier
            )
        ) \
        .then(_nothing_was_recorded_as_read())


@pytest.mark.unit
def test_the_tool_asks_for_a_revision_and_requires_it() -> None:
    # The schema and what serves it have to agree, which is why both halves of a
    # channel live in one module. An optional revision would be a tool the model
    # could call with nothing, to be told off for it a turn later.
    Scenario() \
        .when(lambda: deployment_diff_tool()) \
        .then(all_of(
            _the_tool_takes(REVISION_ARG),
            _the_tool_requires(REVISION_ARG)
        ))


def a_call_about(revision: str) -> ToolCall:
    return ToolCall(
        id="call-1",
        name=DEPLOYMENT_DIFF_TOOL,
        arguments={REVISION_ARG: revision}
    )


def a_deployment_that_changed(lines: list[str]) -> Any:
    the_read_tier = create_autospec(DeploymentDiffFetcher, instance=True)
    the_read_tier.return_value = lines

    return the_read_tier


def _the_answer_mentions(expected: str) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if expected not in answer.result.content:
            raise AssertionError(
                f"Expected the answer to mention [{expected}], and what the "
                f"model is shown is: {answer.result.content}"
            )

        return True

    return assertion


def _the_answer_is_not_empty() -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if not answer.result.content.strip():
            raise AssertionError(
                "The channel answered with empty text, which reads to a model "
                "exactly like a tool that failed to say anything."
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
                "A comparison that could not be made was served as evidence "
                "about the incident, so the model cannot tell a deployment it "
                "has been told about from one nobody could read."
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


def _the_deployment_asked_about_was(the_read_tier: Any,
                                   service: str,
                                   revision: str) -> Assertion[Any]:
    def assertion(dont_care_answer: Any) -> bool:
        asked = the_read_tier.call_args_list

        if not asked:
            raise AssertionError(
                f"Expected the read tier to be asked about [{revision}], and it "
                f"was not asked anything."
            )

        about = asked[0].args + tuple(asked[0].kwargs.values())

        if about[:2] != (service, revision):
            raise AssertionError(
                f"Expected the read tier to be asked about [{service}] at "
                f"[{revision}], and it was asked about {about}."
            )

        return True

    return assertion


def _nothing_was_asked_of(the_read_tier: Any) -> Assertion[Any]:
    def assertion(dont_care_answer: Any) -> bool:
        if the_read_tier.call_args_list:
            raise AssertionError(
                f"Expected a call with no revision to cost no retrieval, and "
                f"{the_read_tier.call_args_list} was asked for."
            )

        return True

    return assertion


def _the_tool_takes(argument: str) -> Assertion[Any]:
    def assertion(tool: Any) -> bool:
        if argument not in tool.properties:
            raise AssertionError(
                f"Expected the tool to offer [{argument}], and it offers "
                f"{sorted(tool.properties)}."
            )

        return True

    return assertion


def _the_tool_requires(argument: str) -> Assertion[Any]:
    def assertion(tool: Any) -> bool:
        if argument not in tool.required:
            raise AssertionError(
                f"Expected the tool to require [{argument}], and it requires "
                f"{sorted(tool.required)}."
            )

        return True

    return assertion
