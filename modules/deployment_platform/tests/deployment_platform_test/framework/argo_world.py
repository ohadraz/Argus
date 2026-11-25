"""An Argo CD server, in-process, serving one `PlatformState` in Argo CD's own shapes.

The port's suite runs the Argo CD adapter against this through its `transport`
seam, beside the in-memory double built from the same seed. So this answers
every route the adapter asks, in the shapes `test_argocd.py` pins on the wire,
and it keeps state: each write is applied to what the next read is answered
with - a merge patch merged as RFC 7386 says, a mark kept on the object it was
written to - or the adapter would be answering questions about a platform that
never changed.

Four behaviours of Argo CD's that `test_argocd.py` does not pin, because the
adapter only reads their answer:
- A live resource, read or patched, is found by group, kind, namespace and
  name together, and one the application's tree holds no node for is refused
  (`getAppLiveResource`, server/application/application.go, with
  `InvalidArgument` - a 400 - "%s %s %s not found as part of application %s").
- A rollback is refused while the application syncs itself
  (`ApplicationServer.Rollback`, server/application/application.go, refuses it
  with `FailedPrecondition` - a 400 - while automated sync is enabled).
- A rollback to an entry the history does not hold is refused (the same
  function, with `InvalidArgument` - a 400 - "application %s does not have
  deployment with id %v").
- A rollback's history entry and a restart's new pods land later than the
  answer: Argo CD records the entry, numbered after the last and dated then,
  once the sync it starts has run (`persistRevisionHistory`,
  controller/state.go), and Kubernetes starts the new pods as the Deployment
  rolls. Both are held here until `finished()` - so the suite reads them only
  once it has said the platform finished.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any, Final

import httpx2
from deployment_platform.argocd import (
    ACCELERATOR_LABEL,
    ANNOTATIONS,
    APPLICATION_MERGE_PATCH,
    AUTOMATED,
    AUTOSCALER_GROUP,
    AUTOSCALER_KIND,
    DEPLOYMENT_GROUP,
    DEPLOYMENT_KIND,
    ENABLED,
    HOST_LABELS,
    HOST_NAME,
    HOSTS,
    INFO,
    INFO_NAME,
    INFO_VALUE,
    METADATA,
    NODE_INFO_ITEM,
    NODE_SELECTOR,
    PATCH_REQUEST_PATCH,
    PATCH_REQUEST_TYPE,
    POD_KIND,
    RESOURCE_MERGE_PATCH,
    SPEC,
    SYNC_POLICY,
    TEMPLATE,
    ArgoCdSettings,
)
from deployment_platform_double import (
    ApplicationState,
    Container,
    HistoryEntry,
    PlatformState,
    Rendering,
)

# Where the stand-in is addressed. Nothing listens there: the transport answers.
_BASE_URL: Final = "http://argocd.invalid"

# The routes, as a real Argo CD server spells them.
_APPLICATION: Final = "/api/v1/applications/{application}"
_ROUTE: Final = re.compile(r"^/api/v1/applications/(?P<application>[^/]+)(?P<rest>/.*)?$")
_RESOURCE: Final = "/resource"
_RESOURCE_ACTIONS: Final = "/resource/actions/v2"
_ROLLBACK: Final = "/rollback"
_RESOURCE_TREE: Final = "/resource-tree"
_MANIFESTS: Final = "/manifests"

# How Argo CD and Kubernetes spell a moment they record: UTC, to the second.
_MOMENT_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"

# Where the application's Deployment and its pods run, as the resource tree
# names their namespace - and the namespace the adapter is configured to find
# the Deployment in.
_NAMESPACE: Final = "production"

# What a request selects a resource by, and the same four as a tree's node
# carries them.
_FOUND_BY: Final = ("group", "kind", "namespace", "resourceName")
_NODE_FIELDS: Final = ("group", "kind", "namespace", "name")

_OK: Final = 200
_BAD_REQUEST: Final = 400
_NOT_FOUND: Final = 404


def argo_cd_settings(argus_account: str | None) -> ArgoCdSettings:
    """The adapter's settings, addressing this stand-in by a real server's
    routes, and recognising `argus_account` as Argus's - none, where it is
    `None`."""
    return ArgoCdSettings(
        argocd_base_url=_BASE_URL,
        argocd_actor=argus_account or "",
        argocd_application_path=_APPLICATION,
        argocd_resource_path=_APPLICATION + _RESOURCE,
        argocd_resource_action_path=_APPLICATION + _RESOURCE_ACTIONS,
        argocd_rollback_path=_APPLICATION + _ROLLBACK,
        argocd_resource_tree_path=_APPLICATION + _RESOURCE_TREE,
        argocd_manifests_path=_APPLICATION + _MANIFESTS,
        scale_namespace=_NAMESPACE
    )


class ArgoWorld:
    """One Argo CD server holding `state`, answering the requests a
    `MockTransport` hands it, dating every answer by `clock`.

    `unreachable` stands up a server nothing reaches: every request fails as a
    refused connection, before a byte of it was sent.
    """

    def __init__(self,
                 state: PlatformState,
                 *,
                 clock: Callable[[], datetime],
                 unreachable: bool = False) -> None:
        self._applications = {application.name: _Application(application)
                              for application in state.applications}
        self._hosts = [{HOST_NAME: node.name,
                        HOST_LABELS: {} if node.card is None else {ACCELERATOR_LABEL: node.card}}
                       for node in state.nodes]
        self._signed_in_as = state.signed_in_as
        self._clock = clock
        self._unreachable = unreachable

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if self._unreachable:
            raise httpx2.ConnectError("connection refused", request=request)

        routed = _ROUTE.match(request.url.path)
        held = None if routed is None else self._applications.get(routed["application"])

        if routed is None or held is None:
            return self._answer(_NOT_FOUND, {})

        return self._route(request, held, routed["rest"] or "")

    def finished(self) -> None:
        """What the platform had still to do once it answered, done: each
        rollback's entry recorded, and each restarted application's pods
        replaced."""
        for held in self._applications.values():
            held.finish(self._now())

    def _route(self, request: httpx2.Request, held: _Application, rest: str) -> httpx2.Response:
        method = request.method
        query = dict(request.url.params)

        if rest == "" and method == "GET":
            return self._answer(_OK, held.application())
        if rest == "" and method == "PATCH":
            return self._patch_the_application(held, _body(request))
        if rest == _RESOURCE and method == "GET":
            return self._live(held, query)
        if rest == _RESOURCE and method == "POST":
            return self._patch_a_resource(held, query, json.loads(_body(request)))
        if rest == _ROLLBACK and method == "POST":
            return self._roll_back(held, _body(request))
        if rest == _RESOURCE_ACTIONS and method == "POST":
            held.restarting_at = self._now()
            return self._answer(_OK, {})
        if rest == _RESOURCE_TREE and method == "GET":
            return self._answer(_OK, held.tree(self._hosts))
        if rest == _MANIFESTS and method == "GET":
            rendered = held.rendering(query.get("revision", ""))
            return self._answer(_OK, {"manifests": [] if rendered is None
                                      else [json.dumps(held.deployment(rendered))]})

        return self._answer(_NOT_FOUND, {})

    def _patch_the_application(self, held: _Application, request: Any) -> httpx2.Response:
        if request.get(PATCH_REQUEST_TYPE) != APPLICATION_MERGE_PATCH:
            return self._answer(_BAD_REQUEST, {})

        patch = json.loads(request[PATCH_REQUEST_PATCH])
        held.sync_policy = _merged(held.sync_policy, patch.get(SPEC, {}).get(SYNC_POLICY, {}))
        held.annotations["application"] = _merged(
            held.annotations["application"], patch.get(METADATA, {}).get(ANNOTATIONS, {})
        )

        return self._answer(_OK, held.application())

    def _live(self, held: _Application, query: dict[str, str]) -> httpx2.Response:
        """The live resource asked for, found as Argo CD finds one."""
        found = self._found(held, query)

        if found == DEPLOYMENT_KIND:
            return self._answer(_OK, {"manifest": json.dumps(
                held.deployment(held.running())
            )})

        if found == AUTOSCALER_KIND:
            return self._answer(_OK, {"manifest": json.dumps(held.autoscaler())})

        return self._not_part_of(held, query)

    def _patch_a_resource(self,
                          held: _Application,
                          query: dict[str, str],
                          patch: dict[str, Any]) -> httpx2.Response:
        if query.get(PATCH_REQUEST_TYPE) != RESOURCE_MERGE_PATCH:
            return self._answer(_BAD_REQUEST, {})

        annotations = patch.get(METADATA, {}).get(ANNOTATIONS, {})
        spec = patch.get(SPEC, {})
        found = self._found(held, query)

        if found == DEPLOYMENT_KIND:
            if "replicas" in spec:
                held.replicas = int(spec["replicas"])

            selector = spec.get(TEMPLATE, {}).get(SPEC, {}).get(NODE_SELECTOR, {})
            if ACCELERATOR_LABEL in selector:
                held.pin = selector[ACCELERATOR_LABEL]

            held.annotations["deployment"] = _merged(held.annotations["deployment"], annotations)
            return self._answer(_OK, {})

        if found == AUTOSCALER_KIND:
            if "minReplicas" in spec:
                held.floor = int(spec["minReplicas"])

            held.annotations["autoscaler"] = _merged(held.annotations["autoscaler"], annotations)
            return self._answer(_OK, {})

        return self._not_part_of(held, query)

    def _found(self, held: _Application, query: dict[str, str]) -> str | None:
        """The kind of the application's resource the request selects, found as
        Argo CD's `FindNode` finds one: the node of the application's tree whose
        group, kind, namespace and name all equal the request's - so a request
        that leaves one out finds nothing."""
        asked = tuple(query.get(selector, "") for selector in _FOUND_BY)

        return next((node["kind"] for node in held.tree(self._hosts)["nodes"]
                     if tuple(node.get(field, "") for field in _NODE_FIELDS) == asked),
                    None)

    def _not_part_of(self, held: _Application, query: dict[str, str]) -> httpx2.Response:
        """Refused as Argo CD refuses a resource it finds no node for, reading
        it or patching it alike (`getAppLiveResource`,
        server/application/application.go)."""
        return self._answer(_BAD_REQUEST, {
            "message": f"{query.get('kind', '')} {query.get('group', '')}"
                       f" {query.get('resourceName', '')} not found as part of application"
                       f" {held.name}"
        })

    def _roll_back(self, held: _Application, request: dict[str, Any]) -> httpx2.Response:
        if held.syncs_itself():
            return self._answer(_BAD_REQUEST, {
                "message": "rollback cannot be initiated when auto-sync is enabled"
            })

        returned_to = next((entry for entry in held.history if entry["id"] == request["id"]),
                           None)

        if returned_to is None:
            return self._answer(_BAD_REQUEST, {
                "message": f"application {held.name} does not have deployment"
                           f" with id {request['id']}"
            })

        held.rolling_back_to.append({
            **{key: value for key, value in returned_to.items() if key == "source"},
            "revision": returned_to["revision"],
            **({} if not self._signed_in_as
               else {"initiatedBy": {"username": self._signed_in_as}})
        })

        return self._answer(_OK, {})

    def _answer(self, status: int, body: Any) -> httpx2.Response:
        return httpx2.Response(status, json=body,
                               headers={"Date": format_datetime(self._now(), usegmt=True)})

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC).replace(microsecond=0)


class _Application:
    """One application, as the server holds it between requests."""

    def __init__(self, seeded: ApplicationState) -> None:
        self.name = seeded.name
        self.history: list[dict[str, Any]] = [_an_entry(entry) for entry in seeded.history]
        self.renderings = seeded.renderings
        self.replicas = seeded.replicas
        self.serving = seeded.serving
        self.updated = seeded.updated
        self.paused = seeded.paused
        self.has_failed = seeded.has_failed
        self.pin = seeded.accelerator_pin
        self.set_by_hand = seeded.running
        self.held_autoscaler = seeded.autoscaler
        self.floor = None if seeded.autoscaler is None else seeded.autoscaler.bounds.floor
        self.pods = [(pod.name, pod.node, pod.started_at) for pod in seeded.pods]
        self.sync_policy: dict[str, Any] = {AUTOMATED: {}} if seeded.syncs_itself else {}
        self.annotations: dict[str, dict[str, Any]] = {
            "application": {}, "deployment": {}, "autoscaler": {}
        }
        self.rolling_back_to: list[dict[str, Any]] = []
        self.restarting_at: datetime | None = None

    def finish(self, now: datetime) -> None:
        # Numbered after the last entry and dated as the sync is recorded, as
        # Argo CD records the next; the sync renders the returned-to revision
        # over anything set by hand.
        for entry in self.rolling_back_to:
            self.history.append({**entry,
                                 "id": self.history[-1]["id"] + 1,
                                 "deployedAt": now.strftime(_MOMENT_FORMAT)})
            self.set_by_hand = None

        self.rolling_back_to = []

        if self.restarting_at is not None:
            self.pods = [(name, node, self.restarting_at) for name, node, _ in self.pods]
            self.restarting_at = None

    def syncs_itself(self) -> bool:
        """As Argo CD reads it: an `automated` whose `enabled` is absent or true."""
        automated = self.sync_policy.get(AUTOMATED)

        return automated is not None and automated.get(ENABLED) is not False

    def application(self) -> dict[str, Any]:
        return {
            METADATA: {"name": self.name, ANNOTATIONS: self.annotations["application"]},
            SPEC: {SYNC_POLICY: self.sync_policy},
            "status": {"history": self.history}
        }

    def running(self) -> Rendering:
        """What the Deployment's pods start: what was set by hand, if anything
        was, and otherwise the last entry's rendering."""
        if self.set_by_hand is not None:
            return Rendering(revision=self.history[-1]["revision"],
                             containers=self.set_by_hand)

        rendered = self.rendering(self.history[-1]["revision"])
        assert rendered is not None, f"the seed renders nothing [{self.name}] runs"

        return rendered

    def rendering(self, revision: str) -> Rendering | None:
        return next((rendering for rendering in self.renderings
                     if rendering.revision == revision), None)

    def deployment(self, rendered: Rendering) -> dict[str, Any]:
        """The Deployment as the platform reports it live, starting `rendered`'s
        containers. A status says only what the seed set, as a manifest with
        none reads as a rollout finished."""
        status: dict[str, Any] = {}

        if self.serving is not None:
            status["replicas"] = self.serving
        if self.updated is not None:
            status["updatedReplicas"] = self.updated
        if self.has_failed:
            status["conditions"] = [{"type": "Progressing", "status": "False"}]

        return {
            "apiVersion": "apps/v1",
            "kind": DEPLOYMENT_KIND,
            METADATA: {"name": self.name, ANNOTATIONS: self.annotations["deployment"]},
            SPEC: {
                "replicas": self.replicas,
                "paused": self.paused,
                TEMPLATE: {SPEC: {
                    NODE_SELECTOR: {} if self.pin is None else {ACCELERATOR_LABEL: self.pin},
                    "containers": [_a_container(one) for one in rendered.containers
                                   if not one.init],
                    "initContainers": [_a_container(one) for one in rendered.containers
                                       if one.init]
                }}
            },
            "status": status
        }

    def autoscaler(self) -> dict[str, Any]:
        held = self.held_autoscaler
        assert held is not None

        return {
            "apiVersion": "autoscaling/v2",
            "kind": AUTOSCALER_KIND,
            METADATA: {"name": held.autoscaler.name,
                       "namespace": held.autoscaler.namespace,
                       ANNOTATIONS: self.annotations["autoscaler"]},
            SPEC: {"minReplicas": self.floor, "maxReplicas": held.bounds.ceiling}
        }

    def tree(self, hosts: list[dict[str, Any]]) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = [
            {
                "kind": POD_KIND,
                "name": name,
                "namespace": _NAMESPACE,
                "createdAt": started_at.astimezone(UTC).strftime(_MOMENT_FORMAT),
                INFO: [] if node is None else [{INFO_NAME: NODE_INFO_ITEM, INFO_VALUE: node}]
            }
            for name, node, started_at in self.pods
        ]

        # The application's own Deployment, as a real tree lists it.
        nodes.append({"group": DEPLOYMENT_GROUP,
                      "kind": DEPLOYMENT_KIND,
                      "name": self.name,
                      "namespace": _NAMESPACE})

        if self.held_autoscaler is not None:
            nodes.append({"group": AUTOSCALER_GROUP,
                          "kind": AUTOSCALER_KIND,
                          "name": self.held_autoscaler.autoscaler.name,
                          "namespace": self.held_autoscaler.autoscaler.namespace})

        return {"nodes": nodes, HOSTS: hosts}


def _an_entry(entry: HistoryEntry) -> dict[str, Any]:
    """A seeded history entry as Argo CD's `RevisionHistory` carries it."""
    source = {key: value for key, value in (("repoURL", entry.repo_url), ("path", entry.path))
              if value is not None}

    return {
        "id": entry.history_id,
        "revision": entry.revision,
        "deployedAt": entry.deployed_at,
        **({"source": source} if source else {}),
        **({"initiatedBy": {"username": entry.initiated_by}} if entry.initiated_by else {})
    }


def _a_container(container: Container) -> dict[str, str]:
    return {"name": container.name, "image": container.image}


def _body(request: httpx2.Request) -> Any:
    return json.loads(request.content)


def _merged(target: Any, patch: Any) -> Any:
    """`patch` applied to `target` as RFC 7386 says: an object merges key by
    key, a `null` removes its key, and anything else replaces what was there."""
    if not isinstance(patch, dict):
        return patch

    result = dict(target) if isinstance(target, dict) else {}

    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = _merged(result.get(key), value)

    return result
