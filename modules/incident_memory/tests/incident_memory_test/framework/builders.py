"""One incident's stored actions, built as the rows a finished walk left behind.

A `TakenAction` carries eleven fields and a memory record reads three of them.
Spelled out per test, the other eight are noise a reader scans past to find the
one the test is about - so they are fixed here, and each builder names only what
its caller cares about.

The incident's identity is fixed too. Every action in one test belongs to one
incident, and a test that had to thread an id through three builders to say so
would be about the threading.
"""

from __future__ import annotations

from datetime import UTC, datetime

from argus_core import new_id
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    Alert,
    CauseType,
    Evidence,
    Hypothesis,
    TakenAction,
    Verdict,
)
from incident_memory.records import RememberedIncident, WhatWasTried

SOME_INCIDENT = "0f5c4d6e-3a1b-4c2d-8e9f-1a2b3c4d5e6f"

DONT_CARE_DESCRIPTION = "checkout began failing after a flag was switched on"

# Both fixed, and neither read by anything under test. An action's moment and
# the tier it was taken at belong to the incident record; a memory of what was
# tried keeps the subject and the verdict and nothing else.
DONT_CARE_MOMENT = datetime(2026, 8, 30, 10, 14, tzinfo=UTC)

# What the investigation concluded, where a test is about something else. It is
# prose in every case that reads it, so one sentence serves them all.
DONT_CARE_CONCLUSION = "the new-checkout-flow flag was switched on"

# What a candidate is about, and how sure the model was, where a test is about
# neither. The ordering's cases name both; nothing else does.
DONT_CARE_SUBJECT = "new-checkout-flow"
DONT_CARE_CONFIDENCE = 0.82
DONT_CARE_SERVICE = "io-shop"
DONT_CARE_ALERT_NAME = "HighErrorRate"


def an_alert(alert_name: str = "HighErrorRate",
             service: str = "io-shop",
             summary: str | None = None) -> Alert:
    """The alert that opened an incident, named only where the name matters."""
    return Alert(
        service=service,
        alert_name=alert_name,
        severity="critical",
        summary=summary,
        started_at=DONT_CARE_MOMENT
    )


def a_hypothesis(summary: str = DONT_CARE_CONCLUSION,
                 observations: list[str] | None = None,
                 subject: str | None = DONT_CARE_SUBJECT,
                 confidence: float = DONT_CARE_CONFIDENCE) -> Hypothesis:
    """What the investigation concluded, and what it said it rests on.

    `observations` are the claims alone. An observation's instant is a field a
    reader follows back to the minute it rests on, and nothing that describes an
    incident for searching reads it - so a test naming one per claim would be
    saying it mattered.

    `subject` and `confidence` are named by the ordering's tests and by nobody
    else: what a candidate is about and how sure the model was are the two
    things an order is decided from, and the cases that are not about ordering
    should not have to state either.
    """
    return Hypothesis(
        incident_id=SOME_INCIDENT,
        summary=summary,
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=confidence,
        supporting_evidence=[
            Evidence(claim=claim, at=DONT_CARE_MOMENT)
            for claim in (observations if observations is not None else [])
        ],
        subject=subject
    )


def a_remembered_incident(incident_id: str = SOME_INCIDENT,
                          tried: list[tuple[str, Verdict]] | None = None,
                          service: str = DONT_CARE_SERVICE) -> RememberedIncident:
    """One past incident, as long-term memory holds it.

    What an ordering reads is `tried` and nothing else, so everything a search
    would have needed to find this record is fixed here.
    """
    return RememberedIncident(
        incident_id=incident_id,
        described_as=DONT_CARE_DESCRIPTION,
        service=service,
        alert_name=DONT_CARE_ALERT_NAME,
        tried=[
            WhatWasTried(subject=subject, verdict=verdict)
            for subject, verdict in (tried if tried is not None else [])
        ]
    )


def an_action(subject: str,
              verdict: Verdict | None = None,
              incident_id: str = SOME_INCIDENT) -> TakenAction:
    """One action as the `action` table holds it.

    `verdict` is optional because a row with no outcome is a real state and one
    the composer has to answer for: the action was claimed and the walk stopped
    between taking it and saying what happened.
    """
    return TakenAction(
        id=new_id(),
        incident_id=incident_id,
        hypothesis_id=new_id(),
        type=REVERT_FEATURE_FLAG,
        subject=subject,
        reversible=True,
        undo_descriptor=None,
        outcome=verdict,
        taken_at=DONT_CARE_MOMENT
    )


def an_action_on_nothing(verdict: Verdict = Verdict.REFUTED) -> TakenAction:
    """An action whose subject was never recorded.

    Nothing later can match on it, so it is the one row a memory record has no
    use for however determined its outcome was.
    """
    return an_action(subject="", verdict=verdict).model_copy(update={"target": None})
