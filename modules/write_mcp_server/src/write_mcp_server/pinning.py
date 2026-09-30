"""Holding a deployment's autoscaler still through the platform (spec §7.3, §12.1,
§13).

The write tier's fifth action, and the first that *stops* something rather than
adding or restoring something. It stops it by raising a floor: the controller is
left running, with nowhere left to scale down to. Nothing is removed, nothing is
deleted, and the ceiling a human declared is never moved - which is what keeps
this reversible, and what makes the thing to put back one number.

Not a resource action, which is what separates it from the scale-out beside it.
Argo CD registers Lua for `scale` on `apps/Deployment` and registers nothing for
an autoscaler, so a floor is written by patching the resource itself: `GET` on
`/resource` is `GetResource` and `POST` on the same route is `PatchResource`. So
this tier learns one more verb on a route it already reads rather than a second
platform.

Where the autoscaler is is discovered rather than configured, which is the other
thing that separates this from the restart and the scale-out. Both of those are
told a namespace, because both address a resource whose name the caller already
knows. An autoscaler's is not knowable that way - it is named by whoever wrote the
chart, and it need not be named after the deployment it scales - and the platform
already publishes the answer: the resource tree names every resource an
application has, with its kind, its own name and its namespace. So a pin asks
where to write rather than being told, and a namespace held in configuration is
one fewer copy of a fact the cluster owns.

The bounds are the platform's to tell and this module's to read. The repository
says what the autoscaler is asked to converge on and the platform says what it is
running, and those are different numbers the moment anybody pins - so the floor to
replace and the ceiling to raise it to are both read from the live resource.
Nothing above the port could have named either honestly.

Four requests rather than one, which is the scale-out's three plus the question of
where to send them. The tree is read for the autoscaler's address. The resource
itself is read for its bounds. The application is read for whether the platform is
reconciling it, which is then suspended - Argo CD re-applies an autoscaler's whole
manifest at its next sync, floor included, so a pin taken under automated sync is a
mitigation with a timer on it and a service that returns to flapping at a moment
nothing in the record explains. Only then is the patch sent.

Which is also why this mitigates without resolving, and why the descriptor it
returns records two things. The repository still declares the floor the controller
was thrashing between, and reconciliation is off so that nothing re-applies it.
Both have to be put back by a withdrawal, and only this module ever knew either.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import httpx
from argus_core import SettingsSlice
from argus_core.mcp_transport import an_exhausted_action, an_unreachable_platform
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    AutoscalerUndo,
    AutoscalingRestored,
)

from write_mcp_server.argocd import (
    REQUEST_TIMEOUT_SECONDS,
    a_sync_policy,
    could_not_be_reached,
    headers_for,
    is_reconciling_itself,
    the_url_of,
)
from write_mcp_server.scaling import THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR

# How the platform addresses an autoscaler, in Kubernetes' own vocabulary. The
# three together are how Argo CD finds one resource among an application's many,
# and a deployment whose size a controller decides has two worth asking about - so
# a read that named no kind would be answered with the Deployment, whose manifest
# has no floor in it at all.
AUTOSCALER_GROUP: Final = "autoscaling"
AUTOSCALER_VERSION: Final = "v2"
AUTOSCALER_KIND: Final = "HorizontalPodAutoscaler"

# What kind of patch this is, in the vendor's own spelling. A merge patch, because
# the body names one field and leaves the rest of the manifest alone; the
# alternatives replace or re-order what they do not mention.
#
# The `+` in it is the documented trap on this endpoint, and the reason the type
# travels in `params` rather than in a url assembled here: httpx percent-encodes a
# query value, where a hand-built query string carries the `+` through to a server
# that reads it as a space and refuses a patch type it has never heard of. Anybody
# tempted to format this into the url is undoing that.
MERGE_PATCH_TYPE: Final = "application/merge-patch+json"

# Where in the manifest the two bounds live, and the one of them a pin writes.
_SPEC: Final = "spec"
_MIN_REPLICAS: Final = "minReplicas"
_MAX_REPLICAS: Final = "maxReplicas"
_MANIFEST: Final = "manifest"

# What the resource tree calls its contents, and the two fields of a node that say
# which resource it is. `name` is the resource's own, which is not the
# application's: an autoscaler is named by whoever wrote the chart.
_NODES: Final = "nodes"
_NAME: Final = "name"

# The selectors the two requests are addressed by, spelled as the platform spells
# them. `resourceName` rather than `name`, which is the field a real Argo CD reads
# and the one its own swagger declares.
_RESOURCE_NAME: Final = "resourceName"
_NAMESPACE: Final = "namespace"
_GROUP: Final = "group"
_VERSION: Final = "version"
_KIND: Final = "kind"
_PATCH_TYPE: Final = "patchType"


class PinSettings(SettingsSlice):
    """Where a pin is asked for, and under what credential.

    Four paths and no namespace, which is what asking the tree buys. The restart
    and the scale-out each carry one because each addresses a resource the caller
    can already name; this addresses one only the platform can name, so the
    address is read rather than configured and there is no setting here to drift
    from the cluster.

    `argocd_resource_path` is read for the bounds and written for the floor, which
    is Argo CD's own arrangement rather than a shortcut - a second setting holding
    the same value would be a second place to correct when a deployment moves.
    `argocd_resource_tree_path` is the route the restart already reads for the pod
    it is waiting on, and is one setting for the same reason.
    """

    argocd_base_url: str
    argocd_application_path: str
    # What the application is made of, which is where an autoscaler's own name and
    # namespace are published.
    argocd_resource_tree_path: str
    # Where the platform says what is actually *running*, which is the only place
    # the bounds in force can be read. The values file says what git asks for.
    argocd_resource_path: str
    argocd_spec_path: str
    argocd_auth_token: str


@dataclass(frozen=True)
class _TheAutoscaler:
    """Which resource a pin is about, as the platform's tree named it.

    Two fields rather than the node itself, because these are the two the other
    requests are addressed by and the rest of a node is the tree's business. Kept
    together rather than passed as a pair of strings: they are one answer to one
    question, and a caller that could swap them would address a namespace by a
    resource's name.
    """

    name: str
    namespace: str


HttpGet = Callable[..., httpx.Response]
HttpPost = Callable[..., httpx.Response]
HttpPut = Callable[..., httpx.Response]


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


def _refusing(said: str, error: Exception,
              left_behind: AutoscalerUndo | None = None) -> PinRefused:
    """This module's refusal, marked where the platform was never reached.

    The mark is what lets a caller tell four actions being unavailable from this
    pin being rejected, without reading the words of either. It is applied here
    rather than in `argocd` for the reason that module holds no exception policy:
    what a response means is the platform's vocabulary, and what to raise about
    it is the action's own.

    `left_behind` is what the failure cost, where it cost anything. Where the
    suspension landed and the floor did not move, that suspension travels on the
    failure - so a caller can narrow itself to a reachable platform and still
    know an application is sitting un-reconciled. Withholding the mark instead
    would have meant this mode was handled only when the platform failed on the
    first call.
    """
    if could_not_be_reached(error):
        return PinRefused(
            an_unreachable_platform(DEPLOYMENT_PLATFORM, said, left_behind)
        )

    return PinRefused(said)


def pin_autoscaler(application: str,
                   settings: PinSettings,
                   get: HttpGet = httpx.get,
                   post: HttpPost = httpx.post,
                   put: HttpPut = httpx.put) -> AutoscalerUndo:
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
    autoscaler = _where_the_autoscaler_is(application, settings, get)
    floor, ceiling = _the_bounds_in_force(autoscaler, application, settings, get)
    the_floor_to_ask_for = min(ceiling, THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR)

    if the_floor_to_ask_for <= floor:
        raise AlreadyHeldStill(
            an_exhausted_action(
                f"[{application}]'s autoscaler may fall to [{floor}] replicas and "
                f"rise to [{ceiling}], and the highest floor Argus may ask for is "
                f"[{the_floor_to_ask_for}] - so there is no room left between the "
                f"two and nothing here for a pin to stop"
            )
        )

    was_syncing_itself = is_reconciling_itself(
        _the_application(application, settings, get)
    )

    if was_syncing_itself:
        _set_sync_policy(application, reconciling=False, settings=settings, put=put)

    # Built before the action rather than after it, because it describes what
    # has already been changed: where sync was suspended, this is what a caller
    # has to put back whether the floor then moves or the platform vanishes.
    undo = AutoscalerUndo(
        application=application,
        was_min_replicas=floor,
        min_replicas_asked_for=the_floor_to_ask_for,
        was_syncing_itself=was_syncing_itself
    )

    _ask_for_a_floor_of(
        autoscaler,
        application,
        the_floor_to_ask_for,
        settings,
        post,
        left_behind=undo if was_syncing_itself else None
    )

    return undo


def restore_autoscaler_floor(descriptor: AutoscalerUndo,
                             settings: PinSettings,
                             get: HttpGet = httpx.get,
                             post: HttpPost = httpx.post,
                             put: HttpPut = httpx.put) -> AutoscalingRestored:
    """Puts back both of the things a pin changed, and says which it managed.

    A pair rather than an exception, for the reason the scale-out's restore answers
    one: a restore can half-succeed and the half that fails is the quiet one. The
    caller turns the pair into a verdict; this reports facts.

    The floor first and reconciliation second, which is the order that leaves
    nothing to chance. Re-enabling sync first would have the platform re-apply the
    autoscaler's manifest on its own - to the same floor, and unverifiably, at a
    moment nothing here chose.

    Reads where the autoscaler is again rather than remembering it, which is why
    this takes a `get` where the scale-out's restore does not. The descriptor
    records what was changed and not where the resource lived, deliberately: a
    withdrawal can arrive hours later, and where a resource lives is the platform's
    to answer at the moment it is asked rather than a fact worth keeping a stale
    copy of.
    """
    floor = _tried(
        lambda: _ask_for_a_floor_of(
            _where_the_autoscaler_is(descriptor.application, settings, get),
            descriptor.application,
            descriptor.was_min_replicas,
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
        return AutoscalingRestored(
            floor_put_back=floor, automated_sync_put_back=True
        )

    return AutoscalingRestored(
        floor_put_back=floor,
        automated_sync_put_back=_tried(
            lambda: _set_sync_policy(
                descriptor.application, reconciling=True, settings=settings, put=put
            )
        )
    )


def _tried(call: Callable[[], None]) -> bool:
    try:
        call()
    except Exception:
        return False

    return True


def _where_the_autoscaler_is(application: str,
                             settings: PinSettings,
                             get: HttpGet) -> _TheAutoscaler:
    """The autoscaler's own name and namespace, as the platform's tree reports
    them.

    Matched on kind alone. A node's group and version are how the tree describes
    the resource and not what distinguishes one of an application's resources from
    another - an application has one horizontal pod autoscaler or none - and matching
    on a version would refuse a cluster serving `v2beta2` for a reason that has
    nothing to do with whether it can be pinned.

    Refused where the tree names none, which is the one thing a caller reading
    this cannot check for itself: a pin performed against a controller that does
    not exist would be reported as done and then confirmed against a world that
    does not exist either.
    """
    tree = _read(
        the_url_of(settings.argocd_base_url, settings.argocd_resource_tree_path,
                   application),
        settings,
        get,
        f"could not read what [{application}] is made of"
    )
    listed = [
        node for node in tree.get(_NODES, [])
        if node.get(_KIND) == AUTOSCALER_KIND
    ]

    if not listed:
        raise PinRefused(
            f"[{application}] has no {AUTOSCALER_KIND} among its resources, so "
            f"there is no autoscaler here to hold still"
        )

    return _TheAutoscaler(
        name=str(listed[0][_NAME]), namespace=str(listed[0][_NAMESPACE])
    )


def _the_bounds_in_force(autoscaler: _TheAutoscaler,
                         application: str,
                         settings: PinSettings,
                         get: HttpGet) -> tuple[int, int]:
    """The floor the controller may fall to and the ceiling it may rise to.

    Read from the live resource and not from the repository, which is the whole
    reason this request exists: after one pin the two disagree, and the floor a
    withdrawal has to put back is the one that was in force.

    The manifest arrives as *text*, which is Argo CD's own shape for it - the
    resource is passed through for the caller to parse - so this parses it and
    refuses a manifest missing either bound rather than assuming one. A guessed
    ceiling would hold a shop at a size nobody declared.
    """
    resource = _read(
        the_url_of(settings.argocd_base_url, settings.argocd_resource_path,
                   application),
        settings,
        get,
        f"could not read [{application}]'s autoscaler",
        params=_the_autoscaler_addressed_as(autoscaler)
    )

    try:
        manifest = json.loads(resource[_MANIFEST])
        floor = int(manifest[_SPEC][_MIN_REPLICAS])
        ceiling = int(manifest[_SPEC][_MAX_REPLICAS])
    except Exception as error:
        raise PinRefused(
            f"[{application}]'s autoscaler manifest does not say what its floor "
            f"and ceiling are: {error}"
        ) from error

    return floor, ceiling


def _the_application(application: str,
                     settings: PinSettings,
                     get: HttpGet) -> dict[str, Any]:
    return _read(
        the_url_of(settings.argocd_base_url, settings.argocd_application_path,
                   application),
        settings,
        get,
        f"could not read [{application}]"
    )


def _read(url: str,
          settings: PinSettings,
          get: HttpGet,
          what_failed: str,
          params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = get(
            url,
            params=params,
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
                     settings: PinSettings,
                     put: HttpPut) -> None:
    url = the_url_of(
        settings.argocd_base_url, settings.argocd_spec_path, application
    )

    try:
        response = put(
            url,
            json=a_sync_policy(reconciling),
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


def _ask_for_a_floor_of(autoscaler: _TheAutoscaler,
                        application: str,
                        replicas: int,
                        settings: PinSettings,
                        post: HttpPost,
                        *,
                        left_behind: AutoscalerUndo | None) -> None:
    url = the_url_of(
        settings.argocd_base_url, settings.argocd_resource_path, application
    )

    try:
        response = post(
            url,
            params={
                **_the_autoscaler_addressed_as(autoscaler),
                _PATCH_TYPE: MERGE_PATCH_TYPE
            },
            json=_a_floor_of(replicas),
            headers=headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise _refusing(
            f"[{application}]'s autoscaler floor could not be raised to "
            f"[{replicas}] at [{url}]: {error}",
            error,
            left_behind
        ) from error


def _the_autoscaler_addressed_as(autoscaler: _TheAutoscaler) -> dict[str, Any]:
    """Which resource of the application both requests are about.

    One spelling for the read and the write, because it is one resource: a read
    addressed at the autoscaler and a patch addressed at anything else would be a
    module that reported one thing and changed another.

    The name and the namespace are the tree's; the group, version and kind are
    this module's, because they are what was asked for rather than what was found.
    """
    return {
        _RESOURCE_NAME: autoscaler.name,
        _NAMESPACE: autoscaler.namespace,
        _GROUP: AUTOSCALER_GROUP,
        _VERSION: AUTOSCALER_VERSION,
        _KIND: AUTOSCALER_KIND
    }


def _a_floor_of(replicas: int) -> str:
    """The patch that raises the floor, as the platform carries a patch.

    A JSON-encoded *string* rather than an object, which is the vendor's own shape
    for this body - it is declared `string` in Argo CD's swagger - and the mirror
    of the manifest arriving as text from the same route. Encoding it here rather
    than taking a string from the caller keeps the wire's shape at the wire.

    One field, because a merge patch says only what changes. A body carrying the
    ceiling as well would re-assert a human's declaration as though Argus had
    decided it.
    """
    return json.dumps({_SPEC: {_MIN_REPLICAS: replicas}})
