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
from datetime import date, datetime
from typing import Final, NamedTuple

from argus_core import said_as_a_day
from argus_core.models import CitedEvidence

from agent_postmortem.figures import AROUND_A_WORD, is_a_figure
from agent_postmortem.stamps import stamped, the_minute_inside

# How a group's label begins. The rest is the start of a digest of the message,
# so a message keeps its label in every run that read it.
LOG_GROUP_PREFIX: Final = "G"

# How much of the digest the label carries. Four hex characters is one name in
# sixty-five thousand, for an incident reading a few dozen distinct messages.
_DIGEST_LENGTH: Final = 4

# Between the first minute of a span and its last.
_TO: Final = "–"
# Between them where they fall on different days. Spaced, so each end is a
# word of its own and the second is read with the day said beside it.
_TO_ANOTHER_DAY: Final = " – "


class LogGroup(NamedTuple):
    """One group as the evidence lists it, and where in its text the message
    it quotes sits - the one part of the row that is in its writer's words."""
    cited: CitedEvidence
    quoted: tuple[int, int]

# A number inside a message - the part that varies from minute to minute.
_A_NUMBER: Final = re.compile(r"(\d+(?:\.\d+)?)")


def grouped(log_lines: Sequence[str],
            metrics_stopped_at: datetime | None,
            day: date) -> list[CitedEvidence]:
    """Every distinct message, in the order it was first logged, each under a
    label of its own and said once - as `the_groups_of` says them."""
    return [group.cited for group in the_groups_of(log_lines, metrics_stopped_at, day)]


def the_groups_of(log_lines: Sequence[str],
                  metrics_stopped_at: datetime | None,
                  day: date) -> list[LogGroup]:
    """Every distinct message, in the order it was first logged, each under a
    label of its own and said once, with where in the row the message sits.

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

    Where the metrics stopped, a message logged on both sides of the stop is
    said in two parts, before and after, each with its own count, span and
    ranges. Summed across the stop, what the shop logged inside a stretch the
    metrics did not cover was lost in what it logged before, and a model told
    only the whole half hour wrote that nothing said how the shop was doing.
    Before comes first, so the figures it names keep their places.

    Every minute is said with its day where that is not the `day` the incident
    began: said bare in an incident whose logs run on another day, the model
    and the reader both took it for a minute of the onset's day.
    """
    groups: dict[str, list[tuple[datetime | None, list[str]]]] = {}
    for line in log_lines:
        logged_at, message = stamped(line)
        groups.setdefault(_key_of(message), []).append((logged_at, _A_NUMBER.split(message)))

    return [_a_group(_label_for(key), *_said(occurrences, metrics_stopped_at, day))
            for key, occurrences in groups.items()]


def _a_group(label: str, text: str, quoted: tuple[int, int]) -> LogGroup:
    return LogGroup(cited=CitedEvidence(label=label, text=text), quoted=quoted)


def labels_reaching_into(log_lines: Sequence[str], since: datetime) -> list[str]:
    """The labels of the groups with a line logged inside a stretch that began
    at `since` and has not ended, in the order they were first logged.

    Inside by `the_minute_inside`, the rule how far they reach is told by, so a
    group named here always has a last minute to say.
    """
    keys: list[str] = []
    reaching: set[str] = set()
    for line in log_lines:
        logged_at, message = stamped(line)
        key = _key_of(message)
        if key not in keys:
            keys.append(key)

        if the_minute_inside(logged_at, since) is not None:
            reaching.add(key)

    return [_label_for(key) for key in keys if key in reaching]


def _key_of(message: str) -> str:
    """What a group is keyed by: everything in the message but its numbers."""
    return "#".join(_A_NUMBER.split(message)[0::2])


def _label_for(key: str) -> str:
    return LOG_GROUP_PREFIX + hashlib.sha1(key.encode()).hexdigest()[:_DIGEST_LENGTH]


def _said(occurrences: list[tuple[datetime | None, list[str]]],
          metrics_stopped_at: datetime | None,
          day: date) -> tuple[str, tuple[int, int]]:
    """One group as one line - in two parts where it was logged on both sides
    of where the metrics stopped, and whole otherwise - and where in it the
    message sits.

    Two parts only where there are two sides to compare, and only where every
    line has a side: a line with no stamp belongs to neither, and a part that
    dropped it would miscount.
    """
    if metrics_stopped_at is not None:
        before: list[tuple[datetime | None, list[str]]] = []
        after: list[tuple[datetime | None, list[str]]] = []
        for each in occurrences:
            if the_minute_inside(each[0], metrics_stopped_at) is not None:
                after.append(each)
            elif each[0] is not None:
                before.append(each)

        if before and after and len(before) + len(after) == len(occurrences):
            message, held = _the_message_of(occurrences)
            return (f"{message} - before the metrics stopped: "
                    f"{_a_part(before, message, held, day)}. "
                    f"After they stopped: {_a_part(after, message, held, day)}",
                    (0, len(message)))

    return _said_once(occurrences, day)


