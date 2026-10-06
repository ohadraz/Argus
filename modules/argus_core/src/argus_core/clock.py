"""The one clock every process of a stack reads, at whatever rate the stack runs.

A stack hands every process the same two numbers - an epoch and a speed - and
each works out the same instant from its own real clock:
`epoch + (real - epoch) * speed`. No process asks another what time it is, so
none can be ahead of an answer it has not had yet. Told neither number, a
process runs on the real clock, read exactly as it always was.

What cannot run this code - Postgres, the flag provider, the Target Service -
follows the same formula through libfaketime, fed by the stack's clock writer.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

# The two settings a stack hands every process, Argus's and the containers'
# alike - which is why they name a clock rather than Argus.
CLOCK_EPOCH_VARIABLE: Final = "SIM_CLOCK_EPOCH"
CLOCK_SPEED_VARIABLE: Final = "SIM_CLOCK_SPEED"


@dataclass(frozen=True)
class Clock:
    """A clock running `speed` times real time, counted from `epoch`.

    Real time and real sleep are held rather than reached for, so a test can
    stand in for both and nothing it asks of the clock waits on a wall clock.
    """

    epoch: float = 0.0
    speed: float = 1.0
    real_time: Callable[[], float] = time.time
    real_sleep: Callable[[float], None] = time.sleep

    def now(self) -> datetime:
        """This clock's instant, in UTC."""
        return datetime.fromtimestamp(
            self.epoch + (self.real_time() - self.epoch) * self.speed, UTC
        )

    def sleep(self, seconds: float) -> None:
        """Waits `seconds` of this clock, which is `seconds / speed` of real time.

        For a wait that stands for time passing in the world being watched. A
        wait bounding real work - a timeout, a budget - is not one, and stays on
        the real clock.
        """
        self.real_sleep(self.in_real_time(seconds))

    def in_real_time(self, seconds: float) -> float:
        """How long `seconds` of this clock lasts on the real one.

        For a wait this process does not sleep through itself - a thread woken
        by an event, say - but which stands for a span some other party measures
        on this clock.
        """
        return seconds / self.speed


def the_clock_named_by(environment: Mapping[str, str]) -> Clock:
    """The clock these settings describe: the real one where neither is set.

    Raises `ValueError` where only one is. A stack configured by half would put
    this process on a different time from every other one in it, and the
    symptom would be a verdict gone wrong minutes later, nowhere near the
    setting that caused it.
    """
    epoch = environment.get(CLOCK_EPOCH_VARIABLE)
    speed = environment.get(CLOCK_SPEED_VARIABLE)

    if epoch is None and speed is None:
        return Clock()

    if epoch is None or speed is None:
        raise ValueError(
            f"A simulated clock needs both {CLOCK_EPOCH_VARIABLE} and "
            f"{CLOCK_SPEED_VARIABLE}; this environment sets only one."
        )

    return Clock(epoch=float(epoch), speed=float(speed))
