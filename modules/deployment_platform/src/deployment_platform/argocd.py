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
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Any, Final, assert_never

import httpx2
from core import AdapterSettings
from core.models import PodPlacement, RolloutProgress
from http_applying import known_not_applied

from deployment_platform.failures import PlatformRefused, PlatformUnreachable
from deployment_platform.port import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentRecord,
    Mark,
    MarkedObject,
    MarkFound,
    RequestedSync,
    SyncOperations,
    SyncPhase,
    SyncRun,
)

logger = logging.getLogger(__name__)

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
# How an application synced from its repository's root names the directory.
_THE_ROOT: Final = "."
_INITIATED_BY: Final = "initiatedBy"
_USERNAME: Final = "username"

# The resource route's wrapper: the manifest arrives as *text*, and the caller
# parses it.
_MANIFEST: Final = "manifest"
# The manifests route's `ManifestResponse`: every manifest the revision renders,
# each as text, as the resource route carries its one.
_MANIFESTS: Final = "manifests"
# Where a manifest names itself.
_METADATA_NAME: Final = "name"
# A pod template's containers, the ones serving and the ones run before them, and
# what each is started from.
_CONTAINERS: Final = "containers"
_INIT_CONTAINERS: Final = "initContainers"
_CONTAINER_NAME: Final = "name"
_IMAGE: Final = "image"
# The manifests route's query parameter naming the revision to render.
_REVISION_PARAMETER: Final = "revision"

# Where an object carries what anybody wrote about it, in Kubernetes' own words,
# and the two keys Argus marks a change of its own with. On the object's own
# metadata and never on a pod template's, which would roll every pod. `argus`
# is a valid prefix for a key: a DNS subdomain may be a single label.
METADATA: Final = "metadata"
ANNOTATIONS: Final = "annotations"
ACTION_ANNOTATION: Final = "argus/action"
WRITTEN_AT_ANNOTATION: Final = "argus/written-at"
# How the moment is spelled: UTC to the second, as the platform spells its own.
_WRITTEN_AT_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"

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
# Where the tree says what a pod is running on. The node is one of a Pod's info
# items, under `Node`; the nodes themselves are listed under `hosts`, each with the
# labels the platform is configured to report (`application.allowedNodeLabels`).
INFO: Final = "info"
INFO_NAME: Final = "name"
INFO_VALUE: Final = "value"
NODE_INFO_ITEM: Final = "Node"
HOSTS: Final = "hosts"
HOST_NAME: Final = "name"
HOST_LABELS: Final = "labels"
# The node label NVIDIA's GPU Feature Discovery publishes a card's product under,
# and so the label a Deployment is held to one card by.
ACCELERATOR_LABEL: Final = "nvidia.com/gpu.product"
# Where a Deployment's pod template keeps its node selector.
TEMPLATE: Final = "template"
NODE_SELECTOR: Final = "nodeSelector"

# The built-in resource action a restart is, by the name Argo CD registers it
# under, and what it is run against: Argo CD dispatches its Lua by group and kind,
# and it is written for `apps/Deployment` - which is also what a patch of the
# Deployment addresses.
RESTART_ACTION: Final = "restart"
DEPLOYMENT_GROUP: Final = "apps"
DEPLOYMENT_VERSION: Final = "v1"
DEPLOYMENT_KIND: Final = "Deployment"

# What an autoscaler is, for addressing it on the resource route. The name and the
# namespace are the tree's; these are what was asked for rather than what was found.
AUTOSCALER_GROUP: Final = "autoscaling"
AUTOSCALER_VERSION: Final = "v2"
AUTOSCALER_KIND: Final = "HorizontalPodAutoscaler"

REQUEST_TIMEOUT_SECONDS: Final = 10.0

# HTTP's header for when an answer was given, by the server's own clock.
_DATE: Final = "Date"

