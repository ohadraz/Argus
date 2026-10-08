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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from argus_core.models import PodPlacement, RolloutProgress
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_answer_was,
)
from deployment_platform import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentPlatformError,
    DeploymentRecord,
    PlatformRefused,
    PlatformUnreachable,
)
from deployment_platform.argocd import ArgoCd, ArgoCdSettings

SOME_APPLICATION = "io-shop"
SOME_TOKEN = "some-argocd-token"
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


def _argo_cd_over(platform: Any, auth_token: str = SOME_TOKEN) -> ArgoCd:
    """The adapter, configured as a real server would be and reaching only `platform`.

    The host does not resolve, so a request that escaped the transport would fail
    as a connection error rather than reach anything real.
    """
    return ArgoCd(
        ArgoCdSettings(
            argocd_base_url=DONT_CARE_BASE_URL,
            argocd_auth_token=auth_token,
            argocd_application_path="/api/v1/applications/{application}",
            argocd_resource_path="/api/v1/applications/{application}/resource",
            argocd_resource_action_path=(
                "/api/v1/applications/{application}/resource/actions/v2"
            ),
            argocd_rollback_path="/api/v1/applications/{application}/rollback",
            argocd_resource_tree_path=(
                "/api/v1/applications/{application}/resource-tree"
            ),
            restart_namespace=SOME_RESTART_NAMESPACE,
            scale_namespace=SOME_SCALE_NAMESPACE
        ),
        transport=httpx2.MockTransport(platform)
    )


def _an_application(syncing: dict[str, Any] | None = None,
                    history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An application as `GET /api/v1/applications/{name}` returns one.

    `syncing` is the `automated` object, or `None` for an application with none.
    """
    sync_policy: dict[str, Any] = {} if syncing is None else {"automated": syncing}
    application: dict[str, Any] = {"spec": {"syncPolicy": sync_policy}, "status": {}}

    if history is not None:
        application["status"]["history"] = history

    return application


def _a_managed_resource(manifest: dict[str, Any]) -> dict[str, Any]:
    """The resource route's wrapper: the manifest arrives as *text*."""
    return {"manifest": json.dumps(manifest)}


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
    # The stand-in needs none, and a placeholder would send a real server
    # something meaningless to reject.
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
            "initiatedBy": {"username": "buki"}
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
                initiated_by="buki"
            )
        ]))


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
def test_the_running_deployment_is_asked_for_with_no_selectors() -> None:
    # There is one Deployment behind the application, and a selector configured
    # here would be a second place to correct when it moves.
    platform = _Platform().answering(
        GET, THE_RESOURCE, _ok(_a_managed_resource({"spec": {"replicas": 3}}))
    )

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.rollout_of(SOME_APPLICATION)) \
        .then(lambda _: _the_last_request_was(platform, GET, THE_RESOURCE, query={}))


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
def test_suspending_sync_merge_patches_the_switch_alone() -> None:
    # Not the spec route, which replaces the whole spec; and not an `automated`
    # object of Argus's own, which would replace the operator's prune and
    # selfHeal.
    platform = _Platform().answering(PATCH, THE_APPLICATION, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.suspend_sync(SOME_APPLICATION)) \
        .then(lambda _: _the_last_request_was(
            platform, PATCH, THE_APPLICATION,
            body=_a_sync_patch_setting_enabled_to(False)
        ))


