"""Rolling a deployment's configuration back through the platform (spec §7.3, §12.1).

The write tier's third action, and the only place in Argus that knows how a
rollback is actually performed. Everything above the port sees an application
name going in and a record of what changed coming back.

Shaped like Argo CD's own rollback: `POST
/api/v1/applications/{application}/rollback`, which re-syncs the application to
an entry in its own deployment history. That is what makes this admissible as
a generic mitigation rather than an infrastructure change somebody has to
approve - the revision it applies was reviewed and ran before, so Argus is
replaying somebody's change rather than authoring one. Nothing is written to
the configuration repository, and nothing here may write one.

Three requests rather than one, because the platform's own rules make it
three. The application is read, for two facts nobody above this port holds:
which entry is currently deployed, and whether the platform is reconciling the
application itself. Automated sync is then suspended, because a real Argo CD
*refuses* a rollback while it is on and would in any case re-apply the
revision being rolled away from at the next pass. Only then is the rollback
asked for.

Which is also why this mitigates without resolving, and why the descriptor it
returns records two things. The configuration repository still holds the
change that caused the incident; the deployment is merely no longer running
it, and reconciliation is off so that it stays that way. Both have to be put
back by a withdrawal, and only this module ever knew either.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

import httpx
from argus_core import SettingsSlice
from argus_core.models import ConfigRollbackUndo, ConfigurationRestored

# Argo CD's own wire vocabulary for the parts of an application this reads.
# Named once here rather than spelled at each lookup: they are another
# project's field names, and a typo in one is a silent `None` rather than an
# error.
_STATUS: Final = "status"
_HISTORY: Final = "history"
_HISTORY_ID: Final = "id"
_REVISION: Final = "revision"
_SPEC: Final = "spec"
_SYNC_POLICY: Final = "syncPolicy"
_AUTOMATED: Final = "automated"

REQUEST_TIMEOUT_SECONDS = 10.0


class RollbackSettings(SettingsSlice):
    """Where a rollback is asked for, and under what credential.

    Three paths, because the operation is three requests against three of the
    platform's routes. Templates rather than fixed routes, for the reason the
    restart path is one: the demo's stand-in and a real server are one setting
    with two values.
    """

    argocd_base_url: str
    argocd_application_path: str
    argocd_rollback_path: str
    argocd_spec_path: str
    argocd_auth_token: str


HttpGet = Callable[..., httpx.Response]
HttpPost = Callable[..., httpx.Response]
HttpPut = Callable[..., httpx.Response]


class NoEarlierRevision(Exception):
    """The application has nothing to roll back to.

    Raised rather than answered with a no-op, and raised *before* anything is
    changed. An application on its first deployment has no earlier entry, and
    a caller told "done" would record a mitigation that never happened and
    then judge the service against it.
    """


class RollbackRefused(Exception):
    """The platform would not perform the rollback."""


def roll_back_configuration(
    application: str,
    settings: RollbackSettings,
    get: HttpGet = httpx.get,
    post: HttpPost = httpx.post,
    put: HttpPut = httpx.put
) -> ConfigRollbackUndo:
    """Returns `application` to the revision it was running before the current
    one, and reports what that cost.

    The entry rolled back to is the platform's to choose, and the choice is the
    one `argocd app rollback APPNAME` makes with its history id omitted: the
    immediately preceding deployment. Nothing above this port holds a
    deployment history to choose from, so a caller naming an entry would be
    naming one it could not have read.

    Raises rather than half-succeeding. An application with no earlier entry
    raises before anything is touched; a platform that refuses the rollback
    raises after sync was suspended, and that is deliberate - the suspension is
    recorded nowhere yet, so leaving it in place and saying so is honest where
    quietly restoring it would hide a state somebody has to know about.
    """
    state = _the_application(application, settings, get)
    history = state.get(_STATUS, {}).get(_HISTORY, [])

    if len(history) < 2:
        raise NoEarlierRevision(
            f"[{application}] has no revision before the one it is running, so "
            f"there is nothing to roll back to"
        )

    running, previous = history[-1], history[-2]
    was_syncing_itself = _is_reconciling_itself(state)

    if was_syncing_itself:
        _stop_reconciling(application, settings, put)

    _ask_for_the_rollback(application, previous[_HISTORY_ID], settings, post)

    return ConfigRollbackUndo(
        application=application,
        was_on_history_id=running[_HISTORY_ID],
        was_on_revision=running[_REVISION],
        was_syncing_itself=was_syncing_itself
    )


def restore_configuration(descriptor: ConfigRollbackUndo,
                          settings: RollbackSettings,
                          post: HttpPost = httpx.post,
                          put: HttpPut = httpx.put) -> ConfigurationRestored:
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
    revision = _tried(
        lambda: _ask_for_the_rollback(
            descriptor.application, descriptor.was_on_history_id, settings, post
        )
    )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return ConfigurationRestored(revision=revision, automated_sync=True)

    return ConfigurationRestored(
        revision=revision,
        automated_sync=_tried(
            lambda: _start_reconciling(descriptor.application, settings, put)
        )
    )


def _tried(call: Callable[[], None]) -> bool:
    try:
        call()
    except Exception:
        return False

    return True


def _the_application(application: str,
                     settings: RollbackSettings,
                     get: HttpGet) -> dict[str, Any]:
    url = f"{settings.argocd_base_url}" + settings.argocd_application_path.format(
        application=application
    )

    try:
        response = get(
            url,
            headers=_headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        state: dict[str, Any] = response.json()
    except Exception as error:
        raise RollbackRefused(
            f"could not read [{application}] from [{url}]: {error}"
        ) from error

    return state


def _is_reconciling_itself(state: dict[str, Any]) -> bool:
    """Whether the platform syncs this application on its own.

    Argo CD spells it as the *presence* of an `automated` object rather than
    as a boolean, so this is a lookup for a key and not a truthiness test - an
    `automated` of `{}` means automated, and reading it as false would leave a
    rollback to be refused by a server this had just called compliant.
    """
    policy = state.get(_SPEC, {}).get(_SYNC_POLICY, {})

    return policy.get(_AUTOMATED) is not None


def _stop_reconciling(application: str,
                      settings: RollbackSettings,
                      put: HttpPut) -> None:
    _set_sync_policy(application, {}, settings, put)


def _start_reconciling(application: str,
                       settings: RollbackSettings,
                       put: HttpPut) -> None:
    _set_sync_policy(application, {_AUTOMATED: {}}, settings, put)


def _set_sync_policy(application: str,
                     policy: dict[str, Any],
                     settings: RollbackSettings,
                     put: HttpPut) -> None:
    url = f"{settings.argocd_base_url}" + settings.argocd_spec_path.format(
        application=application
    )

    try:
        response = put(
            url,
            json={_SYNC_POLICY: policy},
            headers=_headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise RollbackRefused(
            f"could not change the sync policy of [{application}] at [{url}]: "
            f"{error}"
        ) from error


def _ask_for_the_rollback(application: str,
                          to_history_id: int,
                          settings: RollbackSettings,
                          post: HttpPost) -> None:
    url = f"{settings.argocd_base_url}" + settings.argocd_rollback_path.format(
        application=application
    )

    try:
        response = post(
            url,
            json={"name": application, "id": to_history_id},
            headers=_headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise RollbackRefused(
            f"[{application}] could not be rolled back to history entry "
            f"[{to_history_id}] at [{url}]: {error}"
        ) from error


def _headers_for(auth_token: str) -> dict[str, str]:
    """No token means no header at all, as the other Argo CD adapters do."""
    return {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
