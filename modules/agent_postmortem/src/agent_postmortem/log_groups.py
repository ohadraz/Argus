"""The log lines an incident read, one piece of evidence per message.

A service logs the same message every minute it is broken, so an incident's
log block is mostly one line said many times - five copies of one
ZeroDivisionError, cited one by one, is how a causal step came to read like a
traceback. Grouped by message, each says what happened once: how often, over
how long, and how far whatever varied between the copies ranged. Not every
minute it was logged in - a fault that ran three hours is a hundred and eighty
minutes nobody reads to the end.

Each group is named by its message rather than by its place. A recorded answer
is replayed in a run that read a different number of lines - one message more
or fewer - and a label counted by position would then name a different line,
where one derived from the message names the same one or none at all.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Final

from argus_core.models import CitedEvidence

# How a group's label begins. The rest is the start of a digest of the message,
# so a message keeps its label in every run that read it.
LOG_GROUP_PREFIX: Final = "G"

# How much of the digest the label carries. Four hex characters is one name in
# sixty-five thousand, for an incident reading a few dozen distinct messages.
_DIGEST_LENGTH: Final = 4

# The minute a log line opens with, in the service's own wire format.
_STAMPED: Final = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?Z?)\s+")

# Between the first minute of a span and its last.
_TO: Final = "–"

# A number inside a message - the part that varies from minute to minute.
_A_NUMBER: Final = re.compile(r"(\d+(?:\.\d+)?)")


def grouped(log_lines: Sequence[str]) -> list[CitedEvidence]:
    """Every distinct message, in the order it was first logged, each under a
    label of its own and said once.

    A message logged once is shown as it was logged. One logged more often is
    said with the numbers that held every time written in and a `#` where they
    varied, then how many times it was logged over how many minutes, first to
    last - and, for each number that varied, how far it ranged, what it
    typically read, and the minute it was highest.
    """
    groups: dict[str, list[tuple[datetime | None, list[str]]]] = {}
    for line in log_lines:
        logged_at, message = _split(line)
        parts = _A_NUMBER.split(message)
        key = "#".join(parts[0::2])
        groups.setdefault(key, []).append((logged_at, parts))

    return [CitedEvidence(label=_label_for(key), text=_said_once(occurrences))
            for key, occurrences in groups.items()]


def _split(line: str) -> tuple[datetime | None, str]:
    """When a line was logged, and what it said."""
    stamped = _STAMPED.match(line)
    if stamped is None:
        return None, line

    return datetime.fromisoformat(stamped.group(1)), line[stamped.end():]


def _label_for(key: str) -> str:
    return LOG_GROUP_PREFIX + hashlib.sha1(key.encode()).hexdigest()[:_DIGEST_LENGTH]


def _said_once(occurrences: list[tuple[datetime | None, list[str]]]) -> str:
    """One group as one line."""
    if len(occurrences) == 1:
        logged_at, parts = occurrences[0]
        return "".join(parts) if logged_at is None else f"{_clock(logged_at)} {''.join(parts)}"

    first = occurrences[0][1]
    numbers = [parts[1::2] for _, parts in occurrences]
    held = [all(each[position] == numbers[0][position] for each in numbers)
            for position in range(len(numbers[0]))]

    message = "".join(
        part if index % 2 == 0 else (part if held[index // 2] else "#")
        for index, part in enumerate(first)
    )
    varied = [_how_it_ranged([(logged_at, each[position])
                              for (logged_at, _), each in zip(occurrences, numbers, strict=True)])
              for position, kept in enumerate(held) if not kept]

    return "; ".join([f"{message} - {_how_often(occurrences)}", *varied])


def _how_often(occurrences: list[tuple[datetime | None, list[str]]]) -> str:
    """How many times, and over which minutes, counting the first and the last.

    Every line counted: two replicas logging one failure in the same minute are
    two failures. A line with no stamp is counted and dates nothing, since a
    span made up for it would be a guess.
    """
    counted = f"{len(occurrences)} occurrences"
    stamped = sorted(logged_at.replace(second=0, microsecond=0)
                     for logged_at, _ in occurrences if logged_at is not None)

    if not stamped:
        return counted

    first, last = stamped[0], stamped[-1]
    minutes = int((last - first).total_seconds() // 60) + 1

    if minutes == 1:
        return f"{counted} in 1 minute, {_clock(first)}"

    return f"{counted} in {minutes} minutes, {_clock(first)}{_TO}{_clock(last)}"


def _how_it_ranged(readings: list[tuple[datetime | None, str]]) -> str:
    """One varying number: lowest to highest, the middle value read, and the
    minute of the highest.

    Typical is a value some minute actually read - the lower middle, never an
    average no minute logged. Each value is said as it was logged.
    """
    ordered = sorted(readings, key=lambda reading: float(reading[1]))
    typical = ordered[(len(ordered) - 1) // 2][1]
    highest_at, _ = max(readings, key=lambda reading: float(reading[1]))
    when = f", highest at {_clock(highest_at)}" if highest_at is not None else ""

    return f"# was {ordered[0][1]} to {ordered[-1][1]}, typically {typical}{when}"


def _clock(logged_at: datetime) -> str:
    return logged_at.strftime("%H:%M")
