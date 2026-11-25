"""The deployment platform as Argo CD serves it, said in Argus's own values.

The one suite in Argus that knows Argo CD's wire shape. Every action and every
read above the port is tested against the port, so what is pinned here is the
whole of what they rely on: which route each question goes to, the exact body
each change is sent as, how each answer is read - and which failures mean the
platform is not there at all.

The platform is a `MockTransport` rather than a stubbed function, so what is
asserted is the request as it would leave the process: method, path, query,
headers and body. A selector dropped or a body reshaped is a request a real
Argo CD answers differently, and nothing above the port could notice.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx2
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    one_record_was_logged,
    the_answer_was,
)
from core.models import PodPlacement, RolloutProgress
from deployment_platform import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentPlatformError,
    DeploymentRecord,
    Mark,
    MarkedObject,
    MarkFound,
    PlatformRefused,
    PlatformUnreachable,
    RequestedSync,
    SyncOperations,
    SyncPhase,
    SyncRun,
)
from deployment_platform.argocd import ANOTHER_OPERATION_IN_PROGRESS, ArgoCd, ArgoCdSettings

SOME_APPLICATION = "io-shop"
SOME_TOKEN = "some-argocd-token"
# The account Argus signs in as, which is how a deployment it started is told
# from anybody else's - and somebody else's.
THE_ACCOUNT_ARGUS_SIGNS_IN_AS = "Argus"
SOMEBODY_ELSE = "buki"
# Every way whose a deployment or a sync is gets told: the account configured
# as Argus's, the one the platform recorded, and what the adapter says of it.
EVERY_WAY_WHOSE_A_CHANGE_IS_TOLD = [
    # A rollback is recorded as a deployment like any other, under the account
    # that asked for it - so Argus's own is told by that account.
    pytest.param(THE_ACCOUNT_ARGUS_SIGNS_IN_AS, THE_ACCOUNT_ARGUS_SIGNS_IN_AS, True,
                 id="argus-s-own"),
    # The name is configured in one place and recorded in another. Case
    # drifting between them must not quietly read Argus's rollback as a
    # person's, which is the one failure telling them apart exists to prevent.
    pytest.param(THE_ACCOUNT_ARGUS_SIGNS_IN_AS, THE_ACCOUNT_ARGUS_SIGNS_IN_AS.lower(), True,
                 id="in-another-case"),
    pytest.param(THE_ACCOUNT_ARGUS_SIGNS_IN_AS, SOMEBODY_ELSE, False, id="somebody-else-s"),
    # No account recorded is not Argus's account recorded: nobody can say.
    pytest.param(THE_ACCOUNT_ARGUS_SIGNS_IN_AS, None, None, id="nobody-named"),
    # Argus sharing its credential with people cannot tell them apart at all,
    # and saying "not Argus" there would be acting on a guess.
    pytest.param("", THE_ACCOUNT_ARGUS_SIGNS_IN_AS, None, id="no-account-configured")
]
SOME_RESTART_NAMESPACE = "kuki-production"
SOME_SCALE_NAMESPACE = "buki-production"
DONT_CARE_BASE_URL = "http://argocd.invalid"

# The routes, as a real server spells them - the demo's stand-in is the same
# settings with other values.
THE_APPLICATION = f"/api/v1/applications/{SOME_APPLICATION}"
THE_RESOURCE = f"{THE_APPLICATION}/resource"
THE_RESOURCE_ACTIONS = f"{THE_APPLICATION}/resource/actions/v2"
THE_ROLLBACK = f"{THE_APPLICATION}/rollback"
THE_RESOURCE_TREE = f"{THE_APPLICATION}/resource-tree"
THE_MANIFESTS = f"{THE_APPLICATION}/manifests"

SOME_AUTOSCALER = Autoscaler(name="io-shop-hpa", namespace="kuki-namespace")
# How the autoscaler is addressed on the resource route, read and write alike.
THE_AUTOSCALER_SELECTORS = {
    "resourceName": SOME_AUTOSCALER.name,
    "namespace": SOME_AUTOSCALER.namespace,
    "group": "autoscaling",
    "version": "v2",
    "kind": "HorizontalPodAutoscaler"
}

# How the application's own Deployment is addressed on the resource route - read
# and write alike - when a pin to a card is read or set.
THE_DEPLOYMENT_SELECTORS = {
    "resourceName": SOME_APPLICATION,
    "namespace": SOME_SCALE_NAMESPACE,
    "group": "apps",
    "version": "v1",
    "kind": "Deployment"
}
# The node label GPU Feature Discovery publishes a card's product under, which
# Argo CD reports on a host once it is allow-listed. Spelled out rather than
# imported, because this file is what pins the wire shape.
THE_CARD_LABEL = "nvidia.com/gpu.product"
SOME_CARD = "Tesla-V100-SXM2-16GB"
SOME_OTHER_CARD = "NVIDIA-A100-SXM4-40GB"

# What a Deployment's pods start, by container name: the application's own
# container and the init container that runs before it - and another chart's.
THE_IMAGES = {
    SOME_APPLICATION: "io-shop:544cef3",
    "migrate": "io-shop-migrations:544cef3"
}
SOME_OTHER_IMAGES = {"worker": "io-shop-worker:0d8e826"}
# Which of `THE_IMAGES` is an init container rather than one serving.
THE_INIT_CONTAINERS = {"migrate"}

# The mark every write Argus makes is made under: the action row it is made for,
# and when the write tier wrote it - to the millisecond here, so that a moment
# said to the second is seen to be cut there.
SOME_MARK = Mark(
    action_id="6f1c1d2e-0000-4000-8000-0000000000a1",
    written_at=datetime(2026, 11, 18, 13, 5, 0, 417000, tzinfo=UTC)
)
# The mark as it lands on the written object's own metadata. The moment is
# spelled out rather than worked out from the one above: the spelling - UTC, to
# the second, with a `Z` - is the wire shape this file pins.
THE_ACTION_ANNOTATION = "argus/action"
THE_WRITTEN_AT_ANNOTATION = "argus/written-at"
THE_MARKED_METADATA = {
    "annotations": {
        THE_ACTION_ANNOTATION: SOME_MARK.action_id,
        THE_WRITTEN_AT_ANNOTATION: "2026-11-18T13:05:00Z"
    }
}
# The moment the mark above says it was written, read back off the object: cut
# to the second, as it was spelled there.
THE_MOMENT_THE_MARK_SAYS = SOME_MARK.written_at.replace(microsecond=0)
# A moment a mark says it was written at that does not read as a time.
AN_UNREADABLE_MOMENT = "not a moment"
# What somebody else wrote about an object, which a mark is read from beside.
SOMEBODY_ELSES_ANNOTATIONS = {"kubernetes.io/change-cause": "kubectl scale --replicas=6"}

# The one moment RFC 9110 (5.6.7) spells in each of the three formats a
# recipient must accept - its own examples, read here as the platform's clock.
THE_MOMENT_RFC_9110_SPELLS = datetime(1994, 11, 6, 8, 49, 37, tzinfo=UTC)
THE_IMF_FIXDATE = "Sun, 06 Nov 1994 08:49:37 GMT"
THE_OBSOLETE_RFC_850_DATE = "Sunday, 06-Nov-94 08:49:37 GMT"
THE_ASCTIME_DATE = "Sun Nov  6 08:49:37 1994"

# A sync an application is asked for: the revision it is to, the account that
# asked, and the history entry a rollback names.
SOME_REVISION = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
SOME_ACCOUNT = "argus"
# Which is the account Argus signs in as, spelled in another case.
SOME_ACCOUNT_IS_ARGUS_S = True
SOME_HISTORY_ID = 41
# When the controller started a sync, as Argo CD spells it and as Argus reads it.
SOME_SYNC_START = "2026-11-18T13:05:00Z"
THE_SYNC_START_READ = datetime(2026, 11, 18, 13, 5, tzinfo=UTC)
# What the controller says of a run that failed of itself - objects that would
# not apply - which is no stop of anybody's.
A_FAILED_RUN_S_MESSAGE = "one or more objects failed to apply"
# And of a run that errored of itself - the repository it renders from could
# not be reached.
AN_ERRORED_RUN_S_MESSAGE = "rpc error: code = Unavailable desc = connection refused"
# How gitops-engine's `Terminate()` finishes a run somebody terminated: failed,
# saying so, or errored, where the termination itself had errors. Spelled out
# rather than imported, because this file is what pins the wire shape.
THE_TERMINATED_RUN_S_MESSAGE = "Operation terminated"
THE_ERRED_TERMINATION_S_MESSAGE = "Operation termination had errors"
# And errored where it could not read a hook's health while terminating: the
# words `Terminate()` alone writes, followed by whatever error it met - one
# here, as the API server says a resource is gone.
THE_UNREAD_HOOK_S_MESSAGE = (
    "Failed to get hook health: the server could not find the requested resource"
)
# gRPC's code for a request refused for the state the system is in, which Argo
# CD's gateway serves a sync asked during another as.
FAILED_PRECONDITION = 9

GET = "GET"
POST = "POST"
PATCH = "PATCH"


@dataclass
class _Platform:
    """Argo CD's routes, answering what each case set and recording what was asked.

    A route nobody set answers 404, which is what a real server says about an
    application or a route it does not have - so a request sent somewhere it
    should not go fails the case rather than being quietly answered.
    """

    answers: dict[tuple[str, str], httpx2.Response] = field(default_factory=dict)
    asked: list[httpx2.Request] = field(default_factory=list)

    def answering(self, method: str, path: str, response: httpx2.Response) -> _Platform:
        self.answers[(method, path)] = response
        return self

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.asked.append(request)
        return self.answers.get(
            (request.method, request.url.path), httpx2.Response(404)
        )


def _ok(body: Any = None) -> httpx2.Response:
    return httpx2.Response(200, json=body if body is not None else {})


def _ok_dated(date: str | None, body: Any = None) -> httpx2.Response:
    """An answer carrying `date` as its `Date` header, or none where it is `None`."""
    return httpx2.Response(
        200,
        json=body if body is not None else {},
        headers={} if date is None else {"Date": date}
    )


def _argo_cd_over(platform: Any,
                  auth_token: str = SOME_TOKEN,
                  argus: str = THE_ACCOUNT_ARGUS_SIGNS_IN_AS) -> ArgoCd:
    """The adapter, configured as a real server would be and reaching only `platform`.

    The host does not resolve, so a request that escaped the transport would fail
    as a connection error rather than reach anything real.
    """
    return ArgoCd(
        ArgoCdSettings(
            argocd_base_url=DONT_CARE_BASE_URL,
            argocd_auth_token=auth_token,
            argocd_actor=argus,
            argocd_application_path="/api/v1/applications/{application}",
            argocd_resource_path="/api/v1/applications/{application}/resource",
            argocd_resource_action_path=(
                "/api/v1/applications/{application}/resource/actions/v2"
            ),
            argocd_rollback_path="/api/v1/applications/{application}/rollback",
            argocd_resource_tree_path=(
                "/api/v1/applications/{application}/resource-tree"
            ),
            argocd_manifests_path="/api/v1/applications/{application}/manifests",
            restart_namespace=SOME_RESTART_NAMESPACE,
            scale_namespace=SOME_SCALE_NAMESPACE
        ),
        transport=httpx2.MockTransport(platform)
    )


def _an_application(syncing: dict[str, Any] | None = None,
                    history: list[dict[str, Any]] | None = None,
                    metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """An application as `GET /api/v1/applications/{name}` returns one.

    `syncing` is the `automated` object, or `None` for an application with none.
    `metadata` is the application's own, where a case says what it carries.
    """
    sync_policy: dict[str, Any] = {} if syncing is None else {"automated": syncing}
    application: dict[str, Any] = {"spec": {"syncPolicy": sync_policy}, "status": {}}

    if history is not None:
        application["status"]["history"] = history

    if metadata is not None:
        application["metadata"] = metadata

    return application


def _a_managed_resource(manifest: dict[str, Any]) -> dict[str, Any]:
    """The resource route's wrapper: the manifest arrives as *text*."""
    return {"manifest": json.dumps(manifest)}


