"""What Argus may do on its own authority, and the proof that it was asked.

The gate's whole criterion, and the one place the autonomy boundary is decided.
It asks about membership of a closed, declared set - not about whether an action
can be undone, which is what it used to ask and which parted company with
admissibility the moment a mitigation existed that changes nothing to put back -
and then about where the action is aimed.

The set itself is written out here rather than read from the code under test. It
is the reviewable artefact: a test that asked the module what it contained would
agree with it whatever it contained, and the day a kind nobody argued for
appears in it, nothing would go red.

Seven kinds are declared, and they are unalike in the way that matters. One
leaves a value behind to put back, one leaves nothing at all, one leaves two
things behind - a deployment on an earlier revision and a platform no longer
reconciling it - one restores nothing at all, because what it does is add
capacity the deployment never had, one *stops* something rather than adding or
restoring anything, by taking away an autoscaler's room to scale back down, one
removes copies derived from records it never touches, and one drains, moving
pods off a class of hardware while nothing deployed changes. That all seven are
in the set is the clearest statement that membership, and not reversibility, is
what is being asked.

And the answer is a value only the policy can make. `Admitted` is what the
Mitigator's write accepts, so an admission anybody could build would be a gate
anybody could open.
"""

from __future__ import annotations

import copy
import pickle
from collections.abc import Callable

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    attempting,
)
from core.autonomy import (
    GENERIC_MITIGATIONS,
    Admitted,
    AdmittedMitigations,
    admit,
    is_a_generic_mitigation,
    is_within_reach,
)
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
    DiscardCacheEntries,
    FlagUndo,
    Leaves,
    Ownership,
    PinAutoscaler,
    PinToAccelerator,
    Refusal,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
    ServiceDependency,
    the_kind,
)

DONT_CARE_FLAG = "dont-care-flag"
SOME_SERVICE = "io-shop"
SOME_DEPENDENCY = "io-pricing"
SOME_SERVICE_NOBODY_LISTED = "io-billing"
SOME_ACCELERATOR = "Tesla-V100-SXM2-16GB"

# What tells the policy's own refusals from any other `TypeError`, in the words
# each says: an admission built by hand sends its caller to `admit`, and one
# copied or pickled says admissions are never kept. Written out here rather than
# imported, so a refusal whose words drift fails rather than agreeing with itself.
SENDS_THE_CALLER_TO_ADMIT = "admit()"
SAYS_IT_IS_NEVER_STORED = "never stored"


@pytest.mark.unit
def test_an_action_in_the_declared_set_may_be_taken() -> None:
    # Reverting a flag is the mitigation Argus was built around, and it is in
    # the set because somebody put it there - not because a strategy exists
    # that can propose one.
    Scenario() \
        .given(an_admitted_action := _a_revert_of(DONT_CARE_FLAG)) \
        .when(lambda: is_a_generic_mitigation(an_admitted_action)) \
        .then(_it_is_a_declared_kind())


@pytest.mark.unit
def test_pinning_an_autoscaler_may_be_taken_unasked() -> None:
    # The fifth kind, and the one that tests the criterion rather than restating
    # it. Every member before it either restores a value or adds capacity, so a
    # reader could still believe the set was about changes that can be put back.
    # This one stops a controller, and it is admitted on the same ground as the
    # rest: somebody declared it, which is the whole of what the gate asks.
    Scenario() \
        .given(a_pin := PinAutoscaler(application=SOME_SERVICE)) \
        .when(lambda: is_a_generic_mitigation(a_pin)) \
        .then(_it_is_a_declared_kind())


@pytest.mark.unit
def test_holding_a_deployment_to_one_card_may_be_taken_unasked() -> None:
    # The seventh kind, and a drain: Google SRE's list of generic mitigations
    # names draining beside rolling back, restarting and adding capacity. Pods
    # move off a class of hardware and nothing deployed changes, and it is
    # admitted on the ground every other member is - somebody declared it.
    Scenario() \
        .given(a_pin := PinToAccelerator(application=SOME_SERVICE, accelerator=SOME_ACCELERATOR)) \
        .when(lambda: is_a_generic_mitigation(a_pin)) \
        .then(_it_is_a_declared_kind())


@pytest.mark.unit
def test_discarding_cache_entries_may_be_taken_unasked() -> None:
    # The sixth kind, and the one most likely to be mistaken for a weakening of
    # the criterion: removing data sounds heavier than reverting a value, and
    # is not. What is discarded was derived from a store the action never
    # touches, and the service recomputes it on the next read - so nothing is
    # lost, and there is nothing for an undo to put back either.
    Scenario() \
        .given(
            a_discard := DiscardCacheEntries(
                service=SOME_SERVICE, keys=("io-shop:summary:shopper-3",)
            )
        ) \
        .when(lambda: is_a_generic_mitigation(a_discard)) \
        .then(_it_is_a_declared_kind())


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
        .given(a_rollback := RollBackDeployment(application=SOME_SERVICE)) \
        .when(lambda: is_a_generic_mitigation(a_rollback)) \
        .then(_it_is_a_declared_kind())


