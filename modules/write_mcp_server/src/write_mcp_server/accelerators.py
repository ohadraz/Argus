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
from dataclasses import dataclass

from core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    ChangeFound,
    Made,
    NotMade,
    Planned,
)
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    Mark,
    MarkedObject,
    MarkFound,
)
from mcp_transport import (
    ToolRefused,
    a_change_made_since,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
)

from write_mcp_server.refusing import a_platform_refusal, no_claim_to_compare_with
from write_mcp_server.sync_switch import (
    Switch,
    is_this_claim_s,
    suspend_where_it_is_to_be,
    the_switch,
    this_claim_s_suspension_stands,
)

logger = logging.getLogger(__name__)


class AlreadyPinned(ToolRefused):
    """The deployment is already held to the card it was to be pinned to.

    Raised rather than answered with a no-op, and raised *before* anything is
    changed. Nothing would move, so a caller told "done" would record a
    mitigation that never happened and then judge the service against it - and
    the honest account is the one a refusal gives: the action Argus has for this
    cause is exhausted, so the walk moves on to another candidate.

    Marked as an exhausted action on the way out, which is what lets the walk do
    that rather than wake a human over a platform that answered correctly.
    """


class AcceleratorPinRefused(ToolRefused):
    """The platform would not say which card the pods are held to, or would not
    change it."""


def _refusing(said: str, error: DeploymentPlatformError, *,
              asked_to_change: bool,
              left_behind: AcceleratorPinUndo | None = None) -> AcceleratorPinRefused:
    """This module's refusal, of the kind `a_platform_refusal` decides.

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

    A pin written here is answered dated by the platform's answer to it, on its
    own clock; one already made is answered undated, since the platform keeps no
    moment of its own for a patch and the mark's moment is Argus's.

    Raises rather than half-succeeding. A platform that refuses the pin after
    sync was suspended leaves the suspension in place and says so - quietly
    restoring it would hide a state somebody has to know about.
    """
    descriptor = planned.descriptor
    application = descriptor.application
    accelerator = descriptor.pinned_to
    _, compared = _compared_with_the_plan(planned, platform, mark)

    if compared.made:
        logger.info("deployment already pinned to accelerator", extra={
            "application": application, "accelerator": accelerator
        })
        # Undated: the platform keeps no moment of its own for the patch, and
        # the mark's is Argus's clock.
        return descriptor.model_copy(update={"written_at": None})

    suspend_where_it_is_to_be(application, compared.switch, platform, mark, _refusing_a_change)

    try:
        answered_at = platform.pin_to_accelerator(application, accelerator, mark)
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

    return descriptor.model_copy(update={"written_at": answered_at})


def _refusing_a_change(said: str, error: DeploymentPlatformError) -> AcceleratorPinRefused:
    """This module's refusal of a change it asked for, with nothing before it
    left behind."""
    return _refusing(said, error, asked_to_change=True)


def whether_it_was_made(planned: Planned[AcceleratorPinUndo],
                        platform: DeploymentPlatformWrites,
                        action_id: str | None
                        ) -> Made[AcceleratorPinUndo] | NotMade[AcceleratorPinUndo]:
    """Whether the pin `planned` describes was made under the claim `action_id`
    - the write's own rule on the plan, with the write left out, for a walk
    resumed after the worker that claimed it died.

    Made is answered with what the write would answer, dated by the moment the
    claim's mark on the Deployment says the pin was written, `None` where it
    says none. Pods still held where the plan found them, under no mark of the
    claim's, are nothing landed - carrying the plan where the claim's
    suspension of the sync stands, as `scaling`'s read does. Anything else is
    refused exactly as the write refuses it on the same estate, since the two
    are one compare. A call naming no claim is refused plainly, as `scaling`'s
    read refuses one. Writes nothing.
    """
    if action_id is None:
        raise AcceleratorPinRefused(no_claim_to_compare_with(
            f"the pin of [{planned.descriptor.application}] to a card"
        ))

    found, compared = _compared_with_the_plan(planned, platform, action_id)

    if not compared.made:
        return NotMade[AcceleratorPinUndo](left_behind=compared.left_behind)

    return Made[AcceleratorPinUndo](
        descriptor=planned.descriptor.model_copy(update={"written_at": None}),
        made_at=None if found.pin_marked_by is None else found.pin_marked_by.written_at
    )


def still_argus_s(descriptor: AcceleratorPinUndo,
                  platform: DeploymentPlatformWrites,
                  action_id: str | None) -> ChangeFound:
    """Whether the pin `descriptor` records is still as Argus left it - the
    write's own "made" rule, read and not acted on, for a walk resumed after the
    worker that made it died.

    The pods held to the card the pin named under the claim `action_id`'s
    mark, and the sync switch where the pin left it, is still Argus's. Anything
    else is somebody's change since, saying what was found. A read that never
    came back, or a call naming no claim, is a question nobody can answer.
    Writes nothing.
    """
    application = descriptor.application

    if action_id is None:
        return ChangeFound(still_argus_s=None, found=no_claim_to_compare_with(
            f"the pin of [{application}] to a card"
        ).words)

    try:
        found = _what_is_there(application, platform)
    except DeploymentPlatformError as error:
        logger.warning("still-argus-s check failed", exc_info=True,
                       extra={"application": application})
        return ChangeFound(
            still_argus_s=None,
            found=f"could not read which card [{application}] is held to now: {error}"
        )

    if _compared(descriptor, found, action_id).made:
        return ChangeFound(still_argus_s=True)

    return ChangeFound(
        still_argus_s=False,
        found=f"{_as_it_stands(application, found)}, which is not where the pin from "
              f"{_the_card(descriptor.was_pinned_to)} to [{descriptor.pinned_to}] left it"
    )


