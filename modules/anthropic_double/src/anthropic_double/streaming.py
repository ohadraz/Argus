"""One stored response, said again as the stream the SDK asked for.

Code-Fix answers with whole files, which needs more output room than a
non-streaming request is allowed to carry - past 21,333 tokens the SDK
refuses to send one at all. So that agent streams, and a stand-in that only
knows how to hand back a whole JSON body cannot answer it.

Recordings are untouched by this. What is stored is the assembled message, as
it always was, and this says it again in the shape a streamed reader expects:
the transport differs, the content does not. That is what keeps every
recording in the repository valid, keeps `record` forwarding plain JSON
upstream, and keeps the one difference between a streamed run and an
unstreamed one out of the evidence.

Verified against the SDK's own parser rather than written from the
documentation: a synthesis that is subtly wrong reassembles into a message
that is subtly wrong, and every suite downstream would believe it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Final

# What a block of each kind looks like before any of its content has arrived.
# The reader builds the block from the deltas that follow, so these carry only
# what identifies it - for a tool call, the id and name it will be answered by.
_EMPTY_BLOCK: Final[dict[str, dict[str, Any]]] = {
    "text": {"type": "text", "text": ""},
    "thinking": {"type": "thinking", "thinking": "", "signature": ""},
}

# Anthropic's names for the events and the deltas. Here rather than spelled
# inline for the same reason the adapter names its own: these are a third
# party's vocabulary, and one declaration of each is one fact about them.
MESSAGE_START: Final = "message_start"
CONTENT_BLOCK_START: Final = "content_block_start"
CONTENT_BLOCK_DELTA: Final = "content_block_delta"
CONTENT_BLOCK_STOP: Final = "content_block_stop"
MESSAGE_DELTA: Final = "message_delta"
MESSAGE_STOP: Final = "message_stop"

SSE_MEDIA_TYPE: Final = "text/event-stream"


def _event(name: str, payload: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()


def _shell_for(block: dict[str, Any]) -> dict[str, Any]:
    if block["type"] == "tool_use":
        return {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}

    return _EMPTY_BLOCK[block["type"]]


def _deltas_for(block: dict[str, Any]) -> list[dict[str, Any]]:
    """The content of one block, as the updates that would have carried it.

    One delta per field rather than many small ones. A real stream arrives in
    fragments and a reader that assembles them is indifferent to how many
    there were, so a whole-field delta is the same message with less pretence
    about having watched it being written.

    A thinking block needs two: the reasoning and the signature travel
    separately on the wire, and a reader given only the first assembles a
    block whose signature is empty.
    """
    kind = block["type"]

    if kind == "text":
        return [{"type": "text_delta", "text": block["text"]}]

    if kind == "thinking":
        return [
            {"type": "thinking_delta", "thinking": block["thinking"]},
            {"type": "signature_delta", "signature": block["signature"]},
        ]

    if kind == "tool_use":
        return [{"type": "input_json_delta", "partial_json": json.dumps(block["input"])}]

    return []


def as_stream(message: dict[str, Any]) -> Iterator[bytes]:
    """One stored message, as the events a streamed reader assembles it from.

    The opening event carries the message with no content and no output
    count, because at that point in a real exchange neither exists yet; the
    closing delta carries the stop reason and the output tokens, which is
    where a reader learns both. Getting that split wrong is how a double ends
    up reporting a turn that cost nothing, which is exactly the accounting
    every suite downstream trusts.
    """
    opening = {name: value for name, value in message.items() if name != "content"}
    opening["content"] = []
    opening["usage"] = dict(message["usage"], output_tokens=0)

    yield _event(MESSAGE_START, {"type": MESSAGE_START, "message": opening})

    for index, block in enumerate(message["content"]):
        yield _event(CONTENT_BLOCK_START, {
            "type": CONTENT_BLOCK_START, "index": index, "content_block": _shell_for(block)
        })

        for delta in _deltas_for(block):
            yield _event(CONTENT_BLOCK_DELTA, {
                "type": CONTENT_BLOCK_DELTA, "index": index, "delta": delta
            })

        yield _event(CONTENT_BLOCK_STOP, {"type": CONTENT_BLOCK_STOP, "index": index})

    yield _event(MESSAGE_DELTA, {
        "type": MESSAGE_DELTA,
        "delta": {
            "stop_reason": message.get("stop_reason"),
            "stop_sequence": message.get("stop_sequence"),
        },
        "usage": {"output_tokens": message["usage"]["output_tokens"]},
    })

    yield _event(MESSAGE_STOP, {"type": MESSAGE_STOP})
