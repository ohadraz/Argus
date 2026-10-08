from __future__ import annotations

import random
import string
from datetime import UTC, datetime, timedelta

from argus_core.models import (
    DISCARD_CACHE_ENTRIES,
    PIN_TO_ACCELERATOR,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    ActionIdentity,
    ActionType,
    Alert,
    ChangeEvent,
    ChangeKind,
    Evidence,
    FailureMode,
    Hypothesis,
    IncidentStatus,
    PodPlacement,
    RecordedPlacement,
)
from argus_incidents.withdrawal import IsStillWanted
from orchestrator.walk.state import IncidentState


def an_incident_state(
    alert: Alert, status: IncidentStatus, incident_id: str | None = None
) -> IncidentState:
    if incident_id is None:
        incident_id = a_random_id()

    return IncidentState(incident_id=incident_id, alert=alert, status=status)


def a_random_id() -> str:
    letters = "".join(random.choices(string.ascii_lowercase, k=4))
    digits = "".join(random.choices(string.digits, k=3))

    return f"{letters}-{digits}"


def a_determined_hypothesis(incident_id: str, confidence: float = 0.75) -> Hypothesis:
    """A hypothesis that named a cause, which is all the walk asks of one.

    The confidence has a default because nothing decides on it any more - it is
    reported and never read - so a test that is not about it should not have to
    pick a number.
    """
    return Hypothesis(
        incident_id=incident_id,
        summary="kukibuki hypothesis",
        failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
        confidence=confidence,
        supporting_evidence=[Evidence(claim="some log line", at=None)]
    )


def an_undetermined_hypothesis(incident_id: str) -> Hypothesis:
    """A hypothesis that found no cause - and so carries no confidence.

    Two builders rather than one with nullable arguments, because the model
    refuses to hold a cause without a confidence or the reverse: the two valid
    shapes are genuinely different objects.
    """
    return Hypothesis(
        incident_id=incident_id,
        summary="no cause determined from the evidence retrieved",
        failure_mode=None,
        confidence=None,
        supporting_evidence=[Evidence(claim="some log line", at=None)]
    )


def an_identity(action_type: ActionType, subject: str) -> ActionIdentity:
    """What the walk knows an action by: its kind and what it acts on.

    Here rather than in the file that first needed one, because what counts as
    the same action is the rule several suites are written about - the walk
    passes over a candidate it has already tried, and every one of those tests
    has to name the identity the same way to be testing that rule at all.
    """
    return ActionIdentity(action_type=action_type, subject=subject)


def putting_back(flag: str) -> ActionIdentity:
    """Reverting a flag, as the walk identifies it."""
    return an_identity(REVERT_FEATURE_FLAG, flag)


def restarting(service: str) -> ActionIdentity:
    """Restarting a service, as the walk identifies it."""
    return an_identity(RESTART_SERVICE, service)


def rolling_back(application: str) -> ActionIdentity:
    """Rolling a deployment back, as the walk identifies it.

    Here beside the other two because the same rule is asked about it: what the
    walk passes over, and now also which platform an action reaches the estate
    through - and a suite naming the identity its own way would be testing
    neither.
    """
    return an_identity(ROLL_BACK_DEPLOYMENT, application)


def holding_to_a_card(application: str) -> ActionIdentity:
    """Holding a deployment's pods to one card, as the walk identifies it.

    Addressed to the application and never to the card, which is what the
    kernel's own subject says: a pin to one card refuted and a pin to another is
    the same experiment on the same fleet.
    """
    return an_identity(PIN_TO_ACCELERATOR, application)


def discarding(service: str) -> ActionIdentity:
    """Throwing a service's stale cached figures away, as the walk identifies it.

    Addressed to the service and never to the keys, which is what the kernel's
    own subject says: the entries a check finds stale differ between one run and
    the next, so an identity carrying them would make every discard a different
    action and the cap on repeating one unreachable.
    """
    return an_identity(DISCARD_CACHE_ENTRIES, service)


def the_incident_was_withdrawn() -> IsStillWanted:
    """A world in which a human has taken the incident back.

    Answers `False` to every id rather than to a particular one: what the walk
    does with a withdrawal is the subject, and a stub that could say yes to the
    wrong incident would be testing the id-matching of the double instead.
    """
    def still_wanted(dont_care_incident_id: str) -> bool:
        return False

    return still_wanted


