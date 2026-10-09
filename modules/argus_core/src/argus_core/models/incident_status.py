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
    # The symptom stopped and the cause did not. A flag is back where it was, a
    # version is rolled back, and the fault that was exposed is still in the
    # code with a workaround holding it off - which is a different thing from
    # the incident being over, and the thing a reverted flag has always
    # actually been. Argus called it `resolved` before, which was the state
    # machine saying something untrue about the world (spec §10).
    MITIGATED = "mitigated"
    # The cause is gone, not merely held off. Argus does not reach this on its
    # own: what makes a mitigated incident resolved is the permanent fix being
    # merged, and merging is outside its autonomy by construction (§13).
    RESOLVED = "resolved"
    FIXING = "fixing"
    ESCALATED = "escalated"
    # Argus worked out what to do and declined to do it. Not a kind of
    # escalation, which is Argus running out of moves and handing over: here
    # there is a move, it is named, and what stopped it being taken is that
    # nothing could say afterwards whether it had worked. An action Argus cannot
    # verify is one it must not take unasked, however sound the diagnosis - and
    # the difference a reader of an outcome most needs is whether somebody has
    # to work out what to do or go and do a named thing, which is exactly what a
    # shared status would erase.
    RECOMMENDED = "recommended"
    # There was no incident. The alarm reported a condition on a series the
    # system also retrieves, and the window holds no departure in any series it
    # judges - so what fired is the rule rather than the service.
    #
    # Not a kind of escalation, and the distinction is the whole of why it is
    # here. An escalation hands a human an incident nobody has explained, and
    # sends them to look at the service; this hands over nothing, and sends them
    # to look at the rule. Reported as one status, a dashboard of spurious pages
    # is indistinguishable from a dashboard of unsolved outages.
    #
    # Deliberately not `refuted`, which already means a mitigation attempt the
    # evidence undid. One word for both would make every later reader work out
    # which was meant.
    DISPROVEN = "disproven"
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
        sits while Code-Fix looks for a permanent fix - reached once no
        mitigation is left to try, and reached again by a mitigation that
        worked, since the fault outlives the symptom either way. Argus is still
        working on it.

        `acknowledged` is not one either, for the opposite reason: nothing has
        started rather than nothing is left. An incident sitting there is one a
        worker has yet to pick up, which is the state a page polling it most
        needs to keep polling through.

        `withdrawn` is terminal for a reason neither of the other two share:
        nothing is left because a human ended it, not because the walk did. It
        is also the one status the walk itself reads back, since it is the only
        way an incident can end that the walk's own state cannot tell it about.

        `mitigated` is terminal in the same sense `escalated` is - it is as far
        as Argus can take the incident, and what would move it on is a person's
        to do. Something is still owed there, which is exactly what the status
        is for saying; it is not something Argus is still working on, so a page
        polling it would poll forever.

        `recommended` is terminal for that same reason, and the thing owed is
        the sharpest of any status here: a named action nobody has taken. Argus
        has stopped not because it ran out of moves but because it declined the
        one it had, so there is nothing of its own still running and nothing it
        is waiting for.

        `disproven` is the plainest terminal of the set, and the only one with
        nothing owed at all. Every other ending is as far as Argus could take
        something; this is as far as there was anything to take.
        """
        return self in (
            IncidentStatus.MITIGATED,
            IncidentStatus.RESOLVED,
            IncidentStatus.ESCALATED,
            IncidentStatus.RECOMMENDED,
            IncidentStatus.DISPROVEN,
            IncidentStatus.WITHDRAWN
        )

    def is_a_persons_ending(self) -> bool:
        """Whether a person writes this status, from outside the walk.

        `withdrawn` and `resolved`, and nothing else. The walk never derives
        either (`status_after` reaches `mitigated` at furthest), so finding one
        on the row means somebody put it there - which is why nothing the walk
        writes afterwards may replace it, and why the walk stops for both.

        Argus's own endings are not among them. A mitigated incident read as
        ended by a person would have the walk skip the Code-Fix it goes on to.
        """
        return self in (IncidentStatus.WITHDRAWN, IncidentStatus.RESOLVED)

    def accepts_resolution(self) -> bool:
        """Whether a person may report the incident resolved from here.

        Every status but three, the terminal endings Argus reached by stopping
        included: `mitigated`, `escalated` and `recommended` each leave
        something owed, and a person who went on to finish the job is reporting
        exactly that. Taking the report from any of them is also what keeps a
        person from racing the walk - whichever status the incident has reached
        by the time they press, the report is accepted.

        The three it refuses are the endings a resolution would contradict.
        `resolved` already is. `withdrawn` was taken back, and resolving it
        would rewrite why it ended after its changes were put back. `disproven`
        had no incident to resolve.

        On the status for the reason `is_terminal` is: the store that refuses
        the write and the page that hides the control both ask, and two copies
        of the rule are two that can disagree.
        """
        return self not in (
            IncidentStatus.RESOLVED,
            IncidentStatus.WITHDRAWN,
            IncidentStatus.DISPROVEN
        )
