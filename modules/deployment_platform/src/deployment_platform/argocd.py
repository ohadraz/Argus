"""The deployment platform, as an Argo CD server answers for it.

The only place in Argus that knows Argo CD's wire shape: its routes, the selectors
a managed resource is addressed by, the bodies its actions and patches take, and
where in each answer the fact asked about lives. Everything above the port asks
for what it wants and gets Argus's own values back.

One client, built once, carries what every request shares - where the server is,
the credential, and how long to wait - so none of the three can be forgotten on a
request or spelled differently on two. The routes are templates, because the
demo's stand-in and a real server are one set of settings with two sets of values.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Any, Final

import httpx2
from argus_core import SettingsSlice
from argus_core.models import RolloutProgress

from deployment_platform.failures import PlatformRefused, PlatformUnreachable
from deployment_platform.port import Autoscaler, AutoscalerBounds, DeploymentRecord

# Argo CD's own wire vocabulary for an application's sync policy. Named once rather
# than spelled at each lookup: they are another project's field names, and a typo in
# one is a silent `None` rather than an error.
SPEC: Final = "spec"
SYNC_POLICY: Final = "syncPolicy"
AUTOMATED: Final = "automated"
# The switch Argo CD 3.1 put inside `automated`, so that automated sync can be
# turned off while what it was configured to do - `prune`, `selfHeal` - is kept.
# Absent means on.
ENABLED: Final = "enabled"

# The fields of `ApplicationPatchRequest`, the body of
# `PATCH /api/v1/applications/{name}` (bound with `body: "*"`). The patch itself
# travels as a JSON-encoded string and is applied to the whole application.
PATCH_REQUEST_NAME: Final = "name"
PATCH_REQUEST_PATCH: Final = "patch"
PATCH_REQUEST_TYPE: Final = "patchType"
# That route's name for an RFC 7386 merge patch. Not the resource route's
# `application/merge-patch+json`: the two routes spell the same kind of patch
# differently, and one constant for both would send one of them a type it refuses.
APPLICATION_MERGE_PATCH: Final = "merge"
# The resource route's spelling. The `+` in it is the documented trap on that
# route, and the reason the type travels in `params` rather than in a url
# assembled here: httpx2 percent-encodes a query value, where a hand-built query
# string carries the `+` through to a server that reads it as a space and refuses
# a patch type it has never heard of.
RESOURCE_MERGE_PATCH: Final = "application/merge-patch+json"

# An application's recorded deployments.
_STATUS: Final = "status"
_HISTORY: Final = "history"
_HISTORY_ID: Final = "id"
_REVISION: Final = "revision"
# Argo CD always sets `deployedAt`; `deployStartedAt` is a pointer in its own type
# and may be absent. A deploy is "at" the moment it landed.
_DEPLOYED_AT: Final = "deployedAt"
_SOURCE: Final = "source"
_REPO_URL: Final = "repoURL"
_PATH: Final = "path"
_INITIATED_BY: Final = "initiatedBy"
_USERNAME: Final = "username"

# The resource route's wrapper: the manifest arrives as *text*, and the caller
# parses it.
_MANIFEST: Final = "manifest"

# Kubernetes' vocabulary for the parts of a Deployment and an autoscaler read here.
_REPLICAS: Final = "replicas"
_UPDATED_REPLICAS: Final = "updatedReplicas"
_PAUSED: Final = "paused"
_MIN_REPLICAS: Final = "minReplicas"
_MAX_REPLICAS: Final = "maxReplicas"
# A Deployment's `status.conditions`, where the platform says it cannot finish.
# Read by type and status only: the reason is an explanation for a person.
_CONDITIONS: Final = "conditions"
_CONDITION_TYPE: Final = "type"
_CONDITION_STATUS: Final = "status"
_CONDITION_TRUE: Final = "True"
_CONDITION_FALSE: Final = "False"
# Pods the ReplicaSet could not create - a quota, most often - reported at once.
_REPLICA_FAILURE: Final = "ReplicaFailure"
# At `False` once the Deployment has made no progress within the deadline it
# declares. Never `False` while paused: the platform reports `Unknown` then.
_PROGRESSING: Final = "Progressing"

# The resource tree.
_NODES: Final = "nodes"
_KIND: Final = "kind"
_NAME: Final = "name"
_NAMESPACE: Final = "namespace"
_CREATED_AT: Final = "createdAt"
# What a process is, in the tree. Everything else it reports - the Deployment, the
# ReplicaSet, the Service - was created when somebody declared it.
POD_KIND: Final = "Pod"

# The built-in resource actions, by the names Argo CD registers them under, and
# what they are run against: Argo CD dispatches its Lua by group and kind, and both
# are written for `apps/Deployment`.
RESTART_ACTION: Final = "restart"
SCALE_ACTION: Final = "scale"
REPLICAS_PARAMETER: Final = "replicas"
DEPLOYMENT_GROUP: Final = "apps"
DEPLOYMENT_KIND: Final = "Deployment"

# What an autoscaler is, for addressing it on the resource route. The name and the
# namespace are the tree's; these are what was asked for rather than what was found.
AUTOSCALER_GROUP: Final = "autoscaling"
AUTOSCALER_VERSION: Final = "v2"
AUTOSCALER_KIND: Final = "HorizontalPodAutoscaler"

REQUEST_TIMEOUT_SECONDS: Final = 10.0

# The lowest status a server uses to say the failure is its own rather than the
# request's. Below it the platform has read what was asked and rejected it, which
# is the platform working.
_THE_SERVERS_OWN_FAULT: Final = 500


class ArgoCdSettings(SettingsSlice):
    """Where the Argo CD server is, under what credential, and its routes.

    One slice for every request, where there used to be one per action each
    redeclaring the server and the credential. The routes are templates over the
    application, so the demo's stand-in and a real server's
    `/api/v1/applications/{application}` are one setting with two values.

    The token may be empty, which sends no credential at all: the stand-in needs
    none, and a placeholder would send a real server something meaningless to
    reject.

    The two namespaces are the restart's and the scale-out's, each addressing the
    Deployment its action is run against. The autoscaler has none, because its
    address is read from the tree rather than configured.
    """

    argocd_base_url: str
    argocd_auth_token: str
    argocd_application_path: str
    # Where the platform says what is actually *running*, and where an autoscaler
    # is patched. The values file says what git asks for.
    argocd_resource_path: str
    argocd_resource_action_path: str
    argocd_rollback_path: str
    # What an application is made of: its pods, and its autoscaler's own name.
    argocd_resource_tree_path: str
    restart_namespace: str
    scale_namespace: str


class ArgoCd:
    """Both deployment-platform ports, answered by one Argo CD server.

    A class because everything here shares one configured client, and every
    request is a method on it. `transport` is where a test puts the platform; left
    out, requests go over the network.
    """

    def __init__(self,
                 settings: ArgoCdSettings,
                 transport: httpx2.BaseTransport | None = None) -> None:
        self._settings = settings
        self._client = httpx2.Client(
            base_url=settings.argocd_base_url,
            headers=_headers_for(settings.argocd_auth_token),
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport
        )

    def deployments_of(self, application: str, /) -> list[DeploymentRecord]:
        """Every deployment recorded, in the order the platform serves them.

        `history` is `omitempty` in Argo CD's own type, so an application that has
        never deployed has no such key - an ordinary answer, not a malformed one.
        """
        state = self._get(self._settings.argocd_application_path, application)
        history = state.get(_STATUS, {}).get(_HISTORY, [])

        return [
            _parsed(partial(_a_record_of, entry), f"[{application}]'s deployment history")
            for entry in history
        ]

    def rollout_of(self, application: str, /) -> RolloutProgress:
        """How far the running Deployment has got, read from the live resource.

        No selectors: there is one Deployment behind the application, and a
        selector configured here would be a second place to correct when it moves.

        A manifest carrying no rollout status reads as converged, and that is a
        decision rather than a fallback: nothing in it says any replica is lagging.
        A manifest that does not say how many replicas it was asked for is refused,
        because a guessed count is how a rollout nobody can read becomes one
        reported as converged.
        """
        manifest = self._manifest(application, None)

        def progress() -> RolloutProgress:
            wanted = int(manifest[SPEC][_REPLICAS])
            status = manifest.get(_STATUS, {})

            return RolloutProgress(
                replicas_wanted=wanted,
                replicas_serving=int(status.get(_REPLICAS, wanted)),
                replicas_updated=int(status.get(_UPDATED_REPLICAS, wanted)),
                is_paused=bool(manifest[SPEC].get(_PAUSED)),
                has_failed=_cannot_finish(status)
            )

        return _parsed(progress, f"[{application}]'s running Deployment")

    def is_syncing_itself(self, application: str, /) -> bool:
        """Read exactly as Argo CD's own `SyncPolicy.IsAutomatedSyncEnabled` reads it.

        An `automated` object whose `enabled` is absent or true. The presence of
        the object is a lookup for a key and not a truthiness test - an `automated`
        of `{}` means automated, and reading it as false would leave an action to
        be refused by a server this had just called compliant. And
        `enabled: false` means configured and not syncing.
        """
        state = self._get(self._settings.argocd_application_path, application)
        policy = state.get(SPEC, {}).get(SYNC_POLICY) or {}
        automated = policy.get(AUTOMATED)

        return automated is not None and automated.get(ENABLED) is not False

    def suspend_sync(self, application: str, /) -> None:
        self._set_sync(application, reconciling=False)

    def resume_sync(self, application: str, /) -> None:
        self._set_sync(application, reconciling=True)

    def scale(self, application: str, replicas: int, /) -> None:
        """Runs the built-in `scale` action, with the count spelled as text.

        Every resource-action parameter travels as a string, and the action's own
        Lua makes a number of it.
        """
        self._send(
            "POST",
            self._settings.argocd_resource_action_path,
            application,
            body={
                **self._a_deployment_action(
                    SCALE_ACTION, self._settings.scale_namespace, application
                ),
                "resourceActionParameters": [
                    {"name": REPLICAS_PARAMETER, "value": str(replicas)}
                ]
            }
        )

    def roll_back(self, application: str, to_history_id: int, /) -> None:
        self._send(
            "POST",
            self._settings.argocd_rollback_path,
            application,
            body={"name": application, "id": to_history_id}
        )

    def restart(self, service: str, /) -> None:
        """Runs the built-in `restart` action on the service's own Deployment.

        v2 rather than the original, which carries the same fields as query
        parameters and is deprecated since Argo CD 3.1. The name is the service,
        never a configured one: a fixed name carried one deployment into every
        request, and restarted the wrong thing when a dependency was meant.
        """
        self._send(
            "POST",
            self._settings.argocd_resource_action_path,
            service,
            body=self._a_deployment_action(
                RESTART_ACTION, self._settings.restart_namespace, service
            )
        )

    def newest_pod_started_at(self, service: str, /) -> float | None:
        """The newest pod's `createdAt`, as epoch seconds.

        The *newest*, because a rollout has two pods in it for a while and the
        older one is precisely the process a restart has to be told apart from. A
        pod whose creation time cannot be read is passed over: a crash on one
        unparseable timestamp would report an unconfirmable restart as a broken
        one.
        """
        came_up = [
            _when_it_came_up(node.get(_CREATED_AT))
            for node in self._nodes_of(service)
            if node.get(_KIND) == POD_KIND
        ]
        readable = [moment for moment in came_up if moment is not None]

        return max(readable) if readable else None

    def autoscaler_of(self, application: str, /) -> Autoscaler | None:
        """The first autoscaler the tree lists, matched on kind alone.

        An application has one horizontal pod autoscaler or none, and matching on
        a version would refuse a cluster serving `v2beta2` for a reason that has
        nothing to do with whether it can be pinned.
        """
        listed = [
            node for node in self._nodes_of(application)
            if node.get(_KIND) == AUTOSCALER_KIND
        ]

        if not listed:
            return None

        return _parsed(
            lambda: Autoscaler(
                name=str(listed[0][_NAME]), namespace=str(listed[0][_NAMESPACE])
            ),
            f"[{application}]'s autoscaler"
        )

    def autoscaler_bounds(self,
                          application: str,
                          autoscaler: Autoscaler,
                          /) -> AutoscalerBounds:
        manifest = self._manifest(application, _addressing(autoscaler))

        return _parsed(
            lambda: AutoscalerBounds(
                floor=int(manifest[SPEC][_MIN_REPLICAS]),
                ceiling=int(manifest[SPEC][_MAX_REPLICAS])
            ),
            f"[{application}]'s autoscaler bounds"
        )

    def set_autoscaler_floor(self,
                             application: str,
                             autoscaler: Autoscaler,
                             floor: int,
                             /) -> None:
        """A merge patch of the floor alone, as the resource route carries one.

        A JSON-encoded *string* rather than an object - the vendor's own shape for
        this body, and the mirror of the manifest arriving as text from the same
        route. One field, because a merge patch says only what changes: a body
        carrying the ceiling would re-assert a human's declaration as though Argus
        had decided it.
        """
        self._send(
            "POST",
            self._settings.argocd_resource_path,
            application,
            params={**_addressing(autoscaler), PATCH_REQUEST_TYPE: RESOURCE_MERGE_PATCH},
            body=json.dumps({SPEC: {_MIN_REPLICAS: floor}})
        )

    def _set_sync(self, application: str, reconciling: bool) -> None:
        """A merge patch of the switch alone, on the application route.

        Not the spec route: that takes its body as the *whole* spec and replaces
        the application's with it. And not an `automated` object of Argus's own:
        the one the operator declared carries their `prune` and `selfHeal`. Off is
        `enabled: false`; back on is a `null`, which a merge patch reads as removing
        the key and the platform reads as on.
        """
        switch = None if reconciling else False

        self._send(
            "PATCH",
            self._settings.argocd_application_path,
            application,
            body={
                PATCH_REQUEST_NAME: application,
                PATCH_REQUEST_PATCH: json.dumps(
                    {SPEC: {SYNC_POLICY: {AUTOMATED: {ENABLED: switch}}}}
                ),
                PATCH_REQUEST_TYPE: APPLICATION_MERGE_PATCH
            }
        )

    def _a_deployment_action(self,
                             action: str,
                             namespace: str,
                             name: str) -> dict[str, Any]:
        return {
            "namespace": namespace,
            "resourceName": name,
            "group": DEPLOYMENT_GROUP,
            "kind": DEPLOYMENT_KIND,
            "action": action
        }

    def _nodes_of(self, application: str) -> list[dict[str, Any]]:
        tree = self._get(self._settings.argocd_resource_tree_path, application)
        nodes: list[dict[str, Any]] = tree.get(_NODES, [])

        return nodes

    def _manifest(self,
                  application: str,
                  params: dict[str, str] | None) -> dict[str, Any]:
        """A managed resource's live manifest, parsed out of its text wrapper."""
        resource = self._get(self._settings.argocd_resource_path, application, params)

        def manifest() -> dict[str, Any]:
            parsed: dict[str, Any] = json.loads(resource[_MANIFEST])
            return parsed

        return _parsed(manifest, f"[{application}]'s live manifest")

    def _get(self,
             route: str,
             application: str,
             params: dict[str, str] | None = None) -> dict[str, Any]:
        response = self._send("GET", route, application, params=params)

        def body() -> dict[str, Any]:
            parsed: dict[str, Any] = response.json()
            return parsed

        return _parsed(body, f"the answer from [{response.request.url}]")

    def _send(self,
              method: str,
              route: str,
              application: str,
              params: dict[str, str] | None = None,
              body: Any = None) -> httpx2.Response:
        """One request, its failure said as one of the two kinds a caller tells apart.

        A status of the platform's own rather than a list of them: `502` and `503`
        are the same outage seen at different hops, `504` is it seen through a
        proxy that waited, and which arrives is a fact about how the platform is
        fronted.
        """
        path = route.format(application=application)

        try:
            response = self._client.request(method, path, params=params, json=body)
            response.raise_for_status()
        except httpx2.TransportError as error:
            raise PlatformUnreachable(
                f"{method} [{path}] got no answer: {error}"
            ) from error
        except httpx2.HTTPStatusError as error:
            failure = (
                PlatformUnreachable
                if error.response.status_code >= _THE_SERVERS_OWN_FAULT
                else PlatformRefused
            )
            raise failure(
                f"{method} [{path}] was answered "
                f"[{error.response.status_code}]: {error.response.text}"
            ) from error

        return response


