"""Choosing the reversible action that answers the hypothesis, and only that.

The node reads nothing and changes nothing: it hands the cause the Investigator
named, and the flag history the round already read, to the agent that says which
action follows. That is what leaves room for the gate between this node and the
one that acts.

The history is not fetched here, and the cases about reading it are not here
either - they belong to the node that reads it, which is the investigation.
What is left is the part this node owns: which action comes back for a history
that was read, and what happens for one that could not be.

A provider that could not be read is not an error to raise. "Nothing changed"
and "I could not find out" both mean there is no action to take, and the
incident goes to a human either way - crashing the graph instead would drop
everything already learned about it. They are still not the same fact, which is
why one arrives here as an empty history and the other as none at all.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from argus_core.models import (
    Alert,
    Evidence,
    FailureMode,
    FlagChange,
    Hypothesis,
    IncidentStatus,
    RestartService,
    RevertFeatureFlag,
)
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.proposing import mitigation_proposal_node
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.builders import (
    a_determined_hypothesis,
    an_incident_state,
)

DONT_CARE_MOMENT = "2026-08-20T11:05:00Z"
SOME_SERVICE = "kuki-service"


@pytest.mark.unit
def test_the_proposal_node_proposes_an_action_for_the_flag_that_changed() -> None:
    the_flag_that_changed = "monthly-spend-feature"

    Scenario() \
        .given(
            a_mitigating_incident := _a_mitigating_incident(
                read_from_the_provider=[_an_enabling_of(the_flag_that_changed)]
            )
        ) \
        .when(lambda: mitigation_proposal_node(a_mitigating_incident)) \
        .then(all_of(_the_proposed_action_is_about(the_flag_that_changed),
                     _the_proposed_action_turns_the_flag_off()))


@pytest.mark.unit
def test_the_proposal_node_proposes_nothing_when_the_provider_could_not_be_read() -> None:
    # The round before this one asked and got no answer. Proposing on an empty
    # history instead would be acting on "nothing changed" when what happened
    # is that nobody could say.
    Scenario() \
        .given(
            a_mitigating_incident := _a_mitigating_incident(read_from_the_provider=None)
        ) \
        .when(lambda: mitigation_proposal_node(a_mitigating_incident)) \
        .then(_nothing_was_proposed())


@pytest.mark.unit
def test_a_leak_is_answered_by_a_restart_even_where_no_flag_moved() -> None:
    # Which is the whole difference between an empty history and none at all.
    # A leak is not something a flag did, so a provider that answered "nothing
    # changed" leaves the restart exactly where it was - and a provider that
    # could not answer stops it, because the round could not say what it would
    # do about anything.
    Scenario() \
        .given(
            a_leaking_incident := _a_mitigating_incident(
                read_from_the_provider=[], about=_a_leak_nobody_has_words_for
            )
        ) \
        .when(lambda: mitigation_proposal_node(a_leaking_incident)) \
        .then(_the_proposed_action_restarts(SOME_SERVICE))


@pytest.mark.unit
def test_an_incident_with_no_cause_named_has_nothing_proposed_for_it() -> None:
    # Nothing to look a strategy up by. The walk has a place to go when Argus
    # has nothing to offer, and it is the same place as "there was a strategy
    # and it found nothing to reverse".
    some_alert = Alert(service=SOME_SERVICE, alert_name="HighErrorRate")
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    Scenario() \
        .given(
            an_incident_with_no_hypothesis := state.model_copy(
                update={"flag_changes": [_an_enabling_of("monthly-spend-feature")]}
            )
        ) \
        .when(lambda: mitigation_proposal_node(an_incident_with_no_hypothesis)) \
        .then(_nothing_was_proposed())


def _a_leak_nobody_has_words_for(incident_id: str) -> Hypothesis:
    """A leak, named the way a model actually names one.

    The subject is prose about the symptom, which is the reason the restart
    cannot be addressed to it - and the reason the node has to be handed the
    alert's service instead.
    """
    some_confidence = 0.75

    return Hypothesis(
        incident_id=incident_id,
        summary="something is accumulating and never released",
        failure_mode=FailureMode.RESOURCE_LEAK,
        confidence=some_confidence,
        supporting_evidence=[Evidence(claim="some log line", at=None)],
        subject="kuki-service process heap (memory_used_bytes)"
    )


def _a_mitigating_incident(
    read_from_the_provider: list[FlagChange] | None,
    about: Callable[[str], Hypothesis] = a_determined_hypothesis
) -> IncidentState:
    some_alert = Alert(service=SOME_SERVICE, alert_name="HighErrorRate")
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    return state.model_copy(
        update={
            "hypothesis": about(state.incident_id),
            "flag_changes": read_from_the_provider
        }
    )


def _an_enabling_of(flag: str) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at=DONT_CARE_MOMENT)


def _the_proposed_action_is_about(flag: str) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        proposed = updates.proposed_action
        if not isinstance(proposed, RevertFeatureFlag):
            raise AssertionError(
                f"Expected an action about [{flag}], got [{proposed}]."
            )

        if proposed.flag != flag:
            raise AssertionError(
                f"Expected an action about [{flag}], it was about [{proposed.flag}]."
            )

        return True

    return assertion


def _the_proposed_action_turns_the_flag_off() -> Assertion[StateDelta]:
    """The flag was switched on and that is what is being undone, so the action
    is the opposite of the change it answers - never a repeat of it."""
    def assertion(updates: StateDelta) -> bool:
        proposed = updates.proposed_action
        if not isinstance(proposed, RevertFeatureFlag) or proposed.enabled is not False:
            raise AssertionError(
                f"Expected the action to turn the flag off, it was {proposed!r}."
            )

        return True

    return assertion


def _the_proposed_action_restarts(service: str) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        proposed = updates.proposed_action
        if not isinstance(proposed, RestartService) or proposed.service != service:
            raise AssertionError(
                f"Expected a restart of [{service}], got [{proposed!r}]."
            )

        return True

    return assertion


def _nothing_was_proposed() -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        proposed = updates.proposed_action
        if proposed is not None:
            raise AssertionError(
                f"Expected no action to be proposed, got {proposed!r}."
            )

        return True

    return assertion