@pytest.mark.unit
def test_scaling_a_deployment_out_may_be_taken_unasked() -> None:
    # The first member of the set that adds something rather than restoring
    # something, and the clearest statement that the criterion is membership:
    # nothing about this action is admitted by it being reversible, which it
    # happens to be. Google SRE's own list of generic mitigations names adding
    # capacity beside draining, rolling back and restarting, and what makes it
    # applicable before the cause is understood is that it is routine.
    Scenario() \
        .given(a_scale_out := ScaleOut(application=SOME_SERVICE)) \
        .when(lambda: is_a_generic_mitigation(a_scale_out)) \
        .then(_it_is_a_declared_kind())


@pytest.mark.unit
def test_an_action_of_a_kind_the_set_does_not_hold_is_refused() -> None:
    # Absence is a refusal, never a default to permitted. A kind nobody has
    # declared is a kind nobody has argued for, and assuming the best about one
    # is how an unreviewed action reaches production the day it is implemented
    # - so the boundary fails in the restrictive direction, and a deployment
    # that declared nothing takes nothing unasked.
    a_set_holding_no_kind_at_all: AdmittedMitigations = frozenset()

    Scenario() \
        .given(some_action := _a_revert_of(DONT_CARE_FLAG)) \
        .when(
            lambda: is_a_generic_mitigation(
                some_action, admitted=a_set_holding_no_kind_at_all
            )
        ) \
        .then(_it_is_not_a_declared_kind())


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
        DISCARD_CACHE_ENTRIES,
        PIN_TO_ACCELERATOR
    }

    Scenario() \
        .given(GENERIC_MITIGATIONS) \
        .when(lambda: set(GENERIC_MITIGATIONS)) \
        .then(_the_set_is(the_kinds_argus_may_take_unasked))


@pytest.mark.unit
def test_the_service_the_alert_names_is_always_within_reach() -> None:
    # Whatever the register says, and whether or not it holds an entry for it at
    # all. Argus has been restarting and rolling back the alerting service since
    # before there was a register, and making that conditional on a document
    # somebody maintains would let an out-of-date entry withdraw an authority
    # nobody meant to withdraw.
    Scenario() \
        .given(the_service_that_alerted := SOME_SERVICE) \
        .when(
            lambda: is_within_reach(
                _a_restart_of(the_service_that_alerted),
                alerting_service=the_service_that_alerted,
                dependencies=[]
            )
        ) \
        .then(_it_is_within_reach())


