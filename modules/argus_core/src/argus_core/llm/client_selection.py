"""Which `LLMClient` a caller gets when it does not bring its own.

The one module here that is allowed to know both sides: the port next door
states what Argus needs from a model, the adapters below say how one vendor
answers, and choosing between them is neither's business. Keeping the choice
out of `client.py` is what lets a caller name the interface - or a failure it
handles - without the SDK arriving with it.
"""

from __future__ import annotations

from argus_core.llm.adapters.anthropic_adapter import MODEL, AnthropicLLMClient
from argus_core.llm.client import LLMClient
from argus_core.llm.recorded_client import RecordedLLMClient
from argus_core.replay import Replay


def get_llm_client(replay: Replay | None = None) -> LLMClient:
    """The client agents get by default, keeping a receipt when asked to.

    Returned as the Protocol rather than as the adapter, so that a caller
    holding one cannot reach past the interface into whatever answered.

    The wrapping happens here rather than at the call site because this is the
    module already allowed to know both sides. `RecordedLLMClient` needs to be
    told which model it is recording, and `MODEL` is Anthropic's - naming it
    anywhere else would put the vendor into a caller that had managed to avoid
    knowing about one.

    Without a `Replay` the client is unwrapped rather than wrapped around a
    recorder that discards: an agent that is not recording should not be paying
    for a decorator, and the absence should be visible in a stack trace.
    """
    client = AnthropicLLMClient()

    if replay is None:
        return client

    return RecordedLLMClient(client, replay, target=MODEL)
