"""Looking for a permanent fix, once no reversible action is left."""

from __future__ import annotations

from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import ProposeFix
from orchestrator.walk.routes import POSTMORTEM_ROUTE
from orchestrator.walk.state import IncidentState


def codefix_node(state: IncidentState, propose_fix: ProposeFix) -> StateDelta:
    """Looks for a permanent fix, once no reversible action is left (spec §7.4).

    What the agent answered is what this reports, and where the proposal can be
    read is the whole of the report: this is the one step in the walk that ends
    with somebody else's turn, and a line describing a fix without saying where
    it is would leave everyone hunting for a branch.

    The agent is asked even when the walk concluded nothing, about nothing.
    "I looked and found no fix" and "nobody looked" reach the same human and
    only one of them would be true.

    Three outcomes rather than two, because a proposal that could not be *made*
    is a different thing from one that was not warranted - and the difference
    matters to whoever reads it: "no fix was found" is a verdict on the code,
    where "the repository refused" is something somebody can go and repair
    before asking again.
    """
    try:
        proposed = propose_fix(
            state.hypothesis.summary if state.hypothesis else "", state.incident_id
        )
    except Exception as error:
        # Caught deliberately, and caught broadly. What opens a pull request is
        # a tool on another process, so what arrives here is whatever the
        # transport raised - and an incident that failed at this step would
        # never reach the human it was on its way to, taking everything the
        # investigation learned with it. A bad afternoon, not a lost incident.
        return StateDelta(
            fix_found=False,
            narration=Narration(
                action="no code-level fix could be proposed",
                detail=f"the fix could not be proposed: {error}",
            ),
        )

    if proposed is None:
        return StateDelta(
            fix_found=False,
            narration=Narration(
                action="no code-level fix found",
                detail="no code-level fix found, so the incident goes to a human",
            ),
        )

    return StateDelta(
        fix_found=True,
        narration=Narration(
            action="a code-level fix was proposed",
            detail=f"a draft pull request is open at {proposed.url}",
        ),
    )


def route_after_codefix(state: IncidentState) -> str:
    """Wherever it came from and however it went, the incident gets written up.

    One route, because there is one destination. This branched on `resolved`
    against everything else and both arms reached the postmortem anyway - a
    distinction the graph could not act on, and since a mitigation stopped
    being called resolved, one nothing sets either. How the incident ended is
    the status's to say; where it goes next was never in doubt.
    """
    return POSTMORTEM_ROUTE
