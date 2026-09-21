"""Looking for a permanent fix, once mitigation has done what it can."""

from __future__ import annotations

from agent_codefix import FixDeclined, FixNotAnswered
from argus_core.events import FixAttempted, Narrator, Publisher, nobody
from argus_core.models import FixOutcome, OpenedPullRequest

from orchestrator.walk.deltas import Narration, StateDelta
from orchestrator.walk.ports import ProposeFix
from orchestrator.walk.routes import POSTMORTEM_ROUTE
from orchestrator.walk.state import IncidentState


def codefix_node(state: IncidentState,
                 propose_fix: ProposeFix,
                 publisher: Publisher = nobody) -> StateDelta:
    """Looks for a permanent fix, once mitigation has done what it can (spec §7.4).

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

    **It publishes its own account, rather than only narrating.** Every other
    node moves the incident, so the status it implies is written and the
    narration goes with it. This one usually does not: an incident that
    arrived here `mitigated` leaves `mitigated` whatever the agent found, so
    the narration handed up is discarded unwritten (see `narrating.with_status`)
    and the only step that ends with somebody else's turn would leave no trace
    at all. It did, and finding out why took the checkpoint tables.
    """
    narrator = Narrator(state.incident_id, publisher)

    try:
        proposed = propose_fix(state.hypothesis, state.incident_id)
    except FixNotAnswered as error:
        # Caught above the broad clause below, because it is the one failure
        # here that says nothing about the service. The agent read until its
        # turns ran out - a bound that was too small, or a cause too wide to
        # narrow from - and reporting that as "no fix was found" would be a
        # verdict on code nobody finished looking at.
        return _said(
            narrator,
            found=False,
            outcome=FixOutcome.NOT_ANSWERED,
            proposal=None,
            action="no code-level fix was proposed",
            detail=f"the agent did not finish looking: {error}",
        )
    except FixDeclined as declined:
        # Above the broad clause for the same reason as the one above it,
        # and for a different failure: this one says nothing about the
        # repository. The model was asked and said no, which is neither an
        # outage to repair nor a budget to widen, and it read as the first
        # of those for as long as it fell through to the clause below.
        return _said(
            narrator,
            found=False,
            outcome=FixOutcome.DECLINED,
            proposal=None,
            action="no code-level fix was proposed",
            detail=f"the model declined to write one: {declined}",
        )
    except Exception as error:
        # Caught deliberately, and caught broadly. What opens a pull request is
        # a tool on another process, so what arrives here is whatever the
        # transport raised - and an incident that failed at this step would
        # never reach the human it was on its way to, taking everything the
        # investigation learned with it. A bad afternoon, not a lost incident.
        #
        # Swallowed from the walk, not from the reader: what stopped it is the
        # whole value of this branch, and the one outcome somebody can act on
        # before asking again.
        return _said(
            narrator,
            found=False,
            outcome=FixOutcome.NOT_POSSIBLE,
            proposal=None,
            action="no code-level fix could be proposed",
            detail=f"the fix could not be proposed: {error}",
        )

    if proposed is None:
        return _said(
            narrator,
            found=False,
            outcome=FixOutcome.NOT_WARRANTED,
            proposal=None,
            action="no code-level fix found",
            detail="no code-level fix found, so the incident goes to a human",
        )

    return _said(
        narrator,
        found=True,
        outcome=FixOutcome.PROPOSED,
        proposal=proposed,
        action="a code-level fix was proposed",
        detail=f"a draft pull request is open at {proposed.url}",
    )


def _said(narrator: Narrator,
          *,
          found: bool,
          outcome: FixOutcome,
          proposal: OpenedPullRequest | None,
          action: str,
          detail: str) -> StateDelta:
    """The one account of this step, published and handed up in one place.

    Both, rather than either. The narration is what a transition would say if
    this step moved the incident, and on the road here from a refuted walk it
    does; the event is what says so when it does not. Written once so the two
    cannot disagree about what happened - which is the failure that would be
    hardest to see, because each would look right on its own.
    """
    narrator.say(FixAttempted, outcome=outcome, pull_request=proposal, detail=detail)

    return StateDelta(
        fix_found=found, narration=Narration(action=action, detail=detail)
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