def _a_deployment_running(name: str, images: dict[str, str]) -> dict[str, Any]:
    """A Deployment named `name` whose pods start `images` - those named in
    `THE_INIT_CONTAINERS` as init containers, the rest as containers - beside
    the fields a real template carries and nobody compares."""
    def containers(init: bool) -> list[dict[str, Any]]:
        return [{"name": container, "image": image, "imagePullPolicy": "IfNotPresent"}
                for container, image in images.items()
                if (container in THE_INIT_CONTAINERS) is init]

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name},
        "spec": {"replicas": 3, "template": {"spec": {
            "initContainers": containers(init=True),
            "containers": containers(init=False)
        }}}
    }


def _a_tree_of(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"nodes": list(nodes)}


def _a_placed_tree(nodes: list[dict[str, Any]],
                   hosts: list[dict[str, Any]]) -> dict[str, Any]:
    """A tree with the nodes it lists its pods on, as Argo CD reports them."""
    return {"nodes": nodes, "hosts": hosts}


def _a_pod_on(name: str, node: str | None, created_at: str | None) -> dict[str, Any]:
    """A Pod as the tree lists it: its node said only as an info item."""
    pod: dict[str, Any] = {"kind": "Pod", "name": name, "namespace": "dont-care"}

    if created_at is not None:
        pod["createdAt"] = created_at

    if node is not None:
        pod["info"] = [
            {"name": "Status Reason", "value": "Running"},
            {"name": "Node", "value": node}
        ]

    return pod


def _a_host(name: str, card: str | None) -> dict[str, Any]:
    """A node as the tree's `hosts` lists it, labelled with its card where the
    platform reports that label."""
    labels = {"kubernetes.io/hostname": name}

    if card is not None:
        labels[THE_CARD_LABEL] = card

    return {"name": name, "labels": labels}


def _metadata_annotated(annotations: dict[str, str] | None) -> dict[str, Any]:
    """An object's own metadata, carrying `annotations` - or no such key where
    it is `None`, `annotations` being `omitempty` in Kubernetes' `ObjectMeta`."""
    metadata: dict[str, Any] = {"name": SOME_APPLICATION}

    if annotations is not None:
        metadata["annotations"] = annotations

    return metadata


def _a_platform_where(kind: MarkedObject, metadata: dict[str, Any]) -> _Platform:
    """The platform with the object `kind` names carrying `metadata` as its own.

    The application on its own route; the Deployment and the autoscaler as live
    manifests on the resource route, the autoscaler listed in the tree under
    `SOME_AUTOSCALER`'s name and namespace.
    """
    if kind == MarkedObject.APPLICATION:
        return _Platform().answering(
            GET, THE_APPLICATION, _ok(_an_application(metadata=metadata))
        )

    if kind == MarkedObject.DEPLOYMENT:
        return _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
            **_a_deployment_running(SOME_APPLICATION, THE_IMAGES), "metadata": metadata
        })))

    return _Platform() \
        .answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of({
            "kind": "HorizontalPodAutoscaler",
            "name": SOME_AUTOSCALER.name,
            "namespace": SOME_AUTOSCALER.namespace
        }))) \
        .answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
            "kind": "HorizontalPodAutoscaler",
            "metadata": metadata,
            "spec": {"minReplicas": 2, "maxReplicas": 10}
        })))


def _a_platform_with_no_autoscaler() -> _Platform:
    """The platform whose tree lists the application's Deployment and no
    autoscaler - `_a_platform_where`'s autoscaler case, with none to find."""
    return _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of(
        {"kind": "Deployment", "name": SOME_APPLICATION, "namespace": "dont-care"}
    )))


# ---------------------------------------------------------------------------
# Every request
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_request_carries_the_platform_credential() -> None:
    # A real Argo CD answers nothing to a caller it cannot identify, and one
    # request sent bare is one question that can never be answered.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application()))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform, auth_token=SOME_TOKEN)) \
        .when(lambda: argo_cd.is_syncing_itself(SOME_APPLICATION)) \
        .then(lambda _: _the_last_request_carried(
            platform, "Authorization", f"Bearer {SOME_TOKEN}"
        ))


@pytest.mark.unit
def test_an_empty_credential_sends_no_authorization_header() -> None:
    # A placeholder would send a real server something meaningless to reject.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application()))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform, auth_token="")) \
        .when(lambda: argo_cd.is_syncing_itself(SOME_APPLICATION)) \
        .then(lambda _: _the_last_request_carried_no(platform, "Authorization"))


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_applications_deployments_are_read_from_its_history() -> None:
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application(
        history=[{
            "id": 7,
            "revision": "26f1d7e",
            "deployedAt": "2026-10-07T09:14:00Z",
            "deployStartedAt": "2026-10-07T09:13:00Z",
            "source": {"repoURL": "https://github.com/kuki/configs", "path": "apps/shop"},
            "initiatedBy": {"username": SOMEBODY_ELSE}
        }]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.deployments_of(SOME_APPLICATION)) \
        .then(the_answer_was([
            DeploymentRecord(
                history_id=7,
                revision="26f1d7e",
                deployed_at="2026-10-07T09:14:00Z",
                repo_url="https://github.com/kuki/configs",
                path="apps/shop",
                initiated_by=SOMEBODY_ELSE,
                made_by_argus=False
            )
        ]))


