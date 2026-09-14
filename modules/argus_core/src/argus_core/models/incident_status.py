from __future__ import annotations

from enum import StrEnum


class IncidentStatus(StrEnum):
    # Argus has the alert and has committed to handling it, and nothing is
    # looking at it yet. The status of the incident rather than of the graph:
    # a walk is queued for a worker, and the interval before one takes it is
    # real - reporting it as `investigating` would claim attention the incident
    # does not have, and a worker that never starts would never correct it.
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"
    FIXING = "fixing"
    ESCALATED = "escalated"
    # A human took the incident back: they had it in hand, and Argus was told to
    # stop. Its own status rather than a kind of escalation, because escalation
    # is Argus running out of moves and handing over, and this is a handover
    # nobody asked Argus for - the difference a reader of an incident's outcome
    # most needs, and the one a shared status would erase.
    WITHDRAWN = "withdrawn"

    def is_terminal(self) -> bool:
        """Whether the incident has anywhere left to go (spec §10).

        Asked by anything that waits on an incident - a page that polls, a
        report counting what is still open. It lives here rather than in each
        of those callers because it is a fact about the state machine, and a
        second copy of it elsewhere is a second copy that can go stale when the
        machine grows a state.

        `fixing` reads like an ending and is not one: it is where an incident
        sits while Code-Fix looks for a permanent fix, reached once no
        reversible action is left to try. Argus is still working on it.

        `acknowledged` is not one either, for the opposite reason: nothing has
        started rather than nothing is left. An incident sitting there is one a
        worker has yet to pick up, which is the state a page polling it most
        needs to keep polling through.

        `withdrawn` is terminal for a reason neither of the other two share:
        nothing is left because a human ended it, not because the walk did. It
        is also the one status the walk itself reads back, since it is the only
        way an incident can end that the walk's own state cannot tell it about.
        """
        return self in (
            IncidentStatus.RESOLVED,
            IncidentStatus.ESCALATED,
            IncidentStatus.WITHDRAWN
        )
