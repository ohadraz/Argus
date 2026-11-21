"""Building the conversation an agent's loop talks through, with its receipt.

Two agents run a loop that talks to a model, and both need the same thing: one
call to make, and every call filed under the incident that caused it. That is
one shape and one factory, so it is here rather than once in each of them -
which is where it was, written twice, until a test reached for the wrong copy
and kept passing because the two copies still agreed.

`ClientFor` next door moved for the same reason a version earlier. A type two
modules both name is a contract, and so is the factory that produces one.

Nothing here has a default that reaches a vendor. An agent is handed its
`Conversations` by whoever assembled it, built over the provider that process
chose (`conversations_through`), so which model answers is decided in one
place and visible there.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Protocol

from core.llm.building import build_llm_client
from core.llm.client import ClientFor, Conversation, LLMClient, ModelProvider
from core.models.model_policy import ModelPolicy
from core.models.tool_definition import ToolDefinition
from core.models.transcript import Transcript
from core.models.turn import Turn
from core.replay import Recorder, Replay


class Conversations(Protocol):
    """How a recorded conversation is built once the incident is known.

    Named as a shape so a loop can take the factory itself as a seam: a test
    hands over something it can assert was asked for, where production hands
    over one built by `conversations_through`.

    A `Protocol` rather than a `Callable` alias because `policy` is
    keyword-only and optional, which an alias cannot say. Keyword-only on
    purpose: the incident and the recorder are what a conversation is *for*,
    and which model answers it is a separate kind of fact that should not be
    readable as a third unnamed thing at a call site.
    """

    def __call__(self,
                 incident_id: str,
                 recorder: Recorder,
                 *,
                 policy: ModelPolicy | None = None) -> Conversation: ...


def a_conversation_recorded_for(
    incident_id: str,
    recorder: Recorder,
    *,
    policy: ModelPolicy | None = None,
    client_for: ClientFor
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
    it. What this costs is one client per incident, paid when the incident
    starts and not per turn.

    `client_for` is where the client comes from, and it is required: a default
    here would be a vendor every caller got without choosing one. Production
    binds it to a provider (`conversations_through`); a test hands over
    something that answers on the spot.
    """
    client = client_for(Replay(incident_id, recorder), policy)

    def converse_and_record(transcript: Transcript,
                            tools: list[ToolDefinition], /) -> Turn:
        return client.converse(transcript, tools)

    return converse_and_record


type ClientBuilder = Callable[[ModelProvider, Replay | None, ModelPolicy | None], LLMClient]


def conversations_through(provider: ModelProvider,
                          building: ClientBuilder = build_llm_client) -> Conversations:
    """Every recorded conversation a process builds, answered by `provider`.

    What a composition root binds into an agent: the incident, the recorder and
    the policy arrive later, from the agent, and which provider answers is the
    one thing settled here, where the process chose it.

    `building` is the factory each conversation's client comes from - the real
    one, which wraps the provider's client in a trace and a receipt, unless a
    test hands over a stand-in to see what it was asked for.
    """
    return partial(a_conversation_recorded_for, client_for=partial(building, provider))