@pytest.mark.unit
def test_a_dependency_the_organisation_owns_is_within_reach() -> None:
    # A service Argus was not paged about, and may act on anyway - because the
    # register says it is the organisation's own and the alerting service calls
    # it.
    Scenario() \
        .given(ours := _a_dependency(SOME_DEPENDENCY, Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                _a_restart_of(SOME_DEPENDENCY),
                alerting_service=SOME_SERVICE,
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
        .given(theirs := _a_dependency("io-pay", Ownership.THIRD_PARTY)) \
        .when(
            lambda: is_within_reach(
                _a_restart_of("io-pay"),
                alerting_service=SOME_SERVICE,
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
        .given(ours := _a_dependency(SOME_DEPENDENCY, Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                _a_restart_of(SOME_SERVICE_NOBODY_LISTED),
                alerting_service=SOME_SERVICE,
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
        .given(unclassifiable := _a_dependency(SOME_DEPENDENCY, "shared-with-a-partner")) \
        .when(
            lambda: is_within_reach(
                _a_restart_of(SOME_DEPENDENCY),
                alerting_service=SOME_SERVICE,
                dependencies=[unclassifiable]
            )
        ) \
        .then(_it_is_out_of_reach())


@pytest.mark.unit
def test_an_empty_register_still_leaves_the_alerting_service_reachable() -> None:
    # A register that could not be read arrives here as nothing at all, and the
    # consequence must not be that Argus can do nothing: every mitigation
    # addressed to the service that alerted stays available, and an outage in a
    # document store is no reason to stop taking them.
    a_register_that_said_nothing: list[ServiceDependency] = []

    Scenario() \
        .given(a_register_that_said_nothing) \
        .when(
            lambda: is_within_reach(
                _a_restart_of(SOME_SERVICE),
                alerting_service=SOME_SERVICE,
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
        .given(a_revert := _a_revert_of(DONT_CARE_FLAG)) \
        .when(
            lambda: is_within_reach(
                a_revert,
                alerting_service=SOME_SERVICE,
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
        .given(ours := _a_dependency(SOME_DEPENDENCY, Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                RollBackDeployment(application=SOME_SERVICE_NOBODY_LISTED),
                alerting_service=SOME_SERVICE,
                dependencies=[ours]
            )
        ) \
        .then(_it_is_out_of_reach())


@pytest.mark.unit
def test_scaling_out_an_application_the_register_never_named_is_out_of_reach() -> None:
    # The address rule again, over a kind that arrived later. A scale-out names
    # an Argo CD application, which is a service under the platform's word for
    # it, and a reach question that only understood restarts would put the
    # whole platform within reach the day a further kind of action appeared.
    Scenario() \
        .given(ours := _a_dependency(SOME_DEPENDENCY, Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                ScaleOut(application=SOME_SERVICE_NOBODY_LISTED),
                alerting_service=SOME_SERVICE,
                dependencies=[ours]
            )
        ) \
        .then(_it_is_out_of_reach())


@pytest.mark.unit
def test_holding_an_application_the_register_never_named_to_a_card_is_out_of_reach() -> None:
    # The address rule over the pin to a card, for the scale-out's reason: it
    # names an Argo CD application, and the card it carries is no part of where
    # it is aimed - so a reach question that read the card instead would let a
    # pin land on any deployment the platform holds.
    Scenario() \
        .given(ours := _a_dependency(SOME_DEPENDENCY, Ownership.INTERNAL)) \
        .when(
            lambda: is_within_reach(
                PinToAccelerator(
                    application=SOME_SERVICE_NOBODY_LISTED, accelerator=SOME_ACCELERATOR
                ),
                alerting_service=SOME_SERVICE,
                dependencies=[ours]
            )
        ) \
        .then(_it_is_out_of_reach())


@pytest.mark.unit
def test_an_action_of_a_declared_kind_aimed_within_the_estate_is_admitted() -> None:
    # Both questions answered yes, and the answer is the action itself, held by
    # the one value the Mitigator's write accepts - not a yes for a caller to
    # remember and an action for it to pass along beside it.
    Scenario() \
        .given(
            ours := _a_dependency(SOME_DEPENDENCY, Ownership.INTERNAL),
            a_restart_of_a_dependency_of_ours := _a_restart_of(SOME_DEPENDENCY)
        ) \
        .when(
            lambda: admit(
                a_restart_of_a_dependency_of_ours,
                alerting_service=SOME_SERVICE,
                dependencies=[ours]
            )
        ) \
        .then(_it_was_admitted_holding(a_restart_of_a_dependency_of_ours))


@pytest.mark.unit
def test_an_action_aimed_outside_the_estate_is_refused_for_where_it_was_aimed() -> None:
    # The refusal says which question failed, because the two ask different
    # people for different things: this one is usually somebody correcting an
    # entry in the register, never somebody widening the declared set.
    Scenario() \
        .given(ours := _a_dependency(SOME_DEPENDENCY, Ownership.INTERNAL)) \
        .when(
            lambda: admit(
                _a_restart_of(SOME_SERVICE_NOBODY_LISTED),
                alerting_service=SOME_SERVICE,
                dependencies=[ours]
            )
        ) \
        .then(_it_was_refused_because(Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH))


@pytest.mark.unit
def test_an_admission_is_made_by_admit_and_by_nothing_else() -> None:
    # What the write accepts is only worth anything if nothing but the policy
    # can make one. The constructor's key is one nothing outside the policy can
    # name, so the call below is refused twice: by the type checker - which is
    # why it carries an ignore, and why that ignore is reported as unused, and
    # the typecheck fails, the day the key stops being demanded - and, for code
    # nobody type-checked, when it runs. The runtime refusal is the policy's own,
    # sending the caller to `admit`: a constructor that lost its key parameter
    # would raise a `TypeError` too, Python's, and refuse nothing.
    Scenario() \
        .given(some_action := _a_revert_of(DONT_CARE_FLAG)) \
        .when(attempting(
            lambda: Admitted(some_action, key=object())  # type: ignore[arg-type]
        )) \
        .then(_a_type_error_saying(SENDS_THE_CALLER_TO_ADMIT))


@pytest.mark.unit
@pytest.mark.parametrize("rebuilt_by", [
    pytest.param(lambda admission: pickle.loads(pickle.dumps(admission)), id="pickle"),
    pytest.param(copy.copy, id="copy"),
    pytest.param(copy.deepcopy, id="deepcopy")
])
def test_an_admission_is_never_rebuilt_from_a_copy_of_itself(
    rebuilt_by: Callable[[Admitted[Action]], object]
) -> None:
    # A pickle is a row by another name, and the default one for a slotted
    # class is rebuilt past the constructor - and so past the key. An
    # admission written out and read back would be one `admit` never made, and
    # copying goes the same way, so each is refused - by the policy, saying why,
    # rather than by whatever else might fail on the way.
    Scenario() \
        .given(an_admission := _an_admission_of(_a_revert_of(DONT_CARE_FLAG))) \
        .when(attempting(lambda: rebuilt_by(an_admission))) \
        .then(_a_type_error_saying(SAYS_IT_IS_NEVER_STORED))


@pytest.mark.unit
def test_the_declared_set_holds_no_kind_whose_change_is_irreversible() -> None:
    # The one place reversibility decides anything about autonomy (spec §13).
    # Membership admits an action, but a kind that loses something for good is
    # a person's to approve, and a declared set that came to hold one would be
    # a guardrail removed by an edit nobody had to defend - so it fails the
    # build here. Asked of the kernel's own account of each kind, kept with the
    # kind rather than with the set: putting a kind in the set and saying what
    # its change does are two lines in two places, and the second is read by
    # every account of the incident, which is what keeps it honest.
    Scenario() \
        .given(GENERIC_MITIGATIONS) \
        .when(lambda: {kind: the_kind(kind).leaves for kind in GENERIC_MITIGATIONS}) \
        .then(_none_of_them_is_irreversible())


def _a_revert_of(flag: str) -> RevertFeatureFlag:
    return RevertFeatureFlag(
        flag=flag,
        enabled=False,
        undo_descriptor=FlagUndo(flag=flag, was_enabled=True)
    )


def _a_restart_of(service: str) -> RestartService:
    return RestartService(service=service)


def _an_admission_of[A: Action](action: A) -> Admitted[A]:
    """`action` as the policy admits it, aimed where nothing needs the register."""
    admission = admit(action, alerting_service=SOME_SERVICE, dependencies=[])

    if isinstance(admission, Refusal):
        raise AssertionError(f"Expected [{action}] to be admitted, it was refused: "
                             f"[{admission}].")

    return admission


def _a_dependency(name: str, ownership: str) -> ServiceDependency:
    return ServiceDependency(
        name=name,
        purpose="something the caller needs while it serves a request",
        host=f"{name}.example",
        owner="some-team",
        ownership=ownership
    )


def _a_type_error_saying(words: str) -> Assertion[Exception | None]:
    """A `TypeError` raised by the policy, told from any other by `words` in
    what it says."""
    def assertion(error: Exception | None) -> bool:
        if not isinstance(error, TypeError) or words not in str(error):
            raise AssertionError(
                f"Expected a [TypeError] saying [{words}], got "
                f"[{type(error).__name__}]: [{error}]."
            )

        return True

    return assertion


def _none_of_them_is_irreversible() -> Assertion[dict[ActionType, Leaves]]:
    def assertion(left_by_kind: dict[ActionType, Leaves]) -> bool:
        irreversible = sorted(kind for kind, leaves in left_by_kind.items()
                              if leaves is Leaves.IRREVERSIBLE)

        if irreversible:
            raise AssertionError(
                f"Expected no kind Argus may take unasked to be irreversible, and "
                f"{irreversible} is - a kind like that is a person's to approve."
            )

        return True

    return assertion


def _it_is_a_declared_kind() -> Assertion[bool]:
    def assertion(declared: bool) -> bool:
        if not declared:
            raise AssertionError(
                "Expected the action to be of a kind Argus may take unasked, "
                "and it was refused."
            )

        return True

    return assertion


def _it_is_not_a_declared_kind() -> Assertion[bool]:
    def assertion(declared: bool) -> bool:
        if declared:
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


def _it_was_admitted_holding(action: Action) -> Assertion[Admitted[Action] | Refusal]:
    def assertion(admission: Admitted[Action] | Refusal) -> bool:
        if isinstance(admission, Refusal):
            raise AssertionError(
                f"Expected [{action}] to be admitted, and it was refused: [{admission}]."
            )

        if admission.action != action:
            raise AssertionError(
                f"Expected the admission to hold [{action}], and it holds "
                f"[{admission.action}]."
            )

        return True

    return assertion


def _it_was_refused_because(expected: Refusal) -> Assertion[Admitted[Action] | Refusal]:
    def assertion(admission: Admitted[Action] | Refusal) -> bool:
        if admission is not expected:
            raise AssertionError(
                f"Expected the action to be refused as [{expected}], and the "
                f"answer was [{admission}]."
            )

        return True

    return assertion
