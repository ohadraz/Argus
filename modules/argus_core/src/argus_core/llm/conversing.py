"""Building the conversation an agent's loop talks through, with its receipt.

Two agents run a loop that talks to a model, and both need the same thing: one
call to make, and every call filed under the incident that caused it. That is
one shape and one factory, so it is here rather than once in each of them -
which is where it was, written twice, until a test reached for the wrong copy
and kept passing because the two copies still agreed.

`ClientFor` next door moved for the same reason a version earlier. A type two
modules both name is a contract, and so is the factory that produces one.
"""

from __future__ import annotations

from collections.abc import Callable

from argus_core.llm.building import build_llm_client
from argus_core.llm.client import ClientFor, Conversation
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn
from argus_core.replay import Recorder, Replay

# How a recorded conversation is built once the incident is known. Named as a
# shape so a loop can take the factory itself as a seam: a test hands over
# something it can assert was asked for, where production hands over the one
# below.
type Conversations = Callable[[str, Recorder], Conversation]


def a_conversation_recorded_for(
    incident_id: str,
    recorder: Recorder,
    client_for: ClientFor = build_llm_client
) -> Conversation:
    """The conversational seam for real work, writing down what it costs.

    A factory rather than a parameter on the call, because the incident is
    fixed for a whole investigation or a whole fix while the transcript is not.
    Binding it once keeps an incident id out of a signature whose subject is a
    conversation with a model - the same reasoning that puts a `Narrator`
    beside a loop instead of an incident id in every call with something to
    report.

    Nothing is cached, here or below. The wrapper holds the incident it records
    for, so one shared across a process would file every later incident's calls
    under whichever was walked first - and the client it wraps is rebuilt with
    it, because `build_llm_client` constructs an adapter and an SDK client on
    every call. Reading the configuration is the one cached part, and that is
    `config`'s doing rather than anything under here. What this costs is one
    SDK client per incident, paid when the incident starts and not per turn.

    `client_for` is a seam rather than a fixed call so a test can assert what
    was asked for without a vendor answering. It defaults to the real builder,
    which already has this shape.
    """
    client = client_for(Replay(incident_id, recorder))

    def converse_and_record(transcript: Transcript,
                            tools: list[ToolDefinition], /) -> Turn:
        return client.converse(transcript, tools)

    return converse_and_record
