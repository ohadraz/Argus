"""How Code-Fix talks to the model.

The same seam the investigation has, for the same reasons: one call, so a test
can stand it in with a scripted conversation, and a real client built on first
use so a module that only ever injects a double pays for neither the vendor's
SDK nor the configuration it reads on the way up.

The calls are written down. Code-Fix spends more than any other agent here - a
repository's worth of context, resent every turn - and it is the one whose
answer is hardest to second-guess from the outside: a patch it declined to
write leaves nothing behind to read. An incident whose fix cannot be costed or
re-read is one nobody can say anything about afterwards.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from argus_core.llm import LLMClient
from argus_core.models import ToolDefinition, Transcript, Turn
from argus_core.replay import Recorder, Replay

Conversation = Callable[[Transcript, list[ToolDefinition]], Turn]

# How a recorded conversation is built once the incident is known. Named as a
# shape so the loop can take it as a seam: a test hands over something it can
# assert was asked, where production hands over the real factory below.
Conversations = Callable[[str, Recorder], Conversation]

ClientFor = Callable[[Replay], LLMClient]


@lru_cache(maxsize=1)
def _llm_client() -> LLMClient:
    """The one client the whole process shares.

    Built on first use rather than at import, and the import deferred with it -
    building a client pulls in a vendor's SDK, and every unit test of the loop
    injects a conversation and never reaches here.
    """
    from argus_core.llm import build_llm_client

    return build_llm_client()


def _a_recording_client(replay: Replay) -> LLMClient:
    """A client that files a receipt for every call it makes.

    Imported inside for the reason `_llm_client` defers its import: building a
    client pulls in the vendor's SDK, and the loop's unit tests inject a
    conversation and never reach here.

    Not cached, unlike `_llm_client`: the replay it wraps holds one incident,
    so a cached instance would file every later incident's calls under the
    first one walked. What is expensive - reading configuration, building the
    SDK client - is cached inside the adapter, where it is the same for every
    incident.
    """
    from argus_core.llm import build_llm_client

    return build_llm_client(replay)


def a_conversation_recorded_for(
    incident_id: str,
    recorder: Recorder,
    client_for: ClientFor = _a_recording_client
) -> Conversation:
    """The conversational seam for a real fix, writing down its calls.

    A factory rather than a parameter on `converse`, because the incident is
    fixed for the whole attempt while the transcript is not. Binding it once
    keeps an incident id out of a signature whose subject is a conversation
    with a model - the same reasoning that puts a `Narrator` beside a loop
    instead of an incident id in every call that has something to report.
    """
    client = client_for(Replay(incident_id, recorder))

    def converse_and_record(transcript: Transcript,
                            tools: list[ToolDefinition]) -> Turn:
        return client.converse(transcript, tools)

    return converse_and_record


def converse(transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
    """Hands the model the conversation so far and asks what it wants next.

    A module-level function rather than the client object, so the loop's seam
    is one call and a test can `create_autospec` it against a real public name.

    Usually the answer is not the answer: a turn is whatever the model wants
    next - a file to read, a remark, or the one call that ends the work - and
    which of those it is, is the loop's to read rather than this seam's to
    interpret.
    """
    return _llm_client().converse(transcript, tools)
