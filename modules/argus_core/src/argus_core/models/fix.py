from __future__ import annotations

from enum import StrEnum


class FixOutcome(StrEnum):
    """How Code-Fix's turn ended (spec §7.4).

    Five answers rather than a pull request and its absence. Four of these
    carry no proposal and they mean different things: `not-warranted` is a
    verdict on the code - Argus read it and there was nothing there to change -
    where `not-possible` is a repository that refused, which somebody can go
    and repair, and `not-answered` is Argus running out of turns mid-read,
    which is a budget that was too small rather than anything about the
    service. A reader told only that there is no pull request cannot tell those
    apart, and one live incident spent twelve turns exploring and was recorded
    as having found no fix - a statement about the budget dressed as a verdict.

    `declined` is the model itself saying no, and it is none of the other
    three. Nothing is broken, so there is nothing to go and repair; the code
    was never judged, so no verdict was reached; and more turns cannot help,
    because the same question over the same code is declined again. It shared
    `not-possible`'s sentence until somebody noticed that "could not propose a
    fix" sends a reader hunting for an outage that never happened.

    A value rather than a sentence, for the reason `Verdict` is one: the page,
    the relay and the postmortem all have to recognise which of the three
    happened, and three readers matching on prose are three readers who will
    eventually match on different prose.

    This is not a status. A mitigated incident is mitigated whichever of these
    it carries (§10) - what Code-Fix found decides what the incident carries,
    not what state it is in.
    """

    PROPOSED = "proposed"
    NOT_WARRANTED = "not-warranted"
    NOT_POSSIBLE = "not-possible"
    NOT_ANSWERED = "not-answered"
    DECLINED = "declined"
