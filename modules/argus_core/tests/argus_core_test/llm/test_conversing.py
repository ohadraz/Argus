"""How an agent's model calls come to be written down.

The seam a loop talks through is one call, and it is deliberately a function
rather than a client: every unit test of a loop injects a scripted one and
never learns that a vendor exists. This is the other end of it - the
conversation built for real work, which keeps a receipt for the incident it
belongs to.

Here rather than in either agent that holds a loop. It was written twice, once
each in the Investigator and in Code-Fix, and the two copies agreed for exactly
as long as nobody changed one - long enough for a test to build its double from
the other agent's copy and still pass.

The incident is bound once by the factory rather than passed at each turn, for
the same reason a `Narrator` sits beside a loop: it is fixed for a whole
investigation or a whole fix, and a signature whose subject is a conversation
with a model should not carry Argus's domain through every call.

Everything this composes is tested elsewhere - `test_replay.py` holds the seam
and `test_recorded_client.py` holds the wrapping. What is left here is that the
two are joined to the right incident and the given recorder, which is the
wiring nothing else would notice getting wrong: a `Replay` built for the wrong
incident produces well-formed rows, plausible counts, and an eval that joins
them to an investigation which never made them.
"""

from __future__ import annotations

from typing import Any

import pytest
from argus_core.llm.client import LLMClient
from argus_core.llm.conversing import a_conversation_recorded_for
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, Transcript
from argus_core.models.turn import Turn
from argus_core.replay import CallType, Replay
from argus_testkit import Assertion, Scenario, all_of

from argus_core_test.framework.replay import (
    KeptEntries,
    a_recorder_that_keeps_what_it_is_given,
    the_entry_was_recorded_for,
)

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"
ANOTHER_INCIDENT_ID = "9f1b0d2e-5a44-4c31-8b77-2e6cf0a41d5c"

DONT_CARE_TRANSCRIPT: Transcript = [Ask(text="dont care what was asked")]
DONT_CARE_TURN = "dont care"


@pytest.mark.unit
def test_a_recorded_conversation_answers_from_the_client_it_was_built_with() -> None:
    # First, that it is still a conversation. A seam that recorded perfectly and
    # returned something other than the model's turn would fail every
    # investigation while every assertion about recording still passed.
    a_turn = _a_turn_that_said("the error rate climbs at 22:15")

    Scenario() \
        .given(
            asked_for := _a_client_asked_for(_a_client_that_answers(a_turn))
        ) \
        .when(
            lambda: _a_recorded_conversation(asked_for)(
                DONT_CARE_TRANSCRIPT, [_a_tool()]
            )
        ) \
        .then(
            _the_turn_returned_was(a_turn)
        )


@pytest.mark.unit
def test_the_conversation_and_the_tools_reach_the_client_unchanged() -> None:
    # The seam carries both, and both are the model's whole input: a transcript
    # that arrived short is a question nobody asked, and a tool list that
    # arrived short is an answer the model was not allowed to give.
    some_tools = [_a_tool(), _a_tool(name="get_changes")]

    Scenario() \
        .given(
            asked_for := _a_client_asked_for(
                answering := _a_client_that_answers(_a_turn_that_said(DONT_CARE_TURN))
            )
        ) \
        .when(
            lambda: _a_recorded_conversation(asked_for)(DONT_CARE_TRANSCRIPT, some_tools)
        ) \
        .then(
            all_of(
                _the_client_was_asked_about(answering, DONT_CARE_TRANSCRIPT),
                _the_client_was_offered(answering, some_tools)
            )
        )


@pytest.mark.unit
def test_the_client_is_asked_for_one_recording_this_incident_to_this_recorder() -> None:
    # Both halves of the wiring, asserted through the only door the design
    # offers: what a `Replay` was bound to is private to it, so a call is
    # recorded through the one the factory handed over and the entry that comes
    # out the other side is read.
    #
    # Both are worth checking and neither implies the other. A `Replay` built
    # for the wrong incident writes well-formed rows an eval joins to an
    # investigation that never made them; one handed a recorder nobody supplied
    # is simply silent, and silence is what a replay log that is not being
    # written looks like from every angle except this one.
    #
    # An incident id that is not this file's usual one, so that a factory
    # ignoring what it was given and reaching for a default cannot pass.
    asked_for = _a_client_asked_for(_a_client_that_answers(_a_turn_that_said(DONT_CARE_TURN)))

    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _a_call_recorded_by_the_conversation_built_for(
                asked_for, ANOTHER_INCIDENT_ID, recorded.take
            )
        ) \
        .then(
            the_entry_was_recorded_for(recorded, ANOTHER_INCIDENT_ID)
        )


