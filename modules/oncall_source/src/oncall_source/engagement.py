"""What human attention an incident took, as the on-call provider reports it.

Attention is measured in person-minutes: each responder's own acknowledgement
to the end of the incident, summed. Two things follow from that, and both are
the point.

The minutes before anyone acknowledged belong to nobody. An incident that
paged at 2am and was picked up at 2:12 occupied a person for what remained,
not for the twelve minutes it spent waiting - and Argus knows its own
incident's length already, so a source that reported that back would be
answering a question nobody asked.

Two people on an incident spent two people's time. A single span would report
half of what the response actually cost.

The sum is not, however, a figure anything can price on its own: the minutes of
a senior engineer and of a junior are added together here, and the titles come
back beside the total rather than against their own share of it. Pricing these
would need minutes held per title, which is a shape this does not have and a
question nothing has yet asked.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

from pydantic import BaseModel

# The unit the answer is stated in. Minutes rather than seconds because a
# postmortem reporting a response to the second would be claiming an accuracy
# an acknowledgement instant does not have.
A_MINUTE = timedelta(minutes=1)


class OnCallUnavailable(Exception):
    """The on-call provider could not be read.

    Raised by whatever fetches the incident, which is where a vendor's failures
    are known by their own names. Everything above the fetch answers in this
    vocabulary instead, so a provider's SDK stops at the one function that
    imports it.

    An exception rather than an empty answer, because the whole purpose of this
    port is that "nobody responded" and "nobody could say" are different
    answers - and an incident with no acknowledgements already means the first.
    """


class Acknowledgement(BaseModel):
    """One person taking an incident: when, who, and what they were called.

    Argus's object, not a provider's. An on-call provider publishes the moment
    and the identifier on the incident and the title on the person, and putting
    all three here is the adapter's work - which leaves everything above it
    with one object to read instead of two to join.

    The responder is an identifier and not a name: it is enough to tell two
    responders apart, and a document about an incident has no business naming
    people. `job_title` is absent where the provider holds none for them, or
    would not say - nothing above can price or print either, so the two arrive
    the same way.
    """

    at: datetime
    responder_id: str
    job_title: str | None


class ReportedIncident(BaseModel):
    """One incident as the provider holds it.

    Both instants are the provider's, not Argus's. They are the same incident
    and should agree, but the span being measured is the one the
    acknowledgements sit inside, and mixing two clocks to measure it is how a
    negative duration happens.

    `began_at` is carried and nothing computes from it: the measurement starts
    at an acknowledgement, and the incident's own start is what makes the gap
    between the two visible to anyone reading one of these.
    """

    began_at: datetime
    ended_at: datetime
    acknowledgements: list[Acknowledgement]


class Engagement(BaseModel):
    """What the response took: person-minutes, how many people, and what they
    were.

    Zero minutes and no responders is a real answer - an incident that resolved
    with nobody looking at it - and is not the same as the source being
    unreadable, which is `None` from the call that would have produced this.

    The titles are what the responders held, not who they were. A postmortem
    naming people is a document about people; a postmortem saying a senior
    engineer spent an hour on it is a document about an incident. Fewer titles
    than responders means one could not be read, which is a gap in the
    description and not in the measurement.
    """

    minutes: int
    responders: int
    titles: list[str] = []


# One incident, as the provider reports it.
type ReportedIncidents = Callable[[str], ReportedIncident]


def engagement_with(incident_id: str,
                    reported: ReportedIncidents) -> Engagement | None:
    """What attention one incident took, or `None` if nobody could say.

    Each responder counts once, from the first moment they acknowledged: a
    second acknowledgement by the same person is the same person, and taking
    their earliest is what stops a re-acknowledgement shortening the span they
    were on it.
    """
    try:
        incident = reported(incident_id)
    except OnCallUnavailable:
        return None

    took_it = _first_acknowledgement_of_each(incident.acknowledgements)

    return Engagement(
        minutes=sum((incident.ended_at - acknowledgement.at) // A_MINUTE
                    for acknowledgement in took_it.values()),
        responders=len(took_it),
        titles=[acknowledgement.job_title
                for acknowledgement in took_it.values()
                if acknowledgement.job_title is not None]
    )


def _first_acknowledgement_of_each(
    acknowledgements: Iterable[Acknowledgement]
) -> dict[str, Acknowledgement]:
    """One acknowledgement per person: the earliest each of them made.

    The whole acknowledgement rather than its moment, because the title came
    in on it - one person's title being on their own acknowledgement is what
    lets a count and a set of titles be read off the same list.
    """
    earliest: dict[str, Acknowledgement] = {}

    for acknowledgement in acknowledgements:
        responder = acknowledgement.responder_id
        held = earliest.get(responder)

        if held is None or acknowledgement.at < held.at:
            earliest[responder] = acknowledgement

    return earliest
