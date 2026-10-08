"""Holding an autoscaler still through the platform, and letting it move again.

The first action here that stops something rather than adding or restoring
something, and what is worth pinning is that it stops it by *raising a floor* -
the controller is left running, with nowhere left to scale down to. Nothing is
removed, nothing is deleted, and the ceiling a human declared is never moved.

Where the autoscaler is is discovered rather than configured, which is what
separates this from the restart and the scale-out beside it. The platform names
every resource an application has, so a pin asks it where to write instead of
being told - and an autoscaler named something other than its application is
then addressed correctly rather than plausibly.

The bounds are live state only the platform holds, as the scale-out's count is.
The repository says what the autoscaler is asked to converge on, which is a
different pair of numbers the moment anybody pins - so a floor derived from
anything else would be derived from a fact nobody here has.

The order is the platform's rule, as it is for the other two actions that change
live state under a GitOps controller: a reconciling application has the
autoscaler's whole manifest re-applied at its next sync, floor included. The
restore's order is the same rule read backwards - reconciliation last, because
turning it on first would have the platform put the floor back on its own,
unverifiably, at a moment nothing here chose.

How Argo CD is asked any of this - the tree, the selectors, a merge patch carried
as text - is the adapter's, and pinned in its own suite.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from argus_core.models import AutoscalerUndo, AutoscalingRestored
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from deployment_platform import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentPlatformWrites,
    PlatformRefused,
    PlatformUnreachable,
)
from write_mcp_server.pinning import (
    AlreadyHeldStill,
    PinRefused,
    pin_autoscaler,
    restore_autoscaler_floor,
)
from write_mcp_server.scaling import THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR

SOME_APPLICATION = "io-shop"

# What the autoscaler is called and where it lives, as the platform reports them.
# Deliberately not the application's name: an autoscaler named after its
# application is the common case and not the contract, and a module that sent the
# application's name would pass every test that used one name for both.
SOME_AUTOSCALER = Autoscaler(name="io-shop-cpu", namespace="shopping")

# The bounds the fixture's own values file declares: a controller free to move
# between three replicas and six, which is what makes a flap possible at all.
THE_FLOOR = 3
THE_CEILING = 6


def a_platform(floor: int = THE_FLOOR,
               ceiling: int = THE_CEILING,
               reconciling_itself: bool = True,
               holding_an_autoscaler: bool = True) -> Any:
    platform = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.autoscaler_of.return_value = (
        SOME_AUTOSCALER if holding_an_autoscaler else None
    )
    platform.autoscaler_bounds.return_value = AutoscalerBounds(
        floor=floor, ceiling=ceiling
    )
    platform.is_syncing_itself.return_value = reconciling_itself

    return platform


def _pinning(platform: Any) -> AutoscalerUndo:
    return pin_autoscaler(SOME_APPLICATION, platform)


def _restoring(descriptor: AutoscalerUndo, platform: Any) -> AutoscalingRestored:
    return restore_autoscaler_floor(descriptor, platform)


@pytest.mark.unit
def test_a_pin_raises_the_floor_to_the_ceiling() -> None:
    # To the ceiling and no further, because the ceiling is a bound a human
    # declared. The count is not Argus's to choose even in principle: what it is
    # choosing is that the count should stop moving.
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_it_asked_for_a_floor_of(platform, THE_CEILING))


@pytest.mark.unit
def test_the_bounds_read_are_the_autoscaler_the_platform_named() -> None:
    # Discovered rather than configured, and not assumed to be named after its
    # application: the platform says what the resource is called and where it
    # lives, and both travel into the read that follows.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_the_bounds_were_read_of(platform, SOME_AUTOSCALER))


@pytest.mark.unit
def test_an_application_with_no_autoscaler_is_refused() -> None:
    # Nothing to pin, and the one thing a caller reading this cannot check for
    # itself: a pin performed against a controller that does not exist would be
    # confirmed against a world that does not exist either.
    platform = a_platform(holding_an_autoscaler=False)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_ceiling_past_what_argus_may_ask_for_is_clamped_to_it() -> None:
    # One estate, one bound on its capacity. The ceiling is a human's declaration
    # and this is Argus's own limit on what it may hold a deployment at, and where
    # the two disagree the smaller wins.
    platform = a_platform(
        floor=THE_FLOOR, ceiling=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 1
    )

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_it_asked_for_a_floor_of(platform, THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR))


@pytest.mark.unit
def test_reconciliation_is_suspended_before_the_floor_is_raised() -> None:
    # The platform's rule rather than a preference: a reconciling application has
    # the autoscaler's manifest re-applied at its next sync, floor and all, so a
    # pin taken under automated sync is a mitigation with a timer on it.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_it_was_asked_in_order(platform, "suspend_sync", "set_autoscaler_floor"))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_the_sync_policy_was_not_touched(platform))


@pytest.mark.unit
def test_the_descriptor_records_the_floor_and_the_policy_it_found() -> None:
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(all_of(
            _the_descriptor_records_the_floor(THE_FLOOR),
            _the_descriptor_records_sync_was(True)
        ))


@pytest.mark.unit
def test_a_descriptor_records_sync_as_it_was_found_off() -> None:
    # Never a default. An application somebody had already stopped reconciling
    # must be left stopped, and a descriptor that recorded the usual arrangement
    # would have a withdrawal start something Argus did not stop.
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_the_descriptor_records_sync_was(False))


@pytest.mark.unit
def test_the_descriptor_records_the_floor_this_pin_asked_for() -> None:
    # Both floors, because the account of a pin is a transition and one number is
    # half of it. The floor it came from is what a withdrawal puts back; the floor
    # it went to is what a reader has to have in order to tell a controller that
    # was stopped from one that was merely nudged - and it is also the number a
    # withdrawal can compare against the live floor before writing, to find out
    # whether anybody has been in there since.
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(all_of(
            _the_descriptor_records_the_floor(THE_FLOOR),
            _the_descriptor_records_the_floor_it_set(THE_CEILING)
        ))


@pytest.mark.unit
def test_the_floor_recorded_is_argus_own_cap_where_that_is_the_lower() -> None:
    # The case that makes this field worth having rather than a convenience. The
    # tier raises the floor to whichever of the two bounds is smaller, so a
    # sentence naming the destination as "its ceiling" is false exactly here - the
    # floor went to Argus's own cap and the ceiling is somewhere above it. A reader
    # told the ceiling would be told a number nothing wrote.
    platform = a_platform(
        floor=THE_FLOOR, ceiling=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 1
    )

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(
            _the_descriptor_records_the_floor_it_set(
                THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR
            )
        )


@pytest.mark.unit
def test_an_autoscaler_already_held_still_is_refused_before_anything_changes() -> None:
    # A floor already at the ceiling is a count that is not moving, so there is
    # nothing here to stop. Refused rather than answered with a no-op: a caller
    # told "done" would record a mitigation that never happened and then judge the
    # service against it.
    platform = a_platform(floor=THE_CEILING, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(AlreadyHeldStill),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_floor_already_past_what_argus_may_ask_for_is_refused() -> None:
    # The clamp and the refusal are one question asked once: where the floor is
    # already at or above the most Argus may pin it at, a pin would lower it - and
    # reducing a deployment's capacity is the thing nothing here does on its own.
    platform = a_platform(
        floor=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 2,
        ceiling=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 4
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(AlreadyHeldStill),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_will_not_answer_is_not_reported_as_pinned() -> None:
    platform = a_platform()
    platform.autoscaler_of.side_effect = PlatformUnreachable("no route to the platform")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_bounds_the_platform_would_not_report_are_not_reported_as_pinned() -> None:
    # The platform named the autoscaler and then would not say its bounds - a
    # refusal, or a manifest without them. A different failure from an
    # application with no autoscaler at all, and both have to leave the
    # deployment untouched: a guessed ceiling would hold a shop at a size nobody
    # declared.
    platform = a_platform()
    platform.autoscaler_bounds.side_effect = PlatformRefused("not found")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_restoring_puts_back_the_floor_the_autoscaler_had() -> None:
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _it_asked_for_a_floor_of(platform, THE_FLOOR),
            _it_reports_restored(floor=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_asks_again_where_the_autoscaler_is() -> None:
    # Hours later, and nothing in the descriptor says where the resource lives -
    # deliberately, because where it lives is the platform's to say at the moment
    # the question is asked. A record of it taken when the pin was performed would
    # be a record that can have gone stale.
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _the_autoscaler_was_asked_for(platform),
            _it_asked_for_a_floor_of(platform, THE_FLOOR)
        ))


@pytest.mark.unit
def test_a_restore_that_cannot_find_the_autoscaler_says_the_floor_is_not_back() -> None:
    # Reported rather than raised, for the reason the other half is: a withdrawal
    # has to be able to say which of the two things it managed, and a floor it
    # could not reach is one it did not put back.
    platform = a_platform(holding_an_autoscaler=False)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(floor=False, automated_sync=True))


@pytest.mark.unit
def test_the_floor_is_put_back_before_reconciliation_is() -> None:
    # The order that leaves nothing to chance. Turning sync on first would have the
    # platform re-apply the manifest itself - to the same floor, and unverifiably,
    # at a moment nothing here chose.
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_was_asked_in_order(platform, "set_autoscaler_floor", "resume_sync"))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    platform = a_platform()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_reports_restored(floor=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_floor_says_so() -> None:
    # The half that fails is the quiet one: an autoscaler back at its declared
    # floor looks right from every angle a reader has, while the application
    # receives nothing anybody ships to it.
    platform = a_platform()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to the platform")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(floor=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform()
    platform.set_autoscaler_floor.side_effect = PlatformUnreachable("no route")
    platform.resume_sync.side_effect = PlatformUnreachable("no route")

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(a_descriptor, platform)) \
        .then(_it_reports_restored(floor=False, automated_sync=False))


@pytest.mark.unit
def test_an_autoscaler_with_no_room_refuses_in_a_way_a_caller_can_recognise() -> None:
    # The pin's half of the same claim. Both of this tier's exhaustion refusals
    # have to be recognisable, and they are two exceptions in two modules - so a
    # marker applied to one and forgotten on the other is exactly the shape this
    # catches.
    platform = a_platform(floor=THE_CEILING, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(_the_refusal_says_the_action_is_exhausted())


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    # A pin begins by asking the platform what the application is made of, so on
    # a platform that is down this is where it finds out. Nothing has been
    # touched, which is what makes the report honest.
    platform = a_platform()
    platform.autoscaler_of.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a pin changes, so a platform that will
    # not take it has left the estate as it found it.
    platform = a_platform()
    platform.suspend_sync.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_that_died_before_a_pin_that_changed_nothing_is_unreachable() -> None:
    # An application nobody was reconciling needs no suspension, so the patch is
    # the first write - and a platform that stopped answering before it took
    # nothing with it.
    platform = a_platform(reconciling_itself=False)
    platform.set_autoscaler_floor.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_pin_that_left_sync_suspended_says_so_and_still_reports_the_platform() -> None:
    # The last of the three. The platform is gone and the floor never moved, so
    # what is left behind is the suspension alone - and it travels on the
    # failure, so the walk can narrow itself and still know an application is
    # sitting un-reconciled.
    #
    # `min_replicas_asked_for` is the ceiling only while the arrangement's
    # ceiling is at or below the most replicas Argus may ask for. It is six here,
    # so the two coincide; a case that raised the ceiling past that cap would
    # have to name the cap instead.
    platform = a_platform(reconciling_itself=True)
    platform.set_autoscaler_floor.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_says_what_it_left_behind(AutoscalerUndo(
                application=SOME_APPLICATION,
                was_min_replicas=THE_FLOOR,
                min_replicas_asked_for=THE_CEILING,
                was_syncing_itself=True
            ))
        ))


@pytest.mark.unit
def test_a_platform_that_answered_and_refused_is_not_reported_as_unreachable() -> None:
    # Reachable, and this patch is what it would not take. The restart and the
    # scale-out are still worth reaching for, and what a person has to look at
    # is the refusal rather than the platform.
    platform = a_platform(reconciling_itself=False)
    platform.set_autoscaler_floor.side_effect = PlatformRefused("400")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_pin_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production, and what it changed.
    platform = a_platform()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            platform
        ) \
        .when(lambda: _pinning(platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.INFO,
                                  "autoscaler floor raised",
                                  values={"application": SOME_APPLICATION,
                                          "from_floor": THE_FLOOR,
                                          "to_floor": THE_CEILING})
        )


@pytest.mark.unit
def test_a_pin_refused_after_sync_was_suspended_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The refusal leaves reconciliation off on purpose, and the line says so:
    # an application nobody is reconciling looks healthy until the next deploy
    # quietly does not arrive.
    platform = a_platform(reconciling_itself=True)
    platform.set_autoscaler_floor.side_effect = PlatformRefused("400")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.WARNING,
                                  "autoscaler pin refused",
                                  values={"application": SOME_APPLICATION,
                                          "sync_suspended": True})
        )


@pytest.mark.unit
def test_a_complete_restore_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production as much as the action was.
    platform = a_platform()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            descriptor := _a_descriptor(was_syncing_itself=True)
        ) \
        .when(lambda: _restoring(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.INFO,
                                  "autoscaler floor restored",
                                  values={"application": SOME_APPLICATION})
        )


@pytest.mark.unit
def test_a_restore_that_only_managed_the_floor_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The quiet half. The application looks put back and is receiving nothing
    # anybody ships to it, and no other line would say so.
    platform = a_platform()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.WARNING,
                                  "autoscaler floor not fully restored",
                                  values={"application": SOME_APPLICATION,
                                          "floor_put_back": True,
                                          "automated_sync_put_back": False})
        )


@pytest.mark.unit
def test_a_restore_step_that_failed_is_logged_as_an_error(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The restore reports which half it lost, never why. The why is here, and
    # it is what a person putting the other half back by hand needs first.
    platform = a_platform()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: _restoring(descriptor, platform)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.ERROR,
                                  "restore step failed",
                                  values={"application": SOME_APPLICATION,
                                          "step": "automated sync"},
                                  failure=PlatformUnreachable)
        )


def _it_is_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, PinRefused):
            raise AssertionError(
                f"Expected the pin to be refused, and what was raised was "
                f"{raised!r}."
            )

        if UNREACHABLE_PLATFORM_MARKER not in str(raised):
            raise AssertionError(
                f"Expected the refusal to report a platform that could not be "
                f"reached, and it reported [{raised}]."
            )

        return True

    return assertion


def _it_is_not_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, PinRefused):
            raise AssertionError(
                f"Expected the pin to be refused, and what was raised was "
                f"{raised!r}."
            )

        if UNREACHABLE_PLATFORM_MARKER in str(raised):
            raise AssertionError(
                f"Expected the refusal to be reported as this action's own, and "
                f"it reported a platform that could not be reached: [{raised}]."
            )

        return True

    return assertion


def _the_refusal_says_the_action_is_exhausted() -> Assertion[Exception | None]:
    """The refusal carries the marker the transport turns into a type.

    Asserted against the marker rather than the sentence, because the sentence is
    allowed to change and the marker is not. The kernel's suite proves a marked
    refusal arrives as `ActionExhausted`; this proves this refusal is marked, and
    this is the end that has to remember to apply it.
    """
    def assertion(refusal: Exception | None) -> bool:
        if refusal is None or EXHAUSTED_ACTION_MARKER not in str(refusal):
            raise AssertionError(
                f"Expected the refusal to carry [{EXHAUSTED_ACTION_MARKER}], so "
                f"that a caller can tell an exhausted action from a broken "
                f"platform, and it said [{refusal}]."
            )

        return True

    return assertion


def _a_descriptor(was_syncing_itself: bool) -> AutoscalerUndo:
    return AutoscalerUndo(
        application=SOME_APPLICATION,
        was_min_replicas=THE_FLOOR,
        min_replicas_asked_for=THE_CEILING,
        was_syncing_itself=was_syncing_itself
    )


def _it_asked_for_a_floor_of(platform: Any, floor: int) -> Assertion[object]:
    """One floor written, to the autoscaler the platform named."""
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args for call in platform.set_autoscaler_floor.call_args_list]

        if asked != [(SOME_APPLICATION, SOME_AUTOSCALER, floor)]:
            raise AssertionError(
                f"Expected one floor of [{floor}] written to {SOME_AUTOSCALER} of "
                f"[{SOME_APPLICATION}], and the platform was asked {asked}."
            )

        return True

    return assertion


def _the_bounds_were_read_of(platform: Any, autoscaler: Autoscaler) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args for call in platform.autoscaler_bounds.call_args_list]

        if asked != [(SOME_APPLICATION, autoscaler)]:
            raise AssertionError(
                f"Expected the bounds of {autoscaler} to be read, as the platform "
                f"named it, and the platform was asked {asked}."
            )

        return True

    return assertion


def _the_autoscaler_was_asked_for(platform: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args for call in platform.autoscaler_of.call_args_list]

        if asked != [(SOME_APPLICATION,)]:
            raise AssertionError(
                f"Expected the platform to be asked where [{SOME_APPLICATION}]'s "
                f"autoscaler is, and it was asked {asked}."
            )

        return True

    return assertion


def _it_was_asked_in_order(platform: Any, *expected: str) -> Assertion[object]:
    """The named operations happened, and in this order relative to each other."""
    def assertion(dont_care_result: object) -> bool:
        asked = [name for name, _args, _kwargs in platform.method_calls]
        relevant = [name for name in asked if name in expected]

        if relevant != list(expected):
            raise AssertionError(
                f"Expected {list(expected)} in that order, and the platform was "
                f"asked {asked}."
            )

        return True

    return assertion


def _the_sync_policy_was_not_touched(platform: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if platform.suspend_sync.called or platform.resume_sync.called:
            raise AssertionError(
                f"Expected the sync policy to be left as it was found, and the "
                f"platform was asked {platform.method_calls}."
            )

        return True

    return assertion


def _nothing_was_changed(platform: Any) -> Assertion[Exception | None]:
    def assertion(dont_care_error: Exception | None) -> bool:
        changed = [
            name for name, operation in (
                ("the floor", platform.set_autoscaler_floor),
                ("the sync policy", platform.suspend_sync)
            )
            if operation.called
        ]

        if changed:
            raise AssertionError(
                f"Expected a refusal to change nothing, and it wrote "
                f"{sorted(changed)}."
            )

        return True

    return assertion


def _the_descriptor_records_the_floor(floor: int) -> Assertion[AutoscalerUndo]:
    def assertion(descriptor: AutoscalerUndo) -> bool:
        if descriptor.was_min_replicas != floor:
            raise AssertionError(
                f"Expected the descriptor to record [{floor}] replicas as the "
                f"floor the autoscaler had, and it records "
                f"[{descriptor.was_min_replicas}]."
            )

        return True

    return assertion


def _the_descriptor_records_the_floor_it_set(floor: int) -> Assertion[AutoscalerUndo]:
    def assertion(descriptor: AutoscalerUndo) -> bool:
        if descriptor.min_replicas_asked_for != floor:
            raise AssertionError(
                f"Expected the descriptor to record [{floor}] replicas as the "
                f"floor this pin asked for, and it records "
                f"[{descriptor.min_replicas_asked_for}]."
            )

        return True

    return assertion


def _the_descriptor_records_sync_was(syncing: bool) -> Assertion[AutoscalerUndo]:
    def assertion(descriptor: AutoscalerUndo) -> bool:
        if descriptor.was_syncing_itself != syncing:
            raise AssertionError(
                f"Expected the descriptor to record automated sync as "
                f"[{syncing}] when Argus found it, and it records "
                f"[{descriptor.was_syncing_itself}]."
            )

        return True

    return assertion


def _it_reports_restored(floor: bool,
                         automated_sync: bool) -> Assertion[AutoscalingRestored]:
    def assertion(restored: AutoscalingRestored) -> bool:
        reported = (restored.floor_put_back, restored.automated_sync_put_back)

        if reported != (floor, automated_sync):
            raise AssertionError(
                f"Expected the floor put back to be [{floor}] and automated "
                f"sync to be [{automated_sync}], and it reported {reported}."
            )

        return True

    return assertion


def _it_says_what_it_left_behind(
    expected: AutoscalerUndo
) -> Assertion[Exception | None]:
    """The refusal carries the descriptor, and carries the right one.

    The third of the three, for the same reason and with the same shape. Not
    lifted anywhere shared: each compares a different descriptor type, and one
    version would take the union and stop telling a pin's from a scale-out's.
    """
    def assertion(raised: Exception | None) -> bool:
        if LEFT_BEHIND_MARKER not in str(raised):
            raise AssertionError(
                f"Expected the refusal to say what it left behind, and it said "
                f"[{raised}]."
            )

        carried = what_was_left_behind(str(raised))

        if carried != expected:
            raise AssertionError(
                f"Expected the refusal to leave {expected!r} to be put back, it "
                f"left {carried!r}."
            )

        return True

    return assertion
