from __future__ import annotations

from typing import cast

import pytest
from agent_mitigation import Action, propose_action
from argus_core.models.cause import CauseType
from argus_core.models.flag_change import FlagChange
from argus_testkit import Assertion, Scenario

from agent_mitigation_test.framework.builders import (
    DONT_CARE_FLAG,
    EARLIER_IN_THE_WINDOW,
    LATER_IN_THE_WINDOW,
    a_disabling_of,
    a_hypothesis_blaming,
    an_enabling_of,
    an_undetermined_hypothesis,
)


@pytest.mark.unit
def test_a_flag_that_was_switched_on_is_proposed_to_be_switched_off() -> None:
    some_flag = "kuki-flag"

    Scenario() \
        .given(
            the_flag_was_switched_on := an_enabling_of(some_flag)
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                flag_changes=[the_flag_was_switched_on]
            )
        ) \
        .then(
            _the_action_proposed_sets(some_flag, enabled=False)
        )


@pytest.mark.unit
def test_a_flag_that_was_switched_off_is_proposed_to_be_switched_on() -> None:
    # A flag causes an incident by *changing*, and off is a direction it can
    # change in: a fallback disabled, traffic moved back to a path that has
    # since rotted. An agent that only ever turns flags off cannot mitigate
    # this incident at all - it would take an action that changes nothing.
    some_flag = "buki-flag"

    Scenario() \
        .given(
            the_flag_was_switched_off := a_disabling_of(some_flag)
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                flag_changes=[the_flag_was_switched_off]
            )
        ) \
        .then(
            _the_action_proposed_sets(some_flag, enabled=True)
        )


@pytest.mark.unit
def test_undoing_a_switch_on_records_that_the_flag_had_been_on() -> None:
    # The gate node rejects an action whose undo descriptor is empty before
    # anything mutating is called, so the descriptor has to exist at proposal
    # time - not be filled in by the write that it exists to guard.
    some_flag = "tuki-flag"

    Scenario() \
        .given(
            the_flag_was_switched_on := an_enabling_of(some_flag)
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                flag_changes=[the_flag_was_switched_on]
            )
        ) \
        .then(
            _the_undo_records(some_flag, was_enabled=True)
        )


@pytest.mark.unit
def test_undoing_a_switch_off_records_that_the_flag_had_been_off() -> None:
    Scenario() \
        .given(
            the_flag_was_switched_off := a_disabling_of(DONT_CARE_FLAG)
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                flag_changes=[the_flag_was_switched_off]
            )
        ) \
        .then(
            _the_undo_records(DONT_CARE_FLAG, was_enabled=False)
        )


@pytest.mark.unit
def test_a_flag_toggled_more_than_once_is_put_back_to_its_state_before_the_latest_change() -> None:
    # The incident is live, so the state to undo is the one the service is in
    # now - not whatever it was at the far edge of the window.
    some_flag = "shuki-flag"

    Scenario() \
        .given(
            it_was_switched_off_then_on := [
                a_disabling_of(some_flag, at=EARLIER_IN_THE_WINDOW),
                an_enabling_of(some_flag, at=LATER_IN_THE_WINDOW)
            ]
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                flag_changes=it_was_switched_off_then_on
            )
        ) \
        .then(
            _the_action_proposed_sets(some_flag, enabled=False)
        )


@pytest.mark.unit
def test_a_cause_with_no_reversible_action_proposes_nothing() -> None:
    # A bad deployment has no controllable condition until the git write path
    # exists. Proposing an approximate action for it is how an agent takes a
    # confident-looking action on a cause it cannot address.
    Scenario() \
        .given(
            a_flag_did_change := an_enabling_of(DONT_CARE_FLAG)
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.BAD_DEPLOYMENT),
                flag_changes=[a_flag_did_change]
            )
        ) \
        .then(
            _nothing_was_proposed()
        )


@pytest.mark.unit
def test_a_hypothesis_that_identified_no_cause_proposes_nothing() -> None:
    Scenario() \
        .given(
            a_flag_did_change := an_enabling_of(DONT_CARE_FLAG)
        ) \
        .when(
            lambda: propose_action(
                an_undetermined_hypothesis(),
                flag_changes=[a_flag_did_change]
            )
        ) \
        .then(
            _nothing_was_proposed()
        )