class _AClientThatAnswers:
    """An `LLMClient` returning a prepared turn, remembering what it was asked.

    Hand-written rather than autospecced: `LLMClient` is a Protocol, and
    `create_autospec` does not strip `self` from a Protocol's signature, which
    makes every argument assertion fail while printing identically.
    """

    def __init__(self, turn: Turn) -> None:
        self._turn = turn
        self.asked_about: Transcript | None = None
        self.offered: list[ToolDefinition] | None = None

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int = 1) -> Turn:
        self.asked_about = transcript
        self.offered = tools

        return self._turn


class _AClientAskedFor:
    """A stand-in for `build_llm_client`, remembering the `Replay` it was handed.

    The seam this file exists to check. The real one builds an SDK client from
    configuration, which a unit test has none of and should not need: what is
    under test is what the factory asks for, not what answers.
    """

    def __init__(self, client: LLMClient) -> None:
        self._client = client
        self.replay: Replay | None = None

    def for_replay(self, replay: Replay) -> LLMClient:
        """The seam itself, as a method rather than `__call__`.

        `Scenario.given` runs a callable step, so an object that *is* the
        function gets invoked while being arranged - handed over as
        `asked_for.for_replay`, only the factory can call it.
        """
        self.replay = replay

        return self._client

    def the_replay(self) -> Replay:
        if self.replay is None:
            raise AssertionError("Expected a client to have been asked for, and none was.")

        return self.replay


def _a_client_that_answers(turn: Turn) -> _AClientThatAnswers:
    return _AClientThatAnswers(turn)


def _a_client_asked_for(client: _AClientThatAnswers) -> _AClientAskedFor:
    return _AClientAskedFor(client)


def _a_recorded_conversation(asked_for: _AClientAskedFor,
                             incident_id: str = SOME_INCIDENT_ID,
                             recorder: Any = None) -> Any:
    """The subject of this file, built over a client that answers on the spot."""
    kept_by_nobody: KeptEntries = a_recorder_that_keeps_what_it_is_given()

    return a_conversation_recorded_for(
        incident_id,
        recorder if recorder is not None else kept_by_nobody.take,
        client_for=asked_for.for_replay
    )


def _a_call_recorded_by_the_conversation_built_for(asked_for: _AClientAskedFor,
                                                   incident_id: str,
                                                   recorder: Any) -> bool:
    """Builds the conversation, then records one call through what it asked for.

    Two steps in one because the second is only reachable through the first:
    the `Replay` under test does not exist until the factory has run, and it is
    handed to the client rather than returned.
    """
    _a_recorded_conversation(asked_for, incident_id=incident_id, recorder=recorder)

    return _one_call_recorded_through(asked_for)


def _one_call_recorded_through(asked_for: _AClientAskedFor) -> bool:
    """Records one call through whatever `Replay` the factory built.

    The only way to read a binding that is otherwise private to the object
    holding it - and the same way the wrapped client would use it.
    """
    asked_for.the_replay().record(
        call_type=CallType.LLM,
        target="dont-care-model",
        request={"dont": "care"},
        response={"dont": "care"},
        latency_ms=1
    )

    return True


def _a_tool(name: str = "get_logs") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Return the service's log lines for a time window.",
        properties={"window_start": {"type": "string"}},
        required=["window_start"]
    )


def _a_turn_that_said(said: str) -> Turn:
    dont_care_tokens = 1

    return Turn(
        text=said,
        tool_calls=[],
        input_tokens=dont_care_tokens,
        output_tokens=dont_care_tokens
    )


def _the_turn_returned_was(turn: Turn) -> Assertion[Turn]:
    def assertion(returned: Turn) -> bool:
        if returned != turn:
            raise AssertionError(f"Expected [{turn!r}] back, got [{returned!r}].")

        return True

    return assertion


def _the_client_was_asked_about(client: _AClientThatAnswers,
                                transcript: Transcript) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        if client.asked_about != list(transcript):
            raise AssertionError(
                f"Expected the client asked about {list(transcript)!r}, "
                f"got {client.asked_about!r}."
            )

        return True

    return assertion


def _the_client_was_offered(client: _AClientThatAnswers,
                            tools: list[ToolDefinition]) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        if client.offered != tools:
            raise AssertionError(
                f"Expected the client offered {tools!r}, got {client.offered!r}."
            )

        return True

    return assertion
