from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class HowTheMinuteIsKnown(StrEnum):
    """Where the minute an investigation works from came from.

    Three grades rather than measured-or-not, because the model is told a
    different thing in each and the difference is not a caveat. What it is told
    about a measured minute is a departure it can see in the rows below; about a
    stated one, testimony it cannot check; about the third, that the minute dates
    nothing at all and is only where to look from.
    """

    # The first minute a judged signal departed and stayed departed - derived
    # from the buckets Argus retrieved, and re-derivable by anyone reading the
    # incident.
    MEASURED = "measured"
    # Testimony from whatever raised the alert, for a window in which nothing
    # departs. Checkable against nothing Argus holds, which is exactly why the
    # model is told which of the two it has.
    STATED_BY_THE_ALERT = "stated-by-the-alert"
    # Neither. The window is flat, the alert dated nothing, and what stands in
    # for an onset is the minute the alarm itself fired in. Reached only by an
    # alert reporting a finding no series carries - a flat window under a rule
    # watching a series is a disproof rather than an incident with no date.
    NOTHING_DATES_IT = "nothing-dates-it"


class EstablishedOnset(BaseModel, frozen=True):
    """The minute an incident is dated from, and how that minute is known.

    One value rather than two fields beside each other, because the grade is a
    fact about this minute and no other: carried apart, a later round could keep
    the one and re-derive the other from a window Argus has since acted on, and
    grade a stated minute by a departure the action left behind.

    Established once, by the first round that had a minute at all. An incident
    has one beginning, and a later round reads a window Argus has already acted
    on - a departure found there is what followed the action, not a better
    reading of when the incident began.

    A contract rather than the Investigator's own type, because the walk carries
    it from one round to the next and dates the incident's end against it.
    """

    minute: str
    how_known: HowTheMinuteIsKnown