@pytest.mark.unit
@pytest.mark.parametrize(("argus", "started_by", "whether_it_was_argus"),
                         EVERY_WAY_WHOSE_A_CHANGE_IS_TOLD)
def test_whether_argus_started_a_deployment_is_told_by_the_account_it_signs_in_as(
    argus: str,
    started_by: str | None,
    whether_it_was_argus: bool | None
) -> None:
    initiated_by = {} if started_by is None else {"initiatedBy": {"username": started_by}}
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application(
        history=[{"id": 3, "revision": "abc1234", "deployedAt": "2026-10-07T09:00:00Z",
                  **initiated_by}]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform, argus=argus)) \
        .when(lambda: argo_cd.deployments_of(SOME_APPLICATION)[0].made_by_argus) \
        .then(the_answer_was(whether_it_was_argus))


@pytest.mark.unit
def test_deployments_come_back_in_the_order_the_platform_served_them() -> None:
    # Ordering by time is a reader's decision, and the rollback's "the one before
    # the one running" is the platform's own order - so this keeps it.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application(
        history=[
            _a_history_entry(history_id=2, deployed_at="2026-10-07T10:00:00Z"),
            _a_history_entry(history_id=1, deployed_at="2026-10-07T09:00:00Z")
        ]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: [
            record.history_id for record in argo_cd.deployments_of(SOME_APPLICATION)
        ]) \
        .then(the_answer_was([2, 1]))


@pytest.mark.unit
def test_an_application_never_deployed_has_no_deployments() -> None:
    # `history` is `omitempty` in Argo CD's own type, so its absence is an
    # ordinary answer rather than a malformed one.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application()))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.deployments_of(SOME_APPLICATION)) \
        .then(the_answer_was([]))


@pytest.mark.unit
def test_a_deployment_naming_no_source_or_initiator_says_so() -> None:
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application(
        history=[{"id": 3, "revision": "abc1234", "deployedAt": "2026-10-07T09:00:00Z"}]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.deployments_of(SOME_APPLICATION)) \
        .then(the_answer_was([
            DeploymentRecord(
                history_id=3,
                revision="abc1234",
                deployed_at="2026-10-07T09:00:00Z",
                repo_url=None,
                path=None,
                initiated_by=None
            )
        ]))


@pytest.mark.unit
def test_a_deployment_synced_from_the_repositorys_root_names_no_directory() -> None:
    # "." is Argo CD's word for the root, and nothing past this adapter speaks
    # Argo CD: the root is no directory within the repository to name.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application(
        history=[{"id": 3, "revision": "abc1234", "deployedAt": "2026-10-07T09:00:00Z",
                  "source": {"repoURL": "https://github.com/kuki/configs", "path": "."}}]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.deployments_of(SOME_APPLICATION)[0].path) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_a_deployment_with_no_revision_is_refused_rather_than_guessed() -> None:
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application(
        history=[{"id": 3, "deployedAt": "2026-10-07T09:00:00Z"}]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.deployments_of(SOME_APPLICATION))) \
        .then(an_error_was_raised(PlatformRefused))


@pytest.mark.unit
def test_a_rollout_is_read_from_the_running_deployment() -> None:
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"replicas": 6},
        "status": {"replicas": 7, "updatedReplicas": 4}
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.rollout_of(SOME_APPLICATION)) \
        .then(the_answer_was(RolloutProgress(
            replicas_wanted=6,
            replicas_serving=7,
            replicas_updated=4,
            is_paused=False,
            has_failed=False
        )))


@pytest.mark.unit
def test_the_running_deployment_is_asked_for_by_the_deployment_s_own_selectors() -> None:
    # Argo CD finds a live resource by group, kind, namespace and name, and
    # refuses a request that names none of them.
    platform = _Platform().answering(
        GET, THE_RESOURCE, _ok(_a_managed_resource({"spec": {"replicas": 3}}))
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.rollout_of(SOME_APPLICATION)) \
        .then(lambda _: _the_last_request_was(platform, GET, THE_RESOURCE,
                                              query=THE_DEPLOYMENT_SELECTORS))


@pytest.mark.unit
def test_a_deployment_reporting_no_rollout_status_reads_as_converged() -> None:
    # Nothing in it says any replica is lagging, so none is. Assuming a split
    # would invent an incident out of a field the platform did not fill in.
    platform = _Platform().answering(
        GET, THE_RESOURCE, _ok(_a_managed_resource({"spec": {"replicas": 3}}))
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.rollout_of(SOME_APPLICATION)) \
        .then(the_answer_was(RolloutProgress(
            replicas_wanted=3,
            replicas_serving=3,
            replicas_updated=3,
            is_paused=False,
            has_failed=False
        )))


@pytest.mark.unit
def test_a_paused_rollout_says_so() -> None:
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"replicas": 3, "paused": True},
        "status": {"replicas": 3, "updatedReplicas": 1}
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.rollout_of(SOME_APPLICATION).is_paused) \
        .then(the_answer_was(True))


@pytest.mark.unit
@pytest.mark.parametrize(
    "condition",
    [
        {"type": "ReplicaFailure", "status": "True"},
        {"type": "Progressing", "status": "False"}
    ],
    ids=["pods it could not create", "no progress within the deadline"]
)
def test_a_deployment_the_platform_cannot_finish_has_failed(
    condition: dict[str, str]
) -> None:
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"replicas": 6},
        "status": {"replicas": 3, "updatedReplicas": 3, "conditions": [condition]}
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.rollout_of(SOME_APPLICATION).has_failed) \
        .then(the_answer_was(True))


@pytest.mark.unit
def test_a_deployment_still_progressing_has_not_failed() -> None:
    # A paused Deployment reports `Progressing` as `Unknown`, and an ordinary one
    # as `True`; neither is the platform saying it cannot finish.
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"replicas": 6},
        "status": {
            "replicas": 6,
            "updatedReplicas": 3,
            "conditions": [{"type": "Progressing", "status": "Unknown"}]
        }
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.rollout_of(SOME_APPLICATION).has_failed) \
        .then(the_answer_was(False))


@pytest.mark.unit
def test_a_manifest_that_does_not_say_its_size_is_refused() -> None:
    # A guessed count is how a scale-out halves a shop serving three, and how a
    # rollout nobody can read is reported as one that converged.
    platform = _Platform().answering(
        GET, THE_RESOURCE, _ok(_a_managed_resource({"spec": {}}))
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.rollout_of(SOME_APPLICATION))) \
        .then(an_error_was_raised(PlatformRefused))


@pytest.mark.unit
def test_a_resource_whose_manifest_is_not_json_is_refused() -> None:
    platform = _Platform().answering(
        GET, THE_RESOURCE, _ok({"manifest": "kind: Deployment"})
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.rollout_of(SOME_APPLICATION))) \
        .then(an_error_was_raised(PlatformRefused))


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("automated", "expected"),
    [
        ({}, True),
        ({"enabled": True}, True),
        ({"enabled": False}, False),
        (None, False)
    ],
    ids=[
        "an empty automated object",
        "automated and enabled",
        "automated but switched off",
        "no automated object"
    ]
)
def test_whether_an_application_syncs_itself_is_read_as_argo_cd_reads_it(
    automated: dict[str, Any] | None, expected: bool
) -> None:
    # `SyncPolicy.IsAutomatedSyncEnabled`: the object present, and `enabled`
    # absent or true. An `automated` of `{}` is automated, and reading it as false
    # would leave an action to be refused by a server this had called compliant.
    platform = _Platform().answering(
        GET, THE_APPLICATION, _ok(_an_application(syncing=automated))
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.is_syncing_itself(SOME_APPLICATION)) \
        .then(the_answer_was(expected))


@pytest.mark.unit
def test_suspending_sync_merge_patches_the_switch_alone_beside_the_mark() -> None:
    # Not the spec route, which replaces the whole spec; and not an `automated`
    # object of Argus's own, which would replace the operator's prune and
    # selfHeal. The mark rides in the same patch, on the application's own
    # metadata, so the change and what says whose it was land together.
    platform = _Platform().answering(PATCH, THE_APPLICATION, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.suspend_sync(SOME_APPLICATION, SOME_MARK)) \
        .then(lambda _: _the_last_request_was(
            platform, PATCH, THE_APPLICATION,
            body=_a_sync_patch_setting_enabled_to(False)
        ))


