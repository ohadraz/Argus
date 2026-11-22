"""Holding a deployment's autoscaler still through the platform (spec §7.3, §12.1,
§13).

The write tier's fifth action, and the first that *stops* something rather than
adding or restoring something. It stops it by raising a floor: the controller is
left running, with nowhere left to scale down to. Nothing is removed, nothing is
deleted, and the ceiling a human declared is never moved - which is what keeps
this reversible, and what makes the thing to put back one number.

Not a resource action, which is what separates it from the scale-out beside it.
Argo CD registers Lua for `scale` on `apps/Deployment` and registers nothing for
an autoscaler, so a floor is written by patching the resource itself. How is the
platform port's adapter's.

Where the autoscaler is is discovered rather than configured, which is the other
thing that separates this from the restart and the scale-out. Both of those
address a resource whose name the caller already knows. An autoscaler's is not
knowable that way - it is named by whoever wrote the chart, and it need not be
named after the deployment it scales - and the platform already publishes the
answer. So a pin asks where to write rather than being told, and a namespace held
in configuration is one fewer copy of a fact the cluster owns.

The bounds are the platform's to tell and this module's to read. The repository
says what the autoscaler is asked to converge on and the platform says what it is
running, and those are different numbers the moment anybody pins - so the floor to
replace and the ceiling to raise it to are both read from the live resource.
Nothing above the port could have named either honestly.

Several asks rather than one, which is the scale-out's plus the question of where
to send them. The platform is asked where the autoscaler is, then for its bounds,
then whether it is reconciling the application, which is then suspended - Argo CD
re-applies an autoscaler's whole manifest at its next sync, floor included, so a
pin taken under automated sync is a mitigation with a timer on it and a service
that returns to flapping at a moment nothing in the record explains. Only then is
the floor raised.

Which is also why this mitigates without resolving, and why the descriptor it
returns records two things. The repository still declares the floor the controller
was thrashing between, and reconciliation is off so that nothing re-applies it.
Both have to be put back by a withdrawal, and only this module ever knew either.

A withdrawal puts back only what is still Argus's, and reads the platform before
it writes to find out. A floor still the one Argus asked for is put back; one
already back where Argus found it needs no write; any other - or an autoscaler no
longer there at all - is somebody's change since, and is left as they set it, with
the reconciliation Argus suspended left suspended too, because resuming it would
have the platform re-apply git over them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from core.models import (
    AutoscalerUndo,
    AutoscalingRestored,
    ChangeFound,
    Made,
    NotMade,
    Planned,
)
from deployment_platform import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    Mark,
    MarkedObject,
    MarkFound,
)
from mcp_transport import (
    a_change_made_since,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
)

from write_mcp_server.refusing import a_platform_refusal, no_claim_to_compare_with
from write_mcp_server.scaling import THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR
from write_mcp_server.sync_switch import (
    Switch,
    is_this_claim_s,
    suspend_where_it_is_to_be,
    the_switch,
    this_claim_s_suspension_stands,
)

logger = logging.getLogger(__name__)


class AlreadyHeldStill(Exception):
    """There is no room left between the floor and the ceiling.

    Raised rather than answered with a no-op, and raised *before* anything is
    changed. A count that is not moving has nothing about it left to stop, so a
    caller told "done" would record a mitigation that never happened and then
    judge the service against it - and the honest account is the one a refusal
    gives: the action Argus has for this cause is exhausted, so the walk moves on
    to another candidate.

    Marked as an exhausted action on the way out, which is what lets the walk do
    that. The tool worked, the estate was read correctly, and nothing was
    changed; a caller that could not tell this from a platform it failed to reach
    would wake a human over an answer.
    """


class PinRefused(Exception):
    """The platform would not report the bounds, or would not change them."""


def _refusing(said: str, error: DeploymentPlatformError, *,
              asked_to_change: bool,
              left_behind: AutoscalerUndo | None = None) -> PinRefused:
    """This module's refusal, marked as `a_platform_refusal` marks it.

    `left_behind` is what the failure cost, where it cost anything. Where the
    suspension landed and the floor did not move, that suspension travels on the
    failure - so a caller still knows an application is sitting un-reconciled.
    """
    return PinRefused(a_platform_refusal(
        said, error, asked_to_change=asked_to_change, left_behind=left_behind
    ))


def plan_autoscaler_pin(application: str,
                        platform: DeploymentPlatformWrites) -> Planned[AutoscalerUndo]:
    """The pin of `application`'s autoscaler to make, worked out and dated - and
    nothing changed.

    Its floor raised to its ceiling and no further, because the ceiling is a
    bound a human declared. What Argus is choosing here is not how many replicas
    should run - that is not its to choose even in principle - but that the
    count should stop moving, and equal bounds are how a controller is stopped
    without being taken away.

    Dated by the platform's clock, read before anything it dates. An application
    with no autoscaler, or one with no room left between its bounds, raises here,
    before a claim is written for it.
    """
    try:
        since = platform.now(application)
        autoscaler = _where_the_autoscaler_is(application, platform)
        bounds = platform.autoscaler_bounds(application, autoscaler)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read [{application}]'s autoscaler: {error}", error,
            asked_to_change=False
        ) from error

    the_floor_to_ask_for = _the_highest_floor_within(bounds)

    if the_floor_to_ask_for <= bounds.floor:
        raise AlreadyHeldStill(
            an_exhausted_action(
                f"[{application}]'s autoscaler may fall to [{bounds.floor}] "
                f"replica{'' if bounds.floor == 1 else 's'} and rise to "
                f"[{bounds.ceiling}], and the highest floor "
                f"Argus may ask for is [{the_floor_to_ask_for}] - so there is no "
                f"room left between the two and nothing here for a pin to stop"
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
        descriptor=AutoscalerUndo(
            application=application,
            was_min_replicas=bounds.floor,
            min_replicas_asked_for=the_floor_to_ask_for,
            was_syncing_itself=was_syncing_itself
        ),
        since=since
    )


def pin_autoscaler(planned: Planned[AutoscalerUndo],
                   platform: DeploymentPlatformWrites,
                   mark: Mark) -> AutoscalerUndo:
    """Makes the pin `planned` describes, where the platform still stands as the
    plan found it, and reports what that cost - every write carrying `mark`.

    Every comparison is made before anything is written. A floor still the one
    the plan found, under no mark of this claim's, is raised; the floor the plan
    asked for under this claim's mark is this pin already made, answered with the
    plan and nothing written twice; anything else - an autoscaler gone among it -
    is somebody's change since, refused with nothing written, carrying the plan
    where this claim's marks show part of it landed. The sync switch is held to
    the same rule (`sync_switch`).

    The plan is held to this tier's own rule again here rather than trusted - a
    floor above the one it found, within the ceiling read now and the most Argus
    may ask for - and refused plainly, nothing written, where it is not: the plan
    is the caller's data, and the bounds are this tier's.

    A pin written here is answered dated by the platform's answer to it, on its
    own clock; one already made is answered undated, as `scale_out`'s is.

    Raises rather than half-succeeding. A platform that refuses the patch after
    sync was suspended leaves the suspension in place and says so - quietly
    restoring it would hide a state somebody has to know about.
    """
    descriptor = planned.descriptor
    application = descriptor.application
    asked_for = descriptor.min_replicas_asked_for
    autoscaler, _, compared = _compared_with_the_plan(planned, platform, mark)

    if compared.made:
        logger.info("autoscaler floor already raised", extra={
            "application": application, "to_floor": asked_for
        })
        # Undated, as `scaling`'s made answer is.
        return descriptor.model_copy(update={"written_at": None})

    suspend_where_it_is_to_be(application, compared.switch, platform, mark, _refusing_a_change)

    try:
        answered_at = platform.set_autoscaler_floor(application, autoscaler, asked_for, mark)
    except DeploymentPlatformError as error:
        logger.warning("autoscaler pin refused", extra={
            "application": application, "sync_suspended": descriptor.was_syncing_itself
        })
        raise _refusing(
            f"[{application}]'s autoscaler floor could not be raised to "
            f"[{asked_for}]: {error}",
            error,
            asked_to_change=True,
            left_behind=descriptor if descriptor.was_syncing_itself else None
        ) from error

    logger.info("autoscaler floor raised", extra={
        "application": application, "from_floor": descriptor.was_min_replicas,
        "to_floor": asked_for
    })

    return descriptor.model_copy(update={"written_at": answered_at})


def _the_highest_floor_within(bounds: AutoscalerBounds) -> int:
    """The autoscaler's ceiling, or the most Argus may ask for where that is lower."""
    return min(bounds.ceiling, THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR)