# An application's syncs: the one asked and not yet finished, at the top level,
# and the last one the controller ran, under `status`. A rollback is a sync, of
# the history entry's revision.
_OPERATION: Final = "operation"
_OPERATION_STATE: Final = "operationState"
_SYNC: Final = "sync"
_STARTED_AT: Final = "startedAt"
_PHASE: Final = "phase"
_MESSAGE: Final = "message"
# Argo CD's `OperationPhase` values, as Argus names them.
_FAILED: Final = "Failed"
_ERROR: Final = "Error"
_PHASES: Final = {
    "Running": SyncPhase.RUNNING,
    "Succeeded": SyncPhase.SUCCEEDED,
    _FAILED: SyncPhase.FAILED,
    _ERROR: SyncPhase.ERROR,
    "Terminating": SyncPhase.TERMINATING
}
# What the controller says a run ended with where it was terminated - by
# somebody, or by the controller itself where `controller.sync.timeout.seconds`
# is set and the run outlasts it, or its operation state outgrows the size
# limit (controller/appcontroller.go); a timeout's stop taking more than one
# pass ends in "Operation terminated" as a person's does - from
# gitops-engine's `syncContext.Terminate()` (pkg/sync/sync_context.go):
# `setOperationPhase(common.OperationFailed, "Operation terminated")` once every
# hook is stopped, `setOperationPhase(common.OperationError, "Operation
# termination had errors")` where one would not stop, and
# `setOperationPhase(common.OperationError, fmt.Sprintf("Failed to get hook
# health: %v", err))` where a hook's health could not be read on the way. The
# last is written nowhere else in that file - `Sync`'s own health failure is a
# resource's result, lower-cased, never the operation's message - so its prefix
# alone says termination. Once the controller is done the run reads only
# `Failed` or `Error`, and these words are all that tell it from a run that
# failed of itself - so a run carrying any of them is `SyncPhase.TERMINATED`,
# and nothing above the port reads the words.
RUN_TERMINATED_MESSAGE: Final = "Operation terminated"
RUN_TERMINATION_ERRED_MESSAGE: Final = "Operation termination had errors"
RUN_TERMINATION_HOOK_HEALTH_PREFIX: Final = "Failed to get hook health: "
_ENDED_BY_TERMINATION: Final = {(_FAILED, RUN_TERMINATED_MESSAGE),
                                (_ERROR, RUN_TERMINATION_ERRED_MESSAGE)}
# What the platform answers a sync - a rollback among them - asked while
# another is still being run (`FailedPrecondition`, served as a 400).
ANOTHER_OPERATION_IN_PROGRESS: Final = "another operation is already in progress"

# The lowest status a server uses to say the failure is its own rather than the
# request's. Below it the platform has read what was asked and rejected it, which
# is the platform working.
_THE_SERVERS_OWN_FAULT: Final = 500


