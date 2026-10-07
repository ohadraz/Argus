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
"""

from __future__ import annotations

from collections.abc import Callable

from argus_core.mcp_transport import an_exhausted_action, an_unreachable_platform
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    AutoscalerUndo,
    AutoscalingRestored,
)
from deployment_platform import (
    Autoscaler,
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    PlatformUnreachable,
)

from write_mcp_server.scaling import THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR


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


def _refusing(said: str, error: DeploymentPlatformError,
              left_behind: AutoscalerUndo | None = None) -> PinRefused:
    """This module's refusal, marked where the platform was never reached.

    The mark is what lets a caller tell four actions being unavailable from this
    pin being rejected, without reading the words of either. It is applied here
    rather than by the platform: what a response means is the platform's to say,
    and what to raise about it is the action's own.

    `left_behind` is what the failure cost, where it cost anything. Where the
    suspension landed and the floor did not move, that suspension travels on the
    failure - so a caller can narrow itself to a reachable platform and still
    know an application is sitting un-reconciled. Withholding the mark instead
    would have meant this mode was handled only when the platform failed on the
    first call.
    """
    if isinstance(error, PlatformUnreachable):
        return PinRefused(
            an_unreachable_platform(DEPLOYMENT_PLATFORM, said, left_behind)
        )

    return PinRefused(said)


def pin_autoscaler(application: str,
                   platform: DeploymentPlatformWrites) -> AutoscalerUndo:
    """Raises `application`'s autoscaler floor to its ceiling, and reports what
    that cost.

    To the ceiling and no further, because the ceiling is a bound a human
    declared. What Argus is choosing here is not how many replicas should run -
    that is not its to choose even in principle - but that the count should stop
    moving, and equal bounds are how a controller is stopped without being taken
    away.

    Raises rather than half-succeeding. An autoscaler with no room left between
    its bounds raises before anything is touched; a platform that refuses the
    patch raises after sync was suspended, and that is deliberate for the reason
    the scale-out's is - the suspension is recorded nowhere yet, so leaving it in
    place and saying so is honest where quietly restoring it would hide a state
    somebody has to know about.
    """
    try:
        autoscaler = _where_the_autoscaler_is(application, platform)
        bounds = platform.autoscaler_bounds(application, autoscaler)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read [{application}]'s autoscaler: {error}", error
        ) from error

    the_floor_to_ask_for = min(bounds.ceiling, THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR)

    if the_floor_to_ask_for <= bounds.floor:
        raise AlreadyHeldStill(
            an_exhausted_action(
                f"[{application}]'s autoscaler may fall to [{bounds.floor}] "
                f"replicas and rise to [{bounds.ceiling}], and the highest floor "
                f"Argus may ask for is [{the_floor_to_ask_for}] - so there is no "
                f"room left between the two and nothing here for a pin to stop"
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
    # has to put back whether the floor then moves or the platform vanishes.
    undo = AutoscalerUndo(
        application=application,
        was_min_replicas=bounds.floor,
        min_replicas_asked_for=the_floor_to_ask_for,
        was_syncing_itself=was_syncing_itself
    )

    try:
        platform.set_autoscaler_floor(application, autoscaler, the_floor_to_ask_for)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"[{application}]'s autoscaler floor could not be raised to "
            f"[{the_floor_to_ask_for}]: {error}",
            error,
            undo if was_syncing_itself else None
        ) from error

    return undo


def restore_autoscaler_floor(descriptor: AutoscalerUndo,
                             platform: DeploymentPlatformWrites) -> AutoscalingRestored:
    """Puts back both of the things a pin changed, and says which it managed.

    A pair rather than an exception, for the reason the scale-out's restore answers
    one: a restore can half-succeed and the half that fails is the quiet one. The
    caller turns the pair into a verdict; this reports facts.

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
    floor = _tried(
        lambda: platform.set_autoscaler_floor(
            descriptor.application,
            _where_the_autoscaler_is(descriptor.application, platform),
            descriptor.was_min_replicas
        )
    )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return AutoscalingRestored(
            floor_put_back=floor, automated_sync_put_back=True
        )

    return AutoscalingRestored(
        floor_put_back=floor,
        automated_sync_put_back=_tried(
            lambda: platform.resume_sync(descriptor.application)
        )
    )


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


def _tried(call: Callable[[], None]) -> bool:
    try:
        call()
    except Exception:
        return False

    return True
