"""The log lines an incident read, one piece of evidence per message.

A service logs the same message every minute it is broken, so an incident's
log block is mostly one line said many times - five copies of one
ZeroDivisionError, cited one by one, is how a causal step came to read like a
traceback. Grouped by message, each says what happened once: how often, over
how long, and how far whatever varied between the copies ranged. Not every
minute it was logged in - a fault that ran three hours is a hundred and eighty
minutes nobody reads to the end - except after Argus first acted, where the
minutes it was logged in are said as runs of them: whether a change reached the
service is which minutes after it still logged what it changed.

Each group is named by its message rather than by its place. A recorded answer
is replayed in a run that read a different number of lines - one message more
or fewer - and a label counted by position would then name a different line,
where one derived from the message names the same one or none at all.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Final, NamedTuple

from argus_core import said_as_a_day
from argus_core.models import CitedEvidence

from agent_postmortem.figures import (
    AFTER_ARGUS_FIRST_ACTED,
    AROUND_A_WORD,
    BETWEEN_THE_MINUTES_OF_A_SET,
    SPAN_DASH,
    is_a_figure,
)
from agent_postmortem.stamps import stamped, the_minute_inside

# How a group's label begins. The rest is the start of a digest of the message,
# so a message keeps its label in every run that read it.
LOG_GROUP_PREFIX: Final = "G"

# How much of the digest the label carries. Four hex characters is one name in
# sixty-five thousand, for an incident reading a few dozen distinct messages.
_DIGEST_LENGTH: Final = 4

# Between the first minute of a span and its last where a day or more lies
# between them. Spaced, so each end is a word of its own and the second is
# read with the day said beside it.
_TO_ANOTHER_DAY: Final = f" {SPAN_DASH} "

# The shortest span said as two figures: anything shorter is one, wherever
# midnight falls in it.
_A_DAY: Final = timedelta(days=1)

# A number inside a message - the part that varies from minute to minute.
_A_NUMBER: Final = re.compile(r"(\d+(?:\.\d+)?)")

# What a part of a group is said under, by the cut either side of it: where
# the metrics stopped. Neither says a figure, so a part's figures keep their
# places whether or not a run is split.
_BEFORE_THE_STOP: Final = "before the metrics stopped"
_AFTER_THE_STOP: Final = "After they stopped"
# And where they resumed, the cut either side of that - saying no figure
# either.
_BEFORE_THEY_RESUMED: Final = "before they resumed"
_AFTER_THEY_RESUMED: Final = "After they resumed"

# A minute.
_A_MINUTE: Final = timedelta(minutes=1)

# Between two sets of the minutes after the act, a day or more apart: each is
# a figure of its own, with its day said before it.
_BETWEEN_SETS: Final = " and "


class LogGroup(NamedTuple):
    """One group as the evidence lists it, and where in its text the message
    it quotes sits - the one part of the row that is in its writer's words."""
    cited: CitedEvidence
    quoted: tuple[int, int]


def grouped(log_lines: Sequence[str],
            metrics_stopped_at: datetime | None,
            day: date,
            *,
            acted_at: datetime | None = None,
            metrics_resumed_at: datetime | None = None) -> list[CitedEvidence]:
    """Every distinct message, in the order it was first logged, each under a
    label of its own and said once - as `the_groups_of` says them."""
    return [group.cited
            for group in the_groups_of(log_lines, metrics_stopped_at, day, acted_at=acted_at,
                                       metrics_resumed_at=metrics_resumed_at)]