def _said_once(occurrences: list[tuple[datetime | None, list[str]]],
               day: date) -> tuple[str, tuple[int, int]]:
    """One group as one line, and where in it the message sits."""
    if len(occurrences) == 1:
        logged_at, parts = occurrences[0]
        message = "".join(parts)
        if logged_at is None:
            return message, (0, len(message))

        clock = _clock(logged_at, day)
        return f"{clock} {message}", (len(clock) + 1, len(clock) + 1 + len(message))

    message, held = _the_message_of(occurrences)

    return f"{message} - {_a_part(occurrences, message, held, day)}", (0, len(message))


def _the_message_of(occurrences: list[tuple[datetime | None, list[str]]]) -> tuple[str, list[bool]]:
    """The message with the numbers that held every time written in and a `#`
    where they varied, and which of its numbers held."""
    first = occurrences[0][1]
    numbers = [parts[1::2] for _, parts in occurrences]
    held = [all(each[position] == numbers[0][position] for each in numbers)
            for position in range(len(numbers[0]))]

    message = "".join(
        part if index % 2 == 0 else (part if held[index // 2] else "#")
        for index, part in enumerate(first)
    )

    return message, held


def _a_part(occurrences: list[tuple[datetime | None, list[str]]],
            message: str,
            held: list[bool],
            day: date) -> str:
    """How often these lines were logged, and how far each number that varied
    across the whole group ranged among them."""
    first = occurrences[0][1]
    numbers = [parts[1::2] for _, parts in occurrences]
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
                 for (logged_at, _), each in zip(occurrences, numbers, strict=True)], day))
            continue

        names_said.add(word)
        slots = [slot for slot, its_word in enumerate(in_word) if its_word == word]
        names = [[each[slot] for slot in slots] for each in numbers]
        said = said_words[word].strip(AROUND_A_WORD)

        # One name throughout - a part of a group split where the metrics
        # stopped can hold one where the group did not - is said as that name:
        # "took 1 different values" counts it instead of saying it.
        if len({tuple(name) for name in names}) == 1:
            varied.append(f"{said} was {first_words[word].strip(AROUND_A_WORD)}")
            continue

        varied.append(_how_many_names(said, names))

    return "; ".join([_how_often(occurrences, day), *varied])


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


def _how_often(occurrences: list[tuple[datetime | None, list[str]]], day: date) -> str:
    """How many times, and over which minutes, counting the first and the last.

    Every line counted: two replicas logging one failure in the same minute are
    two failures. A line with no stamp is counted and dates nothing, since a
    span made up for it would be a guess.

    A span on one day says that day once, before it, and only where it is not
    the `day` the incident began. One running into another day says each end
    as `_clock` does, the dash spaced: joined, the first end and the dash read
    as one word and the second end's day as part of it.
    """
    counted = f"{len(occurrences)} {'occurrence' if len(occurrences) == 1 else 'occurrences'}"
    stamped = sorted(logged_at.replace(second=0, microsecond=0)
                     for logged_at, _ in occurrences if logged_at is not None)

    if not stamped:
        return counted

    first, last = stamped[0], stamped[-1]
    minutes = int((last - first).total_seconds() // 60) + 1

    if minutes == 1:
        return f"{counted} in 1 minute, {_clock(first, day)}"

    if first.date() != last.date():
        return (f"{counted} in {minutes} minutes, "
                f"{_clock(first, day)}{_TO_ANOTHER_DAY}{_clock(last, day)}")

    return f"{counted} in {minutes} minutes, {_clock(first, day)}{_TO}{last:%H:%M}"


def _how_it_ranged(readings: list[tuple[datetime | None, str]], day: date) -> str:
    """One varying number: lowest to highest, the middle value read, and the
    minute of the highest.

    Typical is a value some minute actually read - the lower middle, never an
    average no minute logged. Each value is said as it was logged.

    A number that read one value - which a part of a group split where the
    metrics stopped can - is said as that value: "0.50 to 0.50, typically
    0.50" is a range of one number.
    """
    if len({value for _, value in readings}) == 1:
        return f"# was {readings[0][1]}"

    ordered = sorted(readings, key=lambda reading: float(reading[1]))
    typical = ordered[(len(ordered) - 1) // 2][1]
    highest_at, _ = max(readings, key=lambda reading: float(reading[1]))
    when = f", highest at {_clock(highest_at, day)}" if highest_at is not None else ""

    return f"# was {ordered[0][1]} to {ordered[-1][1]}, typically {typical}{when}"


def _clock(logged_at: datetime, day: date) -> str:
    """A minute, with its day before it where that is not the `day` the
    incident began."""
    minute = logged_at.strftime("%H:%M")

    return minute if logged_at.date() == day else f"{said_as_a_day(logged_at)} {minute}"
