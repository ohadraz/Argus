"""One message, said as a stream - and one stream, read back as a message.

Code-Fix answers with whole files, which needs more output room than a
non-streaming request is allowed to carry - past 21,333 tokens the SDK
refuses to send one at all. So that agent streams, and a stand-in that only
knows how to hand back a whole JSON body cannot answer it.

Both directions live here because they are one fact about the wire read
twice. Serving a recording turns a stored message into the events a reader
assembles it from; recording a real call turns those events back into the
message. What is stored is the assembled message either way, so the transport
differs and the content does not - which is what keeps every recording in the
repository valid, and keeps the one difference between a streamed run and an
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

# Two more the server never sends and a real stream does: a keep-alive that
# carries nothing, and a failure raised partway through an answer that already
# returned 200.
PING: Final = "ping"
ERROR: Final = "error"

TEXT_DELTA: Final = "text_delta"
THINKING_DELTA: Final = "thinking_delta"
SIGNATURE_DELTA: Final = "signature_delta"
INPUT_JSON_DELTA: Final = "input_json_delta"

TOOL_USE_TYPE: Final = "tool_use"

SSE_MEDIA_TYPE: Final = "text/event-stream"

# The only line of an event that carries anything. The name is on the line
# above it and is repeated inside the payload, so reading the payload alone is
# both sufficient and the one place a type is read from.
_DATA_PREFIX: Final = "data:"


class UpstreamRefused(RuntimeError):
    """An error the API raised partway through an answer it had begun.

    Its own exception because it arrives on a 200: the status said the call
    was accepted and the failure came later, so a caller checking the status
    alone would store an empty message as though the model had sent one.
    """


def _event(name: str, payload: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()


def _shell_for(block: dict[str, Any]) -> dict[str, Any]:
    if block["type"] == TOOL_USE_TYPE:
        return {"type": TOOL_USE_TYPE, "id": block["id"], "name": block["name"], "input": {}}

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
        return [{"type": TEXT_DELTA, "text": block["text"]}]

    if kind == "thinking":
        return [
            {"type": THINKING_DELTA, "thinking": block["thinking"]},
            {"type": SIGNATURE_DELTA, "signature": block["signature"]},
        ]

    if kind == TOOL_USE_TYPE:
        return [{"type": INPUT_JSON_DELTA, "partial_json": json.dumps(block["input"])}]

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


def _apply(block: dict[str, Any], delta: dict[str, Any],
           index: int, partial_json: dict[int, str]) -> None:
    """One update, onto the block it belongs to.

    Concatenated rather than assigned, because a real stream splits a field
    across as many deltas as it likes and a reader that assigns keeps only
    the last fragment. A tool call's input is the exception: it arrives as
    JSON text that is not valid until the last piece has landed, so it is
    accumulated here and parsed when the block closes.
    """
    kind = delta["type"]

    if kind == TEXT_DELTA:
        block["text"] = block.get("text", "") + delta["text"]
    elif kind == THINKING_DELTA:
        block["thinking"] = block.get("thinking", "") + delta["thinking"]
    elif kind == SIGNATURE_DELTA:
        block["signature"] = block.get("signature", "") + delta["signature"]
    elif kind == INPUT_JSON_DELTA:
        partial_json[index] = partial_json.get(index, "") + delta["partial_json"]


def from_stream(payload: str) -> dict[str, Any]:
    """One streamed answer, read back as the message it was.

    The inverse of `as_stream`, and what `record` stores when the call it is
    forwarding asked to be streamed - which Code-Fix's always does. A stored
    stream would be a stored transport: it would have to be reassembled
    before anything could read it, by code that would then be the only reader
    of a shape nothing else uses. So the reassembly happens once, here, and
    every recording in the repository stays the one thing a recording is.

    Only the `data:` line of each event is read. The name on the line above
    it is repeated inside the payload, so reading the payload alone is both
    sufficient and the one place a type is read from - and a keep-alive,
    which carries nothing either way, falls through without a branch of its
    own.
    """
    message: dict[str, Any] = {}
    partial_json: dict[int, str] = {}

    for line in payload.splitlines():
        if not line.startswith(_DATA_PREFIX):
            continue

        event = json.loads(line[len(_DATA_PREFIX):])
        kind = event.get("type")

        if kind == ERROR:
            raise UpstreamRefused(event[ERROR])

        if kind == MESSAGE_START:
            message = event["message"]
        elif kind == CONTENT_BLOCK_START:
            # Appended rather than placed at its index: the API sends blocks
            # in order and so does `as_stream`, and a reader that honoured an
            # out-of-order index would be inventing a guarantee to test.
            message["content"].append(event["content_block"])
        elif kind == CONTENT_BLOCK_DELTA:
            _apply(message["content"][event["index"]], event["delta"],
                   event["index"], partial_json)
        elif kind == CONTENT_BLOCK_STOP:
            accumulated = partial_json.pop(event["index"], None)
            if accumulated is not None:
                message["content"][event["index"]]["input"] = json.loads(accumulated or "{}")
        elif kind == MESSAGE_DELTA:
            message.update(event["delta"])
            message["usage"].update(event.get("usage") or {})

    if not message:
        raise UpstreamRefused({"message": "the stream carried no message_start"})

    return message
