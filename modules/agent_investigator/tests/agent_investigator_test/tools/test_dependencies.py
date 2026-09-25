"""The channel that says whose the failing dependency is.

The only one of the Investigator's channels that is not a window over time. What
a service calls is a fact about how it is built, so there is nothing to date and
nothing to widen - which is why it takes no arguments and records no reading.

It is also the only channel whose silence is not itself evidence. "Nothing
changed in this window" is a conclusion something acts on, which is why the
change channel raises rather than answering emptily; a register that cannot be
reached supports no conclusion at all, so the model is told and goes on.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_investigator.retrieval import DependencyFetcher
from agent_investigator.tools.dependencies import DEPENDENCIES_TOOL, read_dependencies
from argus_core.mcp_transport import McpToolError
from argus_core.models import Ownership, ServiceDependency, ToolCall
from argus_testkit import Assertion, Scenario, all_of

SOME_SERVICE = "io-shop"
SOME_CALL = ToolCall(id="call-1", name=DEPENDENCIES_TOOL, arguments={})


@pytest.mark.unit
def test_the_answer_names_each_dependency_and_whose_it_is() -> None:
    # Both halves in the text the model reads. The name is what an action is
    # addressed to; whose it is decides whether there is an action at all.
    registry = a_register_holding(
        _a_dependency("io-pricing", Ownership.INTERNAL),
        _a_dependency("io-pay", Ownership.THIRD_PARTY)
    )

    Scenario() \
        .given(registry) \
        .when(lambda: read_dependencies(SOME_CALL, SOME_SERVICE, registry)) \
        .then(all_of(
            _the_answer_mentions("io-pricing"),
            _the_answer_mentions("io-pay"),
            _the_answer_mentions(Ownership.INTERNAL),
            _the_answer_mentions(Ownership.THIRD_PARTY),
            _it_was_served()
        ))


@pytest.mark.unit
def test_the_answer_says_what_each_dependency_is_for() -> None:
    # What the dependency was doing on the request path is how the incident is
    # diagnosed. A list of names would have the model guessing from spellings,
    # which is the guessing this channel exists to end.
    some_purpose = "prices a basket while the account page renders"
    registry = a_register_holding(
        _a_dependency("io-pricing", Ownership.INTERNAL, purpose=some_purpose)
    )

    Scenario() \
        .given(registry) \
        .when(lambda: read_dependencies(SOME_CALL, SOME_SERVICE, registry)) \
        .then(_the_answer_mentions(some_purpose))


@pytest.mark.unit
def test_a_service_with_nothing_registered_is_told_so_in_words() -> None:
    # An empty answer and a missing one read alike to a model, so the empty case
    # says what it is: as far as the register knows, this service calls nothing.
    registry = a_register_holding()

    Scenario() \
        .given(registry) \
        .when(lambda: read_dependencies(SOME_CALL, SOME_SERVICE, registry)) \
        .then(all_of(
            _it_was_served(),
            _the_answer_is_not_empty()
        ))


@pytest.mark.unit
def test_a_register_nobody_can_reach_is_reported_rather_than_ending_the_walk() -> None:
    # The change channel raises when it cannot be read, because "nothing
    # changed" is a conclusion something acts on and a source that was never
    # read must not arrive looking like one that was read and found empty.
    #
    # This channel is the other case. An unreadable register supports no
    # conclusion either way, and the model can still answer - at a lower
    # confidence, or by saying which distinction it could not make. Killing the
    # investigation over it would throw away everything already retrieved to
    # avoid a gap the model is perfectly able to report.
    registry = create_autospec(DependencyFetcher, instance=True)
    registry.side_effect = McpToolError("nobody answered")

    Scenario() \
        .given(registry) \
        .when(lambda: read_dependencies(SOME_CALL, SOME_SERVICE, registry)) \
        .then(all_of(
            _it_was_not_served(),
            _the_answer_mentions("register")
        ))


@pytest.mark.unit
def test_the_channel_records_no_reading() -> None:
    # Every other channel reads a window, and a reading is what says which
    # minutes are already in front of the model. There are no minutes here, so a
    # reading would put a windowed retrieval in the record for a question that
    # has no window - and `channels_unread` would start reporting a channel that
    # cannot be unread in the sense the others are.
    registry = a_register_holding(_a_dependency("io-pricing", Ownership.INTERNAL))

    Scenario() \
        .given(registry) \
        .when(lambda: read_dependencies(SOME_CALL, SOME_SERVICE, registry)) \
        .then(_nothing_was_recorded_as_read())


def a_register_holding(*dependencies: ServiceDependency) -> Any:
    registry = create_autospec(DependencyFetcher, instance=True)
    registry.return_value = list(dependencies)

    return registry


def _a_dependency(name: str,
                  ownership: str,
                  purpose: str = "something the caller needs") -> ServiceDependency:
    return ServiceDependency(
        name=name,
        purpose=purpose,
        host=f"{name}.example",
        owner="some-team",
        ownership=ownership
    )


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
                "A service the register holds nothing for was answered with "
                "empty text, which reads to a model exactly like a tool that "
                "failed to say anything."
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
                "A register that could not be read was served as evidence "
                "about the incident, so the model cannot tell an unknown "
                "estate from one it has been told about."
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
