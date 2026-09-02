from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from argus_core.llm.client import LLMClient
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn
from argus_core.replay import Recorder, Replay

Conversation = Callable[[Transcript, list[ToolDefinition]], Turn]

# How a client is obtained for one investigation. A parameter rather than a
# direct call, so a test of the wiring can see what was asked for without
# configuration, an API key or the SDK - the real one needs all three.
ClientFor = Callable[[Replay], LLMClient]


@lru_cache(maxsize=1)
def _llm_client() -> LLMClient:
    """The one client the whole process shares.

    Built on first use rather than at import, and the import is deferred with
    it: choosing a client pulls in a vendor's SDK, and a module that only ever
    injects a double - every unit test of the loop - must pay for neither the
    import nor the settings the client reads at construction.
    """
    from argus_core.llm.client_selection import get_llm_client

    return get_llm_client()


def converse(transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
    """Hands the model the conversation so far and asks what it wants to do next.

    A module-level function rather than the client object itself, so the loop's
    seam is one call, and so a test can `create_autospec` it against a real
    public name instead of a Protocol.

    Usually the answer is not an answer. A turn is whatever the model wants
    next - a retrieval, a remark, or the one tool call that ends the
    investigation - and which of those it is, is the loop's to read rather than
    this seam's to interpret.
    """
    return _llm_client().converse(transcript, tools)


def _a_recording_client(replay: Replay) -> LLMClient:
    """The real client, wrapped so it keeps a receipt for this incident.

    Imported inside for the same reason `_llm_client` defers its import:
    choosing a client pulls in a vendor's SDK, and the loop's unit tests -
    which inject a scripted conversation and never reach here - should pay for
    neither the import nor the configuration it reads on the way up.
    """
    from argus_core.llm.client_selection import get_llm_client

    return get_llm_client(replay)


def a_conversation_recorded_for(incident_id: str,
                                recorder: Recorder,
                                client_for: ClientFor = _a_recording_client) -> Conversation:
    """The conversational seam for a real investigation, writing down its calls.

    A factory rather than a parameter on `converse`, because the incident is
    fixed for a whole investigation while the transcript is not. Binding it once
    is what keeps an incident id out of a signature whose subject is a
    conversation with a model - the same reasoning that puts a `Narrator`
    beside the loop instead of an incident id in every call that has something
    to report.

    Not cached, unlike `_llm_client`. The wrapper holds the incident it records
    for, so one instance shared across a process would file every incident's
    calls under whichever was investigated first. What is expensive - reading
    configuration and building the SDK client - is cached inside the adapter,
    where it is the same for every incident.
    """
    client = client_for(Replay(incident_id, recorder))

    def converse_and_record(transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
        return client.converse(transcript, tools)

    return converse_and_record
