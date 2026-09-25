"""Restarting the service through the deployment platform (spec §7.3, §12.1).

The write tier's second action, and the only place in Argus that knows how a
restart is actually performed. Everything above the port sees a service name
going in and a new process start time coming back.

Shaped like Argo CD's own restart, which is not an endpoint but a **resource
action**: a Lua script the server runs against the live resource, stamping
`kubectl.kubernetes.io/restartedAt` on the pod template so that Kubernetes
rolls it. Argus asks for it by name over `POST
/api/v1/applications/{application}/resource/actions/v2`, exactly as
`argocd app actions run APPNAME restart --kind Deployment` does.

The vendor's shape rather than a friendlier one, for the reason the deploy
history channel is Argo CD's: the adapter here is the code a real deployment
would point at a real server, and a bespoke endpoint would be a lie that
adapter would have to be written around. A deployment on something else - the
Kubernetes API directly, systemd, a platform of its own - replaces this module
and nothing above it.

Restarting is deliberately not "post and return". The action returns as soon as
Argo CD has patched the template, which is before a single pod has rolled, so a
caller that trusted the POST would re-query the metrics against the process
that is still leaking, watch memory stay where it was, and refute a hypothesis
that was right. Waiting for the start time to move is what makes "it landed"
and "it did not help" two different answers.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Final, Protocol

import httpx
from argus_core import SettingsSlice
from argus_core.models import RestartedService

# The action Argo CD runs, by the name it is registered under. A vendor's own
# vocabulary, so it is named once here rather than spelled at the call.
RESTART_ACTION: Final = "restart"

# What the action is run against. Argo CD dispatches its Lua by group and kind,
# and the built-in restart is registered for `apps/Deployment` - a Deployment
# is what a leaking service is, and naming it here rather than configuring it
# keeps the tool from being pointed at a resource whose restart means something
# else.
RESTART_GROUP: Final = "apps"
RESTART_KIND: Final = "Deployment"

# What a process is, in the resource tree. Everything else the tree reports -
# the Deployment, the ReplicaSet, the Service - was created when somebody
# declared it and has not come up since.
POD_KIND: Final = "Pod"

REQUEST_TIMEOUT_SECONDS = 10.0

# How long to keep asking whether the new process is up. A rollout is seconds
# in practice; this is the bound on "it never came back", not the expected
# wait, and it is longer than a flag's because a process starting is slower
# than a value propagating.
_START_TIME_ATTEMPTS = 60
_SECONDS_BETWEEN_ATTEMPTS = 1.0


class RestartSettings(SettingsSlice):
    """Where a restart is asked for, and under what credential.

    The path is a template rather than a fixed route, for the reason the deploy
    history channel's is: the demo's stand-in and a real server's
    `/api/v1/applications/{application}/resource/actions/v2` are one setting
    with two values.

    What the platform calls the thing being restarted used to be configured
    here, and was right for as long as the only service Argus could restart was
    the one it was paged about. A mitigation addressed at a dependency makes a
    fixed name actively wrong: the request would carry the shop's deployment
    whatever application it was sent to, so the platform would restart the wrong
    thing and report success. The resource is the service now, which is what the
    demo's stand-in and a Kubernetes deployment named after its service both
    already assume.
    """

    argocd_base_url: str
    argocd_restart_action_path: str
    argocd_auth_token: str
    restart_namespace: str
    # Where the platform says what is actually running. The write tier reads it
    # itself rather than asking the read tier, for the reason `set_feature_flag`
    # confirms its own write: verifying one's own change is not a retrieval
    # concern, and a write server that depended on the read server could not
    # restart anything while the read server was down.
    #
    # A template like the action path, and per application, which is the whole
    # reason the confirmation is not read off the metrics any more: restarting a
    # dependency moves that dependency's pod and leaves the alerting service's
    # exactly where it was. One gauge scraped from one address cannot tell those
    # apart, and would report a restart that landed as one that never happened.
    argocd_resource_tree_path: str


HttpPost = Callable[..., httpx.Response]
HttpGet = Callable[..., httpx.Response]
# How the wait between looks is spent. Injected for the reason the metrics
# reading is: a rollout that never arrives is a case worth a test, and one
# spending a real minute of it is a case nobody runs.
Sleeper = Callable[[float], None]


class ObserveStartTime(Protocol):
    """What `restart_service` needs in order to confirm its own restart landed.

    A `Protocol` rather than a `Callable` alias for the reason `EvaluateFlags`
    is one: a test stands it in with `create_autospec`, which needs something
    introspectable. It answers the start time of the process serving one
    service, and knows nothing about which restart is being waited on.

    It takes that service, where it used to take nothing. A no-argument reading
    was one address scraped from configuration, which said what the alerting
    service was doing however the restart was addressed - so a dependency
    restarted perfectly well reported a reading that never moved, and the
    restart was raised as one that never happened.
    """

    # Positional-only: the service is the whole question.
    def __call__(self, service: str, /) -> float | None: ...


class ServiceNotRestarted(Exception):
    """The service did not come back under a new process, whatever the reason.

    One exception for an unreachable platform, a rejected credential, a
    refused action and a rollout that never completed, because the caller's
    next move is the same for all four: the restart did not happen, so nothing
    downstream may proceed as though it had. A restart reported optimistically
    would have Mitigation judge a hypothesis against a service nothing was done
    to - and, worse, read the leak still climbing as evidence that restarting
    does not help.
    """


def the_pod_start_time(settings: RestartSettings,
                       get: HttpGet = httpx.get) -> ObserveStartTime:
    """Reads when the process now serving a service came up, from the platform.

    Argo CD's resource tree is how anybody finds out what is actually running,
    and a pod's `createdAt` is the platform's own answer to "did the restart
    land". Read from here rather than from the service's own metrics because it
    is per application: one gauge at one address says what the alerting service
    is doing whoever the restart was addressed to.

    A factory rather than a function taking the address, so that what
    `restart_service` is handed is the `ObserveStartTime` a test can stand in.
    The address is bound once, where the server is built; the service is asked
    per reading.

    The *newest* pod, because a rollout has two of them in it for a while and
    the older one is precisely the process a restart has to be told apart from.
    Only pods: a real tree carries the Deployment, the ReplicaSet and the
    Service too, and their creation times have not moved since somebody declared
    them.

    `None` where nothing is running, and `None` where a creation time cannot be
    read. Both are the absence of a reading rather than a reading of no change,
    which is the distinction the wait below turns on - and a crash on an
    unparseable timestamp would report an unconfirmable restart as a broken one.
    """
    def observe(service: str, /) -> float | None:
        response = get(
            f"{settings.argocd_base_url}"
            f"{settings.argocd_resource_tree_path.format(application=service)}",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        nodes: list[dict[str, Any]] = response.json().get("nodes", [])

        came_up = [
            _when_it_came_up(node.get("createdAt"))
            for node in nodes if node.get("kind") == POD_KIND
        ]
        readable = [moment for moment in came_up if moment is not None]

        return max(readable) if readable else None

    return observe


def _when_it_came_up(created_at: str | None) -> float | None:
    """One `createdAt` as seconds since the epoch, or `None` where it is not one.

    Seconds because that is what everything above compares: the reading before
    the action and the reading after it are told apart by differing, and a pair
    of strings would be compared by spelling.

    Kubernetes stamps these to the second, which is enough. What the value is
    measured against is the *previous* process's start time, minutes old by the
    time anything asks.
    """
    if created_at is None:
        return None

    try:
        return datetime.fromisoformat(created_at).timestamp()
    except ValueError:
        return None


def restart_service(
    service: str,
    settings: RestartSettings,
    post: HttpPost = httpx.post,
    *,
    observe: ObserveStartTime,
    sleep: Sleeper = time.sleep
) -> RestartedService:
    """Restarts `service` and waits until a new process is serving it.

    Returns the new process start time, which is the only evidence that the
    restart landed: memory falling is ambiguous - the process restarted, or the
    traffic dropped - and without the start time a caller cannot tell a restart
    that did not happen from one that happened and did not help.

    Raises `ServiceNotRestarted` unless the platform accepted the action *and*
    the start time moved. There is no undo descriptor and no field for one: a
    restart changes no persistent state, so there is nothing to put back (§13).
    """
    was_started_at = observe(service)
    url = f"{settings.argocd_base_url}{_restart_path(settings, service)}"

    try:
        response = post(
            url,
            headers=_headers_for(settings.argocd_auth_token),
            json=_the_restart_action(settings, service),
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except Exception as error:
        raise ServiceNotRestarted(
            f"could not restart [{service}] at [{url}]: {error}"
        ) from error

    return RestartedService(
        service=service,
        process_start_time_seconds=_wait_until_a_new_process_serves(
            service, was_started_at, observe, sleep
        )
    )


def _the_restart_action(settings: RestartSettings, service: str) -> dict[str, Any]:
    """The action request, in the shape Argo CD's v2 endpoint takes.

    v2 rather than the original, which carries the same fields as query
    parameters and is deprecated since Argo CD 3.1. The resource is addressed
    by group, kind, namespace and name because that is how the server finds
    the Lua registered for it - `apps/Deployment` is what the built-in restart
    is written against.

    The name is the service, not a configured one. A fixed name carried the
    alerting service's deployment into every request, so a restart addressed at
    a dependency reached the right application and restarted the wrong thing -
    and the platform answered that it had worked.
    """
    return {
        "namespace": settings.restart_namespace,
        "resourceName": service,
        "group": RESTART_GROUP,
        "kind": RESTART_KIND,
        "action": RESTART_ACTION
    }


def _wait_until_a_new_process_serves(service: str,
                                     was_started_at: float | None,
                                     observe: ObserveStartTime,
                                     sleep: Sleeper) -> float:
    """The start time of the process now serving, once it differs from the one
    that was serving before.

    A *change*, not a threshold: the start time is a gauge, and a restart is
    the moment it moves. Waiting for it to exceed some instant would need the
    two clocks to agree, and they do not.

    A service that reported no start time before the restart is one this cannot
    wait for - there is nothing to see a change against - so the first reading
    after the action is taken as the answer rather than compared to nothing.
    """
    for attempt in range(_START_TIME_ATTEMPTS):
        try:
            started_at = observe(service)
        except Exception as error:
            raise ServiceNotRestarted(
                f"could not confirm [{service}] restarted: {error}"
            ) from error

        if started_at is not None and started_at != was_started_at:
            return started_at

        if attempt + 1 < _START_TIME_ATTEMPTS:
            sleep(_SECONDS_BETWEEN_ATTEMPTS)

    raise ServiceNotRestarted(
        f"[{service}] was accepted for restart but is still served by the "
        f"process that was running before"
    )


def _restart_path(settings: RestartSettings, service: str) -> str:
    return settings.argocd_restart_action_path.format(application=service)


def _headers_for(token: str) -> dict[str, str]:
    """The credential, or no header at all where none is configured.

    An empty token means the server takes none - the demo's stand-in does - and
    sending `Bearer ` with nothing after it is a malformed credential rather
    than an absent one.
    """
    return {"Authorization": f"Bearer {token}"} if token else {}
