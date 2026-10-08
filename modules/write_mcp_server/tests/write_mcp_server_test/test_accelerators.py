"""Holding a deployment to one card through the platform, and letting it go.

A drain: the pods move off a class of hardware and nothing deployed changes. What
is worth pinning is the order and the record. The order is the platform's rule,
as it is for every action that changes live state under a GitOps controller - a
reconciling application has its declared pod template re-applied at the next
sync, selector included, so reconciliation is suspended first and resumed last.
The record is what the selector was before, including that there was none,
because "there was no pin" and "nobody wrote down what there was" lead an undo
to opposite actions.

Which card to pin to is not decided here. It arrives worked out from a placement
recorded before anything was done; this tier is told it, as the scale-out is told
nothing and the rollback is told nothing, and does the work.

How Argo CD is asked any of this - the selectors, a merge patch carried as text,
a null that removes a key - is the adapter's, and pinned in its own suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from argus_core.models import AcceleratorPinRestored, AcceleratorPinUndo
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from deployment_platform import (
    DeploymentPlatformWrites,
    PlatformRefused,
    PlatformUnreachable,
)
from write_mcp_server.accelerators import (
    AcceleratorPinRefused,
    AlreadyPinned,
    pin_to_accelerator,
    restore_accelerator_pin,
)

SOME_APPLICATION = "io-shop"
THE_FLEETS_CARD = "Tesla-V100-SXM2-16GB"
SOME_OTHER_CARD = "NVIDIA-A100-SXM4-40GB"


def a_platform(pinned_to: str | None = None, reconciling_itself: bool = True) -> Any:
    platform = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.accelerator_pin_of.return_value = pinned_to
    platform.is_syncing_itself.return_value = reconciling_itself

    return platform


def _pinning(platform: Any, to: str = THE_FLEETS_CARD) -> AcceleratorPinUndo:
    return pin_to_accelerator(SOME_APPLICATION, to, platform)


def _restoring(descriptor: AcceleratorPinUndo, platform: Any) -> AcceleratorPinRestored:
    return restore_accelerator_pin(descriptor, platform)


@pytest.mark.unit
def test_a_pin_holds_the_deployment_to_the_card_it_was_given() -> None:
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform, to=THE_FLEETS_CARD)) \
        .then(_it_pinned(platform, [THE_FLEETS_CARD]))


@pytest.mark.unit
def test_reconciliation_is_suspended_before_the_pin() -> None:
    # A pin taken under automated sync is a mitigation with a timer on it: the
    # next sync re-applies the declared template and takes the selector off.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_it_was_asked_in_order(platform, "suspend_sync", "pin_to_accelerator"))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform)) \
        .then(_the_sync_policy_was_not_touched(platform))


@pytest.mark.unit
def test_the_descriptor_records_no_pin_where_there_was_none() -> None:
    platform = a_platform(pinned_to=None, reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform, to=THE_FLEETS_CARD)) \
        .then(_the_descriptor_is(AcceleratorPinUndo(
            application=SOME_APPLICATION,
            was_pinned_to=None,
            pinned_to=THE_FLEETS_CARD,
            was_syncing_itself=True
        )))


@pytest.mark.unit
def test_the_descriptor_records_the_pin_it_replaced_and_sync_as_found_off() -> None:
    platform = a_platform(pinned_to=SOME_OTHER_CARD, reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: _pinning(platform, to=THE_FLEETS_CARD)) \
        .then(_the_descriptor_is(AcceleratorPinUndo(
            application=SOME_APPLICATION,
            was_pinned_to=SOME_OTHER_CARD,
            pinned_to=THE_FLEETS_CARD,
            was_syncing_itself=False
        )))


@pytest.mark.unit
def test_a_deployment_already_pinned_to_the_card_is_refused_before_anything_changes() -> None:
    # Nothing to move. A caller told "done" would record a mitigation that never
    # happened and judge the service against it, so the action is reported
    # exhausted and the walk moves on.
    platform = a_platform(pinned_to=THE_FLEETS_CARD)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform, to=THE_FLEETS_CARD))) \
        .then(all_of(
            an_error_was_raised(AlreadyPinned),
            _the_refusal_says_the_action_is_exhausted(),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    platform = a_platform()
    platform.accelerator_pin_of.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_refused_the_read_is_not_reported_as_unreachable() -> None:
    # It answered, so every other action through it is still there to try - and
    # nothing was touched, because the read is the first thing a pin asks.
    platform = a_platform()
    platform.accelerator_pin_of.side_effect = PlatformRefused("403")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            _it_is_not_reported_as_an_unreachable_platform(),
            _it_pinned(platform, [])
        ))


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a pin changes, so a platform that will
    # not take it has left the estate as it found it, and the card was never
    # asked for.
    platform = a_platform(reconciling_itself=True)
    platform.suspend_sync.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_pinned(platform, [])
        ))


@pytest.mark.unit
def test_a_pin_that_left_sync_suspended_says_so_and_still_reports_the_platform() -> None:
    # The platform went away between the suspension and the pin, so what is left
    # behind is the suspension alone - and it travels on the failure, so the walk
    # can narrow itself and still know an application is sitting un-reconciled.
    platform = a_platform(pinned_to=None, reconciling_itself=True)
    platform.pin_to_accelerator.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform, to=THE_FLEETS_CARD))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_says_what_it_left_behind(AcceleratorPinUndo(
                application=SOME_APPLICATION,
                was_pinned_to=None,
                pinned_to=THE_FLEETS_CARD,
                was_syncing_itself=True
            ))
        ))


@pytest.mark.unit
def test_a_platform_that_answered_and_refused_is_not_reported_as_unreachable() -> None:
    platform = a_platform(reconciling_itself=False)
    platform.pin_to_accelerator.side_effect = PlatformRefused("400")

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: _pinning(platform))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_restoring_takes_the_pin_off_where_there_was_none() -> None:
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _restoring(_a_descriptor(was_pinned_to=None), platform)) \
        .then(all_of(
            _it_pinned(platform, [None]),
            _it_reports_restored(pin=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_restoring_puts_back_the_pin_somebody_else_had_set() -> None:
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _restoring(_a_descriptor(was_pinned_to=SOME_OTHER_CARD), platform)) \
        .then(_it_pinned(platform, [SOME_OTHER_CARD]))


@pytest.mark.unit
def test_the_pin_is_put_back_before_reconciliation_is() -> None:
    # Turning reconciliation on first would have the platform take the selector
    # off on its own - unverifiably, at a moment nothing here chose.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _restoring(_a_descriptor(was_syncing_itself=True), platform)) \
        .then(_it_was_asked_in_order(platform, "pin_to_accelerator", "resume_sync"))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: _restoring(_a_descriptor(was_syncing_itself=False), platform)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_reports_restored(pin=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_pin_says_so() -> None:
    platform = a_platform()
    platform.resume_sync.side_effect = PlatformRefused("409")

    Scenario() \
        .given(platform) \
        .when(lambda: _restoring(_a_descriptor(was_syncing_itself=True), platform)) \
        .then(_it_reports_restored(pin=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform()
    platform.pin_to_accelerator.side_effect = PlatformUnreachable("503")
    platform.resume_sync.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(platform) \
        .when(lambda: _restoring(_a_descriptor(was_syncing_itself=True), platform)) \
        .then(_it_reports_restored(pin=False, automated_sync=False))


def _a_descriptor(was_pinned_to: str | None = None,
                  was_syncing_itself: bool = True) -> AcceleratorPinUndo:
    return AcceleratorPinUndo(
        application=SOME_APPLICATION,
        was_pinned_to=was_pinned_to,
        pinned_to=THE_FLEETS_CARD,
        was_syncing_itself=was_syncing_itself
    )


def _it_pinned(platform: Any, cards: list[str | None]) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args for call in platform.pin_to_accelerator.call_args_list]
        expected = [(SOME_APPLICATION, card) for card in cards]

        if asked != expected:
            raise AssertionError(
                f"Expected the platform to be asked to pin {expected}, and it was "
                f"asked {asked}."
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
                ("the pin", platform.pin_to_accelerator),
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


def _the_descriptor_is(expected: AcceleratorPinUndo) -> Assertion[AcceleratorPinUndo]:
    def assertion(descriptor: AcceleratorPinUndo) -> bool:
        if descriptor != expected:
            raise AssertionError(
                f"Expected the descriptor {expected!r}, and the pin returned "
                f"{descriptor!r}."
            )

        return True

    return assertion


def _the_refusal_says_the_action_is_exhausted() -> Assertion[Exception | None]:
    def assertion(refusal: Exception | None) -> bool:
        if refusal is None or EXHAUSTED_ACTION_MARKER not in str(refusal):
            raise AssertionError(
                f"Expected the refusal to carry [{EXHAUSTED_ACTION_MARKER}], so "
                f"that a caller can tell an exhausted action from a broken "
                f"platform, and it said [{refusal}]."
            )

        return True

    return assertion


def _it_is_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, AcceleratorPinRefused):
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
        if not isinstance(raised, AcceleratorPinRefused):
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


def _it_reports_restored(pin: bool,
                         automated_sync: bool) -> Assertion[AcceleratorPinRestored]:
    def assertion(restored: AcceleratorPinRestored) -> bool:
        reported = (restored.pin_put_back, restored.automated_sync_put_back)

        if reported != (pin, automated_sync):
            raise AssertionError(
                f"Expected the pin put back to be [{pin}] and automated sync to "
                f"be [{automated_sync}], and it reported {reported}."
            )

        return True

    return assertion


def _it_says_what_it_left_behind(
    expected: AcceleratorPinUndo
) -> Assertion[Exception | None]:
    """The refusal carries the descriptor, and carries the right one."""
    def assertion(raised: Exception | None) -> bool:
        if LEFT_BEHIND_MARKER not in str(raised):
            raise AssertionError(
                f"Expected the refusal to say what it left behind, and it said "
                f"[{raised}]."
            )

        left_behind = what_was_left_behind(str(raised))

        if left_behind != expected:
            raise AssertionError(
                f"Expected the refusal to leave behind {expected!r}, and it left "
                f"{left_behind!r}."
            )

        return True

    return assertion