def _refusing_a_change(said: str, error: DeploymentPlatformError) -> PinRefused:
    """This module's refusal of a change it asked for, with nothing before it
    left behind."""
    return _refusing(said, error, asked_to_change=True)


def whether_it_was_made(planned: Planned[AutoscalerUndo],
                        platform: DeploymentPlatformWrites,
                        action_id: str | None
                        ) -> Made[AutoscalerUndo] | NotMade[AutoscalerUndo]:
    """Whether the pin `planned` describes was made under the claim `action_id`
    - the write's own rule on the plan, with the write left out, for a walk
    resumed after the worker that claimed it died.

    Made is answered with what the write would answer, dated by the moment the
    claim's mark on the autoscaler says the floor was written, `None` where it
    says none. The floor still where the plan found it, under no mark of the
    claim's, is nothing landed - carrying the plan where the claim's suspension
    of the sync stands, as `scaling`'s read does. Anything else is refused
    exactly as the write refuses it on the same estate, since the two are one
    compare. A call naming no claim is refused plainly, as `scaling`'s read
    refuses one. Writes nothing.
    """
    if action_id is None:
        raise PinRefused(no_claim_to_compare_with(
            f"the pin of [{planned.descriptor.application}]'s autoscaler"
        ))

    _, found, compared = _compared_with_the_plan(planned, platform, action_id)

    if not compared.made:
        return NotMade[AutoscalerUndo](left_behind=compared.left_behind)

    return Made[AutoscalerUndo](
        descriptor=planned.descriptor.model_copy(update={"written_at": None}),
        made_at=None if found.floor_marked_by is None else found.floor_marked_by.written_at
    )


