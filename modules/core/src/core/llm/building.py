"""Building the `LLMClient` a caller is handed, over the provider it was given.

The provider is the port next door (`ModelProvider`), and which vendor stands
behind it is the composition root's choice: this module wraps whatever client a
provider builds and names no vendor, no SDK and no setting. That is what lets
`from core.llm import LLMClient` cost a unit test nothing - nothing here
imports a vendor's SDK, so a caller that injects a double never loads one.

Building, not selecting. Nothing here chooses between providers; the caller
already has.
"""

from __future__ import annotations

from core.llm.client import LLMClient, ModelProvider
from core.llm.recorded_client import RecordedLLMClient
from core.llm.traced_client import TracedLLMClient
from core.models.model_policy import ModelPolicy
from core.replay import Replay


def build_llm_client(provider: ModelProvider,
                     replay: Replay | None = None,
                     policy: ModelPolicy | None = None) -> LLMClient:
    """Builds the client an agent talks through, keeping a receipt when asked to.

    Built rather than fetched, and named so: each call asks the provider for a
    client of its own, and two callers that asked are holding two.

    Returned as the Protocol rather than as whatever the provider built, so
    that a caller holding one cannot reach past the interface into whatever
    answered.

    The wrapping happens here rather than at the call site because this is the
    one place that holds the policy and the client at once. `RecordedLLMClient`
    needs to be told which model it is recording and how much room that
    model's answers get, and neither is askable through the `LLMClient` it
    wraps - a Protocol with a policy on it would be a Protocol every caller
    could read one off. Both come off the policy this client was built with,
    so the receipt says what the call was given rather than what a decorator
    assumed.

    Without a `Replay` the client is not wrapped in a recorder rather than
    wrapped around one that discards: an agent that is not recording should not
    be paying for a decorator, and the absence should be visible in a stack
    trace.

    Traced always, by contrast, and inside the recorder. A span costs nothing
    until a process installs an SDK, so there is no absence worth making
    visible; and inside, so that what the span times is the call to the model
    and not the recorder's write. The span names the provider by the name the
    provider gives itself.

    Positional after the provider, because `ClientFor` is: a caller holding a
    factory bound to its provider asks it for `(replay, policy)`.
    """
    asked_of = policy if policy is not None else ModelPolicy()
    answering = TracedLLMClient(
        provider.client(asked_of),
        model=asked_of.model,
        provider=provider.name,
        room=asked_of.max_output_tokens
    )

    if replay is None:
        return answering

    return RecordedLLMClient(
        answering, replay, target=asked_of.model, room=asked_of.max_output_tokens
    )
