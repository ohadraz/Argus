from __future__ import annotations

from enum import StrEnum


class IncidentStatus(StrEnum):
    INVESTIGATING = "investigating"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"
    FIXING = "fixing"
    ESCALATED = "escalated"

    def is_terminal(self) -> bool:
        """Whether the incident has anywhere left to go (spec §10).

        Asked by anything that waits on an incident - a page that polls, a
        report counting what is still open. It lives here rather than in each
        of those callers because it is a fact about the state machine, and a
        second copy of it elsewhere is a second copy that can go stale when the
        machine grows a state.

        `fixing` reads like an ending and is not one: it is where a refuted
        action goes to ask whether another candidate is left to try.
        """
        return self in (IncidentStatus.RESOLVED, IncidentStatus.ESCALATED)