def the_groups_of(log_lines: Sequence[str],
                  metrics_stopped_at: datetime | None,
                  day: date,
                  *,
                  acted_at: datetime | None = None,
                  metrics_resumed_at: datetime | None = None) -> list[LogGroup]:
    """Every distinct message, in the order it was first logged, each under a
    label of its own and said once, with where in the row the message sits.

    Each is said with the numbers that held every time written in and a `#`
    where they varied, then how many times it was logged over how many minutes,
    first to last - and, for each number that varied, how far it ranged, what it
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
    Before comes first, so the figures it names keep their places. Where the
    metrics resumed (`metrics_resumed_at`), a message logged after that is said
    in a part of its own, last: summed with the stretch, what the shop logged
    once it was measured again read as what it logged while it was not.

    Where Argus acted (`acted_at`, the first change it made), a message logged
    after it says, last, the minutes it was logged in after it - as one figure,
    a set, for each stretch of them whose minutes are each less than a day
    after the one before (`_a_set_of`). Summed across a switch-off, a flag's
    "on" lines read as on every minute from before it to after it, and a
    write-up said the switch-off may never have reached the service, which
    read it off in most of the minutes after. Not as a cut: when Argus acts
    moves with how fast the walk ran, and a replay that put one minute on the
    other side of a cut turned a moment the recorded answer cited into a
    range. A line is after the act where the instant its stamp names is later
    - a minute alone names its start, so the minute Argus acted in, whose line
    may be from either side, never is. None where nothing was logged after,
    since an empty set is no figure, nor where a line has no stamp, which
    could fill any minute missed.

    Every minute is said with its day where that is not the `day` the incident
    began: said bare in an incident whose logs run on another day, the model
    and the reader both took it for a minute of the onset's day. Two
    exceptions: the end of a span shorter than a day, which is on the day its
    start is or, read earlier on the clock, the day after (`_how_often`); and
    each minute of a set after its first, which is on the day of the one
    before it or, read earlier on the clock, the day after.
    """
    groups: dict[str, list[tuple[datetime | None, list[str]]]] = {}
    for line in log_lines:
        logged_at, message = stamped(line)
        groups.setdefault(_key_of(message), []).append((_in_utc(logged_at),
                                                         _A_NUMBER.split(message)))

    return [_a_group(_label_for(key), *_said(occurrences, metrics_stopped_at, metrics_resumed_at,
                                             _in_utc(acted_at), day))
            for key, occurrences in groups.items()]


def _in_utc(logged_at: datetime | None) -> datetime | None:
    """A stamp in UTC, one written with no zone read as UTC's - as
    `the_minute_inside` reads it. Read as the host's, its minute was said on
    whichever day the host's clock put it."""
    if logged_at is None:
        return None

    return (logged_at if logged_at.tzinfo else logged_at.replace(tzinfo=UTC)).astimezone(UTC)


def _a_group(label: str, text: str, quoted: tuple[int, int]) -> LogGroup:
    return LogGroup(cited=CitedEvidence(label=label, text=text), quoted=quoted)