@pytest.mark.unit
def test_resuming_sync_removes_the_switch_beside_the_mark() -> None:
    # A merge patch's `null` removes the key, which the platform reads as on -
    # what was found, since an application syncing itself had it absent or true.
    platform = _Platform().answering(PATCH, THE_APPLICATION, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.resume_sync(SOME_APPLICATION, SOME_MARK)) \
        .then(lambda _: _the_last_request_was(
            platform, PATCH, THE_APPLICATION,
            body=_a_sync_patch_setting_enabled_to(None)
        ))


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scaling_merge_patches_the_deployments_count_beside_the_mark() -> None:
    # A merge patch on the Deployment rather than the built-in `scale` action,
    # because an action's Lua writes only what it was written to and has no room
    # for the mark - and a write that cannot say whose it was is one nobody can
    # tell from a person's. The count is a number here: it is the manifest's own
    # field, not an action's parameter.
    some_replicas = 6
    platform = _Platform().answering(POST, THE_RESOURCE, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.scale(SOME_APPLICATION, some_replicas, SOME_MARK)) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE,
            query={
                **THE_DEPLOYMENT_SELECTORS,
                "patchType": "application/merge-patch+json"
            },
            body=json.dumps({
                "metadata": THE_MARKED_METADATA,
                "spec": {"replicas": some_replicas}
            })
        ))


@pytest.mark.unit
def test_scaling_asks_nothing_of_the_resource_actions() -> None:
    # One request, and the patch is it. A scale that still ran the action
    # beside the patch would make the change twice, once unmarked.
    some_replicas = 6
    platform = _Platform() \
        .answering(POST, THE_RESOURCE, _ok()) \
        .answering(POST, THE_RESOURCE_ACTIONS, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.scale(SOME_APPLICATION, some_replicas, SOME_MARK)) \
        .then(lambda _: _only_these_were_asked(platform, [(POST, THE_RESOURCE)]))


@pytest.mark.unit
@pytest.mark.parametrize(
    "written_at",
    [
        SOME_MARK.written_at.replace(microsecond=999999),
        SOME_MARK.written_at.astimezone(timezone(timedelta(hours=2)))
    ],
    ids=["a moment late in its second", "a moment in another zone"]
)
def test_the_moment_a_write_was_made_is_said_in_utc_to_the_second(
    written_at: datetime
) -> None:
    # One spelling whichever moment it was handed: an annotation read beside
    # the platform's own timestamps, which are UTC to the second, and compared
    # by a person against them.
    platform = _Platform().answering(POST, THE_RESOURCE, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.pin_to_accelerator(
            SOME_APPLICATION, SOME_CARD,
            Mark(action_id=SOME_MARK.action_id, written_at=written_at)
        )) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE,
            body=json.dumps({
                "metadata": THE_MARKED_METADATA,
                "spec": {"template": {"spec": {"nodeSelector": {THE_CARD_LABEL: SOME_CARD}}}}
            })
        ))


@pytest.mark.unit
def test_restarting_runs_the_built_in_restart_action_on_the_services_deployment() -> None:
    # Addressed by the service, never a configured name: a fixed name carried
    # one deployment into every request and restarted the wrong thing.
    some_service = "io-pricing"
    the_services_actions = f"/api/v1/applications/{some_service}/resource/actions/v2"
    platform = _Platform().answering(POST, the_services_actions, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.restart(some_service)) \
        .then(lambda _: _the_last_request_was(
            platform, POST, the_services_actions,
            body={
                "namespace": SOME_RESTART_NAMESPACE,
                "resourceName": some_service,
                "group": "apps",
                "kind": "Deployment",
                "action": "restart"
            }
        ))


@pytest.mark.unit
def test_rolling_back_names_the_history_entry_to_return_to() -> None:
    some_history_id = 41
    platform = _Platform().answering(POST, THE_ROLLBACK, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.roll_back(SOME_APPLICATION, some_history_id)) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_ROLLBACK,
            body={"name": SOME_APPLICATION, "id": some_history_id}
        ))


@pytest.mark.unit
def test_the_newest_pod_is_the_one_serving() -> None:
    # A rollout has two pods in it for a while, and the older one is precisely the
    # process a restart has to be told apart from. Only pods: the Deployment and
    # the ReplicaSet were created when somebody declared them.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of(
        {"kind": "Deployment", "createdAt": "2026-10-07T11:00:00Z"},
        {"kind": "Pod", "createdAt": "2026-10-07T09:00:00Z"},
        {"kind": "Pod", "createdAt": "2026-10-07T09:05:00Z"}
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.newest_pod_started_at(SOME_APPLICATION)) \
        .then(the_answer_was(datetime(2026, 10, 7, 9, 5, tzinfo=UTC).timestamp()))


@pytest.mark.unit
def test_nothing_running_is_no_start_time_at_all() -> None:
    # The absence of a reading, not a reading of no change - which is what the
    # restart's wait turns on.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of(
        {"kind": "Deployment", "createdAt": "2026-10-07T11:00:00Z"}
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.newest_pod_started_at(SOME_APPLICATION)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_a_pod_whose_start_cannot_be_read_is_passed_over() -> None:
    # A crash on one unparseable timestamp would report an unconfirmable restart
    # as a broken one.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of(
        {"kind": "Pod", "createdAt": "not a moment"},
        {"kind": "Pod"},
        {"kind": "Pod", "createdAt": "2026-10-07T09:00:00Z"}
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.newest_pod_started_at(SOME_APPLICATION)) \
        .then(the_answer_was(datetime(2026, 10, 7, 9, 0, tzinfo=UTC).timestamp()))


@pytest.mark.unit
def test_a_pod_whose_start_cannot_be_read_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Passed over, so a restart can still be confirmed by the pods that can be
    # read - but a platform reporting a time this cannot read is one that has
    # changed its format, and every pod after it will be passed over too.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of(
        {"kind": "Pod", "name": "unreadable", "createdAt": "not a moment"},
        {"kind": "Pod", "name": "readable", "createdAt": "2026-10-07T09:00:00Z"}
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.newest_pod_started_at(SOME_APPLICATION)) \
        .then(
            one_record_was_logged(caplog, "deployment_platform.argocd", logging.WARNING,
                                  "pod start time unreadable",
                                  values={"application": SOME_APPLICATION, "pod": "unreadable"})
        )


@pytest.mark.unit
def test_the_autoscaler_is_found_in_the_resource_tree() -> None:
    # Its name is whoever wrote the chart's, so it is read rather than configured.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of(
        {"kind": "Deployment", "name": SOME_APPLICATION, "namespace": "dont-care"},
        {
            "kind": "HorizontalPodAutoscaler",
            "name": SOME_AUTOSCALER.name,
            "namespace": SOME_AUTOSCALER.namespace
        }
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.autoscaler_of(SOME_APPLICATION)) \
        .then(the_answer_was(SOME_AUTOSCALER))


@pytest.mark.unit
def test_an_application_with_no_autoscaler_has_none() -> None:
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of(
        {"kind": "Deployment", "name": SOME_APPLICATION, "namespace": "dont-care"}
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.autoscaler_of(SOME_APPLICATION)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_the_autoscalers_bounds_are_read_from_its_live_manifest() -> None:
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"minReplicas": 2, "maxReplicas": 10}
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.autoscaler_bounds(SOME_APPLICATION, SOME_AUTOSCALER)) \
        .then(all_of(
            the_answer_was(AutoscalerBounds(floor=2, ceiling=10)),
            lambda _: _the_last_request_was(
                platform, GET, THE_RESOURCE, query=THE_AUTOSCALER_SELECTORS
            )
        ))


@pytest.mark.unit
def test_an_autoscaler_missing_a_bound_is_refused() -> None:
    # A guessed ceiling would hold a shop at a size nobody declared.
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"minReplicas": 2}
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(
            lambda: argo_cd.autoscaler_bounds(SOME_APPLICATION, SOME_AUTOSCALER)
        )) \
        .then(an_error_was_raised(PlatformRefused))


@pytest.mark.unit
def test_raising_the_floor_merge_patches_the_floor_alone_as_text_beside_the_mark() -> None:
    # The resource route's patch is a JSON-encoded *string*, and of the spec it
    # says only the floor: a body carrying the ceiling would re-assert a human's
    # declaration as though Argus had decided it.
    some_floor = 10
    platform = _Platform().answering(POST, THE_RESOURCE, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.set_autoscaler_floor(
            SOME_APPLICATION, SOME_AUTOSCALER, some_floor, SOME_MARK
        )) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE,
            query={
                **THE_AUTOSCALER_SELECTORS,
                "patchType": "application/merge-patch+json"
            },
            body=json.dumps({
                "metadata": THE_MARKED_METADATA,
                "spec": {"minReplicas": some_floor}
            })
        ))


