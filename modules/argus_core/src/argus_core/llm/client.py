from __future__ import annotations

from typing import Protocol

from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn


class ModelDidNotAnswer(Exception):
    """Nothing usable came back from the model.

    The base of a three-way split, because the three ways differ in what a
    caller should do next. Catch this to mean "there is no answer"; catch a
    subclass to decide whether trying again could help.

    Named for the model rather than for any one shape of answer: what a turn
    was supposed to contain is the caller's business, and "the model declined"
    is the same event whatever was asked for.

    Here rather than with an adapter because these are the interface's, not a
    vendor's. What a caller does about a refusal is the same decision whoever
    answered, and a caller that had to import an adapter to name the failure
    it handles would know which vendor it was talking to.
    """


class ModelRefused(ModelDidNotAnswer):
    """The model declined to answer.

    Not malformed - this is a complete, well-formed response that says no.
    Kept separate because it is the one outcome retrying cannot fix: the same
    evidence will be declined again. Escalate instead.
    """


class AnswerTruncated(ModelDidNotAnswer):
    """The model ran out of output room before finishing.

    Separate from the others because nothing is wrong with the model or the
    request - there was simply not enough room. This is the one failure here
    that a retry, with more room, can actually resolve.

    Whether that retry is worth buying is the caller's call, not an adapter's:
    a retry costs tokens, and only the thing holding the budget knows whether
    there are any left. Raised rather than returned so that deciding is not
    something a caller can forget to do.
    """


class TurnPaused(ModelDidNotAnswer):
    """The model paused mid-turn and expects to be resumed.

    Only reachable with server-side tools - ones the provider runs on its own
    infrastructure. Argus offers none, so this cannot happen; it is here
    precisely because it cannot. A pause that arrives anyway means an
    assumption about what was offered is wrong, and that should be loud rather
    than quietly mistaken for a turn that finished.
    """


class LLMClient(Protocol):
    """What Argus needs from a reasoning model, stated in Argus's own terms.

    One way of asking. `converse(transcript, tools) -> Turn` hands the model a
    conversation and a set of tools, and gets back whatever it wants to do next -
    which is usually not an answer but a request for evidence. Argus never poses
    a question whose evidence it has already chosen: deciding *what to look at*
    is the investigation, and it cannot be expressed as a single question.

    Not `complete(prompt) -> str`. A string-in/string-out seam would push prompt
    wording and response parsing into every caller, and would let a test double
    satisfy the type while saying nothing about whether the real adapter works.
    The shape here can only be implemented by something that actually takes a
    turn.

    Nothing crossing this boundary is a vendor's shape, `Transcript` included.
    A tool result is matched to the request it answers by an id the API issued,
    which makes the record of an exchange look wire-shaped - but looking like
    the wire is not being the wire, and a Protocol that named the SDK's types
    would put Anthropic in every caller that holds a conversation. The adapter
    renders a `Transcript` into messages; nobody above it knows what one is.
    """

    def converse(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition],
                 max_tokens: int = ...) -> Turn: ...
