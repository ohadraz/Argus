"""What Argus may do on its own authority, and the shape of that question.

The gate's whole criterion, and the one place the autonomy boundary is decided.
It asks about membership of a closed, declared set - not about whether an action
can be undone, which is what it used to ask and which parted company with
admissibility the moment a mitigation existed that changes nothing to put back.

The set itself is written out here rather than read from the code under test. It
is the reviewable artefact: a test that asked the module what it contained would
agree with it whatever it contained, and the day a kind nobody argued for
appears in it, nothing would go red.

Five kinds are declared, and they are unalike in the way that matters. One
leaves a value behind to put back, one leaves nothing at all, one leaves two
things behind - a deployment on an earlier revision and a platform no longer
reconciling it - one restores nothing at all, because what it does is add
capacity the deployment never had, and one *stops* something rather than adding
or restoring anything, by taking away an autoscaler's room to scale back down.
That all five are in the set is the clearest statement that membership, and not
reversibility, is what is being asked - and the fifth makes it plainest, since
what it leaves behind is a controller held still rather than a value changed.
"""

from __future__ import annotations

import pytest
from agent_mitigation import (
    GENERIC_MITIGATIONS,
    AdmittedMitigations,
    is_a_generic_mitigation,
    is_within_reach,
)
from argus_core.models import (
    DISCARD_CACHE_ENTRIES,
    PIN_AUTOSCALER,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    ActionType,
    DiscardCacheEntries,
    Ownership,
    PinAutoscaler,
    RestartService,
    RollBackDeployment,
    ScaleOut,
    ServiceDependency,
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
def test_pinning_an_autoscaler_may_be_taken_unasked() -> None:
    # The fifth kind, and the one that tests the criterion rather than restating
    # it. Every member before it either restores a value or adds capacity, so a
    # reader could still believe the set was about changes that can be put back.
    # This one stops a controller, and it is admitted on the same ground as the
    # rest: somebody declared it, which is the whole of what the gate asks.
    Scenario() \
        .given(a_pin := PinAutoscaler(application="io-shop")) \
        .when(lambda: is_a_generic_mitigation(a_pin)) \
        .then(_it_is_admitted())


@pytest.mark.unit
def test_discarding_cache_entries_may_be_taken_unasked() -> None:
    # The sixth kind, and the one most likely to be mistaken for a weakening of
    # the criterion: removing data sounds heavier than putting a value back, and
    # is not. What is discarded was derived from a store the action never
    # touches, and the service recomputes it on the next read - so nothing is
    # lost, and there is nothing for an undo to put back either.
    Scenario() \
        .given(
            a_discard := DiscardCacheEntries(
                service="io-shop", keys=("io-shop:summary:shopper-3",)
            )
        ) \
        .when(lambda: is_a_generic_mitigation(a_discard)) \
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
        REVERT_FEATURE_FLAG,
        RESTART_SERVICE,
        ROLL_BACK_DEPLOYMENT,
        SCALE_OUT,
        PIN_AUTOSCALER,
        DISCARD_CACHE_ENTRIES
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
def test_rolling_a_deployment_back_may_be_taken_unasked() -> None:
    # Admissible for one specific reason, and it is not that it can be undone:
    # the revision it returns to was reviewed and ran before, so Argus replays
    # somebody's change rather than authoring one. Writing to the repository
    # would be the other thing, and is refused by not being an action at all.
    #
    # Asked of the kind, which is why one answer covers both modes that reach
    # it. New code that broke a service and a configuration changed into a
    # broken state are different accounts of an incident and the same thing to
    # do about it now, so admitting the kind admits both. A set that named the
    # mode would be the gate keeping a second copy of the strategy mapping.
    Scenario() \
        .given(a_rollback := RollBackDeployment(application="io-shop")) \
        .when(lambda: is_a_generic_mitigation(a_rollback)) \
        .then(_it_is_admitted())


@pytest.mark.unit
def test_the_service_the_alert_names_is_always_within_reach() -> None:
    # Whatever the register says, and whether or not it holds an entry for it at
    # all. Argus has been restarting and rolling back the alerting service since
    # before there was a register, and making that conditional on a document
    # somebody maintains would let an out-of-date entry withdraw an authority
    # nobody meant to withdraw.
    Scenario() \
        .given(the_service_that_alerted := "io-shop") \
        .when(
            lambda: is_within_reach(
                a_restart_of(the_service_that_alerted),
                alerting_service=the_service_that_alerted,
                dependencies=[]
            )
        ) \
        .then(_it_is_within_reach())


@pytest.mark.unit
def test_a_dependency_the_organisation_owns_is_within_reach() -> None:
    # The whole point of the new mode: a service Argus was not paged about, and
    # may act on anyway - because the register says it is the organisation's own
    # and the alerting service calls it.
    Scenario() \
        .given(ours := a_dependency("io-pricing", Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                a_restart_of("io-pricing"),
                alerting_service="io-shop",
                dependencies=[ours]
            )
        ) \
        .then(_it_is_within_reach())


@pytest.mark.unit
def test_a_third_partys_service_is_out_of_reach() -> None:
    # Argus holds credentials for its own estate and its own platform. A restart
    # addressed at another company's service either fails or, far worse, reaches
    # something that happens to answer to the same name.
    Scenario() \
        .given(theirs := a_dependency("io-pay", Ownership.THIRD_PARTY)) \
        .when(
            lambda: is_within_reach(
                a_restart_of("io-pay"),
                alerting_service="io-shop",
                dependencies=[theirs]
            )
        ) \
        .then(_it_is_out_of_reach())


@pytest.mark.unit
def test_a_service_the_register_never_mentioned_is_out_of_reach() -> None:
    # The restrictive direction, as the kind question fails restrictively. This
    # is the case a mistyped or hallucinated name lands in, and an estate is not
    # a thing to guess at: something somewhere answers to almost any plausible
    # service name.
    Scenario() \
        .given(ours := a_dependency("io-pricing", Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                a_restart_of("io-billing"),
                alerting_service="io-shop",
                dependencies=[ours]
            )
        ) \
        .then(_it_is_out_of_reach())


@pytest.mark.unit
def test_an_ownership_nobody_recognises_is_out_of_reach() -> None:
    # It survived the register's own reader deliberately, so that the incident
    # can say which word it was - and it withholds authority just as firmly as a
    # third party's does. Anything but the one word that means ours is not ours.
    Scenario() \
        .given(unclassifiable := a_dependency("io-pricing", "shared-with-a-partner")) \
        .when(
            lambda: is_within_reach(
                a_restart_of("io-pricing"),
                alerting_service="io-shop",
                dependencies=[unclassifiable]
            )
        ) \
        .then(_it_is_out_of_reach())


@pytest.mark.unit
def test_an_empty_register_still_leaves_the_alerting_service_reachable() -> None:
    # A register that could not be read arrives here as nothing at all, and the
    # consequence must not be that Argus can do nothing: every mitigation it had
    # before this change is addressed to the service that alerted, and an outage
    # in a document store is no reason to stop taking them.
    a_register_that_said_nothing: list[ServiceDependency] = []

    Scenario() \
        .given(a_register_that_said_nothing) \
        .when(
            lambda: is_within_reach(
                a_restart_of("io-shop"),
                alerting_service="io-shop",
                dependencies=a_register_that_said_nothing
            )
        ) \
        .then(_it_is_within_reach())


@pytest.mark.unit
def test_an_action_that_names_no_service_is_within_reach() -> None:
    # A flag is not an address. What this asks is whose the thing on the other
    # end is, and that has no meaning for a name identifying a switch in
    # Argus's own provider rather than a service somebody owns. Asked of one
    # anyway, it compares a flag against a list of service names, finds no
    # match, and refuses the mitigation Argus was built around.
    Scenario() \
        .given(a_revert := an_action_setting(DONT_CARE_FLAG, enabled=False)) \
        .when(
            lambda: is_within_reach(
                a_revert,
                alerting_service="io-shop",
                dependencies=[]
            )
        ) \
        .then(_it_is_within_reach())


@pytest.mark.unit
def test_rolling_back_an_application_the_register_never_named_is_out_of_reach() -> None:
    # The address rule covers every action that names a service, not restarts
    # alone: an Argo CD application is a service under the platform's word for
    # it. Worth its own case because the obvious fix above - let anything that
    # is not a restart through - would put the whole platform within reach.
    Scenario() \
        .given(ours := a_dependency("io-pricing", Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                RollBackDeployment(application="io-billing"),
                alerting_service="io-shop",
                dependencies=[ours]
            )
        ) \
        .then(_it_is_out_of_reach())


@pytest.mark.unit
def test_scaling_a_deployment_out_may_be_taken_unasked() -> None:
    # The first member of the set that adds something rather than restoring
    # something, and the clearest statement that the criterion is membership:
    # nothing about this action is admitted by it being reversible, which it
    # happens to be. Google SRE's own list of generic mitigations names adding
    # capacity beside draining, rolling back and restarting, and what makes it
    # applicable before the cause is understood is that it is routine.
    Scenario() \
        .given(a_scale_out := ScaleOut(application="io-shop")) \
        .when(lambda: is_a_generic_mitigation(a_scale_out)) \
        .then(_it_is_admitted())


@pytest.mark.unit
def test_scaling_out_an_application_the_register_never_named_is_out_of_reach() -> None:
    # The address rule again, over the kind that arrived last. Worth its own
    # case for the reason the rollback's is: a scale-out names an Argo CD
    # application, which is a service under the platform's word for it, and a
    # reach question that only understood restarts would put the whole platform
    # within reach the day a fourth kind of action appeared.
    Scenario() \
        .given(ours := a_dependency("io-pricing", Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                ScaleOut(application="io-billing"),
                alerting_service="io-shop",
                dependencies=[ours]
            )
        ) \
        .then(_it_is_out_of_reach())


def a_restart_of(service: str) -> RestartService:
    return RestartService(service=service)


def a_dependency(name: str, ownership: str) -> ServiceDependency:
    return ServiceDependency(
        name=name,
        purpose="something the caller needs while it serves a request",
        host=f"{name}.example",
        owner="some-team",
        ownership=ownership
    )


def _it_is_within_reach() -> Assertion[bool]:
    def assertion(within: bool) -> bool:
        if not within:
            raise AssertionError(
                "Expected the action's subject to be within the estate Argus "
                "may touch, and it was refused."
            )

        return True

    return assertion


def _it_is_out_of_reach() -> Assertion[bool]:
    def assertion(within: bool) -> bool:
        if within:
            raise AssertionError(
                "Expected the action's subject to be outside what Argus may "
                "touch, and it was admitted - so a mutating call would be made "
                "against a service nobody authorised."
            )

        return True

    return assertion
