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
ever knew either.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from argus_core.mcp_transport import an_unreachable_platform
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    DeploymentRestored,
    DeploymentRollbackUndo,
)
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    PlatformUnreachable,
)

logger = logging.getLogger(__name__)


class NoEarlierRevision(Exception):
    """The application has nothing to roll back to.

    Raised rather than answered with a no-op, and raised *before* anything is
    changed. An application on its first deployment has no earlier entry, and
    a caller told "done" would record a mitigation that never happened and
    then judge the service against it.
    """


class RollbackRefused(Exception):
    """The platform would not perform the rollback."""


def _refusing(said: str, error: DeploymentPlatformError,
              left_behind: DeploymentRollbackUndo | None = None
              ) -> RollbackRefused:
    """This module's refusal, marked where the platform was never reached.

    The mark is what lets a caller tell four actions being unavailable from this
    rollback being rejected, without reading the words of either. It is this
    module's to apply rather than the platform's: what a response means is the
    platform's to say, and what to raise about it is the action's own.

    `left_behind` is what the failure cost, where it cost anything. A platform
    that disappears after reconciliation was suspended has left this application
    un-reconciled and recorded nowhere, and the mark used to be withheld for
    exactly that reason - a caller told only that the platform was unavailable
    would narrow to another action believing the estate untouched. Saying what
    was left behind answers that without withholding the fact the caller needs,
    and withholding it meant the mode was handled only when the platform failed
    on the first call.
    """
    if isinstance(error, PlatformUnreachable):
        return RollbackRefused(
            an_unreachable_platform(DEPLOYMENT_PLATFORM, said, left_behind)
        )

    return RollbackRefused(said)


def roll_back_deployment(application: str,
                         platform: DeploymentPlatformWrites) -> DeploymentRollbackUndo:
    """Returns `application` to the revision it was running before the current
    one, and reports what that cost.

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
        raise _refusing(f"could not read [{application}]: {error}", error) from error

    if len(history) < 2:
        raise NoEarlierRevision(
            f"[{application}] has no revision before the one it is running, so "
            f"there is nothing to roll back to"
        )

    running, previous = history[-1], history[-2]

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
    # has to put back whether the rollback then lands or the platform vanishes.
    undo = DeploymentRollbackUndo(
        application=application,
        was_on_history_id=running.history_id,
        was_on_revision=running.revision,
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
            undo if was_syncing_itself else None
        ) from error

    logger.info("deployment rolled back", extra={
        "application": application,
        "from_history_id": running.history_id,
        "to_history_id": previous.history_id
    })

    return undo


def restore_deployment(descriptor: DeploymentRollbackUndo,
                       platform: DeploymentPlatformWrites) -> DeploymentRestored:
    """Puts back both of the things a rollback changed, and says which it
    managed.

    A pair rather than an exception, because a restore can half-succeed and
    the half that fails is the quiet one: a deployment whose revision is back
    looks right from every angle a reader has, while receiving nothing
    anybody ships to it because the reconciliation Argus suspended is still
    suspended. The caller turns the pair into a verdict; this reports facts.

    The revision first and reconciliation second, which is the order the
    platform allows: automated sync refuses a rollback, so re-enabling it
    before returning to the earlier entry would make the second step
    impossible.
    """
    application = descriptor.application

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
                lambda: platform.resume_sync(application)
            )
        ),
        application
    )


def _said(restored: DeploymentRestored, application: str) -> DeploymentRestored:
    """`restored`, once the log has been told how much of it there is."""
    if restored.revision_put_back and restored.automated_sync_put_back:
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
