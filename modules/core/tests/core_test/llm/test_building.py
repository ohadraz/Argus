"""Which client a caller is handed, over the provider it was given.

Two decisions, and neither is the choosing - the caller already chose, by
handing over a `ModelProvider`. What this pins is the rest of the factory's
job: a caller that asked for a receipt is handed a client that keeps one, a
caller that did not is handed the traced client itself rather than a recorder
wrapped around a sink that discards, and either way the policy it was built
with is what the provider is asked for and what the vendor is eventually sent.

The first two matter, and the second is the one nothing else would catch. A
factory that wrapped unconditionally would pass every test Argus has - the
recording is transparent - while charging a decorator to every agent that
never asked for one and putting a frame between every stack trace and the call
that raised.

The whole path - factory, recorder, a vendor's provider and its SDK - is driven
in `llm_anthropic`'s suite, where a provider that reaches a vendor can be built.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario
from core.llm import LLMClient, build_llm_client
from core.llm.recorded_client import RecordedLLMClient
from core.models import ModelPolicy, Reasoning
from core.models.tool_definition import ToolDefinition
from core.models.transcript import Transcript
from core.models.turn import Turn
from core.replay import Replay

from core_test.framework.llm import a_turn_that_said
from core_test.framework.replay import a_recorder_that_keeps_what_it_is_given

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"
# Whichever model and policy a client is built under, where the case is about
# something else.
DONT_CARE_MODEL = "dont-care-model"
DONT_CARE_POLICY = ModelPolicy(model=DONT_CARE_MODEL)

# Room of its own, stated rather than defaulted: the policy has to reach the
# provider whole, so every field of it is set to something a default is not.
SOME_ROOM = 128_000
SOME_BRIEF = "some standing brief"


@pytest.mark.unit
def test_a_caller_that_asked_for_no_receipt_is_handed_the_client_itself() -> None:
    # Unwrapped rather than wrapped around a recorder with nowhere to write:
    # an agent that is not recording should not pay for a decorator, and the
    # absence should be visible in a stack trace rather than one frame down.
    Scenario() \
        .given(
            an_agent_that_is_not_recording := None
        ) \
        .when(
            lambda: build_llm_client(_a_provider(), an_agent_that_is_not_recording,
                                     DONT_CARE_POLICY)
        ) \
        .then(
            _keeps_no_receipt()
        )


@pytest.mark.unit
def test_a_caller_that_asked_to_keep_a_receipt_is_handed_one_that_does() -> None:
    # The wrapping happens in the factory rather than at the call site, because
    # the recorder has to be told which model it is recording - which the
    # policy says, and the client it wraps cannot be asked.
    Scenario() \
        .given(
            an_incident_keeping_its_receipts := Replay(
                SOME_INCIDENT_ID, a_recorder_that_keeps_what_it_is_given().take)
        ) \
        .when(
            lambda: build_llm_client(_a_provider(), an_incident_keeping_its_receipts,
                                     DONT_CARE_POLICY)
        ) \
        .then(
            _keeps_a_receipt()
        )


@pytest.mark.unit
def test_the_provider_is_asked_for_a_client_under_the_callers_policy() -> None:
    # The provider is the one who knows how its vendor spells a model and an
    # effort, so the policy has to reach it whole. A factory that built the
    # client under a policy of its own would answer every agent as the same
    # one - in the same shape, and billed differently.
    some_policy = ModelPolicy(model="claude-haiku-4-5", effort=Reasoning.LOW,
                              max_output_tokens=SOME_ROOM, brief=SOME_BRIEF,
                              one_tool_call_per_turn=True)
    a_provider = _a_provider()

    Scenario() \
        .when(
            lambda: build_llm_client(a_provider, None, some_policy)
        ) \
        .then(
            _the_provider_was_asked_under(a_provider, some_policy)
        )


class _AProvider:
    """A `ModelProvider` handing out one prepared client, remembering the
    policy it was asked under.

    Hand-written rather than autospecced: `ModelProvider` is a Protocol, and
    `create_autospec` does not strip `self` from a Protocol's signature.
    """

    def __init__(self) -> None:
        self.asked_under: list[ModelPolicy] = []

    @property
    def name(self) -> str:
        return "some-provider"

    def client(self, policy: ModelPolicy, /) -> LLMClient:
        self.asked_under.append(policy)

        return _AClientThatSaid(a_turn_that_said("dont care what it said"))


class _AClientThatSaid:
    """An `LLMClient` answering every turn with one prepared turn."""

    def __init__(self, turn: Turn) -> None:
        self._turn = turn

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int | None = None) -> Turn:
        return self._turn


def _a_provider() -> _AProvider:
    return _AProvider()


def _the_provider_was_asked_under(provider: _AProvider,
                                  policy: ModelPolicy) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if provider.asked_under != [policy]:
            raise AssertionError(
                f"Expected the provider asked for one client under [{policy}], got "
                f"{provider.asked_under}."
            )

        return True

    return assertion


def _keeps_a_receipt() -> Assertion[object]:
    def assertion(client: object) -> bool:
        if not isinstance(client, RecordedLLMClient):
            raise AssertionError(
                f"Expected a client that keeps a receipt, got "
                f"[{type(client).__name__}].")

        return True

    return assertion


def _keeps_no_receipt() -> Assertion[object]:
    def assertion(client: object) -> bool:
        if isinstance(client, RecordedLLMClient):
            raise AssertionError(
                "Expected the client itself, and got it wrapped in a recorder "
                "with nothing to record to.")

        return True

    return assertion
