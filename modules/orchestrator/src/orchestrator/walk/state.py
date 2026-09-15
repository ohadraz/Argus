"""The walk's own state, and the machine that says where it stands.

Here rather than in the kernel because one module has a graph: `IncidentState`
is LangGraph's `StateGraph` state, and a type twenty packages install in order
to name a `UuidStr` has no business also describing this module's workflow.

`status_after` comes with it. It reads the state's fields and nothing else, so
wherever the state lives is the only place the machine can be stated without
one of the two importing the other across a boundary.
"""
from __future__ import annotations

from argus_core.models import Action, Alert, Attempt, Hypothesis, IncidentStatus, Reading, Verdict
from pydantic import BaseModel


class IncidentState(BaseModel):
    """LangGraph `StateGraph` state (spec §7.1), mirroring the Postgres
    schema (§11.1)."""

    incident_id: str
    alert: Alert
    status: IncidentStatus
    # The candidate under test - the one the gate judges and Mitigation acts
    # on. Kept beside the list rather than derived at every use, because every
    # node downstream asks "the hypothesis this incident is about", and making
    # each of them index into a list would be four chances to index differently.
    hypothesis: Hypothesis | None = None
    # Every explanation the investigation offered, best first, and how far along
    # them the walk has got. The list is what makes a refuted mitigation
    # something other than a dead end: being wrong about a correlated change is
    # the ordinary case, and the second explanation is usually still on it.
    candidates: list[Hypothesis] = []
    candidate_index: int = 0
    # What has already been tried and did not help. Carried into a later
    # investigation as evidence - it is the one thing a second round knows that
    # the first could not.
    attempts: list[Attempt] = []
    # What earlier rounds of this incident retrieved - which channel, over which
    # window. Carried so that a later round can be told what the one before it
    # saw: it may read the same window again, since that evidence is not in its
    # own transcript, but it should know it would be re-reading rather than
    # reaching somewhere new.
    already_read: list[Reading] = []
    # How many times this incident has been investigated. What bounds the walk,
    # because what buys a later round is the refutation rather than the window:
    # an attempt that failed is evidence no amount of reading produces, and a
    # hard incident has usually spent its whole widening schedule by the time
    # the first attempt comes back refuted.
    rounds: int = 0
    # Chosen by Mitigation and inspected by the tier gate before anything
    # mutating runs (spec §13). It lives in the graph's state rather than being
    # passed between the two, because a gate the acting node could bypass by
    # re-deriving the action would guard nothing.
    proposed_action: Action | None = None
    # Whether the round that just ran found any candidate worth acting on. The
    # Investigator's own answer, recorded because it is the one thing that
    # distinguishes an investigation with nothing to offer from a walk that has
    # worked through everything it was offered - the two leave the same list
    # behind, and they are not the same incident.
    nothing_worth_trying: bool = False
    # What Code-Fix found, and `None` until it has run. Three-valued rather than
    # a bool, because "no fix yet" and "no fix to be had" are the difference
    # between an incident still being worked on and one a human now owns.
    fix_found: bool | None = None
    # Derivable from `hypothesis`, kept because the graph's state is what the
    # Dashboard reads (§7.7) and a confidence-over-time view wants it flat.
    confidence: float | None = None
    # What the attempt concluded, as the verdict itself. Not its spelling: the
    # state machine branches on this, and a comparison against a string is one
    # that keeps compiling after somebody changes how a verdict is written.
    action_outcome: Verdict | None = None


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

    The order of the questions is the design, and the first of them is "did the
    symptom stop". A confirmed action is the strongest evidence anything here
    has - metrics re-queried after the change and recovered - so it is asked
    first, and it is asked before `fix_found` because an incident that was
    mitigated and then had a fix proposed for it carries both at once.

    Only then does the walk's own arithmetic decide, and `fixing` is what is
    left when every question above it has been answered no.

    **Nothing here returns `resolved`.** A mitigation stops a symptom and a
    draft pull request proposes a change nobody has made; neither ends the
    cause, and Argus cannot merge (spec §13). What this derives is how far
    Argus got, and the furthest it gets is `mitigated`.

    `state.status` is never read. Deriving a status from a status would put the
    node that set the previous one back in the business this function takes it
    out of.
    """
    if state.action_outcome == Verdict.CONFIRMED:
        return IncidentStatus.MITIGATED

    # A fix reached without a confirmed mitigation is one Argus arrived at
    # having stopped nothing: the symptom is still happening, and a proposal
    # does not stop it. Whether one was found decides what the incident carries,
    # not what state it is in.
    if state.fix_found is not None:
        return IncidentStatus.ESCALATED

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