@pytest.mark.unit
def test_each_pods_node_and_card_are_read_from_the_tree() -> None:
    # The node off the pod's own info, and the card off the host of that name:
    # the tree says the two things in two places, and only together do they say
    # what a replica is running on.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_placed_tree(
        nodes=[
            {"kind": "Deployment", "name": SOME_APPLICATION, "namespace": "dont-care"},
            _a_pod_on("io-shop-a", "gpu-1", "2026-10-07T09:00:00Z"),
            _a_pod_on("io-shop-b", "gpu-2", "2026-10-07T21:40:30Z")
        ],
        hosts=[_a_host("gpu-1", SOME_CARD), _a_host("gpu-2", SOME_OTHER_CARD)]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.placements_of(SOME_APPLICATION)) \
        .then(all_of(
            the_answer_was([
                PodPlacement(
                    pod="io-shop-a",
                    node="gpu-1",
                    accelerator=SOME_CARD,
                    started_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
                ),
                PodPlacement(
                    pod="io-shop-b",
                    node="gpu-2",
                    accelerator=SOME_OTHER_CARD,
                    started_at=datetime(2026, 10, 7, 21, 40, 30, tzinfo=UTC)
                )
            ]),
            lambda _: _the_last_request_was(platform, GET, THE_RESOURCE_TREE)
        ))


@pytest.mark.unit
def test_a_node_the_platform_reports_no_card_for_has_none() -> None:
    # A platform not configured to report the label, or a node carrying no GPU,
    # says nothing about a card - and nothing is not a guess at one.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_placed_tree(
        nodes=[_a_pod_on("io-shop-a", "general-0", "2026-10-07T09:00:00Z")],
        hosts=[_a_host("general-0", None)]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: [
            placement.accelerator
            for placement in argo_cd.placements_of(SOME_APPLICATION)
        ]) \
        .then(the_answer_was([None]))


@pytest.mark.unit
def test_a_tree_listing_no_hosts_reports_no_card_for_any_pod() -> None:
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_tree_of(
        _a_pod_on("io-shop-a", "gpu-1", "2026-10-07T09:00:00Z")
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: [
            (placement.node, placement.accelerator)
            for placement in argo_cd.placements_of(SOME_APPLICATION)
        ]) \
        .then(the_answer_was([("gpu-1", None)]))


@pytest.mark.unit
def test_a_pod_not_yet_placed_or_with_no_readable_start_is_passed_over() -> None:
    # A pod still pending has no node, and one whose start cannot be read cannot
    # be put either side of an onset - and either, read as something, would be a
    # replica placed somewhere nobody saw.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_placed_tree(
        nodes=[
            _a_pod_on("pending", None, "2026-10-07T09:00:00Z"),
            _a_pod_on("unreadable", "gpu-1", "not a moment"),
            _a_pod_on("undated", "gpu-1", None),
            _a_pod_on("placed", "gpu-1", "2026-10-07T09:00:00Z")
        ],
        hosts=[_a_host("gpu-1", SOME_CARD)]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: [
            placement.pod for placement in argo_cd.placements_of(SOME_APPLICATION)
        ]) \
        .then(the_answer_was(["placed"]))


@pytest.mark.unit
def test_a_placed_pod_whose_start_cannot_be_read_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # A pending pod is ordinary and says nothing. A placed one whose start
    # cannot be read is a replica the onset comparison never sees, and the
    # answer that comes back is short by it without saying so.
    platform = _Platform().answering(GET, THE_RESOURCE_TREE, _ok(_a_placed_tree(
        nodes=[
            _a_pod_on("pending", None, "2026-10-07T09:00:00Z"),
            _a_pod_on("unreadable", "gpu-1", "not a moment"),
            _a_pod_on("placed", "gpu-1", "2026-10-07T09:00:00Z")
        ],
        hosts=[_a_host("gpu-1", SOME_CARD)]
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.placements_of(SOME_APPLICATION)) \
        .then(
            one_record_was_logged(caplog, "deployment_platform.argocd", logging.WARNING,
                                  "pod start time unreadable",
                                  values={"application": SOME_APPLICATION, "pod": "unreadable"})
        )


@pytest.mark.unit
def test_the_card_a_deployment_is_pinned_to_is_read_off_its_live_selector() -> None:
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"template": {"spec": {"nodeSelector": {
            "kubernetes.io/os": "linux",
            THE_CARD_LABEL: SOME_CARD
        }}}}
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.accelerator_pin_of(SOME_APPLICATION)) \
        .then(all_of(
            the_answer_was(SOME_CARD),
            lambda _: _the_last_request_was(
                platform, GET, THE_RESOURCE, query=THE_DEPLOYMENT_SELECTORS
            )
        ))


@pytest.mark.unit
def test_a_deployment_selecting_no_card_is_pinned_to_none() -> None:
    # Other selectors are somebody else's and say nothing about a card.
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/os": "linux"}}}}
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.accelerator_pin_of(SOME_APPLICATION)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_a_deployment_with_no_selector_at_all_is_pinned_to_none() -> None:
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource({
        "spec": {"replicas": 3}
    })))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.accelerator_pin_of(SOME_APPLICATION)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_the_images_running_are_read_off_the_live_deployments_template() -> None:
    # Every container the pods start, init containers too, by name: a `kubectl
    # set image` can change any of them, and a put-back compares all of them
    # with what the revision renders.
    platform = _Platform().answering(GET, THE_RESOURCE, _ok(_a_managed_resource(
        _a_deployment_running(SOME_APPLICATION, THE_IMAGES)
    )))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.images_running(SOME_APPLICATION)) \
        .then(all_of(
            the_answer_was(THE_IMAGES),
            lambda _: _the_last_request_was(
                platform, GET, THE_RESOURCE, query=THE_DEPLOYMENT_SELECTORS
            )
        ))


@pytest.mark.unit
def test_the_images_a_revision_renders_are_read_off_its_manifests() -> None:
    # Argo CD's `ManifestResponse` carries each manifest the revision renders as
    # text. The application's own Deployment is the one of that kind and name;
    # a Service beside it, or another chart's Deployment, says nothing about it.
    some_revision = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
    another_deployment = "io-shop-worker"
    platform = _Platform().answering(GET, THE_MANIFESTS, _ok({"manifests": [
        json.dumps({"kind": "Service", "metadata": {"name": SOME_APPLICATION}}),
        json.dumps(_a_deployment_running(another_deployment, SOME_OTHER_IMAGES)),
        json.dumps(_a_deployment_running(SOME_APPLICATION, THE_IMAGES))
    ]}))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.images_at(SOME_APPLICATION, some_revision)) \
        .then(all_of(
            the_answer_was(THE_IMAGES),
            lambda _: _the_last_request_was(
                platform, GET, THE_MANIFESTS, query={"revision": some_revision}
            )
        ))


@pytest.mark.unit
def test_a_revision_rendering_no_deployment_of_the_application_is_refused() -> None:
    # Answered as no images at all, a put-back would compare the images running
    # with nothing and call Argus's own rollback somebody else's.
    dont_care_revision = "544cef3"
    platform = _Platform().answering(GET, THE_MANIFESTS, _ok({"manifests": [
        json.dumps({"kind": "Service", "metadata": {"name": SOME_APPLICATION}})
    ]}))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.images_at(SOME_APPLICATION, dont_care_revision))) \
        .then(an_error_was_raised(PlatformRefused))


@pytest.mark.unit
def test_pinning_merge_patches_the_card_label_alone_as_text_beside_the_mark() -> None:
    # The template's selector and, of it, only the card. A patch carrying the
    # whole selector would replace selectors somebody else declared.
    platform = _Platform().answering(POST, THE_RESOURCE, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.pin_to_accelerator(SOME_APPLICATION, SOME_CARD, SOME_MARK)) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE,
            query={
                **THE_DEPLOYMENT_SELECTORS,
                "patchType": "application/merge-patch+json"
            },
            body=json.dumps({
                "metadata": THE_MARKED_METADATA,
                "spec": {"template": {"spec": {"nodeSelector": {THE_CARD_LABEL: SOME_CARD}}}}
            })
        ))


@pytest.mark.unit
def test_releasing_a_pin_removes_the_card_label_with_a_null_beside_the_mark() -> None:
    # RFC 7386's own way of deleting a key, which is what an undo of a pin onto a
    # deployment that had none has to send. The undo is a write of Argus's as
    # much as the pin was, and is marked as one.
    platform = _Platform().answering(POST, THE_RESOURCE, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.pin_to_accelerator(SOME_APPLICATION, None, SOME_MARK)) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE,
            body=json.dumps({
                "metadata": THE_MARKED_METADATA,
                "spec": {"template": {"spec": {"nodeSelector": {THE_CARD_LABEL: None}}}}
            })
        ))


