"""Making a deployment larger through the platform (spec §7.3, §12.1, §13).

The write tier's fourth action, and the only one that adds something rather than
restoring something. Everything above the port sees an application name going in
and a record of what changed coming back.

Shaped like Argo CD's own scaling, which is not an endpoint of its own: `scale` is
a built-in resource action for `apps/Deployment`, the same route the restart goes
through. So this tier learns one more action rather than a second platform, where
patching Kubernetes' own scale subresource would have put a Kubernetes client in a
tier that has needed only Argo CD. How it is asked is the platform port's
adapter's.

The count is the platform's to tell and this module's to derive. The repository
says what the deployment is asked to converge on and the platform says what it is
running, and those are different numbers the moment anybody scales - so the count
to replace is read from the live resource, doubled, and bounded by a ceiling this
tier holds. Nothing above the port could have named it honestly: a target is
meaningless without the count it replaces, and an agent asserting one would be
asserting a fact no evidence in front of it carries.

Several asks rather than one, because the platform's own rules make it so. The
live Deployment is read for the count. The platform is asked whether it is
reconciling the application, which is then suspended - Argo CD puts a live replica
count straight back at its next sync, so a scale-out taken under automated sync is
a mitigation with a timer on it and a service that returns to saturation at a
moment nothing in the record explains. Only then is the action run.

Reconciliation is one instance of a general rule and not the rule itself:
**anything that re-derives the state a mitigation just set has to be suspended or
changed before it is set**, and a repository is only one such thing. A live
autoscaler owns the replica count too, and re-derives it from its own metric
within a sync period.

This module deliberately does nothing about that, and the restraint is the point.
A scale-out is not the mitigation for a deployment whose count a controller is
moving - that is a different failure mode with a different answer, and the answer
patches the controller rather than working around it (`pinning.py`). A scale-out
that suspended an autoscaler to make itself stick would be one action quietly
becoming two, and it would be the wrong mode's answer arriving by the back door.
So an autoscaler here is left exactly as it was found, recorded nowhere in the
descriptor, and a scale-out aimed at a flapping deployment is left to be refuted
the way any action the evidence does not bear out is refuted: the count is
re-derived, the service does not recover, and the walk moves on.

Which is also why this mitigates without resolving, and why the descriptor it
returns records two things. The repository still asks for the size that was too
small, and reconciliation is off so that nothing re-applies it. Both have to be put
back by a withdrawal, and only this module ever knew either.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

from argus_core.mcp_transport import an_exhausted_action, an_unreachable_platform
from argus_core.models import DEPLOYMENT_PLATFORM, CapacityRestored, ReplicaUndo
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    PlatformUnreachable,
)

logger = logging.getLogger(__name__)

# How far one scale-out may take a deployment. Two doublings past the three
# replicas this estate's one deployment is declared with, which is the bound on the
# *size* of an attempt where the gate's cap bounds the *number* of them - and
# either alone leaves the other's failure available: a cap of two with no ceiling
# permits an unbounded second attempt, and a ceiling with no cap permits attempts
# without end below it.
#
# A constant rather than a setting because this estate has one deployment, and a
# figure configured per environment would be a knob nobody has a second value for.
# The day there are two deployments of different sizes, this is the line that moves.
THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR: Final = 12


class AlreadyAtItsLargest(Exception):
    """The deployment is already as large as Argus may make it.

    Raised rather than answered with a no-op, and raised *before* anything is
    changed. A caller told "done" would record a mitigation that never happened
    and then judge the service against it - and the honest account is the one a
    refusal gives: the action Argus has for this cause is exhausted, so the walk
    moves on to another candidate.

    Marked as an exhausted action on the way out, which is what lets the walk do
    that. The tool worked, the estate was read correctly, and nothing was
    changed; a caller that could not tell this from a platform it failed to reach
    would wake a human over an answer.
    """


class ScaleRefused(Exception):
    """The platform would not report the size, or would not change it."""


def _refusing(said: str, error: DeploymentPlatformError,
              left_behind: ReplicaUndo | None = None) -> ScaleRefused:
    """This module's refusal, marked where the platform was never reached.

    The mark is what lets a caller tell four actions being unavailable from this
    scale-out being rejected, without reading the words of either. It is applied
    here rather than by the platform: what a response means is the platform's to
    say, and what to raise about it is the action's own.

    `left_behind` is what the failure cost, where it cost anything. This is the
    action most likely to lose the platform part-way - it reads, suspends, and
    only then acts - so withholding the mark on a failure after the suspension
    would have meant handling this mode only when the platform happened to fail
    on the first call. Saying what was left behind lets the caller narrow itself
    and still know a deployment is sitting un-reconciled.
    """
    if isinstance(error, PlatformUnreachable):
        return ScaleRefused(
            an_unreachable_platform(DEPLOYMENT_PLATFORM, said, left_behind)
        )

    return ScaleRefused(said)


def scale_out(application: str, platform: DeploymentPlatformWrites) -> ReplicaUndo:
    """Doubles what `application` is running, and reports what that cost.

    Doubling rather than a figure somebody chose: what a saturated deployment
    needs is more capacity than it has, and the multiple of its current size is
    the only expression of that which does not need to know what the traffic is
    doing. Bounded by the ceiling above, which it reaches rather than exceeds.

    The count is the one the Deployment is asked to run, read from the live
    resource and not from the repository: after one scale-out the two disagree,
    and the number a doubling has to start from is the one in force. A platform
    that cannot say it is refused rather than guessed - a guess of one would
    halve a shop serving three.

    Raises rather than half-succeeding. A deployment already at the ceiling raises
    before anything is touched; a platform that refuses the action raises after
    sync was suspended, and that is deliberate for the reason the rollback's is -
    the suspension is recorded nowhere yet, so leaving it in place and saying so is
    honest where quietly restoring it would hide a state somebody has to know
    about.
    """
    try:
        running = platform.rollout_of(application).replicas_wanted
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read what [{application}] is running: {error}", error
        ) from error

    if running >= THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR:
        raise AlreadyAtItsLargest(
            an_exhausted_action(
                f"[{application}] is running [{running}] replicas, which is as "
                f"large as Argus may make it "
                f"([{THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR}])"
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
    # has to put back whether the count then moves or the platform vanishes.
    undo = ReplicaUndo(
        application=application,
        was_replicas=running,
        was_syncing_itself=was_syncing_itself
    )

    try:
        platform.scale(application, _twice(running))
    except DeploymentPlatformError as error:
        logger.warning("scale-out refused", extra={
            "application": application, "sync_suspended": was_syncing_itself
        })
        raise _refusing(
            f"[{application}] could not be scaled to [{_twice(running)}] "
            f"replicas: {error}",
            error,
            undo if was_syncing_itself else None
        ) from error

    logger.info("deployment scaled out", extra={
        "application": application, "from_replicas": running, "to_replicas": _twice(running)
    })

    return undo


def restore_replica_count(descriptor: ReplicaUndo,
                          platform: DeploymentPlatformWrites) -> CapacityRestored:
    """Puts back both of the things a scale-out changed, and says which it managed.

    A pair rather than an exception, for the reason the rollback's restore answers
    one: a restore can half-succeed and the half that fails is the quiet one. The
    caller turns the pair into a verdict; this reports facts.

    The count first and reconciliation second, which is the order that leaves
    nothing to chance. Re-enabling sync first would have the platform set the
    count back on its own - to the same number, and unverifiably, at a moment
    nothing here chose.

    The recorded count is written back even where something else has since moved
    the live one away from it, and no check is made first. What an undo owes is
    that nothing Argus set is left behind; it does not owe a deployment left at a
    size Argus can vouch for. Where a controller owns the count, the figure written
    here is re-derived within a sync period - and that is the correct outcome
    rather than a failure of this call, because a count a controller immediately
    replaces is a count Argus is no longer responsible for. Reading the live count
    first and declining to write on a mismatch would be this module deciding
    whether somebody else's change should stand, which is not its question to
    answer.
    """
    application = descriptor.application

    count = _tried(
        application, "count", lambda: platform.scale(application, descriptor.was_replicas)
    )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return _said(
            CapacityRestored(count_put_back=count, automated_sync_put_back=True),
            application
        )

    return _said(
        CapacityRestored(
            count_put_back=count,
            automated_sync_put_back=_tried(
                application, "automated sync",
                lambda: platform.resume_sync(application)
            )
        ),
        application
    )


def _said(restored: CapacityRestored, application: str) -> CapacityRestored:
    """`restored`, once the log has been told how much of it there is."""
    if restored.count_put_back and restored.automated_sync_put_back:
        logger.info("replica count restored", extra={"application": application})
    else:
        logger.warning("replica count not fully restored", extra={
            "application": application,
            "count_put_back": restored.count_put_back,
            "automated_sync_put_back": restored.automated_sync_put_back
        })

    return restored


def _twice(replicas: int) -> int:
    """Double the count, up to the ceiling and never past it."""
    return min(replicas * 2, THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR)


def _tried(application: str, step: str, call: Callable[[], None]) -> bool:
    try:
        call()
    except Exception:
        logger.error("restore step failed", exc_info=True,
                     extra={"application": application, "step": step})
        return False

    return True
