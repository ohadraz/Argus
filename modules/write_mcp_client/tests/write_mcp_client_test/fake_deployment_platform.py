from __future__ import annotations

import json
import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any

from argus_core import get_settings
from deployment_platform.argocd import (
    APPLICATION_MERGE_PATCH,
    AUTOMATED,
    ENABLED,
    PATCH_REQUEST_PATCH,
    PATCH_REQUEST_TYPE,
    SPEC,
    SYNC_POLICY,
)

FAKE_PLATFORM_PORT = 8184

RESOURCE_ACTION_PATH = "/argocd/{application}/resource/actions/v2"
RESOURCE_PATH = "/argocd/{application}/resource"
APPLICATION_PATH = "/argocd/{application}"
RESOURCE_TREE_PATH = "/argocd/{application}/resource-tree"
ROLLBACK_PATH = "/argocd/{application}/rollback"

# How the platform spells a creation time, which is Kubernetes' own: RFC 3339
# to the second. The resolution is not a shortcut - what the value is compared
# against is the previous process's start time, minutes old by then.
POD_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# When the pod that is serving came up, and how far a restart moves it. Both
# arbitrary: what a caller can tell from this reading is that it *changed*, and
# nothing else - the two clocks involved are not the same clock. Held as
# seconds since the epoch because that is what the caller ends up holding, and
# a whole number of them survives the round trip through a second-resolution
# timestamp exactly.
THE_PROCESS_THAT_WAS_SERVING = 1_756_000_000.0
A_NEW_PROCESS_LATER = 600.0

# Two entries, because a rollback is addressed to a history entry and an
# application with one entry has nothing to return to. The revisions are commit
# shapes rather than real commits: what a caller can tell from them is which
# entry it came *from*, which is what the descriptor records.
THE_REVISION_RUNNING_NOW = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_BEFORE_IT = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
THE_HISTORY_RUNNING_NOW = 2
THE_HISTORY_BEFORE_IT = 1

# What the deployment is running when anybody looks, which is the size the
# fixture's own values file asks for. A scale-out reads it, doubles it, and the
# resource then reports what it was set to - so the round trip shows the count
# came from the platform rather than from a number the caller invented.
THE_COUNT_RUNNING = 3


def a_gitops_sync_policy() -> dict[str, Any]:
    """Automated sync as an operator declares it, with `selfHeal` on.

    `selfHeal` is there so that a suspension which disturbed the rest of the
    policy is visible: a caller that wrote an `automated` object of its own, or
    removed the operator's, would lose it.
    """
    return {AUTOMATED: {"selfHeal": True}}

_APPLICATION_IN = re.compile(r"^/argocd/(?P<application>[^/]+)")