# ---------------------------------------------------------------------------
# The platform's clock, and Argus's marks
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "date",
    [THE_IMF_FIXDATE, THE_OBSOLETE_RFC_850_DATE, THE_ASCTIME_DATE],
    ids=["IMF-fixdate", "obsolete RFC 850", "asctime"]
)
def test_the_platforms_clock_is_read_off_the_date_the_application_is_served_with(
    date: str
) -> None:
    # The platform's own moment rather than Argus's, so that a change it records
    # is put either side of a moment on the same clock. Off the application's
    # route, a read the adapter makes already. RFC 9110 (5.6.7) has a recipient
    # accept all three of its formats, and these are its own spellings of one
    # moment.
    platform = _Platform().answering(
        GET, THE_APPLICATION, _ok_dated(date, _an_application())
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.now(SOME_APPLICATION)) \
        .then(all_of(
            the_answer_was(THE_MOMENT_RFC_9110_SPELLS),
            lambda _: _only_these_were_asked(platform, [(GET, THE_APPLICATION)])
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "date", [None, "not a moment"], ids=["no date", "a date that is not one"]
)
def test_an_answer_that_does_not_say_when_it_was_given_is_refused(
    date: str | None
) -> None:
    # Argus's own clock in its place would be a moment a change the platform
    # recorded could fall the wrong side of. Refused rather than unreachable,
    # because the platform answered - and a read, so nothing was changed.
    platform = _Platform().answering(
        GET, THE_APPLICATION, _ok_dated(date, _an_application())
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.now(SOME_APPLICATION))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _it_was_known_not_applied(True)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "asked", "selectors"),
    [
        (MarkedObject.APPLICATION, [(GET, THE_APPLICATION)], {}),
        (MarkedObject.DEPLOYMENT, [(GET, THE_RESOURCE)], THE_DEPLOYMENT_SELECTORS),
        (
            MarkedObject.AUTOSCALER,
            [(GET, THE_RESOURCE_TREE), (GET, THE_RESOURCE)],
            THE_AUTOSCALER_SELECTORS
        )
    ],
    ids=["the application", "the deployment", "the autoscaler"]
)
def test_the_mark_on_an_object_is_read_off_its_own_metadata(
    kind: MarkedObject, asked: list[tuple[str, str]], selectors: dict[str, str]
) -> None:
    # Where each write puts it: the application's on its own route, the
    # Deployment's and the autoscaler's on their live manifests - the autoscaler
    # addressed as the tree names it, as its pin is. What comes back is the
    # action it was made for and the moment it says it was written, read from
    # beside somebody else's annotations.
    platform = _a_platform_where(kind, _metadata_annotated({
        **SOMEBODY_ELSES_ANNOTATIONS, **THE_MARKED_METADATA["annotations"]
    }))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.mark_on(SOME_APPLICATION, kind)) \
        .then(all_of(
            the_answer_was(MarkFound(action_id=SOME_MARK.action_id,
                                     written_at=THE_MOMENT_THE_MARK_SAYS)),
            lambda _: _only_these_were_asked(platform, asked),
            lambda _: _the_last_request_was(platform, GET, asked[-1][1], query=selectors)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "kind",
    [MarkedObject.APPLICATION, MarkedObject.DEPLOYMENT, MarkedObject.AUTOSCALER],
    ids=["the application", "the deployment", "the autoscaler"]
)
@pytest.mark.parametrize(
    "annotations",
    [None, SOMEBODY_ELSES_ANNOTATIONS],
    ids=["no annotations", "somebody else's alone"]
)
def test_an_object_carrying_no_mark_has_none(
    kind: MarkedObject, annotations: dict[str, str] | None
) -> None:
    # An object Argus never wrote carries no mark, and may carry no annotations
    # at all - `omitempty` in Kubernetes' own `ObjectMeta`. Either is an
    # ordinary answer: nothing on it says Argus changed it.
    platform = _a_platform_where(kind, _metadata_annotated(annotations))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.mark_on(SOME_APPLICATION, kind)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_a_sync_asked_and_not_yet_run_is_read_off_the_application_s_operation() -> None:
    # Argo CD records a sync - a rollback is one - in the application's
    # `operation` the moment it answers the request, before the controller has
    # started it, so there is no state of its run yet.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok({
        **_an_application(),
        "operation": {"sync": {"revision": SOME_REVISION},
                      "initiatedBy": {"username": SOME_ACCOUNT}}
    }))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.sync_operations_of(SOME_APPLICATION)) \
        .then(the_answer_was(SyncOperations(
            requested=RequestedSync(revision=SOME_REVISION, initiated_by=SOME_ACCOUNT,
                                    made_by_argus=SOME_ACCOUNT_IS_ARGUS_S),
            last_run=None
        )))


@pytest.mark.unit
@pytest.mark.parametrize(("argus", "started_by", "whether_it_was_argus"),
                         EVERY_WAY_WHOSE_A_CHANGE_IS_TOLD)
def test_whether_argus_asked_for_a_sync_is_told_as_whether_it_started_a_deployment(
    argus: str,
    started_by: str | None,
    whether_it_was_argus: bool | None
) -> None:
    # The write tier reads whose a sync is off the request and off the run, as
    # the read tier reads whose a deployment is: one rule, the adapter's.
    asked_by = {} if started_by is None else {"username": started_by}
    operation = {"sync": {"revision": SOME_REVISION}, "initiatedBy": asked_by}
    platform = _Platform().answering(GET, THE_APPLICATION, _ok({
        **_an_application(),
        "operation": operation,
        "status": {"operationState": {"operation": operation, "phase": "Running",
                                      "startedAt": SOME_SYNC_START}}
    }))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform, argus=argus)) \
        .when(lambda: argo_cd.sync_operations_of(SOME_APPLICATION)) \
        .then(_whose_each_sync_is(whether_it_was_argus))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("phase", "read_as"),
    [("Running", SyncPhase.RUNNING), ("Succeeded", SyncPhase.SUCCEEDED),
     ("Failed", SyncPhase.FAILED), ("Error", SyncPhase.ERROR),
     ("Terminating", SyncPhase.TERMINATING)]
)
def test_the_last_sync_run_is_read_off_the_application_s_operation_state(
    phase: str, read_as: SyncPhase
) -> None:
    # The controller's own account of the last sync it ran: what it was to and
    # who asked, when it started, and where it stands - in Argo CD's words for
    # the last, read as Argus's.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok({
        **_an_application(),
        "status": {"operationState": {
            "operation": {"sync": {"revision": SOME_REVISION},
                          "initiatedBy": {"username": SOME_ACCOUNT}},
            "phase": phase,
            "startedAt": SOME_SYNC_START
        }}
    }))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.sync_operations_of(SOME_APPLICATION)) \
        .then(the_answer_was(SyncOperations(
            requested=None,
            last_run=SyncRun(revision=SOME_REVISION, initiated_by=SOME_ACCOUNT,
                             started_at=THE_SYNC_START_READ, phase=read_as,
                             made_by_argus=SOME_ACCOUNT_IS_ARGUS_S)
        )))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("phase", "message", "read_as"),
    [
        pytest.param("Failed", THE_TERMINATED_RUN_S_MESSAGE, SyncPhase.TERMINATED,
                     id="terminated"),
        pytest.param("Error", THE_ERRED_TERMINATION_S_MESSAGE, SyncPhase.TERMINATED,
                     id="termination-had-errors"),
        pytest.param("Error", THE_UNREAD_HOOK_S_MESSAGE, SyncPhase.TERMINATED,
                     id="termination-could-not-read-a-hook"),
        pytest.param("Failed", A_FAILED_RUN_S_MESSAGE, SyncPhase.FAILED,
                     id="failed-of-itself"),
        pytest.param("Error", AN_ERRORED_RUN_S_MESSAGE, SyncPhase.ERROR,
                     id="errored-of-itself")
    ]
)
def test_a_run_somebody_terminated_is_read_apart_from_one_that_failed_of_itself(
    phase: str, message: str, read_as: SyncPhase
) -> None:
    # A terminated run finishes failed or errored, as one that failed of itself
    # does - its message is all that tells the two apart, and only the adapter
    # knows the words. Terminated is somebody's stop; failed is nobody's.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok({
        **_an_application(),
        "status": {"operationState": {
            "operation": {"sync": {"revision": SOME_REVISION},
                          "initiatedBy": {"username": SOME_ACCOUNT}},
            "phase": phase,
            "message": message,
            "startedAt": SOME_SYNC_START
        }}
    }))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.sync_operations_of(SOME_APPLICATION)) \
        .then(the_answer_was(SyncOperations(
            requested=None,
            last_run=SyncRun(revision=SOME_REVISION, initiated_by=SOME_ACCOUNT,
                             started_at=THE_SYNC_START_READ, phase=read_as,
                             made_by_argus=SOME_ACCOUNT_IS_ARGUS_S)
        )))


