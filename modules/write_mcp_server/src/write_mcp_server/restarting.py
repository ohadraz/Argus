"""Restarting the service through the deployment platform (spec §7.3, §12.1).

The write tier's second action. Everything above the port sees a service name
going in and a new process start time coming back.

Shaped like Argo CD's own restart, which is not an endpoint but a **resource
action**: a Lua script the server runs against the live resource, stamping
`kubectl.kubernetes.io/restartedAt` on the pod template so that Kubernetes rolls
it - exactly as `argocd app actions run APPNAME restart --kind Deployment` does.
How it is asked for is the platform port's adapter's. A deployment on something
else - the Kubernetes API directly, systemd, a platform of its own - replaces the
adapter and nothing here.

Restarting is deliberately not "ask and return". The action returns as soon as
the platform has patched the template, which is before a single pod has rolled,
so a caller that trusted it would re-query the metrics against the process that
is still leaking, watch memory stay where it was, and refute a hypothesis that
was right. Waiting for the start time to move is what makes "it landed" and "it
did not help" two different answers.

The start time is the platform's own answer to "did the restart land", read per
service. One gauge at one address says what the alerting service is doing
whoever the restart was addressed to, so a dependency restarted perfectly well
would report a reading that never moved.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Final

from argus_core.mcp_transport import an_unreachable_platform
from argus_core.models import DEPLOYMENT_PLATFORM, RestartedService
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    PlatformUnreachable,
)

logger = logging.getLogger(__name__)

# How long to keep asking whether the new process is up. A rollout is seconds
# in practice; this is the bound on "it never came back", not the expected
# wait, and it is longer than a flag's because a process starting is slower
# than a value propagating.
_START_TIME_ATTEMPTS: Final = 60
_SECONDS_BETWEEN_ATTEMPTS: Final = 1.0

# How the wait between looks is spent. Injected for the reason the metrics
# reading is: a rollout that never arrives is a case worth a test, and one
# spending a real minute of it is a case nobody runs.
Sleeper = Callable[[float], None]


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


def _not_restarted(said: str, error: DeploymentPlatformError) -> ServiceNotRestarted:
    """This module's failure, marked where the platform was never reached.

    One exception still, because what a caller does about this restart is
    unchanged: it did not happen. What the mark adds is about the other three
    actions, not this one - the platform they share is not answering either, so
    reaching for them costs a request each to learn what is already known.

    Reached only from before the action is accepted, and that is the whole of
    why it needs no flag saying so. The other three actions mark a failure that
    came after they changed something and send the descriptor with it; a restart
    cannot, and the reason is verification rather than undo. Once the platform
    has taken the action, pods may be rolling this second and nothing here can
    establish whether they are - so a walk that narrowed to another action would
    measure its recovery against a service that may be coming back on its own,
    and confirm a hypothesis the restart had answered. The failures after that
    point raise `ServiceNotRestarted` plainly and escalate, which is the honest
    report of a state Argus cannot describe.
    """
    if isinstance(error, PlatformUnreachable):
        return ServiceNotRestarted(an_unreachable_platform(DEPLOYMENT_PLATFORM, said))

    return ServiceNotRestarted(said)


def restart_service(service: str,
                    platform: DeploymentPlatformWrites,
                    *,
                    sleep: Sleeper = time.sleep) -> RestartedService:
    """Restarts `service` and waits until a new process is serving it.

    Returns the new process start time, which is the only evidence that the
    restart landed: memory falling is ambiguous - the process restarted, or the
    traffic dropped - and without the start time a caller cannot tell a restart
    that did not happen from one that happened and did not help.

    Raises `ServiceNotRestarted` unless the platform accepted the action *and*
    the start time moved. There is no undo descriptor and no field for one: a
    restart changes no persistent state, so there is nothing to put back (§13).
    """
    try:
        was_started_at = platform.newest_pod_started_at(service)
    except DeploymentPlatformError as error:
        # The first thing a restart does is ask what is serving, so on a
        # platform that is down this is where it finds out - and an action that
        # never reached the request would otherwise report nothing about the
        # platform at all. Nothing has been asked for yet, so the mark is honest.
        raise _not_restarted(
            f"could not read what is serving [{service}]: {error}", error
        ) from error

    try:
        platform.restart(service)
    except DeploymentPlatformError as error:
        raise _not_restarted(f"could not restart [{service}]: {error}", error) from error

    started_at = _wait_until_a_new_process_serves(service, was_started_at, platform, sleep)

    logger.info("service restarted", extra={"service": service})

    return RestartedService(service=service, process_start_time_seconds=started_at)


def _wait_until_a_new_process_serves(service: str,
                                     was_started_at: float | None,
                                     platform: DeploymentPlatformWrites,
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
            started_at = platform.newest_pod_started_at(service)
        except DeploymentPlatformError as error:
            raise ServiceNotRestarted(
                f"could not confirm [{service}] restarted: {error}"
            ) from error

        if started_at is not None and started_at != was_started_at:
            return started_at

        if attempt + 1 < _START_TIME_ATTEMPTS:
            sleep(_SECONDS_BETWEEN_ATTEMPTS)

    logger.warning("restart not confirmed in time", extra={"service": service})

    raise ServiceNotRestarted(
        f"[{service}] was accepted for restart but is still served by the "
        f"process that was running before"
    )
