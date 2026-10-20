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
from datetime import UTC, datetime
from typing import Final

from argus_core.models import CitedEvidence

from agent_postmortem.figures import AROUND_A_WORD, is_a_figure

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
    typically read, and the minute it was highest. A number inside a name - an
    id, an address, a port - is no quantity, by the rule the figures are told
    apart by (`is_a_figure`): a name whose numbers varied is said by how many
    different ones there were. It still keys the group by everything but its
    numbers, punctuation included (`io-pricing:#`), so one dependency's lines
    stay apart from another's and a shopper per minute is one message, not one
    a minute.
    """
    groups: dict[str, list[tuple[datetime | None, list[str]]]] = {}
    for line in log_lines:
        logged_at, message = _split(line)
        groups.setdefault(_key_of(message), []).append((logged_at, _A_NUMBER.split(message)))

    return [CitedEvidence(label=_label_for(key), text=_said_once(occurrences))
            for key, occurrences in groups.items()]


def labels_reaching_into(log_lines: Sequence[str], since: datetime) -> list[str]:
    """The labels of the groups with a line logged inside a stretch that began
    at `since` and has not ended, in the order they were first logged.

    A line is stamped with its minute, and is taken as the whole of it: one
    from the minute `since` falls in reaches into the stretch. Exact for the
    stretch it is asked about, whose start is the first minute the metrics did
    not cover. No end is asked for because that stretch had none - it was still
    running when Argus stopped. A line with no stamp reaches into nothing,
    since naming it would say it was logged inside.
    """
    first_minute = since.replace(second=0, microsecond=0)
    keys: list[str] = []
    reaching: set[str] = set()
    for line in log_lines:
        logged_at, message = _split(line)
        key = _key_of(message)
        if key not in keys:
            keys.append(key)

        # The stamp's `Z` is optional, and a stamp without it is the same clock.
        if logged_at is not None and (
                _in_utc(logged_at).replace(second=0, microsecond=0) >= first_minute):
            reaching.add(key)

    return [_label_for(key) for key in keys if key in reaching]


def _split(line: str) -> tuple[datetime | None, str]:
    """When a line was logged, and what it said."""
    stamped = _STAMPED.match(line)
    if stamped is None:
        return None, line

    return datetime.fromisoformat(stamped.group(1)), line[stamped.end():]


def _key_of(message: str) -> str:
    """What a group is keyed by: everything in the message but its numbers."""
    return "#".join(_A_NUMBER.split(message)[0::2])


def _in_utc(logged_at: datetime) -> datetime:
    return logged_at if logged_at.tzinfo is not None else logged_at.replace(tzinfo=UTC)


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
    in_word = _the_word_each_number_is_in(first)
    first_words, said_words = "".join(first).split(), message.split()
    varied: list[str] = []
    names_said: set[int] = set()

    for position, kept in enumerate(held):
        word = in_word[position]

        if kept or word in names_said:
            continue

        if is_a_figure(first_words[word].strip(AROUND_A_WORD)):
            varied.append(_how_it_ranged(
                [(logged_at, each[position])
                 for (logged_at, _), each in zip(occurrences, numbers, strict=True)]))
            continue

        names_said.add(word)
        slots = [slot for slot, its_word in enumerate(in_word) if its_word == word]
        varied.append(_how_many_names(said_words[word].strip(AROUND_A_WORD),
                                      [[each[slot] for slot in slots] for each in numbers]))

    return "; ".join([f"{message} - {_how_often(occurrences)}", *varied])


def _the_word_each_number_is_in(parts: list[str]) -> list[int]:
    """For each number in a message split around its numbers, which of the
    message's words - counted from 0, split on whitespace - it sits in."""
    indexes = []
    before = ""

    for index, part in enumerate(parts):
        if index % 2:
            words = before.split()
            indexes.append(len(words) if not before or before[-1].isspace() else len(words) - 1)

        before += part

    return indexes


def _how_many_names(said: str, names: list[list[str]]) -> str:
    """A name whose numbers varied - an id, an address - by how many different
    ones there were: its numbers are no quantity, and a range and a typical
    value of them would be statistics of nothing."""
    return f"{said} took {len({tuple(name) for name in names})} different values"


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