class ArgoCdSettings(AdapterSettings):
    """Where the Argo CD server is, under what credential, and its routes.

    One set for every request, where there used to be one per action each
    redeclaring the server and the credential. Read by each tier's root. The
    routes are templates over the application, so the demo's stand-in and a
    real server's `/api/v1/applications/{application}` are one setting with two
    values; a path carrying no placeholder is formatted to itself.

    The defaults are the demo Target Service, which stands in for a real Argo CD
    server - but the adapter makes the request a real Argo CD answers, and
    pointing these at one is the only change needed.

    The two namespaces are the restart's and the scale-out's, each addressing the
    Deployment its action is run against. The autoscaler has none, because its
    address is read from the tree rather than configured.
    """

    argocd_base_url: str = "http://localhost:8080"
    # Empty means no credential is sent at all, rather than an invented one a
    # real server would reject as meaningless. The demo's stand-in answers
    # reads without one and refuses a rollback that carries no token it issued.
    argocd_auth_token: str = ""
    # The name the platform records Argus's own actions under - the account the
    # credential above belongs to, which Argo CD writes on each history entry as
    # `initiatedBy.username`. The counterpart of the flag provider's
    # `UNLEASH_ACTOR`, for the same reason: a rollback Argus made lands in the
    # deploy history a later round reads, and kept there it is offered as the
    # change to undo. Empty switches the filtering off, the honest setting where
    # the credential is shared - and leaves every rollback put-back to a person,
    # since whether a rollback is still Argus's is asked by this name.
    argocd_actor: str = "Argus"
    argocd_application_path: str = "/argocd/{application}"
    # Where the platform says what is actually *running*, and where an autoscaler
    # is patched - the only place a live replica count can be read, since the
    # values file says what git asks for and the two differ the moment anybody
    # scales.
    argocd_resource_path: str = "/argocd/{application}/resource"
    # Where a resource action is run. A real Argo CD's is
    # `/api/v1/applications/{application}/resource/actions/v2` - v2 rather than
    # the original, which takes the same fields as query parameters and is
    # deprecated since Argo CD 3.1. One setting for every action rather than one
    # per action, because it is one endpoint: `restart` and `scale` are both
    # built-in resource actions for a Deployment, dispatched by the name in the
    # body.
    argocd_resource_action_path: str = "/argocd/{application}/resource/actions/v2"
    # Where a rollback is asked for. A real Argo CD's is
    # `/api/v1/applications/{application}/rollback`.
    #
    # A rollback is three requests, not one - the application is read for which
    # entry is running and whether the platform is reconciling it,
    # reconciliation is suspended because a real server refuses a rollback while
    # it is on, and only then is the rollback asked for. The first two go to
    # the application path: the suspension is a merge patch of the application
    # itself (`PATCH /api/v1/applications/{application}`, Argo CD 3.1 or later),
    # never a write to its spec route, which replaces the whole spec with
    # whatever it is sent.
    argocd_rollback_path: str = "/argocd/{application}/rollback"
    # What an application is made of: its pods, and its autoscaler's own name. A
    # pod's creation time is what confirms a restart landed, and it is per
    # application - restarting a dependency is confirmed by looking at the
    # dependency.
    argocd_resource_tree_path: str = "/argocd/{application}/resource-tree"
    # What the platform renders an application as at a revision - what git ships,
    # where the resource route says what is running. A put-back of a rollback
    # compares the two's images, because a `kubectl set image` leaves no history
    # entry to find it by. A real Argo CD's is
    # `/api/v1/applications/{application}/manifests`.
    argocd_manifests_path: str = "/argocd/{application}/manifests"
    # Which namespace the deployment being restarted lives in. The resource
    # itself is not configured: it is the service being restarted, because a
    # fixed name would carry the alerting service's deployment into a request
    # addressed at one of its dependencies.
    restart_namespace: str = "production"
    # And which namespace the one being scaled lives in. Its own setting rather
    # than the restart's reused: a restart may be addressed at a dependency in
    # somebody else's namespace, where a scale-out only ever reaches the
    # deployment Argus was paged about.
    scale_namespace: str = "production"


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
            _parsed(partial(_a_record_of, entry, self._settings.argocd_actor),
                    f"[{application}]'s deployment history")
            for entry in history
        ]

    def rollout_of(self, application: str, /) -> RolloutProgress:
        """How far the running Deployment has got, read from the live resource.

        Asked for by the Deployment's own selectors, as every read of it is: the
        platform finds a live resource by group, kind, namespace and name, and
        refuses a request that leaves them out.

        A manifest carrying no rollout status reads as converged, and that is a
        decision rather than a fallback: nothing in it says any replica is lagging.
        A manifest that does not say how many replicas it was asked for is refused,
        because a guessed count is how a rollout nobody can read becomes one
        reported as converged.
        """
        manifest = self._manifest(application, self._the_deployment_of(application))

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

    def placements_of(self, application: str, /) -> list[PodPlacement]:
        """Each pod's node off its own info, and that node's card off the host of
        the same name.

        The tree says the two things in two places, and only together do they say
        what a replica runs on. A pod with no `Node` item has not been placed, and
        one whose `createdAt` cannot be read cannot be put either side of an onset,
        so both are left out. A tree listing no hosts, or a host without the
        label, says nothing about a card - a platform not allow-listing the label
        and a node with no GPU look the same here, and neither is a guess.
        """
        tree = self._get(self._settings.argocd_resource_tree_path, application)

        def placements() -> list[PodPlacement]:
            cards = {
                str(host[HOST_NAME]): (host.get(HOST_LABELS) or {}).get(ACCELERATOR_LABEL)
                for host in tree.get(HOSTS) or []
            }
            placed = []

            for node in tree.get(_NODES, []):
                if node.get(_KIND) != POD_KIND:
                    continue

                on = _the_node_named_in(node)

                if on is None:
                    continue

                started_at = _when_it_was_created(node.get(_CREATED_AT))

                if started_at is None:
                    logger.warning("pod start time unreadable", extra={
                        "application": application, "pod": node.get(_NAME)
                    })
                    continue

                placed.append(
                    PodPlacement(
                        pod=str(node[_NAME]),
                        node=on,
                        accelerator=cards.get(on),
                        started_at=started_at
                    )
                )

            return placed

        return _parsed(placements, f"[{application}]'s resource tree")

    def now(self, application: str, /) -> datetime:
        """The `Date` the application's own route is answered with.

        Every format RFC 9110 (5.6.7) has a recipient accept, the obsolete two
        among them; the asctime one names no zone, and HTTP's dates are UTC. An
        answer with no readable `Date` is refused rather than dated by this
        process's clock, which a change the platform recorded could fall the
        wrong side of.
        """
        answered = self._send("GET", self._settings.argocd_application_path, application)

        return _parsed(lambda: _the_date_on(answered),
                       f"the date [{application}] was served with")

    def sync_operations_of(self, application: str, /) -> SyncOperations:
        """The application's `operation` and its `status.operationState`.

        The first is set the moment a sync is asked for and cleared only once it
        finishes; the second appears when the controller starts running it. A
        platform that keeps neither - the demo's stand-in keeps no state of its
        runs - answers with neither, and a caller has the history alone.
        """
        state = self._get(self._settings.argocd_application_path, application)

        argus = self._settings.argocd_actor

        def operations() -> SyncOperations:
            requested = state.get(_OPERATION)
            run = (state.get(_STATUS) or {}).get(_OPERATION_STATE)
            asked_by = None if requested is None else _who_asked_for(requested)
            run_by = None if run is None else _who_asked_for(run[_OPERATION])

            return SyncOperations(
                requested=None if requested is None else RequestedSync(
                    revision=_the_revision_synced_by(requested),
                    initiated_by=asked_by,
                    made_by_argus=_whether_argus_started(asked_by, argus)
                ),
                last_run=None if run is None else SyncRun(
                    revision=_the_revision_synced_by(run[_OPERATION]),
                    initiated_by=run_by,
                    started_at=datetime.fromisoformat(str(run[_STARTED_AT])),
                    phase=_the_phase_of(run),
                    made_by_argus=_whether_argus_started(run_by, argus)
                )
            )

        return _parsed(operations, f"[{application}]'s syncs")

    def mark_on(self, application: str, kind: MarkedObject, /) -> MarkFound | None:
        """The mark on the object's own metadata, never on a pod template's:
        Argus writes its mark on the object, and one found in a template is not
        one Argus wrote.

        Each object is read where its write is sent - the application on its own
        route, the Deployment and the autoscaler as live manifests, the
        autoscaler addressed as the tree names it. An application with no
        autoscaler has no mark on one. A mark whose moment is absent, or is not
        spelled as Argus spells one, still names its action; the moment is then
        unknown rather than made up.
        """
        match kind:
            case MarkedObject.APPLICATION:
                found = self._get(self._settings.argocd_application_path, application)
            case MarkedObject.DEPLOYMENT:
                found = self._manifest(application, self._the_deployment_of(application))
            case MarkedObject.AUTOSCALER:
                autoscaler = self.autoscaler_of(application)

                if autoscaler is None:
                    return None

                found = self._manifest(application, _addressing(autoscaler))
            case _:
                assert_never(kind)

        def mark() -> MarkFound | None:
            annotations = (found.get(METADATA) or {}).get(ANNOTATIONS) or {}
            marked = annotations.get(ACTION_ANNOTATION)

            if marked is None:
                return None

            return MarkFound(action_id=str(marked),
                             written_at=_when_it_was_marked(
                                 annotations.get(WRITTEN_AT_ANNOTATION)
                             ))

        return _parsed(mark, f"the mark on [{application}]'s {kind}")

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

    def suspend_sync(self, application: str, mark: Mark, /) -> None:
        self._set_sync(application, reconciling=False, mark=mark)

    def resume_sync(self, application: str, mark: Mark, /) -> None:
        self._set_sync(application, reconciling=True, mark=mark)

    def scale(self, application: str, replicas: int, mark: Mark, /) -> datetime | None:
        """A merge patch of the Deployment's count, beside the mark, answered
        with the answer's `Date` - see `roll_back`.

        Not the built-in `scale` action: its Lua writes the count and nothing
        else, so a resize made through it could not say whose it was. The count
        is a number here, being the manifest's own field.
        """
        return self._a_write_dated(
            "POST",
            self._settings.argocd_resource_path,
            application,
            params={
                **self._the_deployment_of(application),
                PATCH_REQUEST_TYPE: RESOURCE_MERGE_PATCH
            },
            body=json.dumps({**_marked(mark), SPEC: {_REPLICAS: replicas}})
        )

    def roll_back(self, application: str, to_history_id: int, /) -> datetime | None:
        """The rollback route, answered with the answer's `Date`.

        Read as `now` reads it, off the answer to the write itself, so dating
        the change costs no read of its own. `None` where the answer carries no
        readable `Date`: the change landed, so it is never refused for that,
        and this process's clock is no stand-in for the platform's.
        """
        return self._a_write_dated(
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
        readable: list[float] = []

        for node in self._nodes_of(service):
            if node.get(_KIND) != POD_KIND:
                continue

            came_up = _when_it_came_up(node.get(_CREATED_AT))

            if came_up is None:
                logger.warning("pod start time unreadable", extra={
                    "application": service, "pod": node.get(_NAME)
                })
                continue

            readable.append(came_up)

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
                             mark: Mark,
                             /) -> datetime | None:
        """A merge patch of the floor alone, beside the mark, as the resource
        route carries one - answered with the answer's `Date`, as `roll_back` is.

        A JSON-encoded *string* rather than an object - the vendor's own shape for
        this body, and the mirror of the manifest arriving as text from the same
        route. One field of the spec, because a merge patch says only what
        changes: a body carrying the ceiling would re-assert a human's
        declaration as though Argus had decided it.
        """
        return self._a_write_dated(
            "POST",
            self._settings.argocd_resource_path,
            application,
            params={**_addressing(autoscaler), PATCH_REQUEST_TYPE: RESOURCE_MERGE_PATCH},
            body=json.dumps({**_marked(mark), SPEC: {_MIN_REPLICAS: floor}})
        )

    def accelerator_pin_of(self, application: str, /) -> str | None:
        """The card the live Deployment's pod template selects, read off the
        resource the platform is running rather than the values file."""
        manifest = self._manifest(application, self._the_deployment_of(application))

        def pinned_to() -> str | None:
            template = manifest[SPEC].get(TEMPLATE) or {}
            selector = (template.get(SPEC) or {}).get(NODE_SELECTOR) or {}
            card = selector.get(ACCELERATOR_LABEL)

            return None if card is None else str(card)

        return _parsed(pinned_to, f"[{application}]'s node selector")

    def images_running(self, application: str, /) -> dict[str, str]:
        """The images the live Deployment's pod template starts, read off the
        resource the platform is running rather than the values file.

        Every container, init containers too: a `kubectl set image` can change
        any of them, and none of it leaves an entry in the platform's history.
        """
        manifest = self._manifest(application, self._the_deployment_of(application))

        return _parsed(
            lambda: _the_images_in(manifest), f"[{application}]'s running images"
        )

    def images_at(self, application: str, revision: str, /) -> dict[str, str]:
        """The images the application's own Deployment starts as the platform
        renders `revision`.

        Argo CD's `ManifestResponse` carries every manifest the revision renders,
        each as text. The application's Deployment is the one of that kind and
        name; a Service beside it, or another chart's Deployment, says nothing
        about it. A revision rendering none is refused rather than answered as no
        images: compared with nothing, every image running would read as
        somebody else's.
        """
        rendered = self._get(
            self._settings.argocd_manifests_path,
            application,
            {_REVISION_PARAMETER: revision}
        )

        def images() -> dict[str, str]:
            deployments = [
                manifest
                for manifest in (json.loads(text) for text in rendered[_MANIFESTS])
                if manifest.get(_KIND) == DEPLOYMENT_KIND
                and (manifest.get(METADATA) or {}).get(_METADATA_NAME) == application
            ]

            if not deployments:
                raise ValueError(f"no Deployment named [{application}] is rendered")

            return _the_images_in(deployments[0])

        return _parsed(images, f"[{application}]'s manifests at [{revision}]")

    def pin_to_accelerator(self,
                           application: str,
                           accelerator: str | None,
                           mark: Mark,
                           /) -> datetime | None:
        """A merge patch of the card label alone, on the pod template's selector,
        beside the mark on the Deployment's own metadata - answered with the
        answer's `Date`, as `roll_back` is.

        The label and nothing else of the template, because a merge patch says
        only what changes: a body carrying the whole selector would replace
        selectors somebody else declared. A `None` is sent as a null, which RFC
        7386 reads as removing the key - how a pin onto a deployment that had
        none is let go.
        """
        return self._a_write_dated(
            "POST",
            self._settings.argocd_resource_path,
            application,
            params={
                **self._the_deployment_of(application),
                PATCH_REQUEST_TYPE: RESOURCE_MERGE_PATCH
            },
            body=json.dumps({
                **_marked(mark),
                SPEC: {TEMPLATE: {SPEC: {NODE_SELECTOR: {ACCELERATOR_LABEL: accelerator}}}}
            })
        )

    def _the_deployment_of(self, application: str) -> dict[str, str]:
        """The application's own Deployment, as the resource route selects it.

        The scale-out's namespace, because it is the same Deployment a resize is
        run against.
        """
        return {
            "resourceName": application,
            _NAMESPACE: self._settings.scale_namespace,
            "group": DEPLOYMENT_GROUP,
            "version": DEPLOYMENT_VERSION,
            _KIND: DEPLOYMENT_KIND
        }

    def _set_sync(self, application: str, reconciling: bool, mark: Mark) -> None:
        """A merge patch of the switch alone, beside the mark, on the application
        route.

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
                    {**_marked(mark), SPEC: {SYNC_POLICY: {AUTOMATED: {ENABLED: switch}}}}
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
                  params: dict[str, str]) -> dict[str, Any]:
        """A managed resource's live manifest, parsed out of its text wrapper."""
        resource = self._get(self._settings.argocd_resource_path, application, params)

        def manifest() -> dict[str, Any]:
            parsed: dict[str, Any] = json.loads(resource[_MANIFEST])
            return parsed

        return _parsed(manifest, f"[{application}]'s live manifest")

    def _a_write_dated(self,
                       method: str,
                       route: str,
                       application: str,
                       params: dict[str, str] | None = None,
                       body: Any = None) -> datetime | None:
        """One write, answered with its answer's `Date` where it carries a
        readable one and `None` where it does not."""
        answered = self._send(method, route, application, params=params, body=body)

        try:
            return _the_date_on(answered)
        except (KeyError, TypeError, ValueError):
            logger.info("write answered undated", extra={"application": application})

            return None

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
                f"{method} [{path}] got no answer: {error}",
                known_not_applied=known_not_applied(method, error)
            ) from error
        except httpx2.HTTPStatusError as error:
            failure = (
                PlatformUnreachable
                if error.response.status_code >= _THE_SERVERS_OWN_FAULT
                else PlatformRefused
            )
            # Refused, and not for want of anything: a change asked again while
            # the first asking is still being run says nothing of whether that
            # first one will land.
            already_running = ANOTHER_OPERATION_IN_PROGRESS in error.response.text
            raise failure(
                f"{method} [{path}] was answered "
                f"[{error.response.status_code}]: {error.response.text}",
                known_not_applied=known_not_applied(method, error) and not already_running
            ) from error

        return response


