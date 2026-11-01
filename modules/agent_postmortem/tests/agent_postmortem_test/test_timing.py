"""How soon after the alert Argus did what went well, said by code."""

from __future__ import annotations

from datetime import timedelta

import pytest
from agent_postmortem import ActionRecord
from agent_postmortem.timing import how_soon_argus_moved
from argus_core.models import ForCandidate, OpenedPullRequest, TimelineEntry, Verdict
from argus_testkit import Scenario, the_answer_was

from agent_postmortem_test.framework.builders import (
    STARTED_AT,
    a_timeline_entry,
    an_action,
    an_evidence_bundle,
)

SOME_ALERT = STARTED_AT
SOME_PULL_REQUEST = OpenedPullRequest(number=7, url="https://github.com/kuki/shop/pull/7",
                                      branch="argus/kuki")


def _forming(seconds: float, who: str | None = "Investigator Agent") -> TimelineEntry:
    """A line that formed the first candidate, `seconds` after the alert."""
    return a_timeline_entry("dont care", at=SOME_ALERT + timedelta(seconds=seconds)) \
        .model_copy(update={"who": who, "candidates": [0]})


def _for_the_first(seconds: float, who: str = "Mitigation Agent") -> TimelineEntry:
    """A line that acted for the first candidate, `seconds` after the alert."""
    return a_timeline_entry("dont care", at=SOME_ALERT + timedelta(seconds=seconds), who=who) \
        .model_copy(update={"for_candidate": ForCandidate(place=0, said_as="dont care")})


def _confirmed(action: str, line: int, judged: float | None = None) -> ActionRecord:
    """An action for the first candidate, said on `line`, that the service
    confirmed - `judged` seconds after the alert, where a test says when."""
    return an_action(action, verdict=Verdict.CONFIRMED, line=line).model_copy(update={
        "candidate": 1,
        "judged_at": SOME_ALERT + timedelta(seconds=judged) if judged is not None else None})


@pytest.mark.unit
def test_a_confirmed_action_is_timed_from_the_alert_by_whoever_said_each_moment() -> None:
    # Set by the model, the confirmation's span came after "brought the
    # service back", so it read as a three-minute recovery from a service back
    # in one. Each span opens its sentence here, and what the verdict measured
    # is said as it measured it: no longer at the incident's level. The verdict
    # is dated by the record, and said by whoever took the action: its own
    # line ("Judged the action CONFIRMED") names no candidate.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                alerted_at=SOME_ALERT,
                timeline=[_forming(10), _for_the_first(60),
                          a_timeline_entry("Judged the action CONFIRMED",
                                           at=SOME_ALERT + timedelta(seconds=190))],
                actions=[_confirmed("Reverted the feature flag kuki", line=1, judged=190)])
        ) \
        .when(
            lambda: how_soon_argus_moved(evidence)
        ) \
        .then(
            the_answer_was([
                "10 seconds after the alert was raised, the Investigator Agent formed the "
                "cause that was acted on, C1.",
                "1 minute after the alert was raised, the Mitigation Agent reverted the "
                "feature flag kuki.",
                "3 minutes 10 seconds after the alert was raised, the Mitigation Agent "
                "confirmed the service was no longer at the incident's level."
            ])
        )


@pytest.mark.unit
def test_a_cause_is_timed_from_the_line_that_first_formed_it() -> None:
    # A later round can list the same candidate again; it was formed when it
    # was first said.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                alerted_at=SOME_ALERT,
                timeline=[_forming(10), _forming(40), _for_the_first(60)],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED,
                                   line=2).model_copy(update={"candidate": 1})])
        ) \
        .when(
            lambda: how_soon_argus_moved(evidence)[0]
        ) \
        .then(
            the_answer_was("10 seconds after the alert was raised, the Investigator Agent "
                           "formed the cause that was acted on, C1.")
        )


@pytest.mark.unit
@pytest.mark.parametrize("verdict", [Verdict.REFUTED, None], ids=["refuted", "never-judged"])
def test_an_action_nothing_confirmed_is_not_timed(verdict: str | None) -> None:
    # A refuted action did not go well, and one a person's report stopped
    # before Argus judged it confirmed nothing.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                alerted_at=SOME_ALERT,
                timeline=[_forming(10), _for_the_first(60)],
                actions=[an_action("dont care", verdict=verdict,
                                   line=1).model_copy(update={"candidate": 1})])
        ) \
        .when(
            lambda: how_soon_argus_moved(evidence)
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
def test_a_proposed_fix_is_timed_from_the_alert_among_the_rest() -> None:
    # The pull request is what a reader opens next, and told to say no span of
    # its own, the model can no longer time it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                alerted_at=SOME_ALERT,
                timeline=[_forming(10), _for_the_first(60)],
                actions=[_confirmed("Reverted the feature flag kuki", line=1, judged=300)],
                pull_request=SOME_PULL_REQUEST
            ).model_copy(update={"pull_request_opened_at": SOME_ALERT + timedelta(seconds=120)})
        ) \
        .when(
            lambda: how_soon_argus_moved(evidence)[2]
        ) \
        .then(
            the_answer_was("2 minutes after the alert was raised, Code-Fix proposed a draft "
                           "fix, PR #7.")
        )


@pytest.mark.unit
def test_a_span_is_worked_out_from_the_instants_as_the_rows_show_them() -> None:
    # The rows show each instant to the second; worked out from the fractions
    # instead, a span would disagree with the two rows beside it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                alerted_at=SOME_ALERT + timedelta(seconds=0.9),
                timeline=[_forming(10.1), _for_the_first(60)],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED,
                                   line=1).model_copy(update={"candidate": 1})])
        ) \
        .when(
            lambda: how_soon_argus_moved(evidence)[0]
        ) \
        .then(
            the_answer_was("10 seconds after the alert was raised, the Investigator Agent "
                           "formed the cause that was acted on, C1.")
        )


@pytest.mark.unit
def test_a_moment_on_a_line_naming_nobody_is_said_as_argus_s() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                alerted_at=SOME_ALERT,
                timeline=[_forming(10, who=None), _for_the_first(60)],
                actions=[an_action("dont care", verdict=Verdict.CONFIRMED,
                                   line=1).model_copy(update={"candidate": 1})])
        ) \
        .when(
            lambda: how_soon_argus_moved(evidence)[0]
        ) \
        .then(
            the_answer_was("10 seconds after the alert was raised, Argus formed the cause that "
                           "was acted on, C1.")
        )