@pytest.mark.unit
def test_an_application_with_no_sync_asked_or_run_says_neither() -> None:
    # The demo's stand-in keeps no state of its runs, and an application
    # nobody has synced has none either: an ordinary answer, and a caller has
    # the history alone.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok(_an_application()))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.sync_operations_of(SOME_APPLICATION)) \
        .then(the_answer_was(SyncOperations(requested=None, last_run=None)))


@pytest.mark.unit
def test_a_sync_asked_by_the_platform_itself_names_nobody() -> None:
    # An automated sync carries `initiatedBy.automated` and no username.
    platform = _Platform().answering(GET, THE_APPLICATION, _ok({
        **_an_application(),
        "operation": {"sync": {"revision": SOME_REVISION},
                      "initiatedBy": {"automated": True}}
    }))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.sync_operations_of(SOME_APPLICATION)) \
        .then(the_answer_was(SyncOperations(
            requested=RequestedSync(revision=SOME_REVISION, initiated_by=None),
            last_run=None
        )))


@pytest.mark.unit
def test_a_rollback_refused_while_another_operation_is_in_progress_may_yet_land() -> None:
    # Argo CD answers a rollback asked while a sync is still being run with a
    # 400 - and that sync may be the very rollback asked a moment before, whose
    # answer was lost. Refused, but nothing says the change will not land.
    platform = _Platform().answering(POST, THE_ROLLBACK, httpx2.Response(
        400, json={"error": ANOTHER_OPERATION_IN_PROGRESS,
                   "message": ANOTHER_OPERATION_IN_PROGRESS, "code": FAILED_PRECONDITION}
    ))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.roll_back(SOME_APPLICATION, SOME_HISTORY_ID))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _it_was_known_not_applied(False)
        ))


@pytest.mark.unit
def test_a_mark_on_the_pod_template_is_not_the_deployments() -> None:
    # Argus marks the Deployment's own metadata and never its pod template's,
    # which would roll every pod. A mark found in the template is not one Argus
    # wrote there, and says nothing about whose the Deployment's change was.
    deployment = _a_deployment_running(SOME_APPLICATION, THE_IMAGES)
    deployment["spec"]["template"]["metadata"] = THE_MARKED_METADATA
    platform = _Platform().answering(
        GET, THE_RESOURCE, _ok(_a_managed_resource(deployment))
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.mark_on(SOME_APPLICATION, MarkedObject.DEPLOYMENT)) \
        .then(the_answer_was(None))


@pytest.mark.unit
def test_an_application_with_no_autoscaler_has_no_mark_on_one() -> None:
    # Not every application has an autoscaler, and one that has none has no
    # mark on one - an ordinary answer, read off the tree alone, with no
    # manifest asked for an object nobody could name.
    platform = _a_platform_with_no_autoscaler()

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.mark_on(SOME_APPLICATION, MarkedObject.AUTOSCALER)) \
        .then(all_of(
            the_answer_was(None),
            lambda _: _only_these_were_asked(platform, [(GET, THE_RESOURCE_TREE)])
        ))


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [httpx2.ConnectError("connection refused"), httpx2.ReadTimeout("timed out")],
    ids=["refused", "timed out"]
)
def test_a_platform_that_never_answered_is_unreachable(failure: Exception) -> None:
    def never_answering(request: httpx2.Request) -> httpx2.Response:
        raise failure

    Scenario() \
        .given(argo_cd := _argo_cd_over(never_answering)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION, SOME_MARK))) \
        .then(an_error_was_raised(PlatformUnreachable))


@pytest.mark.unit
@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_platform_reporting_its_own_fault_is_unreachable(status: int) -> None:
    # Which of these arrives is a fact about how the platform is fronted; what
    # they share is the server saying the failure is its own.
    platform = _Platform().answering(PATCH, THE_APPLICATION, httpx2.Response(status))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION, SOME_MARK))) \
        .then(an_error_was_raised(PlatformUnreachable))


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_a_platform_rejecting_the_request_refused_it(status: int) -> None:
    # The platform read what was asked and said no, which is the platform
    # working. Read as unreachable it would pass over every action through it.
    platform = _Platform().answering(PATCH, THE_APPLICATION, httpx2.Response(status))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION, SOME_MARK))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _it_was_not(PlatformUnreachable)
        ))


@pytest.mark.unit
def test_an_answer_that_is_not_json_is_refused_not_unreachable() -> None:
    # A bug of Argus's own reading an answer it did not expect is the failure
    # worth guarding: read as unreachability it would pass over five actions
    # because a parse went wrong here.
    platform = _Platform().answering(
        GET, THE_APPLICATION, httpx2.Response(200, text="<html>login</html>")
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.is_syncing_itself(SOME_APPLICATION))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _it_was_not(PlatformUnreachable)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        httpx2.ConnectError("connection refused"),
        httpx2.ConnectTimeout("timed out connecting"),
        httpx2.PoolTimeout("no connection free")
    ],
    ids=["refused", "connect timed out", "pool timed out"]
)
def test_a_change_that_never_left_the_process_is_known_not_applied(
    failure: Exception
) -> None:
    # No connection was had, so nothing was sent and nothing was done - and a
    # caller that knows so can say the estate is as it was.
    def never_connecting(request: httpx2.Request) -> httpx2.Response:
        raise failure

    Scenario() \
        .given(argo_cd := _argo_cd_over(never_connecting)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION, SOME_MARK))) \
        .then(_it_was_known_not_applied(True))


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [
        httpx2.ReadTimeout("timed out"),
        httpx2.WriteTimeout("timed out sending"),
        httpx2.RemoteProtocolError("server disconnected")
    ],
    ids=["read timed out", "write timed out", "disconnected"]
)
def test_a_change_whose_answer_was_lost_may_have_been_applied(failure: Exception) -> None:
    # The request went out and no answer came back to say what became of it.
    # The platform may be doing it this second, and a caller told otherwise
    # would record an estate that has moved as one nothing touched.
    def losing_the_answer(request: httpx2.Request) -> httpx2.Response:
        raise failure

    Scenario() \
        .given(argo_cd := _argo_cd_over(losing_the_answer)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION, SOME_MARK))) \
        .then(_it_was_known_not_applied(False))


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 404, 409, 503])
def test_a_change_the_platform_answered_it_did_not_handle_is_known_not_applied(
    status: int
) -> None:
    # A 4xx is a request read and rejected. A 503 is the server saying it could
    # not handle the request at all (RFC 9110, 15.6.4) - which is also what the
    # demo's platform answers every change with when it is staged as down.
    platform = _Platform().answering(PATCH, THE_APPLICATION, httpx2.Response(status))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION, SOME_MARK))) \
        .then(_it_was_known_not_applied(True))


@pytest.mark.unit
@pytest.mark.parametrize("status", [500, 502, 504])
def test_a_change_the_platform_failed_part_way_may_have_been_applied(status: int) -> None:
    # A server that faulted while handling the request, or a gateway that lost
    # the answer from behind it: neither says the change was not made.
    platform = _Platform().answering(PATCH, THE_APPLICATION, httpx2.Response(status))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION, SOME_MARK))) \
        .then(_it_was_known_not_applied(False))


@pytest.mark.unit
@pytest.mark.parametrize(
    "answer",
    [httpx2.ReadTimeout("timed out"), httpx2.Response(500)],
    ids=["timed out", "faulted"]
)
def test_a_read_that_failed_applied_nothing(answer: Exception | httpx2.Response) -> None:
    # A read changes nothing however its answer went missing, so a failure to
    # read is always one the estate is untouched by.
    def answering(request: httpx2.Request) -> httpx2.Response:
        if isinstance(answer, Exception):
            raise answer

        return answer

    Scenario() \
        .given(argo_cd := _argo_cd_over(answering)) \
        .when(attempting(lambda: argo_cd.is_syncing_itself(SOME_APPLICATION))) \
        .then(_it_was_known_not_applied(True))


@pytest.mark.unit
def test_a_read_whose_answer_could_not_be_read_applied_nothing() -> None:
    # Refused rather than unreachable, and still a read: what went wrong is
    # Argus's reading of the answer, and nothing was asked to change.
    platform = _Platform().answering(
        GET, THE_APPLICATION, httpx2.Response(200, text="<html>login</html>")
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.is_syncing_itself(SOME_APPLICATION))) \
        .then(_it_was_known_not_applied(True))


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure", [PlatformUnreachable, PlatformRefused], ids=["unreachable", "refused"]
)
def test_either_failure_is_a_deployment_platform_error(
    failure: type[DeploymentPlatformError]
) -> None:
    # A reader that only needs to know the platform did not answer what was
    # asked - the read tier - catches one name rather than two.
    Scenario() \
        .given(failure) \
        .when(lambda: issubclass(failure, DeploymentPlatformError)) \
        .then(the_answer_was(True))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _a_history_entry(history_id: int, deployed_at: str) -> dict[str, Any]:
    return {"id": history_id, "revision": f"rev-{history_id}", "deployedAt": deployed_at}


