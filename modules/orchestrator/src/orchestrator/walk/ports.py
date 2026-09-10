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

from agent_investigator import Findings
from agent_mitigation import Action, Outcome
from agent_mitigation.tools import StillWanted
from agent_postmortem import PostmortemDocument
from argus_core.events import IncidentEvent, Publisher, nobody
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.reading import Reading
from argus_core.models.undo_descriptor import UndoDescriptor

# `records_nothing` is aliased because `events` and `replay` each call their
# no-op sink `nobody`, correctly and for the same reason - and this module
# holds both.
from argus_core.replay import Recorder
from argus_core.replay import nobody as records_nothing


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
        recorder: Recorder = records_nothing,
    ) -> Findings: ...


class RecordHypothesis(Protocol):
    # Positional-only: the hypothesis is all this is called with, so any
    # single-argument callable is one, whatever it named its parameter.
    def __call__(self, hypothesis: Hypothesis, /) -> None: ...


class RecordOutcome(Protocol):
    def __call__(self, hypothesis_id: str, tested: bool, result: str) -> None: ...


class PostUpdate(Protocol):
    def __call__(self, incident_id: str, message: str) -> None: ...


class Page(Protocol):
    def __call__(self, incident_id: str, message: str) -> None: ...


class FetchFlagChanges(Protocol):
    def __call__(self) -> list[FlagChange]: ...


class TakeAction(Protocol):
    # The action is positional, so any callable naming it whatever it likes is
    # one. The rest are keyword-only and defaulted: the incident and the
    # publisher are what the action narrates itself against, and `still_wanted`
    # is how the wait for the service to answer hears that somebody stopped the
    # walk. A caller with none of the three takes the same action, tells nobody,
    # and is stopped by nothing.
    def __call__(
        self,
        action: Action,
        /,
        *,
        still_wanted: StillWanted = ...,
        incident_id: str | None = None,
        publisher: Publisher = nobody,
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
        action_type: str,
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
        narrating: IncidentEvent,
    ) -> None: ...


class ChangeLanded(Protocol):
    """Whether Argus's own change to a flag reached the provider after a moment.

    `None` where the provider could not say - unreachable, or attributing
    nothing to Argus because operator and agent share a credential. It is not
    "no change was made": one of those answers means act, and the other means
    say so and stop.
    """

    def __call__(self, flag: str, since: datetime) -> bool | None: ...


class ActionClaimedAt(Protocol):
    """When the claim on this candidate's action was written.

    The moment the provider's log is asked about: a change to the same flag
    before it belongs to whoever made the incident, and only one after it can
    be the attempt that stopped halfway.
    """

    def __call__(self, incident_id: str, hypothesis_id: str) -> datetime | None: ...


class ActionAlreadyTaken(Protocol):
    """What an earlier attempt recorded for this candidate, if anything.

    `None` where the claim exists and nothing was recorded against it: the
    worker holding it stopped between taking the action and saying what
    happened, which is the one case this walk cannot answer for itself.
    """

    def __call__(
        self,
        incident_id: str,
        hypothesis_id: str,
    ) -> str | None: ...


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
        actor: Actor,
        action: str,
        narrating: IncidentEvent,
        result: str | None = None,
        confidence: float | None = None,
    ) -> None: ...


class WritePostmortem(Protocol):
    # Positional-only: the incident is all this is called with, and the real
    # one carries a recorder behind it that a stand-in has no use for.
    def __call__(self, incident_id: str, /) -> PostmortemDocument: ...


class RecordPostmortem(Protocol):
    def __call__(self, incident_id: str, document: PostmortemDocument, /) -> None: ...


class RecordNote(Protocol):
    # The same narration a transition carries, minus the one thing that makes a
    # transition one. A node that has something to say and moved nothing says it
    # through here.
    def __call__(
        self,
        incident_id: str,
        actor: Actor,
        action: str,
        result: str | None = None,
        confidence: float | None = None,
    ) -> None: ...
