"""The one question a walk asks about itself: has a person ended this incident,
and how.

Beside the two doors rather than in the graph, because four things ask it and
only some of them are nodes: the wrapper around every node, the routers, the
agents between their turns, and the worker deciding whether to walk a run and
whether to put anything back afterwards.
"""

from __future__ import annotations

from typing import Protocol

from argus_core import Connections, Holding, RunLost
from argus_core.models import IncidentStatus

from argus_incidents.repository import incidents, runs


class IsStillWanted(Protocol):
    """Whether Argus should take the next step on this incident - or `RunLost`,
    raised, when the run walking it is no longer this process's.

    The yes-or-no the nodes hand their agents, asked between model turns and
    before every change to the world. Either ending a person writes is a reason
    not to take the next step, so a step needs only whether there is one; what
    the walk does after stopping differs between the two, and is decided where
    the ending itself is read.

    Raised rather than answered `False` when the run was taken back, because a
    `False` is an incident somebody ended, and the walk goes on to remember and
    write up an incident ended that way. A walk whose run is another claim's
    does nothing more at all.

    Positional-only: the incident is all it is called with, and a stand-in has
    no use for anything else.
    """

    def __call__(self, incident_id: str, /) -> bool: ...


class StillHeld(Protocol):
    """Whether the run this process is walking is still its own.

    Asked with nothing, because the walk asking it knows no run: which run and
    which claim of it are the process's, held where the run was claimed.
    """

    def __call__(self) -> bool: ...


class EndedByAPerson(Protocol):
    """How a person ended the incident: `withdrawn`, `resolved`, or `None`
    while nobody has.

    The ending itself rather than "is it still wanted", because the walk does
    opposite things with the two. A withdrawal sends it out at once and has its
    changes put back; a resolution sends it on to remember what was tried and
    write the incident up, and puts nothing back. A yes-or-no would have to
    mean one of those, and would be the wrong one for the other.

    Positional-only: the incident is all it is called with, and a stand-in has
    no use for anything else.
    """

    def __call__(self, incident_id: str, /) -> IncidentStatus | None: ...


def ended_by_a_person_via(connections: Connections) -> EndedByAPerson:
    """The real question, bound to the connections that can answer it.

    A factory for the same reason the subscribers are: what asks this is a
    walk, and a walk is entitled to ask with an incident id alone. Where the
    answer is read from is the process's business, settled once where the
    process starts.
    """

    def ended_by_a_person(incident_id: str, /) -> IncidentStatus | None:
        return _ended_by_a_person(incident_id, connections)

    return ended_by_a_person


def still_held_via(connections: Connections, holding: Holding) -> StillHeld:
    """The real question, asked of the run `holding` says this process holds.

    Nothing held answers yes without asking the database. A walk paused past its
    lease still holds the claim it was paused with, so a run taken back is never
    a run held by nobody. A suite holding nothing has no run to lose; a worker
    that forgot to hold one has every write it makes refused for naming no run.
    """

    def still_held() -> bool:
        held = holding.current()

        if held is None:
            return True

        with connections() as conn:
            return runs.is_held(conn, held)

    return still_held


def wanted_until_a_person_ends_it(ended_by_a_person: EndedByAPerson,
                                  still_held: StillHeld) -> IsStillWanted:
    """The yes-or-no, asked of the ending: wanted while nobody has ended it.

    The run is asked first, and a run taken back is `RunLost` raised: the
    incident is somebody else's walk now, and whether a person ended it is
    that walk's question.
    """

    def is_still_wanted(incident_id: str, /) -> bool:
        if not still_held():
            raise RunLost("a newer claim holds this run")

        return ended_by_a_person(incident_id) is None

    return is_still_wanted


def _ended_by_a_person(incident_id: str, connections: Connections) -> IncidentStatus | None:
    """Reads back how a person ended the incident, if one has.

    Argus's own endings answer `None`. A mitigated incident goes on to
    Code-Fix and a postmortem, and reading it as ended by somebody would skip
    both.

    An incident with no row reads as withdrawn. Reading a missing row as
    "carry on" is how a walk goes on writing rows for an incident that no
    longer exists - which is exactly the state a suite leaves behind when it
    empties the database between cases - and withdrawn rather than resolved,
    because a walk stopped by a resolution goes on to write a postmortem for an
    incident that is not there.
    """
    with connections() as conn:
        incident = incidents.get(conn, incident_id)

    if incident is None:
        return IncidentStatus.WITHDRAWN

    return incident.status if incident.status.is_a_persons_ending() else None