def _a_sync_patch_setting_enabled_to(enabled: bool | None) -> dict[str, Any]:
    """`ApplicationPatchRequest`: the patch travels as a JSON-encoded string, and
    carries the mark on the application's own metadata beside the switch."""
    return {
        "name": SOME_APPLICATION,
        "patch": json.dumps({
            "metadata": THE_MARKED_METADATA,
            "spec": {"syncPolicy": {"automated": {"enabled": enabled}}}
        }),
        "patchType": "merge"
    }


def _the_last_request_was(platform: _Platform,
                          method: str,
                          path: str,
                          query: dict[str, str] | None = None,
                          body: Any = None) -> bool:
    """The request as it left the process: every part the case names, compared.

    `query` and `body` are compared only where given, so a case about the route
    does not also fix the body and the reverse. A patch carried as text is
    compared as what it says (`_alike`), so the order its keys are written in -
    which no server reads - is not pinned.
    """
    if not platform.asked:
        raise AssertionError(
            f"Expected a {method} to [{path}], and the platform was asked nothing."
        )

    request = platform.asked[-1]
    wrong = []

    if (request.method, request.url.path) != (method, path):
        wrong.append(f"went {request.method} to [{request.url.path}]")

    if query is not None and dict(request.url.params) != query:
        wrong.append(f"carried the query {dict(request.url.params)}")

    if body is not None and not _alike(json.loads(request.content), body):
        wrong.append(f"carried the body {request.content.decode()}")

    if wrong:
        raise AssertionError(
            f"Expected a {method} to [{path}]"
            f"{f' with the query {query}' if query is not None else ''}"
            f"{f' and the body {body!r}' if body is not None else ''}, "
            f"and the request {'; '.join(wrong)}."
        )

    return True


def _alike(sent: Any, expected: Any) -> bool:
    """Whether `sent` is `expected`, text that encodes JSON compared as what it
    encodes - and only ever against text: a patch sent as an object where the
    route takes a string is still a different body."""
    if isinstance(sent, str) and isinstance(expected, str):
        try:
            return bool(json.loads(sent) == json.loads(expected))
        except ValueError:
            return sent == expected

    if isinstance(sent, dict) and isinstance(expected, dict):
        return sent.keys() == expected.keys() and all(
            _alike(sent[key], expected[key]) for key in expected
        )

    return bool(sent == expected)


def _only_these_were_asked(platform: _Platform, expected: list[tuple[str, str]]) -> bool:
    asked = [(request.method, request.url.path) for request in platform.asked]

    if asked != expected:
        raise AssertionError(f"Expected the platform asked only {expected}, got {asked}.")

    return True


def _the_last_request_carried(platform: _Platform, header: str, value: str) -> bool:
    carried = platform.asked[-1].headers.get(header)

    if carried != value:
        raise AssertionError(
            f"Expected the request to carry [{header}: {value}], and it carried "
            f"[{carried}]."
        )

    return True


def _the_last_request_carried_no(platform: _Platform, header: str) -> bool:
    if header in platform.asked[-1].headers:
        raise AssertionError(
            f"Expected no [{header}] header, and the request carried "
            f"[{platform.asked[-1].headers[header]}]."
        )

    return True


def _it_was_known_not_applied(expected: bool) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if not isinstance(error, DeploymentPlatformError):
            raise AssertionError(
                f"Expected the platform's failure, and what was raised was {error!r}."
            )

        if error.known_not_applied is not expected:
            raise AssertionError(
                f"Expected the failure to say the request was "
                f"{'known not to have been' if expected else 'perhaps'} applied, "
                f"and it said known_not_applied={error.known_not_applied}: [{error}]."
            )

        return True

    return assertion


def _whose_each_sync_is(expected: bool | None) -> Assertion[SyncOperations]:
    """The sync asked and the last one run, both said `expected` of."""
    def assertion(operations: SyncOperations) -> bool:
        said = (None if operations.requested is None else operations.requested.made_by_argus,
                None if operations.last_run is None else operations.last_run.made_by_argus)

        if said != (expected, expected):
            raise AssertionError(
                f"Expected the sync asked and the sync run both said made_by_argus="
                f"{expected}, and they were said {said[0]} and {said[1]}."
            )

        return True

    return assertion


def _it_was_not(failure: type[Exception]) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if isinstance(error, failure):
            raise AssertionError(
                f"Expected anything but [{failure.__name__}], and that is what was "
                f"raised: [{error}]."
            )

        return True

    return assertion


# A count a write asks for, which no case here reads.
DONT_CARE_COUNT = 6

# Each write that makes a change Argus records a way back for, with the route it
# is sent to - asked of the adapter, for the cases about when the platform says
# it was made.
EVERY_WRITE_ARGUS_PUTS_BACK = [
    pytest.param(POST, THE_ROLLBACK,
                 lambda argo_cd: argo_cd.roll_back(SOME_APPLICATION, SOME_HISTORY_ID),
                 id="rollback"),
    pytest.param(POST, THE_RESOURCE,
                 lambda argo_cd: argo_cd.scale(SOME_APPLICATION, DONT_CARE_COUNT, SOME_MARK),
                 id="scale-out"),
    pytest.param(POST, THE_RESOURCE,
                 lambda argo_cd: argo_cd.set_autoscaler_floor(SOME_APPLICATION, SOME_AUTOSCALER,
                                                              DONT_CARE_COUNT, SOME_MARK),
                 id="autoscaler-floor"),
    pytest.param(POST, THE_RESOURCE,
                 lambda argo_cd: argo_cd.pin_to_accelerator(SOME_APPLICATION, SOME_CARD,
                                                            SOME_MARK),
                 id="card-pin")
]


@pytest.mark.unit
@pytest.mark.parametrize(("method", "route", "write"), EVERY_WRITE_ARGUS_PUTS_BACK)
def test_a_write_answers_with_the_moment_the_platform_dated_its_answer(
        method: str, route: str, write: Callable[[ArgoCd], datetime | None]) -> None:
    # What the change's way back is dated by, on the platform's own clock - the
    # clock a later look at its record compares with - and read off the answer
    # to the write itself, which needs no read of its own.
    platform = _Platform().answering(method, route, _ok_dated(THE_IMF_FIXDATE))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: write(argo_cd)) \
        .then(the_answer_was(THE_MOMENT_RFC_9110_SPELLS))


@pytest.mark.unit
@pytest.mark.parametrize(("method", "route", "write"), EVERY_WRITE_ARGUS_PUTS_BACK)
@pytest.mark.parametrize("date", [None, "not a moment"], ids=["no date", "a date that is not one"])
def test_a_write_whose_answer_does_not_say_when_answers_with_no_moment(
        method: str, route: str, write: Callable[[ArgoCd], datetime | None],
        date: str | None) -> None:
    # The change was made, so refusing here would report a change that landed
    # as one that did not. Nor is Argus's clock a stand-in for the platform's:
    # absent says nobody knows when, which is what a reader asks of it.
    platform = _Platform().answering(method, route, _ok_dated(date))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: write(argo_cd)) \
        .then(the_answer_was(None))


@pytest.mark.unit
@pytest.mark.parametrize(
    "kind",
    [MarkedObject.APPLICATION, MarkedObject.DEPLOYMENT, MarkedObject.AUTOSCALER],
    ids=["the application", "the deployment", "the autoscaler"]
)
@pytest.mark.parametrize(
    "the_moment_as_found",
    [
        pytest.param({}, id="absent"),
        pytest.param({THE_WRITTEN_AT_ANNOTATION: AN_UNREADABLE_MOMENT}, id="unreadable")
    ]
)
def test_a_mark_whose_moment_cannot_be_read_still_names_its_claim(
    kind: MarkedObject, the_moment_as_found: dict[str, str]
) -> None:
    # A walk resumed after its worker died dates a change it finds made by the
    # moment the claim's mark says it was written - the only record of when. So
    # a mark is read back whole, and whose the change is does not wait on when:
    # the claim is read, and a moment absent or not a time is said to be
    # unknown rather than made up.
    platform = _a_platform_where(kind, _metadata_annotated({
        THE_ACTION_ANNOTATION: SOME_MARK.action_id, **the_moment_as_found
    }))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.mark_on(SOME_APPLICATION, kind)) \
        .then(the_answer_was(MarkFound(action_id=SOME_MARK.action_id, written_at=None)))
