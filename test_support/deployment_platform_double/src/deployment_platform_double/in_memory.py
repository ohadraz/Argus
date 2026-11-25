"""Both deployment-platform ports, answered from memory.

Built from a `PlatformState` and changed by every write, so a write is read back
as the platform would read it back. Everything it says is what the port
promises and the port's suite pins over both adapters - so what Argo CD does
that the port does not promise, it does not do either: it says every moment to
the second, as Argo CD's marks and HTTP dates do, and tells Argus's own changes
from anybody's as the Argo CD adapter does.

What a platform finishes later - a rollback's history entry once its sync runs,
a restart's new pods once the Deployment rolls - lands here at once. The suite
asks every adapter to finish before it reads such an effect, so "at once" is
never part of the port.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from core.models import PodPlacement, RolloutProgress
from deployment_platform import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentRecord,
    Mark,
    MarkedObject,
    MarkFound,
    PlatformRefused,
    PlatformUnreachable,
    SyncOperations,
)

from deployment_platform_double.state import (
    ApplicationState,
    AutoscalerState,
    HistoryEntry,
    PlatformState,
)

# How the platform spells a moment it records: UTC, to the second.
_DEPLOYED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class InMemoryPlatform:
    """A deployment platform held in memory.

    `argus_account` is the account Argus is configured to recognise as its own
    - empty or `None` where none is, and then nothing is told as Argus's or
    anybody else's. `clock` is the platform's own: what `now` says and what
    every write is answered with. `unreachable` builds a platform nothing
    reaches, every call to which fails as never having been sent.
    """

    def __init__(self,
                 state: PlatformState,
                 *,
                 argus_account: str | None,
                 clock: Callable[[], datetime],
                 unreachable: bool = False) -> None:
        self._applications = {application.name: application
                              for application in state.applications}
        self._cards = {node.name: node.card for node in state.nodes}
        self._signed_in_as = state.signed_in_as
        self._argus_account = argus_account
        self._clock = clock
        self._unreachable = unreachable
        self._marks: dict[tuple[str, MarkedObject], MarkFound] = {}

    def deployments_of(self, application: str, /) -> list[DeploymentRecord]:
        return [
            DeploymentRecord(
                history_id=entry.history_id,
                revision=entry.revision,
                deployed_at=entry.deployed_at,
                repo_url=entry.repo_url,
                path=entry.path,
                initiated_by=entry.initiated_by,
                made_by_argus=self._whether_argus_started(entry.initiated_by)
            )
            for entry in self._the(application).history
        ]

    def rollout_of(self, application: str, /) -> RolloutProgress:
        held = self._the(application)

        return RolloutProgress(
            replicas_wanted=held.replicas,
            replicas_serving=held.replicas if held.serving is None else held.serving,
            replicas_updated=held.replicas if held.updated is None else held.updated,
            is_paused=held.paused,
            has_failed=held.has_failed
        )

    def placements_of(self, application: str, /) -> list[PodPlacement]:
        return [
            PodPlacement(pod=pod.name,
                         node=pod.node,
                         accelerator=self._cards.get(pod.node),
                         started_at=_to_the_second(pod.started_at))
            for pod in self._the(application).pods
            if pod.node is not None
        ]

    def now(self, application: str, /) -> datetime:
        self._the(application)

        return self._now()

    def mark_on(self, application: str, kind: MarkedObject, /) -> MarkFound | None:
        if kind is MarkedObject.AUTOSCALER and self._the(application).autoscaler is None:
            return None

        self._the(application)

        return self._marks.get((application, kind))

    def sync_operations_of(self, application: str, /) -> SyncOperations:
        self._the(application)

        return SyncOperations(requested=None, last_run=None)

    def is_syncing_itself(self, application: str, /) -> bool:
        return self._the(application).syncs_itself

    def suspend_sync(self, application: str, mark: Mark, /) -> None:
        self._change(application, MarkedObject.APPLICATION, mark,
                     lambda held: replace(held, syncs_itself=False))

    def resume_sync(self, application: str, mark: Mark, /) -> None:
        self._change(application, MarkedObject.APPLICATION, mark,
                     lambda held: replace(held, syncs_itself=True))

    def scale(self, application: str, replicas: int, mark: Mark, /) -> datetime | None:
        self._change(application, MarkedObject.DEPLOYMENT, mark,
                     lambda held: replace(held, replicas=replicas))

        return self._now()

    def roll_back(self, application: str, to_history_id: int, /) -> datetime | None:
        """Refused while the platform syncs the application itself, as Argo CD
        refuses it, and refused for an entry the history does not hold."""
        held = self._the(application)

        if held.syncs_itself:
            raise PlatformRefused(f"[{application}] syncs itself, and a rollback is refused",
                                  known_not_applied=True)

        returned_to = next((entry for entry in held.history
                            if entry.history_id == to_history_id), None)

        if returned_to is None:
            raise PlatformRefused(f"[{application}] has no history entry [{to_history_id}]",
                                  known_not_applied=True)

        # Numbered after the last entry, as Argo CD numbers the next.
        added = HistoryEntry(
            history_id=held.history[-1].history_id + 1,
            revision=returned_to.revision,
            deployed_at=self._now().strftime(_DEPLOYED_AT_FORMAT),
            repo_url=returned_to.repo_url,
            path=returned_to.path,
            initiated_by=self._signed_in_as
        )
        self._applications[application] = replace(held, history=(*held.history, added),
                                                   running=None)

        return self._now()

    def restart(self, service: str, /) -> None:
        """Every process serving the service replaced by one started now, on
        the node its predecessor ran on."""
        held = self._the(service)
        started_at = self._now()

        self._applications[service] = replace(
            held, pods=tuple(replace(pod, started_at=started_at) for pod in held.pods)
        )

    def newest_pod_started_at(self, service: str, /) -> float | None:
        """The newest start of every pod, placed or not - a pod still waiting
        for a node is the newest process right after a restart."""
        starts = [_to_the_second(pod.started_at).timestamp()
                  for pod in self._the(service).pods]

        return max(starts, default=None)

    def autoscaler_of(self, application: str, /) -> Autoscaler | None:
        held = self._the(application).autoscaler

        return None if held is None else held.autoscaler

    def autoscaler_bounds(self,
                          application: str,
                          autoscaler: Autoscaler,
                          /) -> AutoscalerBounds:
        return self._the_autoscaler(application, autoscaler).bounds

    def set_autoscaler_floor(self,
                             application: str,
                             autoscaler: Autoscaler,
                             floor: int,
                             mark: Mark,
                             /) -> datetime | None:
        current = self._the_autoscaler(application, autoscaler)
        refloored = replace(current, bounds=replace(current.bounds, floor=floor))
        self._change(application, MarkedObject.AUTOSCALER, mark,
                     lambda held: replace(held, autoscaler=refloored))

        return self._now()

    def accelerator_pin_of(self, application: str, /) -> str | None:
        return self._the(application).accelerator_pin

    def pin_to_accelerator(self,
                           application: str,
                           accelerator: str | None,
                           mark: Mark,
                           /) -> datetime | None:
        self._change(application, MarkedObject.DEPLOYMENT, mark,
                     lambda held: replace(held, accelerator_pin=accelerator))

        return self._now()

    def images_running(self, application: str, /) -> dict[str, str]:
        held = self._the(application)

        if held.running is not None:
            return {container.name: container.image for container in held.running}

        return self.images_at(application, held.history[-1].revision)

    def images_at(self, application: str, revision: str, /) -> dict[str, str]:
        """Refused for a revision rendering no Deployment, as the Argo CD
        adapter refuses it: compared with nothing, every image running would
        read as somebody else's."""
        rendered = next((rendering for rendering in self._the(application).renderings
                         if rendering.revision == revision), None)

        if rendered is None:
            raise PlatformRefused(f"[{application}] renders no Deployment at [{revision}]",
                                  known_not_applied=True)

        return {container.name: container.image for container in rendered.containers}

    def _the(self, application: str) -> ApplicationState:
        """The application held, failing as the platform fails to answer for
        one: unreachable, or refusing an application it does not hold."""
        if self._unreachable:
            raise PlatformUnreachable("the platform is not reachable", known_not_applied=True)

        held = self._applications.get(application)

        if held is None:
            raise PlatformRefused(f"no application [{application}]", known_not_applied=True)

        return held

    def _the_autoscaler(self, application: str, autoscaler: Autoscaler) -> AutoscalerState:
        held = self._the(application).autoscaler

        if held is None or held.autoscaler != autoscaler:
            raise PlatformRefused(f"[{application}] has no autoscaler [{autoscaler.name}]",
                                  known_not_applied=True)

        return held

    def _change(self, application: str, kind: MarkedObject, mark: Mark,
                changed: Callable[[ApplicationState], ApplicationState]) -> None:
        """The application `changed`, and `mark` left on its object `kind`."""
        self._applications[application] = changed(self._the(application))
        self._marks[(application, kind)] = MarkFound(action_id=mark.action_id,
                                                     written_at=_to_the_second(mark.written_at))

    def _whether_argus_started(self, initiated_by: str | None) -> bool | None:
        """As the Argo CD adapter tells it: without regard to case, and `None`
        where either account is missing."""
        if not self._argus_account or not initiated_by:
            return None

        return initiated_by.casefold() == self._argus_account.casefold()

    def _now(self) -> datetime:
        return _to_the_second(self._clock())


def _to_the_second(moment: datetime) -> datetime:
    """`moment` in UTC, to the second, as the platform says every moment."""
    return moment.astimezone(UTC).replace(microsecond=0)
