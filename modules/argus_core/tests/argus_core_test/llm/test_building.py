"""Which client a caller gets when it brings none of its own.

Two decisions, and neither is the choosing. There is a single adapter and no
alternative to weigh it against, so what this pins is the rest of the factory's
job: a caller that asked for a receipt is handed a client that keeps one, a
caller that did not is handed the adapter itself rather than a recorder wrapped
around a sink that discards, and either way the policy it was built with is
what the vendor is eventually asked for.

The first two matter, and the second is the one nothing else would catch. A
factory that wrapped unconditionally would pass every test Argus has - the
recording is transparent - while charging a decorator to every agent that
never asked for one and putting a frame between every stack trace and the call
that raised.

The third is here because nothing else assembles the whole path. The recorder
implements the same Protocol as the thing it wraps, and a default declared on
one implementation and not the other is invisible from both ends: the agent
above still calls two arguments, the adapter below still reads a figure and
believes it, and every suite passes while the per-agent cap is discarded one
layer down. That is not a hypothetical - it is what happened, and it was the
factory's own wiring that nothing drove.

`component` rather than `unit`: the factory reads the process's settings and
builds a vendor client out of them, neither of which it takes as a parameter.
Nothing leaves the process, though - the SDK stand-in answers, and
constructing a real client talks to nobody - so this costs no tokens and needs
no key.

And one thing that is not about the client at all: what it costs to name the
door this is exported from. That is `building.py`'s property - it is the
module that decides when the adapter is reached - and it is here because a
separation stated in a docstring and checked by nothing is a separation that
was quietly undone once already.
"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import Mock

import pytest
from argus_core.llm import build_llm_client
from argus_core.llm.recorded_client import RecordedLLMClient
from argus_core.models import ModelPolicy
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask
from argus_core.models.turn import Turn
from argus_core.replay import Replay
from argus_testkit import Assertion, Scenario

from argus_core_test.framework.llm import an_api_that_answers
from argus_core_test.framework.replay import a_recorder_that_keeps_what_it_is_given

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"

# What Code-Fix is configured to get, stated rather than read: the subject here
# is whether a policy survives the wiring, not what today's deployment sets.
# Above `LARGEST_UNSTREAMED_ANSWER` by design - an answer that is a whole file
# can only be asked for by streaming, so the figure and the transport are one
# fact and a test that checked either alone would pass on half a defect.
A_WHOLE_FILES_WORTH_OF_ROOM = 128_000


@pytest.mark.component
def test_a_caller_that_asked_for_no_receipt_is_handed_the_client_itself() -> None:
    # Unwrapped rather than wrapped around a recorder with nowhere to write:
    # an agent that is not recording should not pay for a decorator, and the
    # absence should be visible in a stack trace rather than one frame down.
    Scenario() \
        .given(
            an_agent_that_is_not_recording := None
        ) \
        .when(
            lambda: build_llm_client(an_agent_that_is_not_recording)
        ) \
        .then(
            _keeps_no_receipt()
        )


@pytest.mark.component
def test_a_caller_that_asked_to_keep_a_receipt_is_handed_one_that_does() -> None:
    # The wrapping happens in the factory rather than at the call site, because
    # the recorder has to be told which model it is recording and that is the
    # one fact a caller managed to avoid knowing.
    Scenario() \
        .given(
            an_incident_keeping_its_receipts := Replay(
                SOME_INCIDENT_ID, a_recorder_that_keeps_what_it_is_given().take)
        ) \
        .when(
            lambda: build_llm_client(an_incident_keeping_its_receipts)
        ) \
        .then(
            _keeps_a_receipt()
        )


@pytest.mark.component
def test_a_recorded_agent_asks_the_vendor_for_the_room_its_policy_gave_it() -> None:
    # Driven through the whole assembly - factory, recorder, adapter, SDK -
    # because the defect this exists for lived in none of them and in the
    # joins. The recorder declared a cap of its own and handed it down; the
    # adapter reads any figure it is given as the caller's word; and the seam
    # an agent holds calls with two arguments, so the recorder's figure was
    # the one supplied every time. A per-agent cap read from configuration was
    # therefore discarded one layer below where it was set, on every
    # production conversation there has ever been, and the streaming path was
    # unreachable.
    #
    # Recorded rather than bare, because that is the only shape production
    # runs in: an unrecorded client would traverse the one path where the
    # defect could not occur.
    some_api = an_api_that_answers()
    a_code_fix_policy = ModelPolicy(max_output_tokens=A_WHOLE_FILES_WORTH_OF_ROOM)
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            writing_whole_files := build_llm_client(
                Replay(SOME_INCIDENT_ID, a_recorder_that_keeps_what_it_is_given().take),
                a_code_fix_policy,
                client=some_api
            )
        ) \
        .when(
            # Two arguments, as the loop above one of these has: the room is
            # nobody's to name up there, which is what made a default declared
            # here the last word on it.
            lambda: writing_whole_files.converse(dont_care_transcript, [_a_tool()])
        ) \
        .then(
            _the_vendor_was_asked_for(some_api, A_WHOLE_FILES_WORTH_OF_ROOM)
        )


@pytest.mark.component
def test_naming_the_front_door_does_not_import_a_vendor() -> None:
    # The separation this module's docstring claims, asked rather than
    # asserted in prose. It was claimed and untrue for as long as the adapter
    # was named at the top of `building.py`: `argus_core.llm` re-exports
    # `build_llm_client`, so naming the interface cost every caller 0.6
    # seconds of Anthropic SDK. Nothing failed, because nothing asked.
    #
    # Not vacuous in an environment without the SDK: `llm/adapters/
    # test_caching.py` imports `anthropic` outright, so a suite that could
    # pass this by having none would fail there first.
    Scenario() \
        .given(
            naming_the_front_door := "import argus_core.llm"
        ) \
        .when(
            lambda: _the_modules_a_fresh_interpreter_has_after(naming_the_front_door)
        ) \
        .then(
            _nothing_imported("anthropic")
        )


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


def _the_vendor_was_asked_for(api: Mock, room: int) -> Assertion[Turn]:
    """That the policy the client was built with is what reached the API.

    Read off the call rather than the answer, and off the streamed call
    specifically. Both halves are the same fact: a cap this size can only be
    asked for by streaming, so a request that arrived in one piece did not
    carry it whatever it says, and a streamed request carrying the old cap is
    an agent that still cannot emit a file. The answer looks the same in every
    one of those cases.
    """
    def assertion(_: Turn) -> bool:
        if not api.messages.stream.called:
            asked = api.messages.create.call_args
            raise AssertionError(
                f"Expected room for [{room}] tokens, which can only be asked for by "
                f"streaming, and the request was made in one piece asking {asked}."
            )

        given = api.messages.stream.call_args.kwargs.get("max_tokens")
        if given != room:
            raise AssertionError(
                f"Expected the agent's own room of [{room}] tokens to reach the API, "
                f"got [{given}]."
            )

        return True

    return assertion


def _a_tool() -> ToolDefinition:
    return ToolDefinition(
        name="read_repository_file",
        description="Return the current contents of one file in the repository.",
        properties={"path": {"type": "string"}},
        required=["path"]
    )


def _the_modules_a_fresh_interpreter_has_after(naming: str) -> set[str]:
    """Everything in `sys.modules` of a new interpreter that has run this.

    A subprocess rather than a snapshot of this one. The suite imported the
    adapter long before this test ran - in the three files whose subject it is
    - and an import that has already happened cannot be watched not happening.
    """
    reading_them_back = "import sys; print(' '.join(sys.modules))"
    finished = subprocess.run(
        [sys.executable, "-c", f"{naming}; {reading_them_back}"],
        capture_output=True,
        text=True,
        check=True
    )

    return set(finished.stdout.split())


def _nothing_imported(vendor: str) -> Assertion[set[str]]:
    def assertion(imported: set[str]) -> bool:
        if vendor in imported:
            raise AssertionError(
                f"Expected naming the front door to leave [{vendor}] unimported, "
                f"and {len(imported)} modules were loaded including it."
            )

        return True

    return assertion
