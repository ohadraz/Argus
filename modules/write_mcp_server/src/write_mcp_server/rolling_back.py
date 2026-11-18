"""Rolling a deployment back through the platform (spec §7.3, §12.1).

The write tier's third action. Everything above the port sees an application
name going in and a record of what changed coming back.

The deployment rather than its configuration, because a revision carries the
code and the configuration it shipped with and the platform returns both
together. So one tool answers a configuration changed into a broken state and
new code that broke it alike; which of the two it was is the mode the
Investigator named, and it decides what fix remains, not what is called here.

Shaped like Argo CD's own rollback, which re-syncs the application to an entry
in its own deployment history. That is what makes this admissible as a generic
mitigation rather than an infrastructure change somebody has to approve - the
revision it applies was reviewed and ran before, so Argus is replaying
somebody's change rather than authoring one. Nothing is written to the
repository the revision came from, and nothing here may write one.

Several asks of the platform rather than one, because its own rules make it so.
It is asked two facts nobody above this port holds: which entry is currently
deployed, and whether it is reconciling the application itself. Automated sync
is then suspended, because a real Argo CD *refuses* a rollback while it is on
and would in any case re-apply the revision being rolled away from at the next
pass. Only then is the rollback asked for. How each is asked is the platform
port's adapter's, and nothing here names a route.

Which is also why this mitigates without resolving, and why the descriptor it
returns records two things. The repository still holds the change that caused
the incident - a values file or the source, according to what broke - and the
deployment is merely no longer running it, with reconciliation off so that it
stays that way. Both have to be put back by a withdrawal, and only this module
ever knew either. It records the revision it rolled back to beside them, which
is what that withdrawal compares the platform against.

A withdrawal puts back only what is still Argus's, and reads the platform before
it writes to find out. Still Argus's is the newest entry in the history being
Argus's own rollback - by the account Argus signs in as, of the revision it went
to - and the Deployment running the images the platform renders for that
revision. The images because a `kubectl set image` or a `rollout undo` leaves no
entry in the history and changes exactly them; images alone because the live
template carries defaulted fields git never states. A deployment already back on
the revision Argus found, running what that renders, needs no rollback. Anything
else is somebody's change since, and is left as they set it - with the
reconciliation Argus suspended left suspended too, because resuming it would
have the platform re-apply git over them. What is read decides it; the marks on
the platform's objects are not read.

What this cannot see is a hand edit that leaves every image alone - an
environment variable changed with `kubectl edit` - which reads as Argus's. An
admission webhook that rewrites images reads as a person's change on every
rollback, which overwrites nothing and escalates each one. And resuming the
reconciliation re-applies git to every object of the application, so a person's
change to another of its objects, made while Argus held it off, is reverted with
it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum, auto

from core.mcp_transport import an_exhausted_action
from core.models import DeploymentRestored, DeploymentRollbackUndo
from deployment_platform import DeploymentPlatformError, DeploymentPlatformWrites, Mark

from write_mcp_server.refusing import a_platform_refusal

logger = logging.getLogger(__name__)


class _Standing(Enum):
    """Where a rollback stands that nobody else has changed since."""

    # The rollback Argus made is still what the platform runs.
    STILL_ARGUS_S = auto()
    # The deployment is already on the revision Argus found it on.
    ALREADY_BACK = auto()


class NoEarlierRevision(Exception):
    """The application has nothing to roll back to.

    Raised rather than answered with a no-op, and raised *before* anything is
    changed. An application on its first deployment has no earlier entry, and
    a caller told "done" would record a mitigation that never happened and
    then judge the service against it.

    Marked as an exhausted action, as a scale-out past the ceiling is: the
    action has nowhere to go and nothing was touched, so the walk tries its
    next explanation rather than reaching a human, and what it records says
    nothing was changed.
    """


class RollbackRefused(Exception):
    """The platform would not perform the rollback."""


def _refusing(said: str, error: DeploymentPlatformError, *,
              asked_to_change: bool,
              left_behind: DeploymentRollbackUndo | None = None
              ) -> RollbackRefused:
    """This module's refusal, marked as `a_platform_refusal` marks it.

    `left_behind` is what the failure cost, where it cost anything. A platform
    that refuses after reconciliation was suspended has left this application
    un-reconciled and recorded nowhere else, so the suspension travels on every
    refusal after it - a caller told only that the rollback failed would pass
    over the application believing the estate untouched.
    """
    return RollbackRefused(a_platform_refusal(
        said, error, asked_to_change=asked_to_change, left_behind=left_behind
    ))


def roll_back_deployment(application: str,
                         platform: DeploymentPlatformWrites,
                         mark: Mark) -> DeploymentRollbackUndo:
    """Returns `application` to the revision it was running before the current
    one, and reports what that cost.

    The suspension carries `mark`. The rollback cannot: the platform records
    under whose account it was made, and its request has nowhere to put more.

    The entry rolled back to is the platform's to choose, and the choice is the
    one `argocd app rollback APPNAME` makes with its history id omitted: the
    immediately preceding deployment, in the order the platform keeps its
    history. Nothing above this port holds a deployment history to choose from,
    so a caller naming an entry would be naming one it could not have read.

    Raises rather than half-succeeding. An application with no earlier entry
    raises before anything is touched; a platform that refuses the rollback
    raises after sync was suspended, and that is deliberate - the suspension is
    recorded nowhere yet, so leaving it in place and saying so is honest where
    quietly restoring it would hide a state somebody has to know about.
    """
    try:
        history = platform.deployments_of(application)
    except DeploymentPlatformError as error:
        raise _refusing(f"could not read [{application}]: {error}", error,
                        asked_to_change=False) from error

    if len(history) < 2:
        raise NoEarlierRevision(
            an_exhausted_action(
                f"[{application}] has no revision before the one it is running, so "
                f"there is nothing to roll back to"
            )
        )

    running, previous = history[-1], history[-2]

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
    # has to put back whether the rollback then lands or the platform vanishes.
    undo = DeploymentRollbackUndo(
        application=application,
        was_on_history_id=running.history_id,
        was_on_revision=running.revision,
        rolled_back_to_revision=previous.revision,
        was_syncing_itself=was_syncing_itself
    )

    try:
        platform.roll_back(application, previous.history_id)
    except DeploymentPlatformError as error:
        logger.warning("rollback refused", extra={
            "application": application, "sync_suspended": was_syncing_itself
        })
        raise _refusing(
            f"[{application}] could not be rolled back to history entry "
            f"[{previous.history_id}]: {error}",
            error,
            asked_to_change=True,
            left_behind=undo if was_syncing_itself else None
        ) from error

    logger.info("deployment rolled back", extra={
        "application": application,
        "from_history_id": running.history_id,
        "to_history_id": previous.history_id
    })

    return undo


def restore_deployment(descriptor: DeploymentRollbackUndo,
                       platform: DeploymentPlatformWrites,
                       mark: Mark,
                       argus_account: str) -> DeploymentRestored:
    """Puts back both of the things a rollback changed, where they are still
    Argus's, and says which it managed - the resumed sync carrying `mark`, as
    the suspension did.

    A pair rather than an exception, because a restore can half-succeed and
    the half that fails is the quiet one: a deployment whose revision is back
    looks right from every angle a reader has, while receiving nothing
    anybody ships to it because the reconciliation Argus suspended is still
    suspended. The caller turns the pair into a verdict; this reports facts.

    The platform is read before anything is written, and what it says decides
    how much is. A rollback still Argus's - the newest entry made by
    `argus_account`, of the revision recorded as rolled back to, and the
    Deployment running what that revision renders - is put back. A deployment
    already back on the revision Argus found, running what that renders, needs
    no rollback, and counts as put back. Anything else is somebody's change
    since: nothing is written, sync is not resumed, and the answer says what was
    found and whether Argus's suspension still stands. Writing over it would be
    this module deciding that somebody else's change should not stand, which is
    not its question to answer.

    A read that never came back writes nothing and claims nothing - neither
    half back, nothing found - and neither does a descriptor recorded without
    the revision it rolled back to, nor an empty `argus_account`, since whose
    the newest entry is cannot be asked without both. A put-back made blind is
    the one the check exists to prevent.

    The revision first and reconciliation second, which is the order the
    platform allows: automated sync refuses a rollback, so re-enabling it
    before returning to the earlier entry would make the second step
    impossible.
    """
    application = descriptor.application
    rolled_back_to = descriptor.rolled_back_to_revision

    if rolled_back_to is None:
        logger.error("restore check impossible", extra={
            "application": application, "missing": "rolled_back_to_revision"
        })
        return _said(_nothing_established(), application)

    # No history entry is ever made by nobody, so with no account to look for,
    # Argus's own rollback would read as somebody else's and be left standing.
    if not argus_account:
        logger.error("restore check impossible", extra={
            "application": application, "missing": "argus_account"
        })
        return _said(_nothing_established(), application)

    try:
        found = _what_became_of_the_rollback(descriptor, rolled_back_to, platform,
                                             argus_account)
    except DeploymentPlatformError:
        logger.error("restore check failed", exc_info=True,
                     extra={"application": application, "read": "the deployment"})
        return _said(_nothing_established(), application)

    if isinstance(found, str):
        return _left_as_somebody_set_it(found, descriptor, platform)

    if found is _Standing.ALREADY_BACK:
        # Already where Argus found it, whoever put it there: nothing is written
        # for the revision, and it counts as put back.
        revision = True
    else:
        revision = _tried(
            application, "revision",
            lambda: platform.roll_back(application, descriptor.was_on_history_id)
        )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return _said(
            DeploymentRestored(revision_put_back=revision, automated_sync_put_back=True),
            application
        )

    return _said(
        DeploymentRestored(
            revision_put_back=revision,
            automated_sync_put_back=_tried(
                application, "automated sync",
                lambda: platform.resume_sync(application, mark)
            )
        ),
        application
    )


def _what_became_of_the_rollback(descriptor: DeploymentRollbackUndo,
                                 rolled_back_to: str,
                                 platform: DeploymentPlatformWrites,
                                 argus_account: str) -> _Standing | str:
    """Where the rollback `descriptor` records stands now, or - where it is
    somebody's change since - what was found, said.

    Reads the history, then the images: the Deployment's, and those the
    platform renders for the revision the newest entry says it should be on.
    Raises `DeploymentPlatformError` where any read fails, so the caller can
    write nothing on it.
    """
    application = descriptor.application
    history = platform.deployments_of(application)

    if not history:
        return f"the platform records no deployment of [{application}] at all"

    newest = history[-1]

    if newest.revision == rolled_back_to and newest.initiated_by == argus_account:
        return _by_its_images(application, rolled_back_to, _Standing.STILL_ARGUS_S, platform)

    if newest.revision == descriptor.was_on_revision:
        return _by_its_images(application, descriptor.was_on_revision,
                              _Standing.ALREADY_BACK, platform)

    return (
        f"the newest deployment of [{application}] is of revision "
        f"[{newest.revision}], made by [{newest.initiated_by or 'an unnamed account'}] "
        f"rather than by Argus's own rollback"
    )


def _by_its_images(application: str,
                   revision: str,
                   standing: _Standing,
                   platform: DeploymentPlatformWrites) -> _Standing | str:
    """`standing`, where the Deployment runs the images `revision` renders - or,
    where it runs others, what it runs, said: something other than a deployment
    set them, and left no entry in the history doing it."""
    running = platform.images_running(application)
    rendered = platform.images_at(application, revision)

    if running == rendered:
        return standing

    return (
        f"[{application}] runs {_listed(running)}, where revision [{revision}] "
        f"renders {_listed(rendered)} - images set since without a deployment"
    )


def _listed(images: dict[str, str]) -> str:
    """Each container and its image, in a stable order."""
    return ", ".join(f"[{container}] on [{image}]" for container, image in sorted(images.items()))


def _left_as_somebody_set_it(because: str,
                             descriptor: DeploymentRollbackUndo,
                             platform: DeploymentPlatformWrites) -> DeploymentRestored:
    """The answer for a rollback somebody changed since: nothing written, sync
    not resumed, `because` said - and whether the reconciliation Argus
    suspended still stands, read from the platform.

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
        DeploymentRestored(
            revision_put_back=False,
            automated_sync_put_back=False,
            left_because=because,
            sync_still_suspended=descriptor.was_syncing_itself and not syncing_now
        ),
        application
    )


def _nothing_established() -> DeploymentRestored:
    """The answer where whose the rollback is could not be found out: nothing
    written, neither half back, nothing found."""
    return DeploymentRestored(revision_put_back=False, automated_sync_put_back=False)


def _said(restored: DeploymentRestored, application: str) -> DeploymentRestored:
    """`restored`, once the log has been told how much of it there is."""
    if restored.left_because is not None:
        logger.warning("deployment left as somebody set it", extra={
            "application": application,
            "found": restored.left_because,
            "sync_still_suspended": restored.sync_still_suspended
        })
    elif restored.revision_put_back and restored.automated_sync_put_back:
        logger.info("deployment restored", extra={"application": application})
    else:
        logger.warning("deployment not fully restored", extra={
            "application": application,
            "revision_put_back": restored.revision_put_back,
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
