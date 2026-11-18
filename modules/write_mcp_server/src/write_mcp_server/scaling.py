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
back by a withdrawal, and only this module ever knew either. It records the count
it asked for beside them, which is what that withdrawal compares the live count
with.

A withdrawal puts back only what is still Argus's, and reads the platform before
it writes to find out. A count still the one Argus asked for is put back; one
already back where Argus found it needs no write; any other is somebody's since,
and is left as they set it - with the reconciliation Argus suspended left
suspended too, because resuming it would have the platform re-apply git over them.
Where an autoscaler owns the count, the count is the controller's whatever it
reads, and nobody's to put back: only the sync is.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final

from core.mcp_transport import an_exhausted_action
from core.models import CapacityRestored, ReplicaUndo
from deployment_platform import DeploymentPlatformError, DeploymentPlatformWrites, Mark

from write_mcp_server.refusing import a_platform_refusal

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


def _refusing(said: str, error: DeploymentPlatformError, *,
              asked_to_change: bool,
              left_behind: ReplicaUndo | None = None) -> ScaleRefused:
    """This module's refusal, marked as `a_platform_refusal` marks it.

    `left_behind` is what the failure cost, where it cost anything. This is the
    action most likely to fail part-way - it reads, suspends, and only then acts
    - so the suspension travels on every refusal after it, and the caller still
    knows a deployment is sitting un-reconciled.
    """
    return ScaleRefused(a_platform_refusal(
        said, error, asked_to_change=asked_to_change, left_behind=left_behind
    ))