@dataclass(frozen=True)
class _Found:
    """What the platform says of a pin's Deployment now: the card its pods are
    held to, whether the application reconciles itself, and the marks on the
    Application and on the Deployment."""

    held_to: str | None
    syncing_now: bool
    switch_marked_by: MarkFound | None
    pin_marked_by: MarkFound | None


@dataclass(frozen=True)
class _Compared:
    """A pin held against what was found: where the sync switch stands, whether
    the claim's pin landed, whether the change is made or somebody's since, and
    what of the claim's is out there."""

    switch: Switch
    pin_landed: bool
    made: bool
    changed_since: bool
    left_behind: AcceleratorPinUndo | None


def _what_is_there(application: str, platform: DeploymentPlatformWrites) -> _Found:
    """The reads a pin to a card is compared with. Raises
    `DeploymentPlatformError` where any of them fails."""
    return _Found(
        held_to=platform.accelerator_pin_of(application),
        syncing_now=platform.is_syncing_itself(application),
        switch_marked_by=platform.mark_on(application, MarkedObject.APPLICATION),
        pin_marked_by=platform.mark_on(application, MarkedObject.DEPLOYMENT)
    )


def _compared(descriptor: AcceleratorPinUndo, found: _Found, claim: Mark | str) -> _Compared:
    """The one rule the write, the claimed read and the performed read share:
    made is the pods on the plan's card under `claim`'s mark, with the switch
    where the change needs it; as the plan found it is the pods where it found
    them under no mark of `claim`'s; anything else - a selector somebody took
    off as much as one somebody moved - is changed since."""
    pin_landed = is_this_claim_s(found.pin_marked_by, claim)
    left_behind = descriptor if pin_landed or this_claim_s_suspension_stands(
        descriptor.was_syncing_itself, found.syncing_now, found.switch_marked_by, claim
    ) else None
    switch = the_switch(descriptor.was_syncing_itself, found.syncing_now,
                        found.switch_marked_by, claim)
    made = pin_landed and found.held_to == descriptor.pinned_to
    still_as_found = not pin_landed and found.held_to == descriptor.was_pinned_to
    changed_since = switch is Switch.CHANGED_SINCE or not (made or still_as_found) or (
        made and switch is Switch.TO_SUSPEND)

    return _Compared(switch=switch, pin_landed=pin_landed,
                     made=made and not changed_since, changed_since=changed_since,
                     left_behind=left_behind)


def _compared_with_the_plan(planned: Planned[AcceleratorPinUndo],
                            platform: DeploymentPlatformWrites,
                            claim: Mark | str) -> tuple[_Found, _Compared]:
    """What the platform is now, held against `planned` for `claim` - every
    comparison the write makes before it writes, raising as it raises.

    The plan is held to this tier's own rule from its own "was" first - a pin
    moves the pods somewhere they were not held - and refused plainly where it
    is not. A read that fails is refused as the platform's failure says.
    Somebody's change since is refused as changed since, carrying what of the
    claim's is out there.
    """
    descriptor = planned.descriptor
    application = descriptor.application
    accelerator = descriptor.pinned_to

    if accelerator == descriptor.was_pinned_to:
        raise AcceleratorPinRefused(a_refusal_saying_what_it_left(
            f"the pin of [{application}] asks to hold its pods to [{accelerator}], "
            f"where it found them held already"
        ))

    try:
        found = _what_is_there(application, platform)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read which card [{application}] is held to now: {error}", error,
            asked_to_change=False
        ) from error

    compared = _compared(descriptor, found, claim)

    if compared.changed_since:
        raise AcceleratorPinRefused(a_change_made_since(
            f"{_as_it_stands(application, found)}, which is not where the pin from "
            f"{_the_card(descriptor.was_pinned_to)} to [{accelerator}] found it or would "
            f"leave it",
            compared.left_behind,
            performed=compared.pin_landed
        ))

    return found, compared


def _as_it_stands(application: str, found: _Found) -> str:
    """The card the pods are held to and the application's reconciliation, as a
    sentence says them."""
    return (f"[{application}]'s pods are held to {_the_card(found.held_to)} and the "
            f"application {'is' if found.syncing_now else 'is not'} syncing itself")


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


def _tried(application: str, step: str, call: Callable[[], object]) -> bool:
    try:
        call()
    except Exception:
        logger.error("restore step failed", exc_info=True,
                     extra={"application": application, "step": step})
        return False

    return True
