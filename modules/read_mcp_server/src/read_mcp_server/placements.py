"""Where a service's replicas run, read as evidence.

The channel that reads what no other one holds. A replica moved to another card
with nothing deployed is in no deployment history, no diff and no flag log: the
platform rescheduled a pod, and the only record of that is where the pods now
are and when each started. So this is how the one failure mode whose cause is a
placement becomes evidence at all.

Nothing here judges. Whether a pod started before the onset or at it, and
whether its card is the one that matters, belongs to whoever holds the onset -
which this tier has never seen. It says what the platform reports, and leaves
the reading.
"""

from __future__ import annotations

from argus_core.models import PodPlacement
from deployment_platform import DeploymentPlatformError, DeploymentPlatformReads


class PlacementUnreadable(Exception):
    """The platform would not say where the service's replicas run.

    Raised rather than answered emptily. An empty list says the service runs
    nowhere, and a reader deciding from it finds no replica that moved - an
    outage read as an all-clear, on exactly the mode only this channel can show.
    """


def where_the_service_runs(service: str,
                           *,
                           platform: DeploymentPlatformReads) -> list[PodPlacement]:
    """Each of `service`'s pods, the node it runs on, that node's card and when
    the pod started - as the platform reports them.

    Refused whichever way the platform failed: a placement this could not read
    is unknown, and unknown must not arrive looking like a service with no pods.
    """
    try:
        return platform.placements_of(service)
    except DeploymentPlatformError as error:
        raise PlacementUnreadable(
            f"could not read where [{service}] is running: {error}"
        ) from error