class FakeDeploymentPlatformHandler(BaseHTTPRequestHandler):
    """A deployment platform in Argo CD's own wire shape, with a memory.

    It answers the surfaces a restart needs - the resource action, and the
    resource tree that says when the pod now serving came up - and running the
    action actually moves the pod's creation time. That is the point:
    `restart_service` returns only once that time has changed, so a fake whose
    POST did not move its own state would hang rather than fail, and would prove
    nothing about the round trip.

    The tree rather than a metrics gauge, because that is where the confirmation
    reads from now. A gauge is one address serving one process, which says what
    the alerting service is doing however the restart was addressed; a tree is
    per application, which is what lets a restart aimed at a dependency be
    confirmed against the dependency.

    It answers the surfaces a rollback needs for the same reason, and the same
    way. A rollback is three requests against two routes - the application is
    read for which entry is running and whether the platform reconciles it
    itself, reconciliation is suspended by a merge patch of the application, and
    only then is the rollback asked for - so a fake that served a static
    application would let a caller that never suspended anything pass. Here the
    patch is actually applied to the policy the application reports, and the
    rollback route refuses while that policy says the platform syncs itself,
    exactly as a real server refuses it.

    One pod's creation time rather than one per application. What a per
    application memory would witness - that the tree read is the one belonging
    to the service restarted - is a property of the adapter, covered where the
    adapter is, and holding it here would buy a second copy of that assertion
    rather than anything this round trip can only show end to end.
    """

    process_start_time_seconds: float = THE_PROCESS_THAT_WAS_SERVING
    actions_run: list[dict[str, Any]] = []
    sync_policy: dict[str, Any] = a_gitops_sync_policy()
    syncs_itself: bool = True
    rolled_back_to: list[int] = []
    sync_patches_received: list[dict[str, Any]] = []
    replicas: int = THE_COUNT_RUNNING

    # Whether this platform's API server is serving at all. Off by default: an
    # unavailable platform is something a test stages, and a fake that had to be
    # told it is up in every other test would be a fake nobody could read.
    unavailable: bool = False

    def _refused_for_being_unavailable(self) -> bool:
        """Answers as a platform whose own API is not serving, where staged.

        Every route at once, and without reading the request. That is what a
        downed API server is: nothing reaches the thing that would have acted,
        so what was asked for never mattered.
        """
        if not self.unavailable:
            return False

        self.send_response(503)
        self.end_headers()

        return True

    def do_GET(self) -> None:
        if self._refused_for_being_unavailable():
            return

        if self.path.endswith("/resource-tree"):
            self._respond_with(self._the_resource_tree())
        elif self.path.endswith("/resource"):
            self._respond_with(self._the_managed_deployment())
        elif self._names_an_application() and self.path.count("/") == 2:
            self._respond_with(self._the_application())
        else:
            self.send_response(404)
            self.end_headers()

    def _the_managed_deployment(self) -> dict[str, Any]:
        """The live Deployment, as Argo CD reports one: a manifest carried as text.

        A string and not an object, because that is the vendor's shape - the
        caller parses it - and a stand-in answering a parsed object would be an
        easier endpoint to write against than the one the adapter meets.

        This is where the count to double is read from, and the only place it can
        be: the repository says what the platform is asked to converge on, which
        is a different number as soon as anybody has scaled.
        """
        return {
            "manifest": json.dumps(
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {
                        "name": self._the_application_named(),
                        "namespace": "production"
                    },
                    "spec": {"replicas": self.replicas}
                }
            )
        }

    def do_PATCH(self) -> None:
        """Argo CD's `PATCH /api/v1/applications/{name}`, for a merge patch.

        The patch arrives as a JSON-encoded string inside the request, as the
        vendor's `ApplicationPatchRequest` carries it, and is applied to the
        policy the application then reports. A merge patch only: a caller that
        sent another type would have it applied differently or not at all, so it
        is refused here rather than answered as though it had landed.
        """
        if self._refused_for_being_unavailable():
            return

        if not (self._names_an_application() and self.path.count("/") == 2):
            self.send_response(404)
            self.end_headers()
            return

        request = self._the_body()

        if request.get(PATCH_REQUEST_TYPE) != APPLICATION_MERGE_PATCH:
            self.send_response(400)
            self.end_headers()
            return

        patch = json.loads(request[PATCH_REQUEST_PATCH])
        type(self).sync_patches_received = self.sync_patches_received + [patch]
        # The write is real, because the refusal below reads it back. A fake
        # that accepted the patch and kept syncing would let a rollback pass
        # that had suspended nothing.
        policy = _merged(self.sync_policy, patch.get(SPEC, {}).get(SYNC_POLICY, {}))
        type(self).sync_policy = policy
        type(self).syncs_itself = _is_syncing(policy)

        self._respond_with(self._the_application())

    def do_POST(self) -> None:
        if self._refused_for_being_unavailable():
            return

        if self.path.endswith("/rollback"):
            self._roll_back()
            return

        if "/resource/actions" not in self.path:
            self.send_response(404)
            self.end_headers()
            return

        asked_for = self._the_body()
        type(self).actions_run = self.actions_run + [
            {"path": self.path, "asked_for": asked_for}
        ]

        if asked_for.get("action") == "scale":
            self._scale(asked_for)
            return

        # A restart is a new process, and the pod's creation time moving is the
        # only way anything outside can tell that it happened.
        type(self).process_start_time_seconds = (
            self.process_start_time_seconds + A_NEW_PROCESS_LATER
        )

        self._respond_with({})

    def _scale(self, asked_for: dict[str, Any]) -> None:
        """Remembers the size it was asked for, which the resource then reports.

        The write is real, for the reason the restart's is: a fake whose action
        changed nothing would answer the same to a caller that read the running
        count and doubled it as to one that sent a number it invented, and the
        round trip would prove neither.

        The pod's creation time does *not* move. Scaling out starts another
        replica and leaves the one already serving where it was, and a fake that
        moved it would let a scale-out be confirmed by the evidence a restart is
        confirmed by.
        """
        parameters = asked_for.get("resourceActionParameters", [])
        counts = [
            parameter["value"] for parameter in parameters
            if parameter["name"] == "replicas"
        ]

        if not counts:
            self.send_response(400)
            self.end_headers()
            return

        type(self).replicas = int(counts[-1])

        self._respond_with({})

    def _roll_back(self) -> None:
        """Refused while the application syncs itself, as the platform refuses it.

        The refusal is what makes the order of a rollback's three requests
        observable. A fake that always accepted would answer the same whether
        the caller suspended reconciliation first or not, and the one thing this
        route exists to witness is that it did.
        """
        if self.syncs_itself:
            self.send_response(400)
            self.end_headers()
            return

        type(self).rolled_back_to = self.rolled_back_to + [self._the_body()["id"]]

        self._respond_with({})

    def _names_an_application(self) -> bool:
        return _APPLICATION_IN.match(self.path) is not None

    def _the_application_named(self) -> str:
        """Which application the path is about, or nothing recognisable.

        Only the pod's name is built from it, which nothing reads - but a pod
        named after an application it does not belong to is a fixture that
        would mislead whoever next looked at a failure here.
        """
        named = _APPLICATION_IN.match(self.path)

        return named.group("application") if named else "unknown"

    def _the_resource_tree(self) -> dict[str, Any]:
        """What is running, in the shape Argo CD's resource tree reports it.

        One pod, because the caller takes the newest and a single one makes that
        unambiguous. A real tree carries the Deployment, the ReplicaSet and the
        Service beside it, and a stand-in inventing creation times for those
        would be putting figures into the world for nobody to read.
        """
        return {
            "nodes": [
                {
                    "kind": "Pod",
                    "name": f"{self._the_application_named()}-7d4f9c",
                    "namespace": "production",
                    "createdAt": datetime.fromtimestamp(
                        self.process_start_time_seconds, UTC
                    ).strftime(POD_TIMESTAMP_FORMAT)
                }
            ]
        }

    def _the_application(self) -> dict[str, Any]:
        """The application in Argo CD's own shape, as much of it as is read.

        The policy as declared and as since patched, `automated` and its switch
        included - so a caller reads the arrangement exactly as a real server
        would report it.
        """
        return {
            SPEC: {SYNC_POLICY: self.sync_policy},
            "status": {
                # `deployedAt` on both, because Argo CD's `RevisionHistory`
                # always carries it - it is not `omitempty` - and the platform
                # port refuses an entry that does not say when it landed.
                "history": [
                    {
                        "id": THE_HISTORY_BEFORE_IT,
                        "revision": THE_REVISION_BEFORE_IT,
                        "deployedAt": "2026-08-20T10:05:00Z"
                    },
                    {
                        "id": THE_HISTORY_RUNNING_NOW,
                        "revision": THE_REVISION_RUNNING_NOW,
                        "deployedAt": "2026-08-20T11:05:00Z"
                    }
                ]
            }
        }

    def _the_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))

        if not length:
            return {}

        body: dict[str, Any] = json.loads(self.rfile.read(length))

        return body

    def _respond_with(self, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence default request logging


def _merged(target: Any, patch: Any) -> Any:
    """`patch` applied to `target` as RFC 7386 says: an object merges key by key,
    a `null` removes its key, and anything else replaces what was there.
    """
    if not isinstance(patch, dict):
        return patch

    result = dict(target) if isinstance(target, dict) else {}

    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = _merged(result.get(key), value)

    return result


def _is_syncing(policy: dict[str, Any]) -> bool:
    """As Argo CD reads it: an `automated` whose `enabled` is absent or true."""
    automated = policy.get(AUTOMATED)

    return automated is not None and automated.get(ENABLED) is not False


@contextmanager
def a_running_platform() -> Generator[type[FakeDeploymentPlatformHandler]]:
    """Runs a fake deployment platform and points the platform settings at it.

    Entered *around* `a_running_write_mcp` rather than inside it: that manager
    copies the environment to launch the server subprocess, so the settings set
    here are the ones the subprocess resolves from. Nesting is what orders the
    two, and the write server must start second.

    Yields the handler class, so a test can read back what the platform was
    asked to do, which process it now reports serving, which history entry it
    was rolled back to, and whether it is still reconciling itself.

    A context manager rather than a `conftest.py` fixture, for the reason the
    flag provider's is one: mypy identifies a module by its filename, so a
    second `conftest` anywhere under `modules/` collides with the first.
    """
    # Cleared per run, because it is class state on a handler the process
    # reuses: a test that staged an unavailable platform would otherwise leave
    # every test after it asking a platform that answers nothing.
    FakeDeploymentPlatformHandler.unavailable = False
    platform = HTTPServer(("127.0.0.1", FAKE_PLATFORM_PORT), FakeDeploymentPlatformHandler)
    platform_thread = Thread(target=platform.serve_forever, daemon=True)
    platform_thread.start()

    address = f"http://127.0.0.1:{FAKE_PLATFORM_PORT}"
    os.environ["ARGOCD_BASE_URL"] = address
    os.environ["ARGOCD_RESOURCE_ACTION_PATH"] = RESOURCE_ACTION_PATH
    os.environ["ARGOCD_RESOURCE_PATH"] = RESOURCE_PATH
    os.environ["ARGOCD_APPLICATION_PATH"] = APPLICATION_PATH
    os.environ["ARGOCD_RESOURCE_TREE_PATH"] = RESOURCE_TREE_PATH
    os.environ["ARGOCD_ROLLBACK_PATH"] = ROLLBACK_PATH
    # Empty on purpose: the stand-in takes no credential, and an inherited one
    # would be sent as a header a real server would then refuse.
    os.environ["ARGOCD_AUTH_TOKEN"] = ""
    get_settings.cache_clear()

    try:
        yield FakeDeploymentPlatformHandler
    finally:
        platform.shutdown()
        platform.server_close()
        platform_thread.join()
        FakeDeploymentPlatformHandler.process_start_time_seconds = THE_PROCESS_THAT_WAS_SERVING
        FakeDeploymentPlatformHandler.actions_run = []
        FakeDeploymentPlatformHandler.sync_policy = a_gitops_sync_policy()
        FakeDeploymentPlatformHandler.syncs_itself = True
        FakeDeploymentPlatformHandler.rolled_back_to = []
        FakeDeploymentPlatformHandler.sync_patches_received = []
        FakeDeploymentPlatformHandler.replicas = THE_COUNT_RUNNING
        del os.environ["ARGOCD_BASE_URL"]
        del os.environ["ARGOCD_RESOURCE_ACTION_PATH"]
        del os.environ["ARGOCD_RESOURCE_PATH"]
        del os.environ["ARGOCD_APPLICATION_PATH"]
        del os.environ["ARGOCD_RESOURCE_TREE_PATH"]
        del os.environ["ARGOCD_ROLLBACK_PATH"]
        del os.environ["ARGOCD_AUTH_TOKEN"]
        get_settings.cache_clear()
