"""What a node asks of the world, said as a type rather than as an import.

Every collaborator a node takes as a default-argument parameter has its shape
here. The node then names a `Protocol`, not a function: the real thing goes in
where the graph is assembled, and a test puts in whatever answers the same
call.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from agent_mitigation import Action, Outcome, StillWanted, Verdict
from argus_core.events import IncidentEvent, Publisher, nobody
from argus_core.models import (
    ActionType,
    Alert,
    Attempt,
    Findings,
    FlagChange,
    Hypothesis,
    IncidentStatus,
    OpenedPullRequest,
    PostmortemDocument,
    Reading,
    UndoDescriptor,
)

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both.
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing
from pydantic import BaseModel


class Investigate(Protocol):
    def __call__(
        self,
        alert: Alert,
        incident_id: str,
        # Keyword-only, because the real `investigate` carries its retrieval
        # seams between these and `incident_id`. A protocol that allowed them
        # positionally would be describing a call nothing can make.
        *,
        already_read: Sequence[Reading] | None = None,
        already_refuted: Sequence[Attempt] | None = None,
        publisher: Publisher = nobody,
        recorder: Recorder = records_nothing
    ) -> Findings: ...


class RecordHypothesis(Protocol):
    # Positional-only: the hypothesis is all this is called with, so any
    # single-argument callable is one, whatever it named its parameter.
    def __call__(self, hypothesis: Hypothesis, /) -> None: ...


class RecordOutcome(Protocol):
    def __call__(self, hypothesis_id: str, tested: bool, result: str) -> None: ...


class FetchFlagChanges(Protocol):
    def __call__(self) -> list[FlagChange]: ...


class TakeAction(Protocol):
    # The action is positional, so any callable naming it whatever it likes is
    # one. The rest are keyword-only and defaulted: the incident and the
    # publisher are what the action narrates itself against, and `still_wanted`
    # is how the wait for the service to answer hears that somebody stopped the
    # walk. A caller with none of the three takes the same action, tells nobody,
    # and is stopped by nothing.
    #
    # `still_wanted` is the same question as `argus_incidents`' `IsStillWanted`,
    # already bound to an incident. The walk holds both names because the walk is
    # what binds them: `mitigating` partials the incident id in before it calls
    # the agent, and the agent below asks without knowing which incident it is
    # asking about. The arity is the whole difference - neither is the other
    # spelt wrong.
    def __call__(
        self,
        action: Action,
        /,
        *,
        still_wanted: StillWanted = ...,
        incident_id: str | None = None,
        publisher: Publisher = nobody
    ) -> Outcome: ...


class RecordAction(Protocol):
    """Claims the right to act on one candidate, before anything is done.

    Answers whether this walk is the one that took the action. `False` means an
    earlier attempt already claimed it - which a walk only ever sees when it has
    been resumed inside this node, since the claim is written before the action
    and outlives the worker that wrote it.
    """

    def __call__(
        self,
        incident_id: str,
        hypothesis_id: str,
        # The tag, not a string. Every caller already holds one - the action it
        # is about to take - so the wider type buys nothing except the ability
        # to claim a row for a kind of action no renderer has words for.
        action_type: ActionType
    ) -> bool: ...


class CompleteAction(Protocol):
    """Records what came of an action already claimed, and says so.

    `narrating` for the reason `TransitionIncident` has one: the verdict and
    the line reporting it are one fact, and two writes of one fact can end up
    disagreeing about it.
    """

    def __call__(
        self,
        incident_id: str,
        hypothesis_id: str,
        outcome: str,
        undo_descriptor: UndoDescriptor | None,
        narrating: IncidentEvent
    ) -> None: ...


class Reversible(Protocol):
    """Whether an action of this kind is one Argus can put back (spec §13).

    A question about the kind, not the instance: the models no longer allow an
    action of a reversible kind to exist without its way back, so what is left
    for the gate to ask is whether Argus knows how to undo actions of this sort
    at all. The real answer comes from the strategy that would have proposed
    one; the gate names the question as a type so that it is asked of something
    a test can replace with a strategy that says no.
    """

    # Positional-only: the action is the whole question.
    def __call__(self, action: Action, /) -> bool: ...


class ChangeLanded(Protocol):
    """Whether Argus's own change to a flag reached the provider after a moment.

    `None` where the provider could not say - unreachable, or attributing
    nothing to Argus because operator and agent share a credential. It is not
    "no change was made": one of those answers means act, and the other means
    say so and stop.
    """

    def __call__(self, flag: str, since: datetime) -> bool | None: ...


class ClaimedAction(BaseModel):
    """What an earlier attempt on this candidate staked, and what came of it.

    Both, because the resuming walk needs both and needs them to describe one
    attempt. Asked separately they were two reads of the same row, which is a
    round trip nobody needed and, worse, two answers that a write landing
    between them could draw from different moments.

    `outcome` is `None` where the claim exists and nothing was recorded against
    it: the worker holding it stopped between taking the action and saying what
    happened, which is the one case this walk cannot answer for itself. It is
    then `claimed_at` that matters - the moment the provider's log is asked
    about, since a change to the same flag before it belongs to whoever made
    the incident, and only one after it can be the attempt that stopped halfway.

    The verdict itself rather than the text of the column it was read from. The
    walk branches on this, and a branch on a string is a branch that goes on
    compiling after somebody changes how a verdict is spelt.
    """

    outcome: Verdict | None
    claimed_at: datetime


class ActionAlreadyTaken(Protocol):
    """What an earlier attempt left on this candidate, if it left anything.

    `None` where no claim was ever written - which the resuming branch does not
    expect to see, since it is reached only by losing a claim to somebody.
    """

    def __call__(
        self,
        incident_id: str,
        hypothesis_id: str
    ) -> ClaimedAction | None: ...


class TransitionIncident(Protocol):
    """Moves the incident and records the account of the move, as one write.

    `narrating` is not optional: a status the incident entered for a reason
    nobody wrote down is a row a human cannot read the incident from, and the
    two being one argument is what stops them being two writes that can
    disagree.
    """

    def __call__(
        self,
        incident_id: str,
        to_status: IncidentStatus,
        narrating: IncidentEvent
    ) -> None: ...


class ProposeFix(Protocol):
    """A draft pull request proposing a permanent fix, or `None` where there is
    none to offer.

    Positional-only. The hypothesis is what Code-Fix works from - the conclusion
    the walk reached, rather than the incident itself, which an agent could
    investigate a second time and reach a different answer about. Whole rather
    than its summary, because the evidence is where a location lives: this
    service's error boundary records the innermost frame, so one of the log
    lines the investigation quoted names the file and the line. An agent handed
    only the sentence searches for what it was already holding. The
    incident id goes with it because the proposal is named after it: two
    incidents patching the same file must not write over each other's branch.

    What comes back is an address, not a sentence. This is the one step in the
    walk that ends with somebody else's turn, so what it hands on has to be
    something a person can open.

    `None` is an answer - looked for, not found - and the node reports it as
    one. That is the difference between an incident a human is told nothing
    could be done about and an incident nobody looked at.
    """

    def __call__(self,
                 hypothesis: Hypothesis | None,
                 incident_id: str, /) -> OpenedPullRequest | None: ...


class WritePostmortem(Protocol):
    # Positional-only: the incident is all this is called with, and the real
    # one carries a recorder behind it that a stand-in has no use for.
    def __call__(self, incident_id: str, /) -> PostmortemDocument: ...


class RecordPostmortem(Protocol):
    def __call__(self, incident_id: str, document: PostmortemDocument, /) -> None: ...