def _headers_for(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}"} if auth_token else {}


def _addressing(autoscaler: Autoscaler) -> dict[str, str]:
    """Which of the application's resources a request is about, as selectors.

    One spelling for the read and the write, because it is one resource: a read
    addressed at the autoscaler and a patch addressed at anything else would
    report one thing and change another. `resourceName` rather than `name`, which
    is the field a real Argo CD reads.
    """
    return {
        "resourceName": autoscaler.name,
        _NAMESPACE: autoscaler.namespace,
        "group": AUTOSCALER_GROUP,
        "version": AUTOSCALER_VERSION,
        _KIND: AUTOSCALER_KIND
    }


def _a_record_of(entry: dict[str, Any]) -> DeploymentRecord:
    source = entry.get(_SOURCE) or {}
    initiated_by = entry.get(_INITIATED_BY) or {}

    return DeploymentRecord(
        history_id=int(entry[_HISTORY_ID]),
        revision=str(entry[_REVISION]),
        deployed_at=str(entry[_DEPLOYED_AT]),
        repo_url=source.get(_REPO_URL),
        path=source.get(_PATH),
        initiated_by=initiated_by.get(_USERNAME)
    )


def _cannot_finish(status: dict[str, Any]) -> bool:
    """Whether the Deployment's own conditions say it cannot finish.

    A condition absent reads as nothing having failed, for the reason a status
    absent reads as converged - the platform says when it has a problem.
    """
    stated = {
        condition.get(_CONDITION_TYPE): condition.get(_CONDITION_STATUS)
        for condition in status.get(_CONDITIONS, [])
    }

    return (
        stated.get(_REPLICA_FAILURE) == _CONDITION_TRUE
        or stated.get(_PROGRESSING) == _CONDITION_FALSE
    )


def _when_it_came_up(created_at: str | None) -> float | None:
    """One `createdAt` as seconds since the epoch, or `None` where it is not one.

    Seconds because that is what a restart compares: the reading before and the
    reading after are told apart by differing, and a pair of strings would be
    compared by spelling.
    """
    if created_at is None:
        return None

    try:
        return datetime.fromisoformat(created_at).timestamp()
    except ValueError:
        return None


def _parsed[T](read: Callable[[], T], what: str) -> T:
    """`read()`, with an answer that does not say what was asked refused.

    Refused rather than unreachable: the platform answered. A parse gone wrong
    here read as an outage would pass over every action through a platform that
    is perfectly well.
    """
    try:
        parsed = read()
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise PlatformRefused(f"{what} does not say what was asked: {error!r}") from error

    return parsed