def still_argus_s(descriptor: AutoscalerUndo,
                  platform: DeploymentPlatformWrites,
                  action_id: str | None) -> ChangeFound:
    """Whether the pin `descriptor` records is still as Argus left it - the
    write's own "made" rule, read and not acted on, for a walk resumed after the
    worker that made it died.

    The floor it asked for under the claim `action_id`'s mark, on an autoscaler
    still there, and the sync switch where the pin left it, is still Argus's.
    Anything else is somebody's change since, saying what was found. A read
    that never came back, or a call naming no claim, is a question nobody can
    answer. Writes nothing.
    """
    application = descriptor.application

    if action_id is None:
        return ChangeFound(still_argus_s=None, found=no_claim_to_compare_with(
            f"the pin of [{application}]'s autoscaler"
        ))

    try:
        found = _what_is_there(application, platform)
    except DeploymentPlatformError as error:
        logger.warning("still-argus-s check failed", exc_info=True,
                       extra={"application": application})
        return ChangeFound(
            still_argus_s=None,
            found=f"could not read what [{application}]'s autoscaler is now: {error}"
        )

    if _compared(descriptor, found, action_id).made:
        return ChangeFound(still_argus_s=True)

    return ChangeFound(
        still_argus_s=False,
        found=f"{_as_it_stands(application, found)}, which is not where the pin from "
              f"[{descriptor.was_min_replicas}] to [{descriptor.min_replicas_asked_for}] "
              f"left it"
    )


@dataclass(frozen=True)
class _Found:
    """What the platform says of a pin's autoscaler now: the autoscaler, its
    bounds, whether the application reconciles itself, and the marks on the
    Application and on the autoscaler."""

    autoscaler: Autoscaler | None
    bounds: AutoscalerBounds | None
    syncing_now: bool
    switch_marked_by: MarkFound | None
    floor_marked_by: MarkFound | None


@dataclass(frozen=True)
class _Compared:
    """A pin held against what was found: where the sync switch stands, whether
    the claim's floor landed, whether the change is made or somebody's since,
    and what of the claim's is out there."""

    switch: Switch
    floor_landed: bool
    made: bool
    changed_since: bool
    left_behind: AutoscalerUndo | None


def _what_is_there(application: str, platform: DeploymentPlatformWrites) -> _Found:
    """The reads a pin is compared with. Raises `DeploymentPlatformError` where
    any of them fails."""
    autoscaler = platform.autoscaler_of(application)

    return _Found(
        autoscaler=autoscaler,
        bounds=(None if autoscaler is None
                else platform.autoscaler_bounds(application, autoscaler)),
        syncing_now=platform.is_syncing_itself(application),
        switch_marked_by=platform.mark_on(application, MarkedObject.APPLICATION),
        floor_marked_by=platform.mark_on(application, MarkedObject.AUTOSCALER)
    )


