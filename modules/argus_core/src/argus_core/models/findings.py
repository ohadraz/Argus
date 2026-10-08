from __future__ import annotations

from dataclasses import dataclass

from argus_core.models.disproof import Disproof
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.placement import RecordedPlacement
from argus_core.models.reading import Reading


@dataclass(frozen=True)
class Findings:
    """What one investigation concluded, and what it read to conclude it.

    Named for the product rather than the process: an investigation is the
    thing that runs, and this is what it hands back.

    `candidates` is every explanation the model offered, best first, and is
    never empty - an investigation that identified no cause says so in one
    candidate carrying the reason. Whether any of them is worth acting on is
    the mitigate threshold's business, not this type's.

    `already_read` is what a later round cannot work out for itself. A round is
    bought by a refutation, not by a wider window, and the round that follows
    should know what the one before it saw - both so it does not pay again for
    the same evidence, and so that a channel nobody asked for stays
    distinguishable from one that was asked and came back empty.

    A contract rather than the Investigator's own type, because the walk names
    it too: the node that investigates hands one to the node that decides, and
    a shape kept inside the agent is one the Orchestrator installs an agent to
    read.
    """

    candidates: list[Hypothesis]
    already_read: list[Reading]
    # Whether any reading covers the minutes from the incident's onset onwards.
    #
    # Here rather than derived where it is used, because only an investigation
    # holds both halves: the gate that reads it has the onset and never the
    # window. What it decides is whether an action on this incident could be
    # confirmed - a channel already reporting every minute of the incident will
    # report the same minutes afterwards, and one reporting none of them has a
    # return to show.
    #
    # A property of the window and never of the mode. Any incident whose minutes
    # were not published is judged this way, whatever the cause turns out to be.
    #
    # `True` by default because that is what every incident before this field
    # existed was: a window with readings throughout, either departing or flat.
    readings_cover_the_incident: bool = True
    # The window that held none of what the alarm claimed, where the alarm was
    # one a window can contradict and this one did.
    #
    # Here for the reason the field above is: only an investigation holds both
    # halves. It has the alert, which says what kind of claim its rule made, and
    # the window, which says what the series did - and neither alone decides
    # anything. The gate that reads this has the one and never the other.
    #
    # `None` for every other outcome, which is every incident there has been.
    # Absent rather than a flag beside a reason, because what a reader of this
    # ending needs is the evidence: an alarm reported wrong on no stated grounds
    # is a second unreviewable claim replacing the first.
    disproof: Disproof | None = None
    # Where the alerting service's pods were running, recorded against the onset
    # before the model was asked anything.
    #
    # Carried out rather than read again where it is used, because the walk
    # decides a pin to a card from it, and a placement read when acting is read
    # after whatever the walk did first has moved the pods.
    #
    # `None` where nothing was recorded: an investigation that ended before it
    # had an onset, or a platform that would not say. Never an empty placement in
    # its place, which would claim the service runs on no pod at all.
    placement: RecordedPlacement | None = None
