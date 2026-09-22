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

from typing import TYPE_CHECKING

from argus_core.config import LLMSettings, get_settings
from argus_core.llm.client import LLMClient
from argus_core.llm.recorded_client import RecordedLLMClient
from argus_core.models.model_policy import ModelPolicy
from argus_core.replay import Replay

if TYPE_CHECKING:
    import anthropic


def build_llm_client(replay: Replay | None = None,
                     policy: ModelPolicy | None = None,
                     client: anthropic.Anthropic | None = None) -> LLMClient:
    """Builds the client agents get by default, keeping a receipt when asked to.

    Built rather than fetched, and named so: each call constructs a client
    of its own, and two callers that asked are holding two. Nothing here
    chooses between alternatives - there is one adapter, and the only
    question is whether it is wrapped in a recorder.

    Returned as the Protocol rather than as the adapter, so that a caller
    holding one cannot reach past the interface into whatever answered.

    The wrapping happens here rather than at the call site because this is the
    module already allowed to know both sides. `RecordedLLMClient` needs to be
    told which model it is recording and how much room that model's answers
    get, and neither is askable through the `LLMClient` it wraps - a Protocol
    with a policy on it would be a Protocol every caller could read one off.
    Both come off the policy this client was built with, so the receipt says
    what the call was given rather than what a decorator assumed.

    Without a `Replay` the client is unwrapped rather than wrapped around a
    recorder that discards: an agent that is not recording should not be paying
    for a decorator, and the absence should be visible in a stack trace.

    The adapter arrives here rather than with the module, so that importing the
    front door this is exported from does not import a vendor's SDK. Nothing is
    deferred by this except the cost: a caller that reaches this line was always
    going to need Anthropic. `client` is annotated rather than imported for the
    same reason - the annotation is a string here, and the name is only needed
    to type it.

    `client` is the adapter's own seam, one layer up, and it is here because
    one layer down is not where the whole thing can be seen. The recorder
    implements the same Protocol as what it wraps, so a cap declared on one and
    not the other is a difference neither end can observe: the agent above
    still calls with two arguments, the adapter below still reads whatever
    figure arrives as the caller's word, and the per-agent policy is discarded
    in between with every suite green. What reaches the API is a property of
    this assembly and of nothing smaller, so this is the layer that has to be
    askable. Configuration still decides everything about a real client;
    passing one only says that this one is not.
    """
    from argus_core.llm.adapters.anthropic_adapter import AnthropicLLMClient

    asked_of = policy if policy is not None else ModelPolicy()
    answering = AnthropicLLMClient(
        LLMSettings.of(get_settings()), policy=asked_of, client=client
    )

    if replay is None:
        return answering

    return RecordedLLMClient(
        answering, replay, target=asked_of.model, room=asked_of.max_output_tokens
    )
