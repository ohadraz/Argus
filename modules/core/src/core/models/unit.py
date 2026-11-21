"""The unit a level is in, in Argus's own words."""

from __future__ import annotations

from enum import StrEnum


class Unit(StrEnum):
    """What a level a series reads is measured in.

    Argus's vocabulary rather than any monitoring stack's: whatever says a unit -
    a dashboard's panel, a metric's name - is translated into one of these by the
    adapter that reads it, and a unit no member names is no unit at all. Unknown,
    never guessed, since a level said in the wrong unit is wrong by its scale.

    A contract because three parties name it: the read tier says the unit of the
    series a rule watches, the postmortem carries it on the levels it measures,
    and the rendering writes each level in it.

    `SHARE_OF_ONE` is a fraction - 0.25 for a quarter - and `PERCENT` a number
    already out of a hundred; both are said as a percentage.
    """

    SHARE_OF_ONE = "share_of_one"
    PERCENT = "percent"
    MILLISECONDS = "milliseconds"
    SECONDS = "seconds"
    BYTES = "bytes"