def _compared(descriptor: AutoscalerUndo, found: _Found, claim: Mark | str) -> _Compared:
    """The one rule the write, the claimed read and the performed read share:
    made is the floor asked for under `claim`'s mark, with the switch where the
    change needs it; as the plan found it is the floor it found under no mark of
    `claim`'s; anything else - an autoscaler gone among it, since a pin would
    have nowhere to go - is changed since."""
    floor_landed = is_this_claim_s(found.floor_marked_by, claim)
    left_behind = descriptor if floor_landed or this_claim_s_suspension_stands(
        descriptor.was_syncing_itself, found.syncing_now, found.switch_marked_by, claim
    ) else None
    switch = the_switch(descriptor.was_syncing_itself, found.syncing_now,
                        found.switch_marked_by, claim)
    floor = None if found.bounds is None else found.bounds.floor
    made = floor_landed and floor == descriptor.min_replicas_asked_for
    still_as_found = not floor_landed and floor == descriptor.was_min_replicas
    changed_since = found.autoscaler is None or switch is Switch.CHANGED_SINCE or not (
        made or still_as_found) or (made and switch is Switch.TO_SUSPEND)

    return _Compared(switch=switch, floor_landed=floor_landed,
                     made=made and not changed_since, changed_since=changed_since,
                     left_behind=left_behind)


def _compared_with_the_plan(planned: Planned[AutoscalerUndo],
                            platform: DeploymentPlatformWrites,
                            claim: Mark | str) -> tuple[Autoscaler, _Found, _Compared]:
    """What the platform is now, held against `planned` for `claim` - every
    comparison the write makes before it writes, raising as it raises - with
    the autoscaler the change is to be made on.

    The reads come first, because the plan is held to this tier's own rule
    against the bounds read now: a floor raised, and no higher than those
    bounds allow - refused plainly where it is not, carrying what of the
    claim's is out there. Somebody's change since is refused as changed since,
    carrying the same.
    """
    descriptor = planned.descriptor
    application = descriptor.application
    asked_for = descriptor.min_replicas_asked_for

    try:
        found = _what_is_there(application, platform)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read what [{application}]'s autoscaler is now: {error}", error,
            asked_to_change=False
        ) from error

    compared = _compared(descriptor, found, claim)

    if asked_for <= descriptor.was_min_replicas or (
            found.bounds is not None and asked_for > _the_highest_floor_within(found.bounds)):
        raise PinRefused(a_refusal_saying_what_it_left(
            f"the pin of [{application}]'s autoscaler asks for a floor of "
            f"[{asked_for}] from [{descriptor.was_min_replicas}], which is not a "
            f"floor raised within what Argus may ask for",
            compared.left_behind
        ))

    if compared.changed_since or found.autoscaler is None:
        raise PinRefused(a_change_made_since(
            f"{_as_it_stands(application, found)}, which is not where the pin from "
            f"[{descriptor.was_min_replicas}] to [{asked_for}] found it or would leave it",
            compared.left_behind,
            performed=compared.floor_landed
        ))

    return found.autoscaler, found, compared


def _as_it_stands(application: str, found: _Found) -> str:
    """The autoscaler's floor and the application's reconciliation, as a
    sentence says them."""
    floor = None if found.bounds is None else found.bounds.floor

    return (f"[{application}]'s autoscaler "
            f"{'is gone' if floor is None else f'may fall to [{floor}]'} and the "
            f"application {'is' if found.syncing_now else 'is not'} syncing itself")