@pytest.mark.unit
def test_resuming_sync_removes_the_switch() -> None:
    # A merge patch's `null` removes the key, which the platform reads as on -
    # what was found, since an application syncing itself had it absent or true.
    platform = _Platform().answering(PATCH, THE_APPLICATION, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.resume_sync(SOME_APPLICATION)) \
        .then(lambda _: _the_last_request_was(
            platform, PATCH, THE_APPLICATION,
            body=_a_sync_patch_setting_enabled_to(None)
        ))


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scaling_runs_the_built_in_scale_action_with_the_count_as_text() -> None:
    # Every resource-action parameter travels as a string, and the action's own
    # Lua makes a number of it.
    some_replicas = 6
    platform = _Platform().answering(POST, THE_RESOURCE_ACTIONS, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.scale(SOME_APPLICATION, some_replicas)) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE_ACTIONS,
            body={
                "namespace": SOME_SCALE_NAMESPACE,
                "resourceName": SOME_APPLICATION,
                "group": "apps",
                "kind": "Deployment",
                "action": "scale",
                "resourceActionParameters": [
                    {"name": "replicas", "value": str(some_replicas)}
                ]
            }
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
def test_raising_the_floor_merge_patches_the_floor_alone_as_text() -> None:
    # The resource route's patch is a JSON-encoded *string*, and it says only the
    # floor: a body carrying the ceiling would re-assert a human's declaration as
    # though Argus had decided it.
    some_floor = 10
    platform = _Platform().answering(POST, THE_RESOURCE, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.set_autoscaler_floor(
            SOME_APPLICATION, SOME_AUTOSCALER, some_floor
        )) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE,
            query={
                **THE_AUTOSCALER_SELECTORS,
                "patchType": "application/merge-patch+json"
            },
            body=json.dumps({"spec": {"minReplicas": some_floor}})
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
def test_pinning_merge_patches_the_card_label_alone_as_text() -> None:
    # The template's selector and, of it, only the card. A patch carrying the
    # whole selector would replace selectors somebody else declared.
    platform = _Platform().answering(POST, THE_RESOURCE, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.pin_to_accelerator(SOME_APPLICATION, SOME_CARD)) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE,
            query={
                **THE_DEPLOYMENT_SELECTORS,
                "patchType": "application/merge-patch+json"
            },
            body=json.dumps({"spec": {"template": {"spec": {"nodeSelector": {
                THE_CARD_LABEL: SOME_CARD
            }}}}})
        ))


@pytest.mark.unit
def test_releasing_a_pin_removes_the_card_label_with_a_null() -> None:
    # RFC 7386's own way of deleting a key, which is what an undo of a pin onto a
    # deployment that had none has to send.
    platform = _Platform().answering(POST, THE_RESOURCE, _ok())

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(lambda: argo_cd.pin_to_accelerator(SOME_APPLICATION, None)) \
        .then(lambda _: _the_last_request_was(
            platform, POST, THE_RESOURCE,
            body=json.dumps({"spec": {"template": {"spec": {"nodeSelector": {
                THE_CARD_LABEL: None
            }}}}})
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
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION))) \
        .then(an_error_was_raised(PlatformUnreachable))


@pytest.mark.unit
@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_platform_reporting_its_own_fault_is_unreachable(status: int) -> None:
    # Which of these arrives is a fact about how the platform is fronted; what
    # they share is the server saying the failure is its own.
    platform = _Platform().answering(PATCH, THE_APPLICATION, httpx2.Response(status))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION))) \
        .then(an_error_was_raised(PlatformUnreachable))


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
def test_a_platform_rejecting_the_request_refused_it(status: int) -> None:
    # The platform read what was asked and said no, which is the platform
    # working. Read as unreachable it would pass over every action through it.
    platform = _Platform().answering(PATCH, THE_APPLICATION, httpx2.Response(status))

    Scenario() \
        .given(argo_cd := _argo_cd_over(platform)) \
        .when(attempting(lambda: argo_cd.suspend_sync(SOME_APPLICATION))) \
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
    """`ApplicationPatchRequest`: the patch travels as a JSON-encoded string."""
    return {
        "name": SOME_APPLICATION,
        "patch": json.dumps(
            {"spec": {"syncPolicy": {"automated": {"enabled": enabled}}}}
        ),
        "patchType": "merge"
    }


def _the_last_request_was(platform: _Platform,
                          method: str,
                          path: str,
                          query: dict[str, str] | None = None,
                          body: Any = None) -> bool:
    """The request as it left the process: every part the case names, compared.

    `query` and `body` are compared only where given, so a case about the route
    does not also fix the body and the reverse.
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

    if body is not None and json.loads(request.content) != body:
        wrong.append(f"carried the body {request.content.decode()}")

    if wrong:
        raise AssertionError(
            f"Expected a {method} to [{path}]"
            f"{f' with the query {query}' if query is not None else ''}"
            f"{f' and the body {body!r}' if body is not None else ''}, "
            f"and the request {'; '.join(wrong)}."
        )

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


def _it_was_not(failure: type[Exception]) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if isinstance(error, failure):
            raise AssertionError(
                f"Expected anything but [{failure.__name__}], and that is what was "
                f"raised: [{error}]."
            )

        return True

    return assertion
