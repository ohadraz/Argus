"""What Argus asks of whatever deploys its services, and what comes back.

Two ports, split where the MCP servers are split (spec §12.1): one that can only
read, and one that can also change the platform. The read server is handed the
first, so a change typed there does not type-check, and the line the two servers
draw holds in the code they run as well as in the processes they run in.

Every operation is named for what Argus wants rather than for the route that
answers it, and every answer is Argus's own value. Nothing here is a URL, a
selector or a response body; those are an adapter's, and an adapter is named for
its vendor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from argus_core.models import PodPlacement, RolloutProgress


@dataclass(frozen=True)
class DeploymentRecord:
    """One deployment the platform recorded of an application.

    `history_id` is how the platform names the entry, and what a rollback is asked
    to return to. `deployed_at` is when it landed, which is the moment its symptoms
    could start. Where it was synced from and who started it are `None` where the
    platform did not say.
    """

    history_id: int
    revision: str
    deployed_at: str
    repo_url: str | None
    path: str | None
    initiated_by: str | None


@dataclass(frozen=True)
class Autoscaler:
    """Which autoscaler an application has, as the platform names it.

    Two fields rather than a pair of strings: they are one answer to one question,
    and a caller that could swap them would address a namespace by a resource's
    name.
    """

    name: str
    namespace: str


@dataclass(frozen=True)
class AutoscalerBounds:
    """The fewest replicas an autoscaler may fall to, and the most it may rise to."""

    floor: int
    ceiling: int


class DeploymentPlatformReads(Protocol):
    """What reading the platform can ask, and nothing that changes it.

    Failures raise a `DeploymentPlatformError`, never an empty answer: an outage
    read as "nothing deployed" or "it converged" is a fabricated account of an
    incident.
    """

    def deployments_of(self, application: str, /) -> list[DeploymentRecord]:
        """Every deployment the platform recorded, in the order it serves them."""
        ...

    def rollout_of(self, application: str, /) -> RolloutProgress:
        """How far the running Deployment has got towards what it was asked for."""
        ...

    def placements_of(self, application: str, /) -> list[PodPlacement]:
        """Where each of the application's pods is running, and since when.

        A pod whose node or start the platform does not say is left out, and a
        node whose card it does not say has none - never a guess at either.
        """
        ...


class DeploymentPlatformWrites(DeploymentPlatformReads, Protocol):
    """What changing the platform can ask, beside everything reading can."""

    def is_syncing_itself(self, application: str, /) -> bool:
        """Whether the platform reconciles the application on its own."""
        ...

    def suspend_sync(self, application: str, /) -> None:
        """Stops the platform reconciling the application, keeping its policy."""
        ...

    def resume_sync(self, application: str, /) -> None:
        """Lets the platform reconcile the application again."""
        ...

    def scale(self, application: str, replicas: int, /) -> None:
        """Asks for `replicas` of the application's Deployment."""
        ...

    def roll_back(self, application: str, to_history_id: int, /) -> None:
        """Returns the application to the recorded deployment named."""
        ...

    def restart(self, service: str, /) -> None:
        """Restarts the processes serving `service`."""
        ...

    def newest_pod_started_at(self, service: str, /) -> float | None:
        """When the newest process serving `service` came up, in epoch seconds.

        `None` where nothing is running or no start time can be read - the
        absence of a reading, never a reading of no change.
        """
        ...

    def autoscaler_of(self, application: str, /) -> Autoscaler | None:
        """The application's autoscaler, or `None` where it has none."""
        ...

    def autoscaler_bounds(self,
                          application: str,
                          autoscaler: Autoscaler,
                          /) -> AutoscalerBounds:
        """The bounds in force, read from the live resource."""
        ...

    def set_autoscaler_floor(self,
                             application: str,
                             autoscaler: Autoscaler,
                             floor: int,
                             /) -> None:
        """Raises or lowers the autoscaler's floor, and nothing else about it."""
        ...

    def accelerator_pin_of(self, application: str, /) -> str | None:
        """The card the live Deployment's pods are held to, or `None` where they
        are held to none."""
        ...

    def pin_to_accelerator(self, application: str, accelerator: str | None, /) -> None:
        """Holds the Deployment's pods to one card, or releases them where
        `accelerator` is `None` - and changes nothing else it selects on."""
        ...
