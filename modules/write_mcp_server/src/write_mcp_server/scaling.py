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

Planned before it is made. The plan reads the count and whether the platform is
reconciling the application, works out the count to ask for, is dated by the
platform's own clock, and changes nothing - so a claim can carry it before
anything in the estate moves. The write takes the plan rather than working it out
again, and reads the platform once more before it writes: what it finds decides
whether the change is still to be made, was already made under this claim's mark,
or has been overtaken by somebody's change since.

Several asks rather than one, because the platform's own rules make it so. The
reconciliation is suspended before the count is written - Argo CD puts a live
replica count straight back at its next sync, so a scale-out taken under automated
sync is a mitigation with a timer on it and a service that returns to saturation
at a moment nothing in the record explains. Only then is the action run.

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

from core.mcp_transport import (
    a_change_made_since,
    a_refusal_saying_what_it_left,
    an_exhausted_action,
)
from core.models import CapacityRestored, Planned, ReplicaUndo
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


def plan_scale_out(application: str, platform: DeploymentPlatformWrites) -> Planned[ReplicaUndo]:
    """The scale-out of `application` to make, worked out and dated - and
    nothing changed.

    Doubling rather than a figure somebody chose: what a saturated deployment
    needs is more capacity than it has, and the multiple of its current size is
    the only expression of that which does not need to know what the traffic is
    doing. Bounded by the ceiling above, which it reaches rather than exceeds.

    The count is the one the Deployment is asked to run, read from the live
    resource and not from the repository: after one scale-out the two disagree,
    and the number a doubling has to start from is the one in force. A platform
    that cannot say it is refused rather than guessed - a guess of one would
    halve a shop serving three.

    Dated by the platform's clock, read before anything it dates. A deployment
    already at the ceiling raises here, before a claim is written for it.
    """
    try:
        since = platform.now(application)
        running = platform.rollout_of(application).replicas_wanted
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read what [{application}] is running: {error}", error,
            asked_to_change=False
        ) from error

    _refuse_where_it_is_as_large_as_it_may_be(application, running)

    try:
        was_syncing_itself = platform.is_syncing_itself(application)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read whether [{application}] syncs itself: {error}", error,
            asked_to_change=False
        ) from error

    return Planned(
        descriptor=ReplicaUndo(
            application=application,
            was_replicas=running,
            replicas_asked_for=_twice(running),
            was_syncing_itself=was_syncing_itself
        ),
        since=since
    )


