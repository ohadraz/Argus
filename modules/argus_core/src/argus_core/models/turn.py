from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ToolCall(BaseModel):
    """One thing the model asked to have run, and how to answer it.

    All three fields are needed to complete the round trip. `name` picks the
    function, `arguments` are what to call it with, and `id` is what the
    result has to be labelled with on the way back - a result sent without it
    answers nothing, and the model waits for a reply that never comes.

    `arguments` is a plain mapping rather than a typed payload because what is
    valid depends on which tool was named, and that is the dispatcher's
    business. Validating it here would mean this module knowing every tool.
    """

    id: str
    name: str
    arguments: dict[str, Any]


class Turn(BaseModel):
    """One reply from the model, as the loop that drives it reads.

    Not the SDK's `Message` passed along. A caller dispatches on this, counts
    a budget from it, and narrates it, and none of those should be written
    against a vendor's response shape - the loop would then break on a field
    Anthropic renamed rather than on anything Argus got wrong.

    There is deliberately no `stop_reason` here. "Did the model ask for
    something" is `bool(turn.tool_calls)`, which is the question a loop
    actually has; the stop reasons that mean something else - a refusal, a
    truncated answer - are failures the adapter raises rather than states a
    caller has to interpret.

    Nothing here knows how to build one from a vendor's response, and that is
    the point: reading a provider's payload is the adapter's work, and a domain
    model that imported an SDK to do it would make every module holding a
    `Turn` depend on whoever answered.

    Four token counts rather than two, because a prompt is not billed at one
    rate once caching is on: `input_tokens` is only the uncached remainder,
    and the rest of what the model read arrives as a cache read or a cache
    write. The whole prompt is the three of them summed - so a reader adding
    the cached counts to `input_tokens` expecting a total is already holding
    one, and a reader taking `input_tokens` alone as the prompt size is looking
    at a fraction of it.

    Recorded rather than priced. What the counts cost is a rate applied to
    them, and rates are the vendor's to change; the counts are what the model
    reported and stay true.
    """

    text: str
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    # Zero rather than optional: a turn that used no cache used none of it,
    # which is a measured quantity, and a column of counts should not make a
    # reader decide what a missing one meant. It is also what every turn of a
    # run against a model or a double that does not cache reports.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