def scale_out(application: str,
              platform: DeploymentPlatformWrites,
              mark: Mark) -> ReplicaUndo:
    """Doubles what `application` is running, and reports what that cost - every
    write carrying `mark`.

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
            f"could not read what [{application}] is running: {error}", error,
            asked_to_change=False
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
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read whether [{application}] syncs itself: {error}", error,
            asked_to_change=False
        ) from error

    # Apart from the read before it, because this is the first change asked
    # for: a failure here may have suspended the sync, where one there cannot.
    if was_syncing_itself:
        try:
            platform.suspend_sync(application, mark)
        except DeploymentPlatformError as error:
            raise _refusing(
                f"could not suspend the sync of [{application}]: {error}", error,
                asked_to_change=True
            ) from error

    # Built before the action rather than after it, because it describes what
    # has already been changed: where sync was suspended, this is what a caller
    # has to put back whether the count then moves or the platform vanishes.
    undo = ReplicaUndo(
        application=application,
        was_replicas=running,
        replicas_asked_for=_twice(running),
        was_syncing_itself=was_syncing_itself
    )

    try:
        platform.scale(application, _twice(running), mark)
    except DeploymentPlatformError as error:
        logger.warning("scale-out refused", extra={
            "application": application, "sync_suspended": was_syncing_itself
        })
        raise _refusing(
            f"[{application}] could not be scaled to [{_twice(running)}] "
            f"replicas: {error}",
            error,
            asked_to_change=True,
            left_behind=undo if was_syncing_itself else None
        ) from error

    logger.info("deployment scaled out", extra={
        "application": application, "from_replicas": running, "to_replicas": _twice(running)
    })

    return undo


def restore_replica_count(descriptor: ReplicaUndo,
                          platform: DeploymentPlatformWrites,
                          mark: Mark) -> CapacityRestored:
    """Puts back both of the things a scale-out changed, where they are still
    Argus's, and says which it managed - every write carrying `mark`, as the
    scale-out's did.

    A pair rather than an exception, for the reason the rollback's restore answers
    one: a restore can half-succeed and the half that fails is the quiet one. The
    caller turns the pair into a verdict; this reports facts.

    The platform is read before anything is written, and what it says decides how
    much is. A live count still the one Argus asked for is put back. One already
    back where Argus found it needs no write, and counts as put back. Any other is
    somebody's change since: nothing is written, sync is not resumed, and the
    answer says what was found and whether Argus's suspension still stands.
    Writing over it would be this module deciding that somebody else's change
    should not stand, which is not its question to answer.

    Where an autoscaler owns the count, no count is written whatever it reads: a
    figure written here would be re-derived within a sync period, and a count a
    controller replaces is one Argus is not responsible for. The sync Argus
    suspended is still Argus's, and is resumed; the answer says the count was left
    to its autoscaler.

    A read that never came back writes nothing and claims nothing - neither half
    back, nothing found - and neither does a descriptor recorded without the count
    it asked for, since whether the live count is still Argus's cannot be asked
    without it. A put-back made blind is the one the check exists to prevent.

    The count first and reconciliation second, which is the order that leaves
    nothing to chance. Re-enabling sync first would have the platform set the
    count back on its own - to the same number, and unverifiably, at a moment
    nothing here chose.
    """
    application = descriptor.application
    asked_for = descriptor.replicas_asked_for

    if asked_for is None:
        logger.error("restore check impossible", extra={
            "application": application, "missing": "replicas_asked_for"
        })
        return _said(_nothing_established(), application)

    try:
        autoscaler = platform.autoscaler_of(application)
        running = (
            None if autoscaler is not None
            else platform.rollout_of(application).replicas_wanted
        )
    except DeploymentPlatformError:
        logger.error("restore check failed", exc_info=True,
                     extra={"application": application, "read": "the count"})
        return _said(_nothing_established(), application)

    if autoscaler is not None:
        logger.info("replica count left to its autoscaler", extra={
            "application": application, "autoscaler": autoscaler.name
        })
        return _with_the_sync_put_back(descriptor, platform, mark, count=True,
                                       left_to_its_autoscaler=True)

    if running == asked_for:
        return _with_the_sync_put_back(
            descriptor, platform, mark,
            count=_tried(
                application, "count",
                lambda: platform.scale(application, descriptor.was_replicas, mark)
            )
        )

    if running == descriptor.was_replicas:
        # Already where Argus found it, whoever put it there: nothing is written
        # for the count, and it counts as put back.
        return _with_the_sync_put_back(descriptor, platform, mark, count=True)

    return _left_as_somebody_set_it(
        f"[{application}] is asked to run [{running}] replicas, which is neither "
        f"the [{descriptor.was_replicas}] Argus found nor the [{asked_for}] it asked for",
        descriptor, platform
    )


def _with_the_sync_put_back(descriptor: ReplicaUndo,
                            platform: DeploymentPlatformWrites,
                            mark: Mark, *,
                            count: bool,
                            left_to_its_autoscaler: bool = False) -> CapacityRestored:
    """The answer once the count's half is settled as `count`: the sync resumed
    where Argus suspended it, carrying `mark`."""
    application = descriptor.application

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return _said(
            CapacityRestored(count_put_back=count, automated_sync_put_back=True,
                             count_left_to_its_autoscaler=left_to_its_autoscaler),
            application
        )

    return _said(
        CapacityRestored(
            count_put_back=count,
            automated_sync_put_back=_tried(
                application, "automated sync",
                lambda: platform.resume_sync(application, mark)
            ),
            count_left_to_its_autoscaler=left_to_its_autoscaler
        ),
        application
    )


def _left_as_somebody_set_it(because: str,
                             descriptor: ReplicaUndo,
                             platform: DeploymentPlatformWrites) -> CapacityRestored:
    """The answer for a count somebody changed since: nothing written, sync not
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
        CapacityRestored(
            count_put_back=False,
            automated_sync_put_back=False,
            left_because=because,
            sync_still_suspended=descriptor.was_syncing_itself and not syncing_now
        ),
        application
    )


def _nothing_established() -> CapacityRestored:
    """The answer where whose the count is could not be found out: nothing
    written, neither half back, nothing found."""
    return CapacityRestored(count_put_back=False, automated_sync_put_back=False)


def _said(restored: CapacityRestored, application: str) -> CapacityRestored:
    """`restored`, once the log has been told how much of it there is."""
    if restored.left_because is not None:
        logger.warning("replica count left as somebody set it", extra={
            "application": application,
            "found": restored.left_because,
            "sync_still_suspended": restored.sync_still_suspended
        })
    elif restored.count_put_back and restored.automated_sync_put_back:
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