def a_candidate_blaming(incident_id: str, flag: str) -> Hypothesis:
    """An explanation that names the flag it blames.

    Carries a subject where `a_determined_hypothesis` does not, which is the
    whole reason it exists separately: what the walk refuses to try twice is an
    *action*, not a hypothesis object, and for a flag the action is addressed to
    the name the candidate gives - so two candidates blaming the same flag are
    different findings answered by one experiment.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="kukibuki hypothesis",
                      failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=flag)


def a_leak_blamed_on(incident_id: str, prose: str) -> Hypothesis:
    """An explanation that a resource is leaking, in the model's own words.

    The subject is prose on purpose. It is what the real ones look like, and it
    is the reason a restart cannot be addressed to the candidate.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="something is accumulating and never released",
                      failure_mode=FailureMode.RESOURCE_LEAK,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=prose)


def a_divergence_blamed_on(incident_id: str, prose: str) -> Hypothesis:
    """An explanation that cached copies have stopped agreeing with the records.

    The subject is prose for the reason the leak's is, and the consequence here
    is sharper: an entry in a store is addressed by a key, a key's format
    belongs to whoever wrote the store, and so the action answering this
    candidate can be worked out from nothing the candidate itself says. It is
    the one candidate a caller can fail to find an answer for while every other
    kind still gets one.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="the cache is serving figures the ledger has moved past",
                      failure_mode=FailureMode.STATE_DIVERGENCE,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=prose)


def a_corruption_blamed_on(incident_id: str, prose: str) -> Hypothesis:
    """An explanation that what the service wrote is wrong, in the model's words.

    Names no flag on purpose. The mode names the damage rather than the change,
    so what answers it is read off the change histories rather than off the
    candidate - and a candidate that named a flag would let the flag history
    answer for a case that is about the deploy history.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="monthly totals have stopped keeping up with purchases",
                      failure_mode=FailureMode.SILENT_DATA_CORRUPTION,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=prose)


def an_accelerator_blamed_on(incident_id: str, prose: str) -> Hypothesis:
    """An explanation that a replica moved onto another card, in the model's
    words.

    The card is nowhere in it on purpose. Which card to hold the fleet to is read
    off the placement the round recorded, so a candidate naming one would let the
    candidate answer for a case that is about the placement.
    """
    some_confidence = 0.75

    return Hypothesis(incident_id=incident_id,
                      summary="one replica answers differently since it moved",
                      failure_mode=FailureMode.ACCELERATOR_HETEROGENEITY,
                      confidence=some_confidence,
                      supporting_evidence=[Evidence(claim="some log line", at=None)],
                      subject=prose)


def a_deployment() -> ChangeEvent:
    """A revision the platform recorded going out.

    Which revision and when are nobody's concern here: what reads it asks only
    whether the platform recorded one.
    """
    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at="2026-09-27T09:14:00Z",
        reference="26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2",
        summary="dont-care-summary"
    )


def a_placement() -> RecordedPlacement:
    """Where a service's pods were running, recorded against an onset.

    Two pods on two cards, one serving long before the onset and one placed at
    it, because that is the shape a placement is read for. Which pods and which
    cards are nobody's concern where this is used: what reads it there asks only
    whether the placement arrived.
    """
    onset = datetime(2026, 10, 7, 21, 41, tzinfo=UTC)

    return RecordedPlacement(
        onset=onset,
        pods=(
            PodPlacement(
                pod="io-shop-5b8c6d-x2kqp",
                node="gpu-v100-0",
                accelerator="Tesla-V100-SXM2-16GB",
                started_at=onset - timedelta(hours=2)
            ),
            PodPlacement(
                pod="io-shop-5b8c6d-r7wzt",
                node="gpu-a100-0",
                accelerator="NVIDIA-A100-SXM4-40GB",
                started_at=onset - timedelta(seconds=30)
            )
        )
    )


def the_incident_is_still_wanted() -> IsStillWanted:
    """A world in which nobody has taken the incident back.

    The counterpart of `the_incident_was_withdrawn`, and the one most tests
    need: a walk has to be allowed to proceed before anything about how it
    proceeds can be asked.
    """
    def still_wanted(dont_care_incident_id: str) -> bool:
        return True

    return still_wanted
