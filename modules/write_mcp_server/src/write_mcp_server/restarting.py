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

    `restart_resource_name` is what the platform calls the thing being
    restarted, which is not what the alert calls the service. Configured rather
    than derived, because the mapping between the two is a deployment's fact
    and there is no rule that produces one from the other.
    """

    argocd_base_url: str
    argocd_restart_action_path: str
    argocd_auth_token: str
    restart_namespace: str
    restart_resource_name: str
    # Where the start time is read back from. The write tier reads it itself
    # rather than asking the read tier, for the reason `set_feature_flag`
    # confirms its own write: verifying one's own change is not a retrieval
    # concern, and a write server that depended on the read server could not
    # restart anything while the read server was down. No credential is named
    # - this is the same unauthenticated gauge every monitoring stack scrapes.
    target_service_url: str


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
    introspectable. It answers the current process start time, and knows
    nothing about which restart is being waited on.
    """

    def __call__(self) -> float | None: ...


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


def the_process_start_time(settings: RestartSettings,
                           get: HttpGet = httpx.get) -> ObserveStartTime:
    """Reads the start time of the process now serving, from the metrics.

    A factory rather than a function taking the address, so that what
    `restart_service` is handed stays the no-argument `ObserveStartTime` a test
    can stand in with a lambda. The address is bound once, where the server is
    built.

    The *latest* minute's reading, because that is the one that says what is
    serving now - an older bucket describes the process that was. A window with
    no minutes in it answers `None`: a service reporting nothing is one this
    cannot see a restart in, which is a different answer from one reporting
    that it has not restarted.
    """
    def observe() -> float | None:
        response = get(
            f"{settings.target_service_url}/metrics",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        buckets: list[dict[str, Any]] = response.json()

        if not buckets:
            return None

        started_at = buckets[-1].get("process_start_time_seconds")

        return float(started_at) if started_at is not None else None

    return observe


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
    was_started_at = observe()
    url = f"{settings.argocd_base_url}{_restart_path(settings, service)}"

    try:
        response = post(
            url,
            headers=_headers_for(settings.argocd_auth_token),
            json=_the_restart_action(settings),
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


def _the_restart_action(settings: RestartSettings) -> dict[str, Any]:
    """The action request, in the shape Argo CD's v2 endpoint takes.

    v2 rather than the original, which carries the same fields as query
    parameters and is deprecated since Argo CD 3.1. The resource is addressed
    by group, kind, namespace and name because that is how the server finds
    the Lua registered for it - `apps/Deployment` is what the built-in restart
    is written against.
    """
    return {
        "namespace": settings.restart_namespace,
        "resourceName": settings.restart_resource_name,
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
            started_at = observe()
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
