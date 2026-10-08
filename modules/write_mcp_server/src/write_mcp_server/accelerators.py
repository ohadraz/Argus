"""Holding a deployment to one accelerator card through the platform, and letting
it go (spec §7.3, §12.1, §13).

A drain: the pods move off a class of hardware and nothing deployed changes. The
platform is told which card the deployment's pods may be scheduled onto, and the
scheduler does the rest. Nothing is removed and no replica count is touched,
which is what keeps this reversible, and what makes the thing to put back one
selector - including that there was none.

Which card is not decided here. It arrives worked out from a placement recorded
before anything was done; this tier is told it, and does the work. A tier that
chose the card would be judging which hardware is at fault from a cluster it can
see only now, after the walk had already read it as it was at the onset.

Several asks rather than one, in the order every action that changes live state
under a GitOps controller takes. The platform is asked which card the pods are
held to, then whether it is reconciling the application, which is then
suspended - a reconciling application has its declared pod template re-applied
at the next sync, selector included, so a pin taken under automated sync is a
mitigation with a timer on it. Only then is the pin written.

Which is also why this mitigates without resolving, and why the descriptor it
returns records two things. The repository still declares a template that lets
the pods land on any card, and reconciliation is off so that nothing re-applies
it. Both have to be put back by a withdrawal, and only this module ever knew
either.

How Argo CD is asked any of this is the platform port's adapter's.
"""

from __future__ import annotations

from collections.abc import Callable

from argus_core.mcp_transport import an_exhausted_action, an_unreachable_platform
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    AcceleratorPinRestored,
    AcceleratorPinUndo,
)
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    PlatformUnreachable,
)


class AlreadyPinned(Exception):
    """The deployment is already held to the card it was to be pinned to.

    Raised rather than answered with a no-op, and raised *before* anything is
    changed. Nothing would move, so a caller told "done" would record a
    mitigation that never happened and then judge the service against it - and
    the honest account is the one a refusal gives: the action Argus has for this
    cause is exhausted, so the walk moves on to another candidate.

    Marked as an exhausted action on the way out, which is what lets the walk do
    that rather than wake a human over a platform that answered correctly.
    """


class AcceleratorPinRefused(Exception):
    """The platform would not say which card the pods are held to, or would not
    change it."""


def _refusing(said: str, error: DeploymentPlatformError,
              left_behind: AcceleratorPinUndo | None = None) -> AcceleratorPinRefused:
    """This module's refusal, marked where the platform was never reached.

    `left_behind` is what the failure cost, where it cost anything: a suspension
    that landed before the pin did not travels on the failure, so a caller can
    narrow itself to a reachable platform and still know an application is
    sitting un-reconciled.
    """
    if isinstance(error, PlatformUnreachable):
        return AcceleratorPinRefused(
            an_unreachable_platform(DEPLOYMENT_PLATFORM, said, left_behind)
        )

    return AcceleratorPinRefused(said)


def pin_to_accelerator(application: str,
                       accelerator: str,
                       platform: DeploymentPlatformWrites) -> AcceleratorPinUndo:
    """Holds `application`'s pods to `accelerator`, and reports what that cost.

    Raises rather than half-succeeding. A deployment already held to the card
    raises before anything is touched; a platform that refuses the pin raises
    after sync was suspended, and that is deliberate for the reason the other
    actions under a GitOps controller give - the suspension is recorded nowhere
    yet, so leaving it in place and saying so is honest where quietly restoring
    it would hide a state somebody has to know about.
    """
    try:
        was_pinned_to = platform.accelerator_pin_of(application)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read which card [{application}] is held to: {error}", error
        ) from error

    if was_pinned_to == accelerator:
        raise AlreadyPinned(
            an_exhausted_action(
                f"[{application}] is already held to [{accelerator}], so there "
                f"is nothing here for a pin to move"
            )
        )

    try:
        was_syncing_itself = platform.is_syncing_itself(application)

        if was_syncing_itself:
            platform.suspend_sync(application)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not suspend the sync of [{application}]: {error}", error
        ) from error

    # Built before the action rather than after it, because it describes what
    # has already been changed: where sync was suspended, this is what a caller
    # has to put back whether the pin then lands or the platform vanishes.
    undo = AcceleratorPinUndo(
        application=application,
        was_pinned_to=was_pinned_to,
        pinned_to=accelerator,
        was_syncing_itself=was_syncing_itself
    )

    try:
        platform.pin_to_accelerator(application, accelerator)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"[{application}] could not be held to [{accelerator}]: {error}",
            error,
            undo if was_syncing_itself else None
        ) from error

    return undo


def restore_accelerator_pin(descriptor: AcceleratorPinUndo,
                            platform: DeploymentPlatformWrites
                            ) -> AcceleratorPinRestored:
    """Puts back both of the things a pin changed, and says which it managed.

    A pair rather than an exception, for the reason the other restores answer
    one: a restore can half-succeed and the half that fails is the quiet one.

    The pin first and reconciliation second. Re-enabling sync first would have
    the platform take the selector off on its own - unverifiably, at a moment
    nothing here chose. Where there was no pin, putting it back is taking this
    one off; the pods already placed stay where they are until something
    reschedules them.
    """
    pin = _tried(
        lambda: platform.pin_to_accelerator(
            descriptor.application, descriptor.was_pinned_to
        )
    )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return AcceleratorPinRestored(pin_put_back=pin, automated_sync_put_back=True)

    return AcceleratorPinRestored(
        pin_put_back=pin,
        automated_sync_put_back=_tried(
            lambda: platform.resume_sync(descriptor.application)
        )
    )


def _tried(call: Callable[[], None]) -> bool:
    try:
        call()
    except Exception:
        return False

    return True
