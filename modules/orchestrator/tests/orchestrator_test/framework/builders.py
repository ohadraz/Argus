from __future__ import annotations

import random
import string

from argus_core.models import (
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ActionIdentity,
    ActionType,
    Alert,
    Evidence,
    FailureMode,
    Hypothesis,
    IncidentStatus,
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


def the_incident_is_still_wanted() -> IsStillWanted:
    """A world in which nobody has taken the incident back.

    The counterpart of `the_incident_was_withdrawn`, and the one most tests
    need: a walk has to be allowed to proceed before anything about how it
    proceeds can be asked.
    """
    def still_wanted(dont_care_incident_id: str) -> bool:
        return True

    return still_wanted
