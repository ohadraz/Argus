"""Building the `LLMClient` a caller gets when it brings none of its own.

The one module here that is allowed to know both sides: the port next door
states what Argus needs from a model, the adapters below say how one vendor
answers, and binding one to the other is neither's business. Keeping that out
of `client.py` is what lets a caller name the interface - or a failure it
handles - without the SDK arriving with it.

Which is why the adapter is reached inside the function rather than at the top
of this file. `argus_core.llm` re-exports `build_llm_client`, so anything that
names the front door imports this module - and while the adapter was named
here, `from argus_core.llm import LLMClient` cost 0.6 seconds of Anthropic SDK
to a unit test that injects a double and never asks anybody anything. The
separation was structural and the saving it was written for was not happening.

Building, not selecting. There is one adapter and no alternative to weigh it
against, and a module named for a choice it does not make sends a reader
looking for the switch.
"""

from __future__ import annotations

from argus_core.config import LLMSettings, get_settings
from argus_core.llm.client import LLMClient
from argus_core.llm.recorded_client import RecordedLLMClient
from argus_core.replay import Replay


def build_llm_client(replay: Replay | None = None) -> LLMClient:
    """Builds the client agents get by default, keeping a receipt when asked to.

    Built rather than fetched, and named so: each call constructs a client
    of its own, and two callers that asked are holding two. Nothing here
    chooses between alternatives - there is one adapter, and the only
    question is whether it is wrapped in a recorder.

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

    The adapter arrives here rather than with the module, so that importing the
    front door this is exported from does not import a vendor's SDK. Nothing is
    deferred by this except the cost: a caller that reaches this line was always
    going to need Anthropic.
    """
    from argus_core.llm.adapters.anthropic_adapter import MODEL, AnthropicLLMClient

    client = AnthropicLLMClient(LLMSettings.of(get_settings()))

    if replay is None:
        return client

    return RecordedLLMClient(client, replay, target=MODEL)
