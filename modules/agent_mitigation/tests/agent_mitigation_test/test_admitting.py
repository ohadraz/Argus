"""What Argus may do on its own authority, and the shape of that question.

The gate's whole criterion, and the one place the autonomy boundary is decided.
It asks about membership of a closed, declared set - not about whether an action
can be undone, which is what it used to ask and which parted company with
admissibility the moment a mitigation existed that changes nothing to put back.

The set itself is written out here rather than read from the code under test. It
is the reviewable artefact: a test that asked the module what it contained would
agree with it whatever it contained, and the day a kind nobody argued for
appears in it, nothing would go red.

Three kinds are declared, and they are unalike in the way that matters. One
leaves a value behind to put back, one leaves nothing at all, and one leaves
two things behind - a deployment on an earlier revision and a platform no
longer reconciling it. That all three are in the set is the clearest statement
that membership, and not reversibility, is what is being asked.
"""

from __future__ import annotations

import pytest
from agent_mitigation import (
    GENERIC_MITIGATIONS,
    AdmittedMitigations,
    is_a_generic_mitigation,
)
from argus_core.models import (
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    ActionType,
    RollBackDeployment,
)
from argus_testkit import Assertion, Scenario

from agent_mitigation_test.framework.builders import DONT_CARE_FLAG, an_action_setting


@pytest.mark.unit
def test_an_action_in_the_declared_set_may_be_taken() -> None:
    # Reverting a flag is the mitigation Argus was built around, and it is in
    # the set because somebody put it there - not because a strategy exists
    # that can propose one.
    Scenario() \
        .given(an_admitted_action := an_action_setting(DONT_CARE_FLAG, enabled=False)) \
        .when(lambda: is_a_generic_mitigation(an_admitted_action)) \
        .then(_it_is_admitted())


@pytest.mark.unit
def test_an_action_of_a_kind_the_set_does_not_hold_is_refused() -> None:
    # Absence is a refusal, never a default to permitted. A kind nobody has
    # declared is a kind nobody has argued for, and assuming the best about one
    # is how an unreviewed action reaches production the day it is implemented
    # - so the boundary fails in the restrictive direction, and a deployment
    # that declared nothing takes nothing unasked.
    a_set_holding_no_kind_at_all: AdmittedMitigations = frozenset()

    Scenario() \
        .given(some_action := an_action_setting(DONT_CARE_FLAG, enabled=False)) \
        .when(
            lambda: is_a_generic_mitigation(
                some_action, admitted=a_set_holding_no_kind_at_all
            )
        ) \
        .then(_it_is_refused())


@pytest.mark.unit
def test_the_declared_set_is_exactly_what_it_is_written_down_as() -> None:
    # Stated, not derived. Adding a kind is a line somebody writes and defends,
    # and this is where the defending gets noticed: a change to the set that
    # nobody meant fails here, naming both what it was and what it became.
    the_kinds_argus_may_take_unasked: set[ActionType] = {
        REVERT_FEATURE_FLAG, RESTART_SERVICE, ROLL_BACK_DEPLOYMENT
    }

    Scenario() \
        .given(GENERIC_MITIGATIONS) \
        .when(lambda: set(GENERIC_MITIGATIONS)) \
        .then(_the_set_is(the_kinds_argus_may_take_unasked))


def _it_is_admitted() -> Assertion[bool]:
    def assertion(admitted: bool) -> bool:
        if not admitted:
            raise AssertionError(
                "Expected the action to be one Argus may take unasked, "
                "and it was refused."
            )

        return True

    return assertion


def _it_is_refused() -> Assertion[bool]:
    def assertion(admitted: bool) -> bool:
        if admitted:
            raise AssertionError(
                "Expected the action to be refused as one nobody declared, "
                "and it was admitted."
            )

        return True

    return assertion


def _the_set_is(expected: set[ActionType]) -> Assertion[set[ActionType]]:
    def assertion(declared: set[ActionType]) -> bool:
        if declared != expected:
            raise AssertionError(
                f"Expected the mitigations Argus may take unasked to be "
                f"{sorted(expected)}, and they are {sorted(declared)}."
            )

        return True

    return assertion


@pytest.mark.unit
def test_rolling_a_configuration_back_may_be_taken_unasked() -> None:
    # Admissible for one specific reason, and it is not that it can be undone:
    # the revision it applies was reviewed and ran before, so Argus replays
    # somebody's change rather than authoring one. Writing to the
    # configuration repository would be the other thing, and is refused by
    # not being an action at all.
    Scenario() \
        .given(a_rollback := RollBackDeployment(application="io-shop")) \
        .when(lambda: is_a_generic_mitigation(a_rollback)) \
        .then(_it_is_admitted())
