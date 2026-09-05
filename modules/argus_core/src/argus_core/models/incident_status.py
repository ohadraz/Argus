from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from .action import Verdict

if TYPE_CHECKING:
    # Imported for the annotation only. `IncidentState` names this module for
    # its own `status` field, so importing it here at runtime would close a
    # cycle; the reducer reads the state's attributes and never needs the class.
    from .incident_state import IncidentState


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
        """
        return self in (IncidentStatus.RESOLVED, IncidentStatus.ESCALATED)


def status_after(state: IncidentState, max_rounds: int) -> IncidentStatus:
    """Where the incident stands, given everything done to it so far (spec §10).

    The state machine, stated once. Every node in the graph produces work - a
    verdict measured against re-queried metrics, a list of candidates, an
    attempt that did not help - and the status is a conclusion drawn from that
    work rather than a decision any node gets to make. Five nodes each drawing
    it separately is how `fixing` came to mean "looking for the next candidate"
    in one place and "Code-Fix is working" in another.

    Pure, and deliberately so. Every input here was measured: a verdict comes
    from metrics re-queried after the change, an index from a list the
    investigation produced. A model asked to re-derive this would be
    second-guessing evidence with prose, and would make the one part of an
    incident that has to be reproducible depend on a sampled call.

    `max_rounds` is a parameter rather than read from `Settings`, for the reason
    `Hypothesis.is_confident_enough` takes its threshold: a domain rule has no
    business knowing how Argus is configured, and the caller already holds the
    value.

    The order of the questions is the design. A code fix settles the incident
    outright, so it is asked first. An action's verdict comes next, because it
    is the strongest evidence anything here has. Only then does the walk's own
    arithmetic decide, and `fixing` is what is left when every question above it
    has been answered no.

    `state.status` is never read. Deriving a status from a status would put the
    node that set the previous one back in the business this function takes it
    out of.
    """
    if state.fix_found is not None:
        return IncidentStatus.RESOLVED if state.fix_found else IncidentStatus.ESCALATED

    if state.action_outcome == Verdict.CONFIRMED:
        return IncidentStatus.RESOLVED

    # Not a third opinion on the hypothesis: nothing was changed and nothing was
    # measured, so a further experiment would run against a world Argus cannot
    # describe.
    if state.action_outcome == Verdict.ESCALATED:
        return IncidentStatus.ESCALATED

    # The investigation's own answer, and the one place it differs from the
    # walk's. A round that named nothing worth trying has already widened its
    # window as far as it can, so the rounds that remain would buy a re-read of
    # the same evidence - unlike a refuted attempt, which is evidence no amount
    # of reading produces.
    if state.nothing_worth_trying:
        return IncidentStatus.ESCALATED

    # Every node that sets the index sets it to something worth trying, or past
    # the end of the list - so the index alone says whether a candidate is under
    # test, and this function never re-runs the search that produced it.
    if state.candidate_index < len(state.candidates):
        return IncidentStatus.MITIGATING

    if state.rounds < max_rounds:
        return IncidentStatus.INVESTIGATING

    return IncidentStatus.FIXING
