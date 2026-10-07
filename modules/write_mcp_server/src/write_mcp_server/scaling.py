"""Making a deployment larger through the platform (spec §7.3, §12.1, §13).

The write tier's fourth action, and the only one that adds something rather than
restoring something. Everything above the port sees an application name going in
and a record of what changed coming back.

Shaped like Argo CD's own scaling, which is not an endpoint of its own: `scale` is
a built-in resource action for `apps/Deployment`, run through `POST
/api/v1/applications/{application}/resource/actions/v2` with a `replicas`
parameter - the same route the restart goes through. So this tier learns one more
action name and one parameter rather than a second platform, where patching
Kubernetes' own scale subresource would have put a Kubernetes client in a tier
that has needed only Argo CD.

The count is the platform's to tell and this module's to derive. The repository
says what the deployment is asked to converge on and the platform says what it is
running, and those are different numbers the moment anybody scales - so the count
to replace is read from the live resource, doubled, and bounded by a ceiling this
tier holds. Nothing above the port could have named it honestly: a target is
meaningless without the count it replaces, and an agent asserting one would be
asserting a fact no evidence in front of it carries.

Three requests rather than one, because the platform's own rules make it three.
The live Deployment is read for the count. The application is read for whether the
platform is reconciling it, which is then suspended - Argo CD puts a live replica
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

import json
from collections.abc import Callable
from typing import Any, Final

import httpx2
from argus_core import SettingsSlice
from argus_core.mcp_transport import an_exhausted_action, an_unreachable_platform
from argus_core.models import DEPLOYMENT_PLATFORM, CapacityRestored, ReplicaUndo

from write_mcp_server.argocd import (
    REQUEST_TIMEOUT_SECONDS,
    a_sync_patch,
    could_not_be_reached,
    headers_for,
    is_reconciling_itself,
    the_url_of,
)

# The action, by the name Argo CD registers it under, and what it reads its count
# from. The vendor's own words, and the parameter's value is a *string* on the
# wire - every resource-action parameter is, and the action's own Lua is what makes
# a number of it.
SCALE_ACTION: Final = "scale"
REPLICAS_PARAMETER: Final = "replicas"

# What the action is run against, for the reason the restart names its own: Argo CD
# dispatches its Lua by group and kind, and the built-in `scale` is registered for
# `apps/Deployment`.
SCALE_GROUP: Final = "apps"
SCALE_KIND: Final = "Deployment"

# Where in a manifest the count lives.
_SPEC: Final = "spec"
_REPLICAS: Final = "replicas"
_MANIFEST: Final = "manifest"

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


class ScaleSettings(SettingsSlice):
    """Where a scale-out is asked for, and under what credential.

    Three paths, because the operation is four requests against three of the
    platform's routes - the application is read and patched on one - and the
    undo uses two of them. Templates rather than fixed
    routes, for the reason every other Argo CD path here is one: the demo's
    stand-in and a real server are one setting with two values.

    `argocd_resource_action_path` is the route the restart also uses, and it is one
    setting rather than two because it is one endpoint: `restart` and `scale` are
    both built-in resource actions, and a second setting holding the same value
    would be a second place to correct when a deployment moves.
    """

    argocd_base_url: str
    argocd_application_path: str
    # Where the platform says what is actually *running*, which is the only place
    # the count to replace can be read. The values file says what git asks for.
    argocd_resource_path: str
    argocd_resource_action_path: str
    argocd_auth_token: str
    scale_namespace: str


HttpGet = Callable[..., httpx2.Response]
HttpPost = Callable[..., httpx2.Response]
HttpPatch = Callable[..., httpx2.Response]


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


def _refusing(said: str, error: Exception,
              left_behind: ReplicaUndo | None = None) -> ScaleRefused:
    """This module's refusal, marked where the platform was never reached.

    The mark is what lets a caller tell four actions being unavailable from this
    scale-out being rejected, without reading the words of either. It is applied
    here rather than in `argocd` for the reason that module holds no exception
    policy: what a response means is the platform's vocabulary, and what to raise
    about it is the action's own.

    `left_behind` is what the failure cost, where it cost anything. This is the
    action most likely to lose the platform part-way - it reads, suspends, and
    only then acts - so withholding the mark on a failure after the suspension
    would have meant handling this mode only when the platform happened to fail
    on the first call. Saying what was left behind lets the caller narrow itself
    and still know a deployment is sitting un-reconciled.
    """
    if could_not_be_reached(error):
        return ScaleRefused(
            an_unreachable_platform(DEPLOYMENT_PLATFORM, said, left_behind)
        )

    return ScaleRefused(said)


def scale_out(application: str,
              settings: ScaleSettings,
              get: HttpGet = httpx2.get,
              post: HttpPost = httpx2.post,
              patch: HttpPatch = httpx2.patch) -> ReplicaUndo:
    """Doubles what `application` is running, and reports what that cost.

    Doubling rather than a figure somebody chose: what a saturated deployment
    needs is more capacity than it has, and the multiple of its current size is
    the only expression of that which does not need to know what the traffic is
    doing. Bounded by the ceiling above, which it reaches rather than exceeds.

    Raises rather than half-succeeding. A deployment already at the ceiling raises
    before anything is touched; a platform that refuses the action raises after
    sync was suspended, and that is deliberate for the reason the rollback's is -
    the suspension is recorded nowhere yet, so leaving it in place and saying so is
    honest where quietly restoring it would hide a state somebody has to know
    about.
    """
    running = _the_count_running(application, settings, get)

    if running >= THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR:
        raise AlreadyAtItsLargest(
            an_exhausted_action(
                f"[{application}] is running [{running}] replicas, which is as "
                f"large as Argus may make it "
                f"([{THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR}])"
            )
        )

    was_syncing_itself = is_reconciling_itself(
        _the_application(application, settings, get)
    )

    if was_syncing_itself:
        _set_sync_policy(application, reconciling=False, settings=settings, patch=patch)

    # Built before the action rather than after it, because it describes what
    # has already been changed: where sync was suspended, this is what a caller
    # has to put back whether the count then moves or the platform vanishes.
    undo = ReplicaUndo(
        application=application,
        was_replicas=running,
        was_syncing_itself=was_syncing_itself
    )

    _ask_for(
        application,
        _twice(running),
        settings,
        post,
        left_behind=undo if was_syncing_itself else None
    )

    return undo


def restore_replica_count(descriptor: ReplicaUndo,
                          settings: ScaleSettings,
                          post: HttpPost = httpx2.post,
                          patch: HttpPatch = httpx2.patch) -> CapacityRestored:
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
    count = _tried(
        lambda: _ask_for(
            descriptor.application,
            descriptor.was_replicas,
            settings,
            post,
            # Nothing reads the refusal on this path - `_tried` turns it into a
            # `False` the caller reports - and a descriptor here would describe
            # putting back a change this call is itself the putting back of.
            left_behind=None
        )
    )

    if not descriptor.was_syncing_itself:
        # It was already off when Argus found it, so leaving it off *is* the
        # restore. Turning it on because that is the usual arrangement would be
        # Argus starting something it did not stop.
        return CapacityRestored(count_put_back=count, automated_sync_put_back=True)

    return CapacityRestored(
        count_put_back=count,
        automated_sync_put_back=_tried(
            lambda: _set_sync_policy(
                descriptor.application, reconciling=True, settings=settings, patch=patch
            )
        )
    )


def _twice(replicas: int) -> int:
    """Double the count, up to the ceiling and never past it."""
    return min(replicas * 2, THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR)


def _tried(call: Callable[[], None]) -> bool:
    try:
        call()
    except Exception:
        return False

    return True


def _the_count_running(application: str,
                       settings: ScaleSettings,
                       get: HttpGet) -> int:
    """How many replicas the platform says are serving.

    Read from the live resource and not from the repository, which is the whole
    reason this request exists: after one scale-out the two disagree, and the
    number a doubling has to start from is the one in force.

    The manifest arrives as *text*, which is Argo CD's own shape for it - the
    resource is passed through for the caller to parse - so this parses it and
    refuses a manifest with no count rather than assuming one. A guess of one
    would halve a shop serving three.
    """
    resource = _read(
        the_url_of(settings.argocd_base_url, settings.argocd_resource_path,
                   application),
        settings,
        get,
        f"could not read what [{application}] is running"
    )

    try:
        manifest = json.loads(resource[_MANIFEST])
        replicas = manifest[_SPEC][_REPLICAS]
    except Exception as error:
        raise ScaleRefused(
            f"[{application}]'s manifest does not say how many replicas it is "
            f"running: {error}"
        ) from error

    return int(replicas)


def _the_application(application: str,
                     settings: ScaleSettings,
                     get: HttpGet) -> dict[str, Any]:
    return _read(
        the_url_of(settings.argocd_base_url, settings.argocd_application_path,
                   application),
        settings,
        get,
        f"could not read [{application}]"
    )


def _read(url: str,
          settings: ScaleSettings,
          get: HttpGet,
          what_failed: str) -> dict[str, Any]:
    try:
        response = get(
            url,
            headers=headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
    except Exception as error:
        raise _refusing(f"{what_failed} from [{url}]: {error}", error) from error

    return body


def _set_sync_policy(application: str,
                     reconciling: bool,
                     settings: ScaleSettings,
                     patch: HttpPatch) -> None:
    url = the_url_of(
        settings.argocd_base_url, settings.argocd_application_path, application
    )

    try:
        response = patch(
            url,
            json=a_sync_patch(application, reconciling),
            headers=headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise _refusing(
            f"could not change the sync policy of [{application}] at [{url}]: "
            f"{error}",
            error
        ) from error


def _ask_for(application: str,
             replicas: int,
             settings: ScaleSettings,
             post: HttpPost,
             *,
             left_behind: ReplicaUndo | None) -> None:
    url = the_url_of(
        settings.argocd_base_url, settings.argocd_resource_action_path, application
    )

    try:
        response = post(
            url,
            json=_the_scale_action(settings, application, replicas),
            headers=headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise _refusing(
            f"[{application}] could not be scaled to [{replicas}] replicas at "
            f"[{url}]: {error}",
            error,
            left_behind
        ) from error


def _the_scale_action(settings: ScaleSettings,
                      application: str,
                      replicas: int) -> dict[str, Any]:
    """The body the resource-action endpoint takes, as the restart's is built.

    The resource is addressed by group, kind, namespace and name because that is
    how the server finds the Lua registered for it, and the count travels in
    `resourceActionParameters` - which is what separates this endpoint from the v1
    it replaced, and the reason a scale can be asked for through it at all.

    The count is spelled as text, because that is how the platform carries every
    action parameter. Stringifying it here rather than taking a string from the
    caller keeps the wire's shape at the wire.
    """
    return {
        "namespace": settings.scale_namespace,
        "resourceName": application,
        "group": SCALE_GROUP,
        "kind": SCALE_KIND,
        "action": SCALE_ACTION,
        "resourceActionParameters": [
            {"name": REPLICAS_PARAMETER, "value": str(replicas)}
        ]
    }
