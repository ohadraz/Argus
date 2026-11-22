"""The provider, built into a client by the kernel's factory, as a process uses it.

Here because nothing else assembles the whole path. The recorder implements the
same Protocol as the thing it wraps, and a default declared on one
implementation and not the other is invisible from both ends: the agent above
still calls two arguments, the adapter below still reads a figure and believes
it, and every suite passes while the per-agent cap is discarded one layer down.
That is not a hypothetical - it is what happened, and it was the factory's own
wiring that nothing drove. These cases build the provider over an SDK stand-in,
or one listening on a port of its own; nothing leaves the machine, so they cost
no tokens and need no key.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest
from anthropic.types import Message, TextBlock, Usage
from argus_testkit import Assertion, Kept, Scenario
from core.llm import build_llm_client
from core.models import Ask, ModelPolicy, ToolDefinition, Turn
from core.replay import Replay, ReplayEntry
from llm_anthropic import (
    ASSISTANT_ROLE,
    END_TURN_STOP_REASON,
    MESSAGE_TYPE,
    TEXT_TYPE,
    AnthropicProvider,
    AnthropicSettings,
)

from llm_anthropic_test.framework.llm import an_api_that_answers, settings_that_reach_no_api

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"
SOME_KEY = "some-key"
# Whichever model and policy a client is built under, where the case is about
# something else.
DONT_CARE_MODEL = "dont-care-model"
DONT_CARE_POLICY = ModelPolicy(model=DONT_CARE_MODEL)

# What Code-Fix is configured to get, stated rather than read: the subject here
# is whether a policy survives the wiring, not what today's deployment sets.
# Above `LARGEST_UNSTREAMED_ANSWER` by design - an answer that is a whole file
# can only be asked for by streaming, so the figure and the transport are one
# fact and a test that checked either alone would pass on half a defect.
A_WHOLE_FILES_WORTH_OF_ROOM = 128_000


@pytest.mark.integration
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
    a_code_fix_policy = ModelPolicy(model=DONT_CARE_MODEL,
                                    max_output_tokens=A_WHOLE_FILES_WORTH_OF_ROOM)
    dont_care_transcript = [Ask(text="dont care what was asked")]

    Scenario() \
        .given(
            writing_whole_files := build_llm_client(
                AnthropicProvider(settings_that_reach_no_api(), sdk=some_api),
                Replay(SOME_INCIDENT_ID, Kept[ReplayEntry]().take),
                a_code_fix_policy
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


@pytest.mark.integration
def test_a_provider_handed_settings_of_its_own_reaches_the_model_where_they_say() -> None:
    # The grounding judge is reached at an address of its own, so a replay can
    # serve it from a stand-in of its own. A client that read the process's
    # settings whatever its provider was built with would ask the writer's
    # stand-in, and be served the writer's recordings out of turn.
    with _an_api_listening() as an_api:
        Scenario() \
            .given(
                a_judge := build_llm_client(
                    AnthropicProvider(AnthropicSettings(anthropic_api_key=SOME_KEY,
                                                        anthropic_base_url=an_api.address)),
                    None,
                    DONT_CARE_POLICY
                )
            ) \
            .when(
                lambda: a_judge.converse([Ask(text="dont care what was asked")], [_a_tool()])
            ) \
            .then(
                _it_was_asked(an_api)
            )


class _AnApiListening:
    """A stand-in for the Messages API at an address of its own, answering
    every request with one finished turn and keeping the path of each."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.asked: list[str] = []


@contextmanager
def _an_api_listening() -> Generator[_AnApiListening]:
    """The stand-in, listening on a port of its own on this machine for as
    long as the block runs."""
    answered = Message(id="dont_care_id", model="dont_care_model", role=ASSISTANT_ROLE,
                       type=MESSAGE_TYPE, stop_reason=END_TURN_STOP_REASON, stop_sequence=None,
                       content=[TextBlock(type=TEXT_TYPE, text="dont care what it said")],
                       usage=Usage(input_tokens=1, output_tokens=1)).model_dump_json().encode()
    asked: list[str] = []

    class Answering(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            asked.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(answered)))
            self.end_headers()
            self.wfile.write(answered)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Answering)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    listening = _AnApiListening(f"http://127.0.0.1:{server.server_address[1]}")
    listening.asked = asked
    try:
        yield listening
    finally:
        server.shutdown()
        server.server_close()


def _it_was_asked(api: _AnApiListening) -> Assertion[Turn]:
    def assertion(_: Turn) -> bool:
        if len(api.asked) != 1:
            raise AssertionError(
                f"Expected the model asked once at [{api.address}], and it was asked "
                f"there {len(api.asked)} times: {api.asked}.")

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
