"""The shop's random draws, moved to the minutes a recording was captured in.

The shop draws each minute's figures from a sequence named after the minute, so
the replay's minute takes the name of the recorded minute it stands for. Only
names that begin with a minute move: a shopper's own sequence is named after the
shopper, and no clock has anything to say about it.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from types import ModuleType
from typing import Any


class ShiftedDraws:
    """Stands where the shop's generator keeps the `random` module.

    `shift` is how far the replay's world is ahead of the recorded one: zero,
    and every sequence is the shop's own. Everything but `Random` is the module
    itself, because nothing else the shop draws is named after a minute.
    """

    def __init__(self, module: ModuleType, minute_format: str) -> None:
        self.shift = timedelta(0)
        self._module = module
        self._minute_format = minute_format
        # How long a minute's name is in that format: every one is the same
        # length, so the name is the first that many characters of a seed and
        # whatever follows it is the sequence's own suffix.
        self._minute_length = len(datetime(2000, 1, 1).strftime(minute_format))

    def Random(self, seed: Any = None) -> random.Random:  # the module's own name for it
        """The sequence the shop asked for, named for the minute it stands for."""
        sequence: random.Random = self._module.Random(self._moved(seed))

        return sequence

    def __getattr__(self, name: str) -> Any:
        return getattr(self._module, name)

    def _moved(self, seed: Any) -> Any:
        if not isinstance(seed, str) or not self.shift:
            return seed

        named, suffix = seed[:self._minute_length], seed[self._minute_length:]

        try:
            minute = datetime.strptime(named, self._minute_format)
        except ValueError:
            return seed

        return (minute - self.shift).strftime(self._minute_format) + suffix
