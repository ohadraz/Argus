from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Evidence(BaseModel):
    """One thing a hypothesis rests on, and when it happened.

    The claim stays prose, because it is prose: the model writes *about* the
    lines it read rather than quoting them whole, and a claim reduced to fields
    would lose the reasoning that makes it evidence rather than a row.

    `at` is a field for the opposite reason. A reader checking a claim wants
    the minute it rests on, and the instant is the one part of the sentence
    that was never prose - it is a value the model copied out of a line it
    retrieved. Recovered by pattern-matching the sentence afterwards it is a
    guess, and a guess that lands on the wrong minute points a reader
    confidently at evidence nobody cited.

    `None` where the claim names no moment - an absence of changes in a window
    happened at no instant, and a plausible time invented for it would link to
    a row the claim does not rest on.

    Null is stated rather than defaulted. "This rests on no particular moment"
    and "the field was not filled in" are different answers, and a default
    would make them the same one: a model that quietly omitted the field would
    be read as having considered the question. Required here, as the answer
    tool's schema already declares it.
    """

    claim: str
    at: datetime | None
