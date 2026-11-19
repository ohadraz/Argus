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

A withdrawal lets go only of what is still Argus's, and reads the platform before
it writes to find out. Pods still held to the card Argus pinned them to are let
go; pods already back where Argus found them need no write; any other selector -
another card, or none at all - is somebody's change since, and is left as they set
it, with the reconciliation Argus suspended left suspended too, because resuming
it would have the platform re-apply git over them.

How Argo CD is asked any of this is the platform port's adapter's.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from core.mcp_transport import (
    a_change_made_since,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
)
from core.models import AcceleratorPinRestored, AcceleratorPinUndo, Planned
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    Mark,
    MarkedObject,
)

from write_mcp_server.refusing import a_platform_refusal
from write_mcp_server.sync_switch import (
    Switch,
    suspend_where_it_is_to_be,
    the_switch,
    this_claim_s_suspension_stands,
)

logger = logging.getLogger(__name__)


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


def _refusing(said: str, error: DeploymentPlatformError, *,
              asked_to_change: bool,
              left_behind: AcceleratorPinUndo | None = None) -> AcceleratorPinRefused:
    """This module's refusal, marked as `a_platform_refusal` marks it.

    `left_behind` is what the failure cost, where it cost anything: a suspension
    that landed before the pin did not travels on the failure, so a caller still
    knows an application is sitting un-reconciled.
    """
    return AcceleratorPinRefused(a_platform_refusal(
        said, error, asked_to_change=asked_to_change, left_behind=left_behind
    ))


def plan_accelerator_pin(application: str,
                         accelerator: str,
                         platform: DeploymentPlatformWrites) -> Planned[AcceleratorPinUndo]:
    """The pin of `application`'s pods to `accelerator` to make, worked out and
    dated - and nothing changed.

    Dated by the platform's clock, read before anything it dates. A deployment
    already held to the card raises here, before a claim is written for it.
    """
    try:
        since = platform.now(application)
        was_pinned_to = platform.accelerator_pin_of(application)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read which card [{application}] is held to: {error}", error,
            asked_to_change=False
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
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read whether [{application}] syncs itself: {error}", error,
            asked_to_change=False
        ) from error

    return Planned(
        descriptor=AcceleratorPinUndo(
            application=application,
            was_pinned_to=was_pinned_to,
            pinned_to=accelerator,
            was_syncing_itself=was_syncing_itself
        ),
        since=since
    )


def pin_to_accelerator(planned: Planned[AcceleratorPinUndo],
                       platform: DeploymentPlatformWrites,
                       mark: Mark) -> AcceleratorPinUndo:
    """Makes the pin `planned` describes, where the platform still stands as the
    plan found it, and reports what that cost - every write carrying `mark`.

    Every comparison is made before anything is written. Pods still held where
    the plan found them, under no mark of this claim's, are pinned; pods on the
    plan's card under this claim's mark are this pin already made, answered with
    the plan and nothing written twice; anything else - a selector somebody took
    off as much as one somebody moved - is somebody's change since, refused with
    nothing written, carrying the plan where this claim's marks show part of it
    landed. The sync switch is held to the same rule (`sync_switch`).

    A plan naming the card it found the pods held to is refused plainly, nothing
    written: the plan is the caller's data, and the rule is this tier's.

    Raises rather than half-succeeding. A platform that refuses the pin after
    sync was suspended leaves the suspension in place and says so - quietly
    restoring it would hide a state somebody has to know about.
    """
    descriptor = planned.descriptor
    application = descriptor.application
    accelerator = descriptor.pinned_to

    # The plan is held to this tier's own rule from its own "was": a pin moves
    # the pods somewhere they were not held.
    if accelerator == descriptor.was_pinned_to:
        raise AcceleratorPinRefused(a_refusal_saying_what_it_left(
            f"the pin of [{application}] asks to hold its pods to [{accelerator}], "
            f"where it found them held already"
        ))

    try:
        held_to = platform.accelerator_pin_of(application)
        syncing_now = platform.is_syncing_itself(application)
        switch_marked_by = platform.mark_on(application, MarkedObject.APPLICATION)
        pin_marked_by = platform.mark_on(application, MarkedObject.DEPLOYMENT)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read which card [{application}] is held to now: {error}", error,
            asked_to_change=False
        ) from error

    switch = the_switch(descriptor.was_syncing_itself, syncing_now, switch_marked_by, mark)
    pin_landed = pin_marked_by == mark.action_id
    made = pin_landed and held_to == accelerator
    still_as_found = not pin_landed and held_to == descriptor.was_pinned_to

    if switch is Switch.CHANGED_SINCE or not (made or still_as_found) or (
            made and switch is Switch.TO_SUSPEND):
        landed = pin_landed or this_claim_s_suspension_stands(
            descriptor.was_syncing_itself, syncing_now, switch_marked_by, mark
        )
        raise AcceleratorPinRefused(a_change_made_since(
            f"[{application}]'s pods are held to {_the_card(held_to)} and the "
            f"application {'is' if syncing_now else 'is not'} syncing itself, which "
            f"is not where the pin from {_the_card(descriptor.was_pinned_to)} to "
            f"[{accelerator}] found it or would leave it",
            descriptor if landed else None,
            performed=pin_landed
        ))

    if made:
        logger.info("deployment already pinned to accelerator", extra={
            "application": application, "accelerator": accelerator
        })
        return descriptor

    suspend_where_it_is_to_be(application, switch, platform, mark, _refusing_a_change)

    try:
        platform.pin_to_accelerator(application, accelerator, mark)
    except DeploymentPlatformError as error:
        logger.warning("accelerator pin refused", extra={
            "application": application, "sync_suspended": descriptor.was_syncing_itself
        })
        raise _refusing(
            f"[{application}] could not be held to [{accelerator}]: {error}",
            error,
            asked_to_change=True,
            left_behind=descriptor if descriptor.was_syncing_itself else None
        ) from error

    logger.info("deployment pinned to accelerator", extra={
        "application": application, "accelerator": accelerator
    })

    return descriptor


