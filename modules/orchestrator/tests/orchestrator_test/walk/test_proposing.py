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

One cause is answered by neither the history nor the service, and it is the one
that pins what this node has to carry. An entry in a store is addressed by a key
nothing in Argus can compose, so the keys the alert arrived with are the whole of
what the answer can be worked out from - and the node holds the alert.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from argus_core.models import (
    Alert,
    DiscardCacheEntries,
    Evidence,
    FailureMode,
    FlagChange,
    Hypothesis,
    IncidentStatus,
    PinToAccelerator,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
)
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.proposing import mitigation_proposal_node
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.builders import (
    a_corruption_blamed_on,
    a_deployment,
    a_determined_hypothesis,
    a_divergence_blamed_on,
    a_placement,
    an_accelerator_blamed_on,
    an_incident_state,
)

DONT_CARE_MOMENT = "2026-08-20T11:05:00Z"
SOME_SERVICE = "kuki-service"
# The card `a_placement` has the fleet running on before the onset.
THE_FLEETS_CARD = "Tesla-V100-SXM2-16GB"


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
def test_a_divergence_is_answered_by_discarding_the_entries_the_alert_named() -> None:
    # What this node has to carry from the alert beyond the service. Every
    # other mitigation is addressed to something the history or the alert names
    # outright; this one is addressed to keys, and a node handing on the cause
    # and the service alone would propose nothing at all for a cause it
    # diagnosed correctly - with nothing anywhere saying why.
    the_entries_the_check_found = ("io-shop:summary:2026-09:shopper-4",
                                   "io-shop:summary:2026-09:shopper-9")

    Scenario() \
        .given(
            a_diverging_incident := _a_diverging_incident(the_entries_the_check_found)
        ) \
        .when(lambda: mitigation_proposal_node(a_diverging_incident)) \
        .then(_the_proposed_action_discards(the_entries_the_check_found))


@pytest.mark.unit
def test_a_corruption_a_deployment_caused_is_answered_by_rolling_it_back() -> None:
    # The node hands on the deploy history the round read, as it hands on the
    # flag history. Without it, a corruption with no flag behind it would have
    # nothing proposed for it, and an incident Argus had diagnosed correctly
    # would end without the one thing it could recommend.
    some_alert = Alert(service=SOME_SERVICE, alert_name="SpendTotalsDoNotReconcile")
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    Scenario() \
        .given(
            a_corrupting_incident := state.model_copy(
                update={
                    "hypothesis": a_corruption_blamed_on(
                        state.incident_id, "monthly totals fall behind the purchases"
                    ),
                    "flag_changes": [],
                    "deployments": [a_deployment()]
                }
            )
        ) \
        .when(lambda: mitigation_proposal_node(a_corrupting_incident)) \
        .then(_the_proposed_action_rolls_back(SOME_SERVICE))


@pytest.mark.unit
def test_a_replica_moved_onto_another_card_is_answered_by_holding_the_fleet_to_its_card() -> None:
    # The node hands on the placement the round recorded, as it hands on the
    # histories. Without it the pin has no card to name, and an incident Argus
    # had diagnosed correctly would have nothing proposed for it.
    some_alert = Alert(service=SOME_SERVICE, alert_name="FraudHoldsHigh")
    state = an_incident_state(some_alert, IncidentStatus.MITIGATING)

    Scenario() \
        .given(
            an_incident_whose_replica_moved := state.model_copy(
                update={
                    "hypothesis": an_accelerator_blamed_on(
                        state.incident_id, "one replica holds far more for review"
                    ),
                    "flag_changes": [],
                    "placement": a_placement()
                }
            )
        ) \
        .when(lambda: mitigation_proposal_node(an_incident_whose_replica_moved)) \
        .then(_the_proposed_action_holds_the_fleet_to(SOME_SERVICE, THE_FLEETS_CARD))


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


def _a_diverging_incident(stale_entry_keys: tuple[str, ...]) -> IncidentState:
    """A mitigating incident whose alert named the entries that disagree.

    The count is stated beside the keys because the alert refuses a pair that
    does not account for itself - which is the model's own guard against a
    truncated list, and not this file's subject.

    The history is empty rather than absent. A copy that fell behind is not
    something a flag did, so what is under test here must not be reachable by
    the separate route a provider nobody could read takes.
    """
    the_alert_that_found_them = Alert(
        service=SOME_SERVICE,
        alert_name="CachedSpendTotalsAreStale",
        stale_entry_keys=stale_entry_keys,
        stale_entries_found=len(stale_entry_keys)
    )
    state = an_incident_state(the_alert_that_found_them, IncidentStatus.MITIGATING)

    return state.model_copy(
        update={
            "hypothesis": a_divergence_blamed_on(
                state.incident_id, "cached monthly totals disagree with the ledger"
            ),
            "flag_changes": []
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


def _the_proposed_action_discards(keys: tuple[str, ...]) -> Assertion[StateDelta]:
    """The entries the alert named, exactly and in the order it named them.

    Order and duplicates are part of the claim rather than pedantry: a
    collection that sorted or collapsed them would be a different set of
    entries wearing the same count, and the store's receipt - a number -
    cannot tell the two apart afterwards.
    """
    def assertion(updates: StateDelta) -> bool:
        proposed = updates.proposed_action
        if not isinstance(proposed, DiscardCacheEntries):
            raise AssertionError(
                f"Expected a discard of {list(keys)}, got [{proposed!r}]."
            )

        if proposed.keys != keys:
            raise AssertionError(
                f"Expected a discard of {list(keys)}, it named "
                f"{list(proposed.keys)}."
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


def _the_proposed_action_rolls_back(application: str) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        proposed = updates.proposed_action
        if not isinstance(proposed, RollBackDeployment) \
                or proposed.application != application:
            raise AssertionError(
                f"Expected a rollback of [{application}], got [{proposed!r}]."
            )

        return True

    return assertion


def _the_proposed_action_holds_the_fleet_to(application: str,
                                           card: str) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        proposed = updates.proposed_action
        if proposed != PinToAccelerator(application=application, accelerator=card):
            raise AssertionError(
                f"Expected [{application}] to be held to [{card}], got "
                f"[{proposed!r}]."
            )

        return True

    return assertion