def scale_out(planned: Planned[ReplicaUndo],
              platform: DeploymentPlatformWrites,
              mark: Mark) -> ReplicaUndo:
    """Makes the scale-out `planned` describes, where the platform still stands
    as the plan found it, and reports what that cost - every write carrying
    `mark`.

    Every comparison is made before anything is written. A count still the one
    the plan found, under no mark of this claim's, is written; the count the plan
    asked for under this claim's mark is this scale-out already made, answered
    with the plan and nothing written twice; anything else is somebody's change
    since, refused with nothing written - carrying the plan where this claim's
    marks show part of it landed. The sync switch is held to the same rule
    (`sync_switch`).

    Under an autoscaler the count is the controller's to move, so it is no
    evidence either way: this claim's mark alone says the scale-out was made, and
    a count moved since the plan is doubled from where it is now - refused as
    exhausted where that is already as large as Argus may make it.

    The plan is held to this tier's own rule again here rather than trusted - a
    doubling of the count it found, within the ceiling, and larger than that
    count - and refused plainly, nothing written, where it is not: the plan is
    the caller's data, and the rule is this tier's.

    Raises rather than half-succeeding. A platform that refuses the action after
    sync was suspended leaves the suspension in place and says so - quietly
    restoring it would hide a state somebody has to know about.
    """
    descriptor = planned.descriptor
    application = descriptor.application
    asked_for = descriptor.replicas_asked_for

    # The plan is held to this tier's own rule from its own "was": a doubling,
    # bounded by the ceiling, and larger than what it found.
    if asked_for is None or asked_for != _twice(descriptor.was_replicas) or (
            asked_for <= descriptor.was_replicas):
        raise ScaleRefused(a_refusal_saying_what_it_left(
            f"the scale-out of [{application}] asks for [{asked_for}] replicas from "
            f"[{descriptor.was_replicas}], which is not twice that within the "
            f"[{THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR}] Argus may ask for"
        ))

    try:
        running = platform.rollout_of(application).replicas_wanted
        autoscaler = platform.autoscaler_of(application)
        syncing_now = platform.is_syncing_itself(application)
        count_marked_by = platform.mark_on(application, MarkedObject.DEPLOYMENT)
        switch_marked_by = platform.mark_on(application, MarkedObject.APPLICATION)
    except DeploymentPlatformError as error:
        raise _refusing(
            f"could not read what [{application}] is now: {error}", error,
            asked_to_change=False
        ) from error

    # What of this claim's is out there is worked out before any refusal that
    # follows the reads, so every one of them carries it.
    count_landed = count_marked_by == mark.action_id
    left_behind = descriptor if count_landed or this_claim_s_suspension_stands(
        descriptor.was_syncing_itself, syncing_now, switch_marked_by, mark
    ) else None

    switch = the_switch(descriptor.was_syncing_itself, syncing_now, switch_marked_by, mark)
    # Under an autoscaler a count says nothing of whose it is: the controller
    # moves it within a sync period of any write.
    made = count_landed and (autoscaler is not None or running == asked_for)
    still_as_found = not count_landed and (
        autoscaler is not None or running == descriptor.was_replicas
    )

    if switch is Switch.CHANGED_SINCE or not (made or still_as_found) or (
            made and switch is Switch.TO_SUSPEND):
        raise ScaleRefused(a_change_made_since(
            f"[{application}] is asked to run [{running}] replicas and "
            f"{'is' if syncing_now else 'is not'} syncing itself, which is not where "
            f"the scale-out from [{descriptor.was_replicas}] to [{asked_for}] found "
            f"it or would leave it",
            left_behind,
            performed=count_landed
        ))

    if made:
        logger.info("deployment already scaled out", extra={
            "application": application, "to_replicas": asked_for
        })
        return descriptor

    undo, to_replicas = descriptor, asked_for

    if running != descriptor.was_replicas:
        # The autoscaler moved it since the plan, and that is its routine move
        # rather than somebody's: the scale-out doubles from where it is now.
        if left_behind is not None and running >= THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR:
            # Spent, but not untouched: this claim's suspension stands, and an
            # exhausted action says it left nothing. Refused plainly instead,
            # carrying the plan that puts it back.
            raise ScaleRefused(a_refusal_saying_what_it_left(
                f"[{application}] is running [{running}] replicas, which is as "
                f"large as Argus may make it ([{THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR}])",
                left_behind
            ))

        _refuse_where_it_is_as_large_as_it_may_be(application, running)
        to_replicas = _twice(running)
        undo = descriptor.model_copy(update={
            "was_replicas": running, "replicas_asked_for": to_replicas
        })

    suspend_where_it_is_to_be(application, switch, platform, mark, _refusing_a_change)

    try:
        platform.scale(application, to_replicas, mark)
    except DeploymentPlatformError as error:
        logger.warning("scale-out refused", extra={
            "application": application, "sync_suspended": undo.was_syncing_itself
        })
        raise _refusing(
            f"[{application}] could not be scaled to [{to_replicas}] replicas: {error}",
            error,
            asked_to_change=True,
            left_behind=undo if undo.was_syncing_itself else None
        ) from error

    logger.info("deployment scaled out", extra={
        "application": application, "from_replicas": undo.was_replicas,
        "to_replicas": to_replicas
    })

    return undo


def _refuse_where_it_is_as_large_as_it_may_be(application: str, running: int) -> None:
    """Raises `AlreadyAtItsLargest` where `running` is at the ceiling or past it."""
    if running >= THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR:
        raise AlreadyAtItsLargest(
            an_exhausted_action(
                f"[{application}] is running [{running}] replicas, which is as "
                f"large as Argus may make it "
                f"([{THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR}])"
            )
        )


def _refusing_a_change(said: str, error: DeploymentPlatformError) -> ScaleRefused:
    """This module's refusal of a change it asked for, with nothing before it
    left behind."""
    return _refusing(said, error, asked_to_change=True)


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