def _marked(mark: Mark) -> dict[str, Any]:
    """The part of a merge patch that marks the object as Argus's: both
    annotations on its own metadata, the moment in UTC to the second."""
    return {
        METADATA: {
            ANNOTATIONS: {
                ACTION_ANNOTATION: mark.action_id,
                WRITTEN_AT_ANNOTATION: mark.written_at.astimezone(UTC).strftime(
                    _WRITTEN_AT_FORMAT
                )
            }
        }
    }


def _when_it_was_marked(written_at: object) -> datetime | None:
    """A mark's moment read back as `_marked` spells it, or `None` where it is
    absent or spelled otherwise."""
    if not isinstance(written_at, str):
        return None

    try:
        return datetime.strptime(written_at, _WRITTEN_AT_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _the_images_in(deployment: dict[str, Any]) -> dict[str, str]:
    """Each container's image in a Deployment's pod template, by container name.

    A template that does not list its containers is refused rather than read as
    starting none - a Deployment always lists them, and no images compared with
    any would read as a change. Init containers are optional, and their absence
    is an ordinary answer.
    """
    pod = deployment[SPEC][TEMPLATE][SPEC]
    containers = [*(pod.get(_INIT_CONTAINERS) or []), *pod[_CONTAINERS]]

    return {
        str(container[_CONTAINER_NAME]): str(container[_IMAGE])
        for container in containers
    }


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


def _the_revision_synced_by(operation: dict[str, Any]) -> str | None:
    """The revision an operation syncs to, or `None` where it names none."""
    revision = (operation.get(_SYNC) or {}).get(_REVISION)

    return None if revision is None else str(revision)


def _the_phase_of(run: dict[str, Any]) -> SyncPhase:
    """Where a run the controller ran stands - `TERMINATED` where it ended
    failed or errored in the words the controller ends a terminated run with,
    since only those words tell it from a run that failed of itself."""
    phase, message = run[_PHASE], run.get(_MESSAGE)

    if (phase, message) in _ENDED_BY_TERMINATION or (
            phase == _ERROR and isinstance(message, str)
            and message.startswith(RUN_TERMINATION_HOOK_HEALTH_PREFIX)):
        return SyncPhase.TERMINATED

    return _PHASES[run[_PHASE]]


def _who_asked_for(operation: dict[str, Any]) -> str | None:
    """The account an operation was asked for by, or `None` where it names none
    - the platform's own sync."""
    username = (operation.get(_INITIATED_BY) or {}).get(_USERNAME)

    return str(username) if username else None


def _a_record_of(entry: dict[str, Any], argus: str) -> DeploymentRecord:
    source = entry.get(_SOURCE) or {}
    initiated_by = (entry.get(_INITIATED_BY) or {}).get(_USERNAME)

    return DeploymentRecord(
        history_id=int(entry[_HISTORY_ID]),
        revision=str(entry[_REVISION]),
        deployed_at=str(entry[_DEPLOYED_AT]),
        repo_url=source.get(_REPO_URL),
        # The root is no directory within the repository, and "." is only
        # Argo CD's way of saying it.
        path=None if source.get(_PATH) == _THE_ROOT else source.get(_PATH),
        initiated_by=initiated_by,
        made_by_argus=_whether_argus_started(initiated_by, argus)
    )


def _whether_argus_started(initiated_by: str | None, argus: str) -> bool | None:
    """Whether the account a deployment or a sync was started by is the one
    Argus signs in as. The one place either tier learns whose a change is: the
    read tier from a deployment's `made_by_argus`, the write tier from a
    deployment's and a sync's alike.

    Without regard to case. The account is seeded in the Target Environment's
    repository and named again in Argus's configuration, and case drifting
    between the two would quietly make Argus's own changes somebody else's.

    `None` where either is missing. With no account configured as Argus's,
    Argus shares its credential with people and nothing can tell them apart;
    with no account recorded, nobody is named. Reading either as "not Argus"
    would be acting on a guess - and in the one direction that matters, since a
    rollback Argus made, read as somebody else's, is a deployment it would then
    propose rolling back.
    """
    if not argus or not initiated_by:
        return None

    return initiated_by.casefold() == argus.casefold()


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
    moment = _when_it_was_created(created_at)

    return None if moment is None else moment.timestamp()


def _when_it_was_created(created_at: str | None) -> datetime | None:
    """One `createdAt` as a moment, or `None` where it is not one."""
    if created_at is None:
        return None

    try:
        return datetime.fromisoformat(created_at)
    except ValueError:
        return None


def _the_node_named_in(pod: dict[str, Any]) -> str | None:
    """The node a pod's info says it runs on, or `None` where it says none."""
    for item in pod.get(INFO) or []:
        if item.get(INFO_NAME) == NODE_INFO_ITEM and item.get(INFO_VALUE):
            return str(item[INFO_VALUE])

    return None


def _the_date_on(answered: httpx2.Response) -> datetime:
    """The answer's `Date`, in every format RFC 9110 (5.6.7) has a recipient
    accept; the asctime one names no zone, and HTTP's dates are UTC. Raises
    where there is none, or none readable - the caller decides what that is."""
    dated = parsedate_to_datetime(answered.headers[_DATE])

    return dated if dated.tzinfo is not None else dated.replace(tzinfo=UTC)


def _parsed[T](read: Callable[[], T], what: str) -> T:
    """`read()`, with an answer that does not say what was asked refused.

    Refused rather than unreachable: the platform answered. A parse gone wrong
    here read as an outage would pass over every action through a platform that
    is perfectly well.

    Known not to have applied anything: only a read's answer is parsed, and a
    read changes nothing however its answer reads.
    """
    try:
        parsed = read()
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise PlatformRefused(f"{what} does not say what was asked: {error!r}",
                              known_not_applied=True) from error

    return parsed
