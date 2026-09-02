from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from argus_core.models.turn import Turn


class Ask(BaseModel):
    """Something Argus put to the model in its own words.

    In practice the opening message of an investigation - the alert, the onset,
    and what earlier rounds already learned. Everything after it in a
    transcript is a record of what the model did and what it got back, so this
    is the one entry Argus writes as prose.
    """

    text: str


class ToolResult(BaseModel):
    """What one requested tool produced, labelled with the call it answers.

    `call_id` is the id the model's own request carried. It is not decoration:
    a result sent without it, or with the wrong one, answers nothing, and the
    model waits for a reply it will never recognise.

    `failed` is how a tool that could not be served still answers. An
    unanswered call leaves the model waiting, so a failure travels as a result
    rather than as a missing one - and the flag is what tells the model this is
    something to recover from rather than evidence about the incident.
    """

    call_id: str
    content: str
    failed: bool = False


class ToolResults(BaseModel):
    """Every result for one turn's calls, held together.

    Together is the entire reason this type exists. A model may ask for several
    tools in a single turn, and all their results belong in one reply; sending
    them separately is accepted without complaint and quietly teaches the model
    to stop asking for tools in parallel - a regression nothing fails on and
    nobody sees.

    Making the grouping a property of the type means a loop cannot get it
    wrong by appending one result at a time.
    """

    results: list[ToolResult]


# One conversation, in Argus's own terms: what was asked, what the model did
# about it, and what its requests produced. A loop appends to this and hands
# the whole thing back each turn, because the API keeps no state of its own.
#
# Only the adapter knows what any of it looks like on the wire. A loop building
# vendor-shaped dictionaries directly would put the provider a module further
# up than the adapter, and changing providers would then be a rewrite of the
# loop rather than of the thing whose job that is.
#
# A `Sequence` rather than a `list`, because `list` is invariant: a caller
# holding a list of one kind of exchange - an investigation that has only just
# opened, holding a single `Ask` - could not pass it without the type checker
# refusing. A transcript is read here, never appended to, so nothing is given
# up by asking only that it can be iterated in order.
type Exchange = Ask | Turn | ToolResults
type Transcript = Sequence[Exchange]