def _refusing_a_change(said: str, error: DeploymentPlatformError) -> AcceleratorPinRefused:
    """This module's refusal of a change it asked for, with nothing before it
    left behind."""
    return _refusing(said, error, asked_to_change=True)


def restore_accelerator_pin(descriptor: AcceleratorPinUndo,
                            platform: DeploymentPlatformWrites,
                            mark: Mark
                            ) -> AcceleratorPinRestored:
    """Puts back both of the things a pin changed, where they are still Argus's,
    and says which it managed - every write carrying `mark`, as the pin's did.

    A pair rather than an exception, for the reason the other restores answer
    one: a restore can half-succeed and the half that fails is the quiet one.

    The platform is read before anything is written, and what it says decides how
    much is. Pods still held to the card Argus pinned them to are let go. Pods
    already held where Argus found them need no write, and count as put back. Any
    other selector is somebody's change since - one somebody took off as much as
    one somebody moved: nothing is written, sync is not resumed, and the answer
    says what was found and whether Argus's suspension still stands. Writing over
    it would be this module deciding that somebody else's change should not stand,
    which is not its question to answer. A read that never came back writes
    nothing and claims nothing - neither half back, nothing found.

    The pin first and reconciliation second. Re-enabling sync first would have
    the platform take the selector off on its own - unverifiably, at a moment
    nothing here chose. Where there was no pin, putting it back is taking this
    one off; the pods already placed stay where they are until something
    reschedules them.
    """
    application = descriptor.application

    try:
        held_to = platform.accelerator_pin_of(application)
    except DeploymentPlatformError:
        logger.error("restore check failed", exc_info=True,
                     extra={"application": application, "read": "the pin"})
        return _said(_nothing_established(), application)

    if held_to == descriptor.pinned_to:
        pin = _tried(
            application, "pin",
            lambda: platform.pin_to_accelerator(application, descriptor.was_pinned_to, mark)
        )
    elif held_to == descriptor.was_pinned_to:
        # Already where Argus found them, whoever put them there: nothing is
        # written for the pin, and it counts as put back.
        pin = True
    else:
        return _left_as_somebody_set_it(
            f"[{application}]'s pods are held to {_the_card(held_to)}, which is "
            f"neither {_the_card(descriptor.was_pinned_to)} Argus found nor "
            f"{_the_card(descriptor.pinned_to)} it pinned them to",
            descriptor, platform
        )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return _said(
            AcceleratorPinRestored(pin_put_back=pin, automated_sync_put_back=True),
            application
        )

    return _said(
        AcceleratorPinRestored(
            pin_put_back=pin,
            automated_sync_put_back=_tried(
                application, "automated sync",
                lambda: platform.resume_sync(application, mark)
            )
        ),
        application
    )


def _the_card(card: str | None) -> str:
    """A card as a sentence names it - including that there was none."""
    return "no card at all" if card is None else f"[{card}]"


def _left_as_somebody_set_it(because: str,
                             descriptor: AcceleratorPinUndo,
                             platform: DeploymentPlatformWrites) -> AcceleratorPinRestored:
    """The answer for a pin somebody changed since: nothing written, sync not
    resumed, `because` said - and whether the reconciliation Argus suspended
    still stands, read from the platform.

    Read rather than taken from the descriptor, because only the platform knows:
    a person who reverted in git and turned sync back on has ended Argus's
    suspension themselves, and sync that was off before Argus came was never
    Argus's to have suspended. A read that fails here establishes nothing, and
    the answer claims nothing.
    """
    application = descriptor.application

    try:
        syncing_now = platform.is_syncing_itself(application)
    except DeploymentPlatformError:
        logger.error("restore check failed", exc_info=True,
                     extra={"application": application, "read": "automated sync"})
        return _said(_nothing_established(), application)

    return _said(
        AcceleratorPinRestored(
            pin_put_back=False,
            automated_sync_put_back=False,
            left_because=because,
            sync_still_suspended=descriptor.was_syncing_itself and not syncing_now
        ),
        application
    )


def _nothing_established() -> AcceleratorPinRestored:
    """The answer where whose the pin is could not be found out: nothing
    written, neither half back, nothing found."""
    return AcceleratorPinRestored(pin_put_back=False, automated_sync_put_back=False)


def _said(restored: AcceleratorPinRestored, application: str) -> AcceleratorPinRestored:
    """`restored`, once the log has been told how much of it there is."""
    if restored.left_because is not None:
        logger.warning("accelerator pin left as somebody set it", extra={
            "application": application,
            "found": restored.left_because,
            "sync_still_suspended": restored.sync_still_suspended
        })
    elif restored.pin_put_back and restored.automated_sync_put_back:
        logger.info("accelerator pin restored", extra={"application": application})
    else:
        logger.warning("accelerator pin not fully restored", extra={
            "application": application,
            "pin_put_back": restored.pin_put_back,
            "automated_sync_put_back": restored.automated_sync_put_back
        })

    return restored


def _tried(application: str, step: str, call: Callable[[], None]) -> bool:
    try:
        call()
    except Exception:
        logger.error("restore step failed", exc_info=True,
                     extra={"application": application, "step": step})
        return False

    return True
