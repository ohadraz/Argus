"""The events an incident produced, as a human would be told them, and a
destination that remembers being told."""

from __future__ import annotations

from agent_communicator.policy import Register
from agent_communicator.relaying import Outcome
from argus_core.events import ActionTaken, IncidentEvent, OnsetDetected, StatusChanged
from argus_core.models import IncidentStatus
from argus_narration import NarrationLine
from chat_platform import Link


def three_steps_of(incident_id: str) -> list[IncidentEvent]:
    """An incident's onset, the action taken for it, and where it ended.

    Three things a human is meant to hear, so that what these tests measure is
    the reading, the order and the place rather than the policy. Three rather
    than one because the questions worth asking of a relay - did it keep the
    order, did it stop where it said it stopped - cannot be asked of a single
    event.
    """
    return [
        OnsetDetected(incident_id=incident_id, onset="2026-08-30T10:03:00Z"),
        ActionTaken(
            incident_id=incident_id,
            hypothesis_id=None,
            action_type="revert-feature-flag",
            subject="monthly-spend-feature",
            enabled=False
        ),
        StatusChanged(incident_id=incident_id, to_status=IncidentStatus.RESOLVED)
    ]


class ADestination:
    """A destination that remembers what it was told, and can refuse.

    Hand-written rather than a mock because every test of the relay asks the
    same three questions - what was said, how loudly, and in what order - and a
    recorder answers them in the language of the subject rather than in call
    tuples.
    """

    def __init__(self,
                 gives_up_after: int | None = None,
                 gives_up_with: Outcome = Outcome.NOT_NOW) -> None:
        self.told: list[tuple[str, NarrationLine, Register]] = []
        self._gives_up_after = gives_up_after
        self._gives_up_with = gives_up_with

    def __call__(self,
                 incident_id: str,
                 line: NarrationLine,
                 register: Register,
                 link: Link | None = None, /) -> Outcome:
        if (self._gives_up_after is not None
                and len(self.told) >= self._gives_up_after):
            return self._gives_up_with

        self.told.append((incident_id, line, register))

        return Outcome.SAID


def a_destination_that_takes_everything() -> ADestination:
    return ADestination()


def a_destination_that_cannot_say_more_now(landed: int) -> ADestination:
    return ADestination(gives_up_after=landed, gives_up_with=Outcome.NOT_NOW)


def a_destination_that_will_never_say_more(landed: int) -> ADestination:
    return ADestination(gives_up_after=landed, gives_up_with=Outcome.NEVER)
