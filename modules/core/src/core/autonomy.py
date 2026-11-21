"""What Argus may do on its own authority, and the proof that it was asked
(spec §13).

The policy the gate applies, kept apart from the agent that performs the write.
A guarantee enforced by the code it constrains is a convention rather than a
guarantee, and while this lived inside the Mitigator a change to the Mitigator
alone could widen what Argus does unasked. In the kernel because two parties
name what is here - the walk asks the question, and the Mitigator accepts only
its answer - and a contract kept inside either is one the other installs an
agent to read.

Two things, and they are one module because they share a secret.

The declared set of generic mitigations, and the two questions asked of an
action against it: whether its kind is one Argus may take unasked, and whether
where it is aimed is within the estate Argus may touch.

`Admitted`, the proof that an action was put to both and passed. Only `admit`
can build one - the constructor demands a key nothing outside this module can
name - so a value of the type is evidence rather than a claim, and the
Mitigator's `take_action` accepts nothing else. That makes the gate a fact the
type checker reads, where it used to be an edge in a graph somebody had to
remember to draw.

What admits an action is membership, not reversibility, and the one place the
two meet is held by the set's own test rather than here: no kind in the set may
be one whose change is irreversible (`Leaves.IRREVERSIBLE`). A kind that loses
something for good is a tier up and a person's to approve, and a set that came
to hold one would be a guardrail removed by an edit nobody had to defend - so it
is a build that fails instead.

Membership is asked of a closed set rather than of whether the action can be
undone. That is the criterion both industry frames actually use: Google SRE's
*generic mitigations* are a defined, small set - drain, roll back, restart, add
capacity - applied before the cause is known, and ITIL's *standard change* is
pre-authorised for being routine and well understood rather than for being
reversible. A restart can be undone by nothing, so "must be undoable" would put
the industry's most common first response behind a human gate while flipping a
production flag stayed automatic - backwards on any reading of blast radius.

The set is declared here as a literal rather than derived from the registered
strategies. A strategy answers "what should be done about this cause"; this
answers "may Argus do that unasked", and deriving the second from the first
would let an action acquire autonomy by being implemented. Adding a kind is a
line somebody writes and defends.
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from typing import Final, NoReturn, final

from core.models import (
    DISCARD_CACHE_ENTRIES,
    PIN_AUTOSCALER,
    PIN_TO_ACCELERATOR,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    Action,
    ActionType,
    Refusal,
    ServiceDependency,
    the_service_addressed_by,
)

__all__ = [
    "GENERIC_MITIGATIONS",
    "Admitted",
    "AdmittedMitigations",
    "admit",
    "is_a_generic_mitigation",
    "is_within_reach"
]

# The kinds of action that may be taken without a human. Small enough to read
# in one sitting, which is the property that makes it reviewable at all.
type AdmittedMitigations = AbstractSet[ActionType]

GENERIC_MITIGATIONS: Final[AdmittedMitigations] = frozenset(
    {
        REVERT_FEATURE_FLAG,
        RESTART_SERVICE,
        ROLL_BACK_DEPLOYMENT,
        SCALE_OUT,
        PIN_AUTOSCALER,
        # The sixth member, and the first that removes something rather than
        # restoring, adding or stopping something. Saying so a third time is the
        # point: what admits an action unasked is membership of this set, never
        # the kind of change it makes - and this is the member most easily read
        # as a weakening, because removing data sounds heavier than putting a
        # value back.
        #
        # It is not heavier. What it removes was derived from records it never
        # reaches, the service recomputes each figure from those records the next
        # time anybody asks for it, and what is gone cannot be stale. A
        # responder would do it by hand without pausing.
        DISCARD_CACHE_ENTRIES,
        # The seventh, and a drain: pods moved off a class of hardware with
        # nothing deployed changed, which Google SRE's list of generic
        # mitigations names beside rolling back, restarting and adding capacity.
        PIN_TO_ACCELERATOR
    }
)


@final
class _AdmissionKey:
    """What `Admitted` asks for before it will hold an action. One exists, and
    nothing outside this module can name it."""

    __slots__ = ()


_ADMISSION: Final = _AdmissionKey()


@final
class Admitted[A: Action]:
    """An action the declared set admits, aimed within the estate Argus may
    touch - and the proof that both were asked.

    Built by `admit` and by nothing else. The constructor takes a key only this
    module holds, so a caller outside it cannot satisfy the type checker and
    cannot get past the check below either: what holds one of these was handed
    it by the policy, and what takes one - `mitigation.take_action` - may act
    on it unasked.

    Never stored. A walk's state is checkpointed as data, and a proof that could
    be read back from a row would be one anybody could write into the row - so
    a walk resumed after its worker died asks `admit` again from the same
    action, the same alert and the same register, and is answered as the gate
    was answered. Nor pickled: a pickle is a row by another name, and the
    default one for a slotted class rebuilds it without the key.

    Admission is the whole of what this says. The cap on attempts and whether
    anything could confirm the action are the walk's questions, asked by its
    gate before the action is taken; nothing here carries their answers.
    """

    __slots__ = ("_action",)

    def __init__(self, action: A, *, key: _AdmissionKey) -> None:
        if key is not _ADMISSION:
            raise TypeError("an action is admitted by admit(), never constructed")

        self._action: Final = action

    @property
    def action(self) -> A:
        """The action that was admitted."""
        return self._action

    def __repr__(self) -> str:
        return f"Admitted({self._action!r})"

    def __reduce__(self) -> NoReturn:
        """Refuses to be pickled. `copy` and `pickle` both rebuild an object
        from what this returns, and the default for a slotted class rebuilds it
        through `object.__new__` - past `__init__`, and so past the key."""
        raise TypeError("an admission is never stored - ask admit() again")


def admit[A: Action](action: A,
                     *,
                     alerting_service: str,
                     dependencies: Sequence[ServiceDependency]) -> Admitted[A] | Refusal:
    """`action` admitted, or the refusal that says why it is not (spec §13).

    Two questions, asked in the order they narrow: whether Argus does this sort
    of thing at all, then whether it may do it *there*. Asked the other way
    round, an action nobody pre-authorised anywhere would be reported as aimed
    at the wrong address. They are separate refusals because they ask different
    people for different things - "Argus does not do that" asks somebody to
    widen the declared set and defend the addition, and "Argus does not touch
    that" usually asks somebody to correct an entry in the register.

    The dependencies arrive as a value, retrieved before the walk reached this
    question - whether Argus may act cannot depend on a document store being
    reachable at the moment it asks. An empty list is what an unreadable
    register looks like, and leaves everything addressed to the alerting
    service exactly as admitted as it was.
    """
    if not is_a_generic_mitigation(action):
        return Refusal.NOT_A_GENERIC_MITIGATION

    if not is_within_reach(action, alerting_service, dependencies):
        return Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH

    return Admitted(action, key=_ADMISSION)


def is_a_generic_mitigation(action: Action,
                            admitted: AdmittedMitigations = GENERIC_MITIGATIONS) -> bool:
    """Whether Argus may take an action of this kind on its own authority
    (spec §13).

    A question about the kind, never about the instance. Absence from the set
    is a refusal rather than a default to permitted: a kind nobody has declared
    is one nobody has argued for, and assuming the best about it is how an
    unreviewed action reaches production the day it is implemented.

    `admitted` is a parameter so the restrictive direction can be shown with a
    set that holds nothing. Widening it builds nothing: an answer of yes here is
    a `bool`, and the only thing `take_action` accepts is what `admit` builds
    against the declared set.
    """
    return action.action_type in admitted


def is_within_reach(action: Action,
                    alerting_service: str,
                    dependencies: Sequence[ServiceDependency]) -> bool:
    """Whether the thing this action is addressed to is within the estate Argus
    may touch.

    The second question, and the one the kind cannot answer. An address that
    comes from an investigation can name a third party, a service in another
    part of the estate, or prose a model mistook for a hostname, and no fact
    about the kind of action rules any of those out.

    Within reach is the alerting service itself, always - Argus has been
    restarting and rolling that one back since before there was a register, and
    making it conditional on a document somebody maintains would let a stale
    entry withdraw an authority nobody meant to withdraw. Otherwise it is a
    dependency the register lists for that service *and* marks as the
    organisation's own.

    Everything else is refused, and the refusal is the restrictive direction on
    purpose: an estate is not a thing to guess at, because something somewhere
    answers to almost any plausible service name. That includes an ownership
    nothing here recognises - `ServiceDependency.is_ours` tests for the one word
    that means ours, so a register that grows a fourth answer withholds authority
    rather than granting it.
    """
    addressed_to = the_service_addressed_by(action)

    if addressed_to is None or addressed_to == alerting_service:
        return True

    return any(
        dependency.name == addressed_to and dependency.is_ours
        for dependency in dependencies
    )
