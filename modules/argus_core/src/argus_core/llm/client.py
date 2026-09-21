from __future__ import annotations

from typing import Protocol

from argus_core.models.model_policy import ModelPolicy
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Transcript
from argus_core.models.turn import Turn
from argus_core.replay import Replay


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

    Carries what the attempt was billed, because not answering is not the same
    as being free. A refusal is a complete response and charged as one; a turn
    cut short generated to its cap before it was stopped, so its output is
    produced and billed in full. A caller that retried on either without
    charging for it would have a loop no bound could see - the one count that
    would notice is the one that never moves.

    Said as a `Turn` with nothing in it rather than as a second shape for
    spend. That is what happened - tokens went, nothing came back - and it
    means whoever is keeping a budget charges this the way it charges an
    answer, with one arithmetic rather than two to keep in agreement. The
    empty `tool_calls` is a fact too: an attempt that carried nothing asked
    for nothing, and a call count that moved would bound the wrong thing.

    Free by default, because most of these are raised by code with no usage to
    hand - a double, a test, an adapter that failed before the model answered.
    """

    def __init__(self, message: str, billed: Turn | None = None) -> None:
        super().__init__(message)
        self.billed = billed if billed is not None else Turn(
            text="", tool_calls=[], input_tokens=0, output_tokens=0
        )


class ModelRefused(ModelDidNotAnswer):
    """The model declined to answer.

    Not malformed - this is a complete, well-formed response that says no.
    Kept separate because it is the one outcome retrying cannot fix: the same
    evidence will be declined again. Escalate instead.
    """


class AnswerTruncated(ModelDidNotAnswer):
    """The model ran out of output room before finishing.

    Separate from the others because nothing is wrong with the model or the
    request - there was simply not enough room. It is the one failure here
    that more room would resolve, which is not the same as one a retry
    resolves: asking again through a seam that carries no larger bound puts
    the identical request, and differs from the first attempt only by
    resampling. A caller with no way to offer more room has nothing to buy.

    What to do about it is still the caller's call, not an adapter's - and
    the call costs something either way, which is why this carries what the
    attempt was billed. A turn stopped at its cap generated every token of
    that cap before it was stopped. Raised rather than returned so that
    deciding is not something a caller can forget to do.
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


class Conversation(Protocol):
    """The one call a loop that talks to a model makes.

    Narrower than `LLMClient` on purpose. A loop asks for a turn and reads what
    the model wants next; it has no business holding a client, choosing a token
    bound, or knowing that either exists. What it is handed is this, and every
    unit test of a loop hands it a script.

    A `Protocol` rather than a `Callable` alias, because a test has to build a
    double from it and an alias is not introspectable at runtime -
    `create_autospec` needs a real class or function to read a signature off.
    The alternative was a module-level function existing to be that name, whose
    body nothing ever called.
    """

    def __call__(self,
                 transcript: Transcript,
                 tools: list[ToolDefinition], /) -> Turn: ...


# Here rather than beside either caller: the investigator's loop and the
# postmortem's gathering both name this, which makes it a contract, and a
# contract kept inside one of the parties is one the other reaches into.
# `client.py` rather than `building.py` because a type belongs with the
# interface it produces rather than with the one function that produces one.
class ClientFor(Protocol):
    """How a caller that records its calls gets a client for one incident.

    A factory rather than a client, because the receipt belongs to an incident
    while the client does not: a wrapper holding one incident, shared across a
    process, would file every later incident's calls under the first one.

    `policy` is which model is to answer and how hard it is asked to think,
    and it is optional here rather than required so that a caller with no
    opinion is not made to invent one. Where it is named, it is named by
    whoever assembled the agent - the same place that already decides which
    payment provider answers the revenue question.

    A `Protocol` rather than a `Callable` alias, because an alias cannot say
    that the second argument has a default, and every existing caller passes
    only the first.
    """

    def __call__(self,
                 replay: Replay,
                 policy: ModelPolicy | None = None) -> LLMClient: ...