def restore_autoscaler_floor(descriptor: AutoscalerUndo,
                             platform: DeploymentPlatformWrites,
                             mark: Mark) -> AutoscalingRestored:
    """Puts back both of the things a pin changed, where they are still Argus's,
    and says which it managed - every write carrying `mark`, as the pin's did.

    A pair rather than an exception, for the reason the scale-out's restore answers
    one: a restore can half-succeed and the half that fails is the quiet one. The
    caller turns the pair into a verdict; this reports facts.

    The platform is read before anything is written, and what it says decides how
    much is. A floor still the one Argus asked for is put back. One already back
    where Argus found it needs no write, and counts as put back. Any other is
    somebody's change since, and so is an autoscaler no longer among the
    application's resources - somebody took away the controller Argus held still.
    Either way nothing is written, sync is not resumed, and the answer says what
    was found and whether Argus's suspension still stands. Writing over it would
    be this module deciding that somebody else's change should not stand, which is
    not its question to answer; resuming sync over a removed autoscaler would have
    the platform bring back what they removed.

    A read that never came back writes nothing and claims nothing - neither half
    back, nothing found. An autoscaler the platform could not be asked about is not
    one somebody removed.

    The floor first and reconciliation second, which is the order that leaves
    nothing to chance. Re-enabling sync first would have the platform re-apply the
    autoscaler's manifest on its own - to the same floor, and unverifiably, at a
    moment nothing here chose.

    Asks where the autoscaler is again rather than remembering it. The descriptor
    records what was changed and not where the resource lived, deliberately: a
    withdrawal can arrive hours later, and where a resource lives is the platform's
    to answer at the moment it is asked rather than a fact worth keeping a stale
    copy of.
    """
    application = descriptor.application

    try:
        autoscaler = platform.autoscaler_of(application)
    except DeploymentPlatformError:
        logger.error("restore check failed", exc_info=True,
                     extra={"application": application, "read": "the autoscaler"})
        return _said(_nothing_established(), application)

    if autoscaler is None:
        return _left_as_somebody_set_it(
            f"[{application}] has no autoscaler among its resources any more, so "
            f"the one Argus held still was taken away since",
            descriptor, platform
        )

    try:
        floor = platform.autoscaler_bounds(application, autoscaler).floor
    except DeploymentPlatformError:
        logger.error("restore check failed", exc_info=True,
                     extra={"application": application, "read": "the floor"})
        return _said(_nothing_established(), application)

    if floor == descriptor.min_replicas_asked_for:
        floor_put_back = _tried(
            application, "floor",
            lambda: platform.set_autoscaler_floor(
                application, autoscaler, descriptor.was_min_replicas, mark
            )
        )
    elif floor == descriptor.was_min_replicas:
        # Already where Argus found it, whoever put it there: nothing is written
        # for the floor, and it counts as put back.
        floor_put_back = True
    else:
        return _left_as_somebody_set_it(
            f"[{application}]'s autoscaler may fall to [{floor}], which is neither "
            f"the [{descriptor.was_min_replicas}] Argus found nor the "
            f"[{descriptor.min_replicas_asked_for}] it asked for",
            descriptor, platform
        )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return _said(
            AutoscalingRestored(floor_put_back=floor_put_back, automated_sync_put_back=True),
            application
        )

    return _said(
        AutoscalingRestored(
            floor_put_back=floor_put_back,
            automated_sync_put_back=_tried(
                application, "automated sync",
                lambda: platform.resume_sync(application, mark)
            )
        ),
        application
    )


def _left_as_somebody_set_it(because: str,
                             descriptor: AutoscalerUndo,
                             platform: DeploymentPlatformWrites) -> AutoscalingRestored:
    """The answer for a floor somebody changed since: nothing written, sync not
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
        AutoscalingRestored(
            floor_put_back=False,
            automated_sync_put_back=False,
            left_because=because,
            sync_still_suspended=descriptor.was_syncing_itself and not syncing_now
        ),
        application
    )


def _nothing_established() -> AutoscalingRestored:
    """The answer where whose the floor is could not be found out: nothing
    written, neither half back, nothing found."""
    return AutoscalingRestored(floor_put_back=False, automated_sync_put_back=False)


def _said(restored: AutoscalingRestored, application: str) -> AutoscalingRestored:
    """`restored`, once the log has been told how much of it there is."""
    if restored.left_because is not None:
        logger.warning("autoscaler floor left as somebody set it", extra={
            "application": application,
            "found": restored.left_because,
            "sync_still_suspended": restored.sync_still_suspended
        })
    elif restored.floor_put_back and restored.automated_sync_put_back:
        logger.info("autoscaler floor restored", extra={"application": application})
    else:
        logger.warning("autoscaler floor not fully restored", extra={
            "application": application,
            "floor_put_back": restored.floor_put_back,
            "automated_sync_put_back": restored.automated_sync_put_back
        })

    return restored


def _where_the_autoscaler_is(application: str,
                             platform: DeploymentPlatformWrites) -> Autoscaler:
    """The autoscaler the platform names for `application`, or a refusal.

    Refused where it names none, which is the one thing a caller reading this
    cannot check for itself: a pin performed against a controller that does not
    exist would be reported as done and then confirmed against a world that does
    not exist either.
    """
    autoscaler = platform.autoscaler_of(application)

    if autoscaler is None:
        raise PinRefused(
            f"[{application}] has no autoscaler among its resources, so there is "
            f"no autoscaler here to hold still"
        )

    return autoscaler


def _tried(application: str, step: str, call: Callable[[], object]) -> bool:
    try:
        call()
    except Exception:
        logger.error("restore step failed", exc_info=True,
                     extra={"application": application, "step": step})
        return False

    return True
