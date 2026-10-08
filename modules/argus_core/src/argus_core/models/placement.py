from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from pydantic import BaseModel

# How long before the onset a pod may have started and still count as having
# started at it. A measured onset is the first whole minute that departed, and a
# pod is placed inside a minute: the minute it lands in is partly served each
# way and may not depart on its own, so the first minute that does can be the
# one after.
THE_ONSETS_GRACE: Final = timedelta(minutes=1)


class PodPlacement(BaseModel, frozen=True):
    """Where one of an application's pods is running, and since when.

    `accelerator` is the product of the card the pod's node carries, as the
    platform reports it - or `None` where the platform reports none, which is a
    node with no card or a platform not configured to say, and never a guess.
    `started_at` is when the pod came up, which is the moment it was last placed.
    """

    pod: str
    node: str
    accelerator: str | None
    started_at: datetime


class RecordedPlacement(BaseModel, frozen=True):
    """Where an application's pods were running, recorded against the onset.

    The two travel together because the placement means nothing without the
    minute it was read against: which pods started at the onset is what makes a
    card a suspect, and four readers ask it - the model's opening message, the
    timeline, the postmortem and the strategy that pins a deployment to a card.
    The rule is said once, here, so that all four mark the same pods.

    A contract rather than the Investigator's own type, because the walk carries
    it to a strategy and an event carries it to the page, and a shape kept
    inside the agent is one the others install an agent to read.
    """

    onset: datetime
    pods: tuple[PodPlacement, ...]

    def started_before_the_onset(self) -> list[PodPlacement]:
        """The pods that were serving before the incident began, in the order
        they were recorded."""
        return [pod for pod in self.pods if not self._started_at_the_onset(pod)]

    def started_at_the_onset(self) -> list[PodPlacement]:
        """The pods started at the onset or since, in the order they were
        recorded - the ones that have only ever served during the incident."""
        return [pod for pod in self.pods if self._started_at_the_onset(pod)]

    def _started_at_the_onset(self, pod: PodPlacement) -> bool:
        return pod.started_at >= self.onset - THE_ONSETS_GRACE
