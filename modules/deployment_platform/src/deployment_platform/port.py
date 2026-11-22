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
from datetime import datetime
from enum import Enum, StrEnum, auto
from typing import Protocol

from core.models import PodPlacement, RolloutProgress


class MarkedObject(StrEnum):
    """Which of an application's objects a mark is read off (`mark_on`): the one
    whose sync switch a suspension writes, the Deployment a count or a card is
    written to, and the autoscaler whose floor a pin raises. Each carries the
    mark of whatever last wrote it.

    An enum rather than strings, so an adapter answering for every kind is
    checked to answer for every one, and a caller cannot name a kind there is
    none of.
    """

    APPLICATION = "application"
    DEPLOYMENT = "deployment"
    AUTOSCALER = "autoscaler"


@dataclass(frozen=True)
class DeploymentRecord:
    """One deployment the platform recorded of an application.

    `history_id` is how the platform names the entry, and what a rollback is asked
    to return to. `deployed_at` is when it landed, which is the moment its symptoms
    could start. Where it was synced from and who started it are `None` where the
    platform did not say.

    `made_by_argus` is whether the account that started it is the one Argus
    goes by on the platform - which only the adapter knows - and `None` where
    that cannot be told: no account recorded, or none configured as Argus's.
    """

    history_id: int
    revision: str
    deployed_at: str
    repo_url: str | None
    path: str | None
    initiated_by: str | None
    made_by_argus: bool | None = None


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


class SyncPhase(Enum):
    """Where a sync the platform ran stands.

    `TERMINATING` while it is being stopped, and `TERMINATED` once it has ended
    stopped - told apart from `FAILED` and `ERROR`, a run that failed of
    itself, because a stopped run was stopped by somebody, or by the platform
    itself where it stops runs on its own (a sync timeout), and the two may end
    in the same words. Who stopped it is not said here. How a platform says a
    run ended stopped is its adapter's to read.
    """

    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    ERROR = auto()
    TERMINATING = auto()
    TERMINATED = auto()


@dataclass(frozen=True)
class RequestedSync:
    """A sync asked of the platform and not yet finished - a rollback among
    them, from the moment the request is answered: the revision it is to, and
    the account that asked, `None` where it names none (the platform's own).

    `made_by_argus` as `DeploymentRecord` has it."""

    revision: str | None
    initiated_by: str | None
    made_by_argus: bool | None = None


@dataclass(frozen=True)
class SyncRun:
    """The last sync the platform started running: the revision it is to, the
    account that asked, when it started, and where it stands.

    `made_by_argus` as `DeploymentRecord` has it."""

    revision: str | None
    initiated_by: str | None
    started_at: datetime
    phase: SyncPhase
    made_by_argus: bool | None = None


@dataclass(frozen=True)
class SyncOperations:
    """What the platform says of an application's syncs: the one asked and not
    yet finished, and the last one it ran - either `None` where it says none.

    Both, because they are told apart in time. A request is recorded the moment
    it is answered and runs only later, and the history gains its entry only
    when the run finishes - so between the two a change already asked for shows
    nowhere else.
    """

    requested: RequestedSync | None
    last_run: SyncRun | None


@dataclass(frozen=True)
class Mark:
    """Argus's mark on a change it writes: which action it was made for, by the
    action's row id, and when the write tier wrote it.

    Carried by the change itself, on the object changed, so that whoever reads
    the platform afterwards - a put-back asking whether anybody changed it since,
    a walk resumed after its worker died - can tell Argus's change from a
    person's, and which of Argus's actions it was.
    """

    action_id: str
    written_at: datetime


@dataclass(frozen=True)
class MarkFound:
    """A `Mark` as it is read back off an object: the action it names, and the
    moment it says it was written - `None` where it says none, or says one that
    does not read as a time.

    Its own type rather than a `Mark`, because a mark written always knows when
    and one read back may not: whose the change is does not wait on when, and a
    moment nobody can read is said to be unknown rather than made up.
    """

    action_id: str
    written_at: datetime | None


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
    """What changing the platform can ask, beside everything reading can.

    Every write that leaves an object changed carries Argus's `Mark` on it. A
    rollback does not: the platform records who rolled back itself, and its
    request has nowhere to put one. Nor does a restart, which leaves nothing to
    put back.
    """

    def now(self, application: str, /) -> datetime:
        """The platform's own clock, as it dates its answer about `application`.

        What a change is planned `since`, read before the state it dates: a
        change the platform records is then put either side of it on one clock.
        """
        ...

    def mark_on(self, application: str, kind: MarkedObject, /) -> MarkFound | None:
        """The mark the application's object `kind` carries - the action it
        names, by its row id, and when it says it was written - or `None` where
        it carries none, or where the application has no such object."""
        ...

    def sync_operations_of(self, application: str, /) -> SyncOperations:
        """The application's sync asked and not yet finished, and the last one
        the platform ran."""
        ...

    def is_syncing_itself(self, application: str, /) -> bool:
        """Whether the platform reconciles the application on its own."""
        ...

    def suspend_sync(self, application: str, mark: Mark, /) -> None:
        """Stops the platform reconciling the application, keeping its policy."""
        ...

    def resume_sync(self, application: str, mark: Mark, /) -> None:
        """Lets the platform reconcile the application again."""
        ...

    def scale(self, application: str, replicas: int, mark: Mark, /) -> datetime | None:
        """Asks for `replicas` of the application's Deployment, and answers
        with when the platform answered, by its own clock - see `roll_back`."""
        ...

    def roll_back(self, application: str, to_history_id: int, /) -> datetime | None:
        """Returns the application to the recorded deployment named, and answers
        with when the platform answered, by its own clock.

        What the change's way back is dated by. `None` where the answer did not
        say when: the change landed, so it is not refused, and no other clock
        stands in for the platform's - a reader takes absent as unknown.
        """
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
                             mark: Mark,
                             /) -> datetime | None:
        """Raises or lowers the autoscaler's floor, and nothing else about it -
        answering with when the platform answered, as `roll_back` does."""
        ...

    def accelerator_pin_of(self, application: str, /) -> str | None:
        """The card the live Deployment's pods are held to, or `None` where they
        are held to none."""
        ...

    def pin_to_accelerator(self,
                           application: str,
                           accelerator: str | None,
                           mark: Mark,
                           /) -> datetime | None:
        """Holds the Deployment's pods to one card, or releases them where
        `accelerator` is `None` - and changes nothing else it selects on.
        Answers with when the platform answered, as `roll_back` does."""
        ...

    def images_running(self, application: str, /) -> dict[str, str]:
        """The image each of the live Deployment's containers starts, by
        container name - init containers among them."""
        ...

    def images_at(self, application: str, revision: str, /) -> dict[str, str]:
        """The image each container of the application's Deployment is started
        from as the platform renders `revision`, by container name - init
        containers among them.

        Beside `images_running`, it says whether what is running is what that
        revision ships: a change made to the Deployment outside the platform - an
        image set by hand - leaves no history entry, and shows only here.
        """
        ...