@pytest.mark.unit
def test_more_than_one_changed_flag_proposes_nothing_rather_than_guessing() -> None:
    # "The evidence says a flag, and I cannot tell which" is a real state, and
    # a human resolves it in seconds. Reverting one of two at random is a
    # production change made on a coin flip.
    some_flag = "kukibuki"
    some_other_flag = "shukituki"

    Scenario() \
        .given(
            two_flags_changed := [
                an_enabling_of(some_flag),
                a_disabling_of(some_other_flag)
            ]
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                flag_changes=two_flags_changed
            )
        ) \
        .then(
            _nothing_was_proposed()
        )


@pytest.mark.unit
def test_the_flag_the_hypothesis_names_is_the_one_proposed() -> None:
    # The case this exists for. Two flags moved recently - a previous
    # incident's, and this one's - and the Investigator already worked out
    # which. Deriving the answer again from the history alone throws that
    # away and escalates an incident that was solved.
    some_blamed_flag = "kukibuki-flag"
    not_the_blamed_flag = "shuki-flag"

    Scenario() \
        .given(
            two_flags_changed := [
                an_enabling_of(not_the_blamed_flag),
                a_disabling_of(some_blamed_flag)
            ]
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(
                    CauseType.FEATURE_FLAG_TOGGLE, subject=some_blamed_flag),
                flag_changes=two_flags_changed
            )
        ) \
        .then(
            _the_action_proposed_sets(some_blamed_flag, enabled=True)
        )


@pytest.mark.unit
def test_the_direction_comes_from_the_recorded_change_not_from_the_hypothesis() -> None:
    # The hypothesis says *which*; the provider says *which way*. A model that
    # described the toggle backwards in its prose must not be able to turn a
    # flag the wrong way, so the direction is never read from it.
    some_blamed_flag = "kuki-flag"

    Scenario() \
        .given(
            the_flag_was_switched_off := a_disabling_of(some_blamed_flag)
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(
                    CauseType.FEATURE_FLAG_TOGGLE, subject=some_blamed_flag),
                flag_changes=[the_flag_was_switched_off]
            )
        ) \
        .then(
            _the_action_proposed_sets(some_blamed_flag, enabled=True)
        )


@pytest.mark.unit
def test_a_named_flag_the_provider_never_recorded_proposes_nothing() -> None:
    # Two authorities disagreeing about one incident. Falling back to the
    # single-change rule here would act on a flag the Investigator did not
    # blame while its stated conclusion went uncorroborated - and a name that
    # is in no recorded change may be one the model invented.
    some_flag = "kukibuki"
    a_flag_nobody_recorded_changing = "shukituki"

    Scenario() \
        .given(
            a_different_flag_changed := an_enabling_of(some_flag)
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(
                    CauseType.FEATURE_FLAG_TOGGLE,
                    subject=a_flag_nobody_recorded_changing
                ),
                flag_changes=[a_different_flag_changed]
            )
        ) \
        .then(
            _nothing_was_proposed()
        )


@pytest.mark.unit
def test_no_flag_change_proposes_nothing() -> None:
    Scenario() \
        .given(
            nothing_changed := cast(list[FlagChange], [])
        ) \
        .when(
            lambda: propose_action(
                a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
                flag_changes=nothing_changed
            )
        ) \
        .then(
            _nothing_was_proposed()
        )


def _the_action_proposed_sets(flag: str, enabled: bool) -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if action is None:
            raise AssertionError(
                f"Expected an action setting flag [{flag}] to [{enabled}], "
                f"got none."
            )

        if (action.flag, action.enabled) != (flag, enabled):
            raise AssertionError(
                f"Expected an action setting flag [{flag}] to [{enabled}], "
                f"got flag [{action.flag}] to [{action.enabled}]."
            )

        return True

    return assertion


def _the_undo_records(flag: str, was_enabled: bool) -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if action is None:
            raise AssertionError(
                f"Expected an action recording flag [{flag}] as [{was_enabled}], "
                f"got none."
            )

        recorded = (action.undo_descriptor["flag"], action.undo_descriptor["was_enabled"])
        if recorded != (flag, was_enabled):
            raise AssertionError(
                f"Expected the undo to record flag [{flag}] as [{was_enabled}], "
                f"got {recorded}."
            )

        return True

    return assertion


def _nothing_was_proposed() -> Assertion[Action | None]:
    def assertion(action: Action | None) -> bool:
        if action is not None:
            raise AssertionError(
                f"Expected no action to be proposed, got [{action}]."
            )

        return True

    return assertion