def labels_reaching_into(log_lines: Sequence[str],
                         since: datetime,
                         until: datetime | None = None) -> list[str]:
    """The labels of the groups with a line logged inside a stretch that began
    at `since` and ended at `until` - or has not ended - in the order they were
    first logged.

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

        if the_minute_inside(logged_at, since, until) is not None:
            reaching.add(key)

    return [_label_for(key) for key in keys if key in reaching]


def _key_of(message: str) -> str:
    """What a group is keyed by: everything in the message but its numbers."""
    return "#".join(_A_NUMBER.split(message)[0::2])


def _label_for(key: str) -> str:
    return LOG_GROUP_PREFIX + hashlib.sha1(key.encode()).hexdigest()[:_DIGEST_LENGTH]


class _Part(NamedTuple):
    """Some of a group's lines, and the cuts either side of them as their
    label says them: the one they follow, and the one they come before -
    `None` for an end of the group."""
    lines: list[tuple[datetime | None, list[str]]]
    follows: str | None = None
    precedes: str | None = None

    @property
    def label(self) -> str:
        return ", ".join(cut for cut in (self.follows, self.precedes) if cut is not None)


def _said(occurrences: list[tuple[datetime | None, list[str]]],
          metrics_stopped_at: datetime | None,
          metrics_resumed_at: datetime | None,
          acted_at: datetime | None,
          day: date) -> tuple[str, tuple[int, int]]:
    """One group as one line - in parts where it was logged on more than one
    side of where the metrics stopped and where they resumed, and whole
    otherwise, then the minutes it was logged in after Argus acted - and where
    in it the message sits.

    A part only where there are two sides to compare, and only where every
    line has a side: a line with no stamp belongs to neither, and a part that
    dropped it would miscount.

    A message logged once is said as any other is, with how often and when.
    Led by its minute instead, it read as saying what held from then on: a
    write-up handed one minute's split of a flag's evaluations gave it as how
    far the flag reached, though every evaluation after that minute was on.
    """
    message, held = _the_message_of(occurrences)
    parts = [_Part(occurrences)]
    dated = all(logged_at is not None for logged_at, _ in occurrences)

    if dated and metrics_stopped_at is not None:
        before, inside, after = _parted(occurrences, metrics_stopped_at, metrics_resumed_at)
        cut = [part for part in (_Part(before, precedes=_BEFORE_THE_STOP),
                                 _Part(inside, follows=_AFTER_THE_STOP,
                                       precedes=_BEFORE_THEY_RESUMED if after else None),
                                 _Part(after, follows=_AFTER_THEY_RESUMED))
               if part.lines]
        if len(cut) > 1:
            parts = cut

    said = [_a_part(part.lines, message, held, day) for part in parts]
    whole = (said[0] if len(parts) == 1 else
             ". ".join(f"{part.label}: {its}" for part, its in zip(parts, said, strict=True)))
    after_the_act = (_the_minutes_after(occurrences, acted_at)
                     if dated and acted_at is not None else [])
    and_after = (f". {AFTER_ARGUS_FIRST_ACTED} {_a_set_of(after_the_act, day)}"
                 if after_the_act else "")

    return f"{message} - {whole}{and_after}", (0, len(message))


def _parted(occurrences: list[tuple[datetime | None, list[str]]],
            since: datetime,
            until: datetime | None) -> tuple[list[tuple[datetime | None, list[str]]],
                                             list[tuple[datetime | None, list[str]]],
                                             list[tuple[datetime | None, list[str]]]]:
    """The lines logged before the minute `since` falls in, those logged from
    it up to `until`, and those logged at `until` or after - by
    `the_minute_inside`, as how far a group reaches is. Nothing after where the
    stretch never ended."""
    before: list[tuple[datetime | None, list[str]]] = []
    inside: list[tuple[datetime | None, list[str]]] = []
    after: list[tuple[datetime | None, list[str]]] = []
    for each in occurrences:
        logged_at = _in_utc(each[0])
        if until is not None and logged_at is not None and logged_at >= until:
            after.append(each)
        elif the_minute_inside(logged_at, since, until) is not None:
            inside.append(each)
        else:
            before.append(each)

    return before, inside, after


def _the_minutes_after(occurrences: list[tuple[datetime | None, list[str]]],
                       acted_at: datetime) -> list[datetime]:
    """The distinct minutes, in order, of the lines whose stamps name an
    instant later than `acted_at`."""
    return sorted({logged_at.replace(second=0, microsecond=0)
                   for logged_at, _ in occurrences
                   if logged_at is not None and logged_at > acted_at})


def _a_set_of(minutes: list[datetime], day: date) -> str:
    """Distinct minutes as sets, one where each is less than a day after the
    one before it, and a set of its own from any that is a day or more after -
    read off the clock, a minute a day later is the same minute, so a set is
    one figure only as a span shorter than a day is."""
    sets: list[list[datetime]] = []
    for minute in minutes:
        if sets and minute - sets[-1][-1] < _A_DAY:
            sets[-1].append(minute)
        else:
            sets.append([minute])

    return _BETWEEN_SETS.join(_one_set_of(each, day) for each in sets)


def _one_set_of(minutes: list[datetime], day: date) -> str:
    """Distinct minutes, each less than a day after the one before it, as one
    word, a set: runs of consecutive ones, each a minute or a span, joined
    without a space - `23:40,23:42–23:43,23:45`. Its first day said before it
    where that is not the `day` the incident began, and a minute earlier on the
    clock than the one before it on the next day, as a span's end is: said with
    its day inside, the set would be more than one figure, and how many would
    follow midnight."""
    runs: list[list[datetime]] = []
    for minute in minutes:
        if runs and minute - runs[-1][-1] == _A_MINUTE:
            runs[-1].append(minute)
        else:
            runs.append([minute])

    said = BETWEEN_THE_MINUTES_OF_A_SET.join(
        f"{run[0]:%H:%M}" if len(run) == 1 else f"{run[0]:%H:%M}{SPAN_DASH}{run[-1]:%H:%M}"
        for run in runs)

    return said if minutes[0].date() == day else f"{said_as_a_day(minutes[0])} {said}"


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
                 for (logged_at, _), each in zip(occurrences, numbers, strict=True)],
                _its_unit(first, position), day))
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

    A span shorter than a day is one figure wherever midnight falls in it: it
    says its first day once, before it, and only where that is not the `day`
    the incident began, and an end earlier on the clock than its start is on
    the next day. Two figures across midnight, a replay run across it named
    every figure after the span one place on from the daytime run its answer
    was recorded in. A day or more says each end as `_clock` does, the dash
    spaced - joined, the first end and the dash read as one word and the
    second end's day as part of it - and is two figures in every run.
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

    return f"{counted} in {minutes} minutes, {_a_stretch(first, last, day)}"


def _a_stretch(first: datetime, last: datetime, day: date) -> str:
    """The minutes from `first` to `last`, as a span: one figure where it is
    shorter than a day, two where it is not (`_how_often`)."""
    if last - first >= _A_DAY:
        return f"{_clock(first, day)}{_TO_ANOTHER_DAY}{_clock(last, day)}"

    return f"{_clock(first, day)}{SPAN_DASH}{last:%H:%M}"


def _its_unit(parts: list[str], position: int) -> str:
    """What a message split around its numbers writes right after one of them,
    to the end of its word: the `%` of `36.50%`, the `ms` of `2300ms`.

    A number another follows inside its word - the first of `1.5-2.0` - has
    none of its own, and the punctuation closing the word is no part of one.
    """
    after = parts[2 * position + 2]
    attached = after.split()[0] if after and not after[0].isspace() else ""

    if attached == after and 2 * position + 3 < len(parts):
        return ""

    return attached.rstrip(AROUND_A_WORD)


def _how_it_ranged(readings: list[tuple[datetime | None, str]], unit: str, day: date) -> str:
    """One varying number: lowest to highest, the middle value read, and the
    minute of the highest.

    Typical is a value some minute actually read - the lower middle, never an
    average no minute logged. Each value is said as it was logged, with the
    `unit` its message writes after it: handed `0.50 to 36.50` of a rate logged
    as `36.50%`, a write-up said the rate was as high as 36.50.

    A number that read one value - which a part of a group split where the
    metrics stopped can - is said as that value: "0.50 to 0.50, typically
    0.50" is a range of one number.
    """
    if len({value for _, value in readings}) == 1:
        return f"# was {readings[0][1]}{unit}"

    ordered = sorted(readings, key=lambda reading: float(reading[1]))
    typical = ordered[(len(ordered) - 1) // 2][1]
    highest_at, _ = max(readings, key=lambda reading: float(reading[1]))
    when = f", highest at {_clock(highest_at, day)}" if highest_at is not None else ""

    return (f"# was {ordered[0][1]}{unit} to {ordered[-1][1]}{unit}, "
            f"typically {typical}{unit}{when}")


def _clock(logged_at: datetime, day: date) -> str:
    """A minute, with its day before it where that is not the `day` the
    incident began."""
    minute = logged_at.strftime("%H:%M")

    return minute if logged_at.date() == day else f"{said_as_a_day(logged_at)} {minute}"
