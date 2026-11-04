"""The figures a write-up may state, each by its name, and the write-up with
every one written in.

The model writes no figure. Every figure a postmortem states is one Argus
measured, one the alert reported, or one a piece of evidence states, and a
model left to restate one rounds it, works it out again, or - refused its
digits - spells it out in words nobody can read: "one thousand two hundred
ninety-seven and thirty-one hundredths". So each figure the model is shown
carries its name after it, the model writes the name where the figure goes,
and code writes the figure in, in digits, exactly as the incident gave it.

A figure the incident never gave as one - how long until it was back to normal,
how many times worse it got - is a working of two it did,
`{back_to_normal - began}`, which
code works out from the two figures as the model was shown them: by their kinds,
so an instant less an instant is a span and two shares subtract to points, and
from what was shown rather than what was measured, so the result never
disagrees with the figures beside it by a rounding.

The figure written in is the run's own. A recorded answer names `{duration}`,
and the run replaying it writes in the duration it measured, so a page never
quotes a figure from the incident a recording was made against.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from argus_core import (
    A_DAY_SAID,
    level_given_in,
    level_said_in,
    parse_iso,
    said_as_a_day,
    said_as_a_level,
    said_as_a_share,
    said_as_a_span,
    said_as_a_time,
    the_day_said,
    to_iso,
)
from argus_core.events import HUNK_HEADER, PATCH_LINE_INDENT
from argus_core.models import (
    CitedEvidence,
    DetectionLesson,
    DetectionPart,
    FirstTold,
    said_as_money,
    the_detection_lesson_said,
)
from pydantic import BaseModel

from agent_postmortem.detection_lesson import no_start_from_the_line, the_detection_lesson
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.measuring import Measurements
from agent_postmortem.sources import NotPaged
from agent_postmortem.stamps import the_last_minute_logged_inside

if TYPE_CHECKING:
    from agent_postmortem.prompting import SubmittedPostmortem

# What each figure Argus measured is named, as the model writes it between
# braces. Named for what it is rather than numbered: a recorded answer naming
# one has to name the same figure in every run it is replayed in, and a number
# counted down a list moves the moment one run measures something another did
# not.
ALERT_RAISED_FIGURE: Final = "alert_raised"
BEGAN_FIGURE: Final = "began"
BACK_TO_NORMAL_FIGURE: Final = "back_to_normal"
METRICS_STOPPED_AT_FIGURE: Final = "metrics_stopped_at"
LOGS_REACH_UNTIL_FIGURE: Final = "logs_reach_until"
LOG_READING_ENDED_FIGURE: Final = "log_reading_ended"
CUSTOMER_LOSS_FIGURE: Final = "customer_loss"
DURATION_FIGURE: Final = "duration"
HELD_FIGURE: Final = "held"
RULE_WAITS_FIGURE: Final = "rule_waits"
RULE_LOOKS_BACK_FIGURE: Final = "rule_looks_back"
AFTER_THE_WAIT_FIGURE: Final = "after_the_wait"
ALERTED_AFTER_THE_ONSET_FIGURE: Final = "alerted_after_the_onset"
# The spans the lesson on detection says, where the page weighs detection -
# by the parts it names (`DETECTION_PART_FIGURES`).
DETECTION_GAP_FIGURE: Final = "detection_gap"
RULE_EVALUATED_EVERY_FIGURE: Final = "rule_evaluated_every"
SCRAPING_ALLOWANCE_FIGURE: Final = "scraping_allowance"
ACCOUNTED_FOR_FIGURE: Final = "accounted_for"
BEYOND_ACCOUNTED_FOR_FIGURE: Final = "beyond_accounted_for"
DETECTION_PART_FIGURES: Final = {
    DetectionPart.GAP: DETECTION_GAP_FIGURE,
    DetectionPart.RULE_WAITS: RULE_WAITS_FIGURE,
    DetectionPart.RULE_LOOKS_BACK: RULE_LOOKS_BACK_FIGURE,
    DetectionPart.RULE_EVALUATED_EVERY: RULE_EVALUATED_EVERY_FIGURE,
    DetectionPart.SCRAPING_AND_STORING: SCRAPING_ALLOWANCE_FIGURE,
    DetectionPart.ACCOUNTED_FOR: ACCOUNTED_FOR_FIGURE,
    DetectionPart.BEYOND: BEYOND_ACCOUNTED_FOR_FIGURE
}
ARGUS_STOPPED_FIGURE: Final = "argus_stopped"
ACTED_FIGURE: Final = "acted"
FIRST_TOLD_FIGURE: Final = "first_told"
ERRORS_BEFORE_FIGURE: Final = "errors_before"
ERRORS_WHILE_BROKEN_FIGURE: Final = "errors_while_broken"
ERRORS_AT_WORST_FIGURE: Final = "errors_at_worst"
ERRORS_RISE_FIGURE: Final = "errors_rise"
SERIES_BEFORE_FIGURE: Final = "series_before"
SERIES_WHILE_BROKEN_FIGURE: Final = "series_while_broken"
SERIES_AT_WORST_FIGURE: Final = "series_at_worst"

# What a measured onset can tell an instant to: it is the first whole minute
# that departed, so anything shorter is inside it.
A_MINUTE: Final = timedelta(minutes=1)

# The alert's own figures, which are the sender's words and have no meaning
# Argus knows: numbered in the order the alert states them, which is the one
# thing about them that holds still from run to run.
_ALERT_FIGURE_PREFIX: Final = "A"

# A figure written in digits: a number, with whatever marks a number wears - a
# sign, a currency, a percentage, a unit, the rest of a date or an instant. Any
# other word with a digit in it is a name: a label (`T2`, `AI-3`), a revision,
# a pod. Refusing those refused the evidence's own words, and a revision refused
# as a figure was swapped for a label nobody outside the prompt can read.
#
# A time wears the marks a log or a clock writes it with: a trailing `Z` for
# UTC, a clock's `23h16`, a span's `5m`.
_A_FIGURE: Final = re.compile(
    r"[~≈]?[-+−]?[$€£¥₪]?"
    r"\d[\d,.:/-]*"
    r"(?:T[\d:.]+Z?)?"
    r"(?:-?(?:%|[kKMB]|bn|ms|s|secs?|m|mins?|minutes?|h\d{2}|h|hrs?|hours?"
    r"|d|days?|weeks?|x|[KMGT]i?B|am|pm|Z))?"
)

# What joins two figures into one word: a range (`21:35–21:39`, the form log
# groups are printed in) or an interval (`…Z/…Z`, as an instant pair is written).
_BETWEEN_FIGURES: Final = re.compile(r"[–—/]")

# What a word is trimmed of before it is judged: the punctuation prose wraps a
# word in, which is not part of the number it is.
AROUND_A_WORD: Final = "()[],;:.!?\"'"

# A figure's name: a word, and where the figure is one a piece of evidence
# states, its place in that evidence (`Gbac1.2`).
_A_NAME: Final = r"[A-Za-z][A-Za-z0-9_]*(?:\.\d+)?"

# A figure's name as the prose writes it.
A_FIGURE_NAME: Final = re.compile(rf"\{{({_A_NAME})\}}")

# One operation on two figures as the prose writes it, `{back_to_normal - began}`:
# the model names what it wants worked out, and code works it out.
_A_WORKING: Final = re.compile(rf"\{{\s*({_A_NAME})\s*([-+/])\s*({_A_NAME})\s*\}}")

# Either, in the order a sentence writes them: a name alone in group 1, or a
# working's two names in groups 2 and 4.
_A_NAMING: Final = re.compile(f"{A_FIGURE_NAME.pattern}|{_A_WORKING.pattern}")


class _Measure(StrEnum):
    """What a unit measures, which decides which other units it can be
    mistaken for."""

    TIME = "time"
    SHARE = "share"
    POINTS = "points"
    RATIO = "ratio"


# Each unit a figure is written in with, by every spelling a sentence says it
# in, and what it measures. A figure written in carries its unit, and a model
# reading "215.13 ms {series_before}" writes "{series_before} ms" as often as
# the name alone - the unit sits outside the name where it is shown. Said again
# in another spelling it is still the same unit; said as another unit of the
# same measure it is a misreading of the figure's scale, which only the model
# can put right.
_UNITS: Final = {
    spelling: (unit, measure)
    for unit, measure, spellings in (
        ("millisecond", _Measure.TIME,
         ("ms", "msec", "msecs", "millisecond", "milliseconds")),
        ("second", _Measure.TIME, ("s", "sec", "secs", "second", "seconds")),
        ("minute", _Measure.TIME, ("min", "mins", "minute", "minutes")),
        ("hour", _Measure.TIME, ("h", "hr", "hrs", "hour", "hours")),
        ("day", _Measure.TIME, ("day", "days")),
        ("week", _Measure.TIME, ("week", "weeks")),
        ("percent", _Measure.SHARE, ("%", "percent", "per cent")),
        ("percentage point", _Measure.POINTS,
         ("percentage point", "percentage points", "point", "points")),
        ("times", _Measure.RATIO, ("times",)))
    for spelling in spellings
}

# The longest spelling first, so "percentage points" is not read as "points".
_SPELLINGS_LONGEST_FIRST: Final = sorted(_UNITS, key=len, reverse=True)

# What a sentence says straight after a figure's name or a working, which may
# be its unit again: a percent sign, with or without a space, a unit `_UNITS`
# spells, or any other word - a unit as Grafana names it ("bytes", "reqps") is
# the figure's own where the figure ends in it, and the writer's where not.
_A_UNIT_AFTER: Final = (
    r"(?P<after>\s*%|\s+(?:"
    + "|".join(re.escape(spelling).replace(r"\ ", r"\s+")
               for spelling in _SPELLINGS_LONGEST_FIRST if spelling != "%")
    + r")\b|\s+[^\W\d_]+\b)?"
)
_A_NAME_AND_A_UNIT: Final = re.compile(A_FIGURE_NAME.pattern + _A_UNIT_AFTER, re.IGNORECASE)
_A_WORKING_AND_A_UNIT: Final = re.compile(_A_WORKING.pattern + _A_UNIT_AFTER, re.IGNORECASE)


class _Kind(StrEnum):
    """What a figure is a measure of, which decides what it can be worked with.

    Said as the fault about a working says it.
    """

    INSTANT = "an instant"
    SPAN = "a span"
    SHARE = "a share"
    LEVEL = "a level"


# Each figure Argus measured's kind, by its name. A figure the alert or the
# evidence states has none, unless it is an instant (`_kind_of`): what any other
# of its numbers measures is its writer's to know, so none is worked with.
_KINDS: Final = {
    ALERT_RAISED_FIGURE: _Kind.INSTANT,
    BEGAN_FIGURE: _Kind.INSTANT,
    BACK_TO_NORMAL_FIGURE: _Kind.INSTANT,
    METRICS_STOPPED_AT_FIGURE: _Kind.INSTANT,
    LOGS_REACH_UNTIL_FIGURE: _Kind.INSTANT,
    LOG_READING_ENDED_FIGURE: _Kind.INSTANT,
    ARGUS_STOPPED_FIGURE: _Kind.INSTANT,
    ACTED_FIGURE: _Kind.INSTANT,
    FIRST_TOLD_FIGURE: _Kind.INSTANT,
    DURATION_FIGURE: _Kind.SPAN,
    HELD_FIGURE: _Kind.SPAN,
    RULE_WAITS_FIGURE: _Kind.SPAN,
    RULE_LOOKS_BACK_FIGURE: _Kind.SPAN,
    AFTER_THE_WAIT_FIGURE: _Kind.SPAN,
    ALERTED_AFTER_THE_ONSET_FIGURE: _Kind.SPAN,
    DETECTION_GAP_FIGURE: _Kind.SPAN,
    RULE_EVALUATED_EVERY_FIGURE: _Kind.SPAN,
    SCRAPING_ALLOWANCE_FIGURE: _Kind.SPAN,
    ACCOUNTED_FOR_FIGURE: _Kind.SPAN,
    BEYOND_ACCOUNTED_FOR_FIGURE: _Kind.SPAN,
    ERRORS_BEFORE_FIGURE: _Kind.SHARE,
    ERRORS_WHILE_BROKEN_FIGURE: _Kind.SHARE,
    ERRORS_AT_WORST_FIGURE: _Kind.SHARE,
    ERRORS_RISE_FIGURE: _Kind.SHARE,
    SERIES_BEFORE_FIGURE: _Kind.LEVEL,
    SERIES_WHILE_BROKEN_FIGURE: _Kind.LEVEL,
    SERIES_AT_WORST_FIGURE: _Kind.LEVEL
}

# What a ratio is written to: as far as a reader compares two levels by.
_A_TENTH: Final = Decimal("0.1")

# Each operation a working may ask for, as a sentence says it.
_OPERATIONS: Final = {"-": "minus", "+": "plus", "/": "divided by"}

# How each operation on two kinds is worked out, from the two figures as the
# model was shown them, into what the page writes. One missing works out to
# nothing, and is sent back to the model.
#
# A difference of two shares is in points rather than a share: "rose by 32.7%"
# reads as a share of where it started. A difference of two levels is a level,
# in whatever unit the paging rule watches.
_WORKINGS: Final[dict[tuple[_Kind, str, _Kind],
                      Callable[[Figure, Figure, date | None], str]]] = {
    (_Kind.INSTANT, "-", _Kind.INSTANT):
        lambda first, second, _: said_as_a_span(parse_iso(first.given)
                                                - parse_iso(second.given)),
    (_Kind.INSTANT, "+", _Kind.SPAN):
        lambda first, second, day: _as_a_reader_says(parse_iso(first.given)
                                                     + _span_shown(second), day),
    (_Kind.INSTANT, "-", _Kind.SPAN):
        lambda first, second, day: _as_a_reader_says(parse_iso(first.given)
                                                     - _span_shown(second), day),
    (_Kind.SPAN, "+", _Kind.SPAN):
        lambda first, second, _: said_as_a_span(_span_shown(first) + _span_shown(second)),
    (_Kind.SPAN, "-", _Kind.SPAN):
        lambda first, second, _: said_as_a_span(_span_shown(first) - _span_shown(second)),
    (_Kind.SPAN, "/", _Kind.SPAN):
        lambda first, second, _: _how_many_times(_seconds_shown(first) / _seconds_shown(second)),
    (_Kind.SHARE, "-", _Kind.SHARE):
        lambda first, second, _: (f"{_percent_shown(first) - _percent_shown(second)} "
                                  f"percentage points"),
    (_Kind.SHARE, "/", _Kind.SHARE):
        lambda first, second, _: _how_many_times(_percent_shown(first) / _percent_shown(second)),
    (_Kind.LEVEL, "-", _Kind.LEVEL):
        lambda first, second, _: _a_difference_of_levels(first, second),
    (_Kind.LEVEL, "/", _Kind.LEVEL):
        lambda first, second, _: _how_many_times(_level_shown(first) / _level_shown(second))
}

# A level as the model was shown it: the number, and whatever unit follows it -
# a space and the unit's name, or a percent sign straight after. The number
# may be one that is none, as Prometheus writes it (`+Inf`, `NaN`).
_A_LEVEL_SHOWN: Final = re.compile(r"^(?P<number>[-+]?(?:[\d.]+|Inf|NaN))(?P<unit>.*)$")
_PERCENT_SHOWN: Final = "%"

# A span as `said_as_a_span` says one, a count and its unit at a time.
_A_COUNT_OF_A_UNIT: Final = re.compile(r"(\d+) (day|hour|minute|second)s?")

# An instant as a wire format writes one, which the alert's sender may.
_AN_INSTANT: Final = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?")

# A time of day as the kernel says one, to the minute or to the second.
_A_TIME_OF_DAY: Final = re.compile(r"(\d{2}):(\d{2})(?::(\d{2}))?")

# A measurement with a fraction, as a group of log lines says one: the whole
# part, the fraction short of the zeros that end it, and its unit - `36.50%` is
# `36`, `5` and `%`. Only a unit of measure: a number with none, or with a
# magnitude (`1.50M`), can be a price, whose two places are how money is read.
_A_MEASUREMENT: Final = re.compile(
    r"(\d[\d,]*)\.(\d*?)0*"
    r"(%|ms|s|secs?|m|mins?|minutes?|h|hrs?|hours?|d|days?|weeks?|x|[KMGT]i?B)")

# What joins the two ends of a span shorter than a day, as a log group says one.
SPAN_DASH: Final = "–"

# What a log group says right before the minutes it was logged in after Argus
# first acted, and what joins those minutes into one word: one figure, a set,
# however many it holds - with a space after each, a replay that logged one
# minute more named every figure after it one place on.
AFTER_ARGUS_FIRST_ACTED: Final = "After Argus first acted, logged in"
BETWEEN_THE_MINUTES_OF_A_SET: Final = ","

# A set of minutes as a log group says one: minutes and spans of them, each to
# the minute, joined by `BETWEEN_THE_MINUTES_OF_A_SET`.
_A_RUN_OF_MINUTES: Final = rf"\d{{2}}:\d{{2}}(?:{SPAN_DASH}\d{{2}}:\d{{2}})?"
_A_SET_OF_MINUTES: Final = re.compile(
    rf"{_A_RUN_OF_MINUTES}(?:{re.escape(BETWEEN_THE_MINUTES_OF_A_SET)}{_A_RUN_OF_MINUTES})*")

# An instant or a span of them as the page writes one on the day the incident
# began: in UTC, and without the day, which the page's head says once - a span
# past midnight says the day its end fell on.
_A_TIME_WITHOUT_ITS_DAY: Final = re.compile(
    rf"\d{{2}}:\d{{2}}(?::\d{{2}})?"
    rf"(?:{SPAN_DASH}(?:{A_DAY_SAID.pattern}, )?\d{{2}}:\d{{2}}(?::\d{{2}})?)? UTC")

# A span between two times less than a day apart, `21:35–21:39` - or `23:58–00:04`,
# whose end is on the next day.
_A_SPAN_OF_THE_CLOCK: Final = re.compile(
    rf"(\d{{2}}):(\d{{2}})(?::(\d{{2}}))?{SPAN_DASH}(\d{{2}}):(\d{{2}})(?::(\d{{2}}))?")


def is_a_figure(word: str) -> bool:
    """Whether a word is a figure written in digits - or a range or interval of
    them, every part of which is one.

    Matched whole first, so that a rate (`5/s`, `120/min`) is the one figure it
    is rather than a number and a unit split apart. Then split, so that a range
    whose first half ends in a `Z` or a time is still read part by part, and so
    that `HTTP/2` and `AI-3/AI-4` stay the names they are: neither is a figure
    whole, and not every part of either is one.
    """
    parts = [part for part in _BETWEEN_FIGURES.split(word) if part]

    return (bool(_A_FIGURE.fullmatch(word))
            or (bool(parts) and all(_A_FIGURE.fullmatch(part) for part in parts)))


class Figure(BaseModel):
    """One figure the incident gives: as the model is shown it, and as the
    document writes it in.

    Two forms, because they are read for different things. The model reads an
    instant to the second in the form every other instant it is handed takes,
    and compares them; a reader reads a sentence.

    `a_set_of_minutes` where it is the minutes a log group was logged in after
    Argus first acted: known by what it is, since a set of one minute is
    written as a moment is, and a sentence placing a moment at it says less
    than it does.
    """

    given: str
    written: str
    a_set_of_minutes: bool = False


def figures_of(evidence: IncidentEvidence, measured: Measurements) -> dict[str, Figure]:
    """Every figure the model may name, by its name.

    Only what was measured: a figure nobody could read has no name, so a model
    cannot write in a number the incident never had. The alert's figures come
    last, after Argus's own.
    """
    day = the_day_it_began(evidence, measured)
    figures = {ALERT_RAISED_FIGURE: _an_instant(evidence.alerted_at, day)}

    # Nothing began where the alarm was disproven, and nothing lasted: named,
    # the alert and the time Argus held it read as a stretch it was broken for.
    if not evidence.disproven:
        figures[BEGAN_FIGURE] = _an_instant(_the_instant_it_began(evidence, measured), day)

    if measured.back_to_normal_at is not None:
        figures[BACK_TO_NORMAL_FIGURE] = _an_instant(measured.back_to_normal_at, day)

    if measured.metrics_stopped_at is not None:
        figures[METRICS_STOPPED_AT_FIGURE] = _an_instant(measured.metrics_stopped_at, day)

        # How far the logs read reach into the stretch the metrics did not
        # cover. Told only which lines reached in, a model wrote that nothing
        # was known after the onset; given the instant by name, saying so
        # contradicts a figure it was handed.
        logged_until = the_last_minute_logged_inside(evidence.log_lines,
                                                     measured.metrics_stopped_at)
        if logged_until is not None:
            figures[LOGS_REACH_UNTIL_FIGURE] = _an_instant(logged_until, day)

        # And where the reading of them ended, which is as often where the
        # lines stop as the service is: told only how far they reach, a model
        # wrote that nothing was known of minutes nobody had read.
        if evidence.log_reading_ended is not None:
            figures[LOG_READING_ENDED_FIGURE] = _an_instant(evidence.log_reading_ended, day)

    if not evidence.disproven:
        figures[DURATION_FIGURE] = _a_span(measured.duration_in_hours)
    figures[HELD_FIGURE] = _a_span(measured.time_to_close_in_hours)
    figures[ARGUS_STOPPED_FIGURE] = _an_instant(evidence.ended_at, day)

    # A wait of nothing is said in words - the rule fires as soon as its
    # condition holds - and a span of no time is no figure to work with.
    if measured.rule_waits:
        figures[RULE_WAITS_FIGURE] = _a_span(measured.rule_waits / timedelta(hours=1))

    # Where the page weighs detection, the brief says the page's own lesson,
    # and each span it names is a figure - and nothing it does not name: from
    # the rule's own series the look-back is in every reading, and a figure
    # for it beside the lesson invites counting it twice.
    lesson = the_detection_lesson(evidence, measured)
    if lesson is not None:
        figures |= {DETECTION_PART_FIGURES[part]: _a_span(span / timedelta(hours=1))
                    for part, span in _the_detection_parts_named(lesson)}
    else:
        # How much of the time from the onset to the alert can be the
        # condition's own window filling - nothing named for a check that
        # looks back over no range, as a wait of nothing is said in words.
        if measured.rule_looks_back:
            figures[RULE_LOOKS_BACK_FIGURE] = _a_span(
                measured.rule_looks_back / timedelta(hours=1))

        # Only from a minute up: a measured onset is a whole minute, so less
        # than one after the wait is inside what the onset can tell, and a
        # name for it would be a lag in seconds nobody measured. Named for the
        # onset under a rule that waits for nothing: beside a sentence saying
        # so, a model citing the wait's name cites a wait that is not there.
        # None where the rule's series shows no start to weigh from: counted
        # from the onset there, what came after the wait is the fault's own
        # growth.
        after_the_wait = what_came_after_the_wait(evidence, measured)
        if (after_the_wait is not None and after_the_wait >= A_MINUTE
                and no_start_from_the_line(evidence, measured) is None):
            name = (AFTER_THE_WAIT_FIGURE if measured.rule_waits
                    else ALERTED_AFTER_THE_ONSET_FIGURE)
            figures[name] = _a_span(after_the_wait / timedelta(hours=1))

    # Only where it is said: the service back before the action credited with
    # it, which the write-up cannot say without the action's time.
    credited = evidence.credited_action
    if measured.back_before_the_action and credited is not None:
        figures[ACTED_FIGURE] = _an_instant(credited.taken_at, day)

    # Only where it is said, as the action's time is.
    told = the_post_beside_nobody_paged(evidence, measured)
    if told is not None:
        figures[FIRST_TOLD_FIGURE] = _an_instant(told.at, day)

    rates = measured.error_rates
    if rates is not None:
        figures[ERRORS_BEFORE_FIGURE] = _a_share(rates.baseline)
        figures[ERRORS_WHILE_BROKEN_FIGURE] = _a_share(rates.while_broken)
        figures[ERRORS_AT_WORST_FIGURE] = _a_share(rates.at_its_worst)
        # A rise at or below nothing, or within what the rate reaches on its
        # own, is told in words; a name for it would let the model write a
        # rise nobody can tell from noise, or a negative share failing.
        if rates.rise > 0 and rates.rose_beyond_its_variation:
            figures[ERRORS_RISE_FIGURE] = _a_share(rates.rise)

    levels = measured.rule_series
    if levels is not None:
        unit = measured.rule_series_unit
        the_error_rate = measured.rule_series_is_the_error_rate
        figures[SERIES_BEFORE_FIGURE] = _a_level(levels.baseline, unit, the_error_rate)
        figures[SERIES_WHILE_BROKEN_FIGURE] = _a_level(levels.while_broken, unit, the_error_rate)
        figures[SERIES_AT_WORST_FIGURE] = _a_level(levels.at_its_worst, unit, the_error_rate)

    # A loss of nothing is said in words, as the page says it: "0.00 USD"
    # reads as a figure nobody filled in.
    if measured.loss and measured.currency is not None:
        figures[CUSTOMER_LOSS_FIGURE] = _an_amount(measured.loss, measured.currency)

    if evidence.alert_finding:
        figures.update(the_alerts_figures(evidence.alert_finding, day))

    return figures


def the_post_beside_nobody_paged(evidence: IncidentEvidence,
                                 measured: Measurements) -> FirstTold | None:
    """When and where Argus first posted about the incident, where nobody was
    paged - the one incident the brief says it of, because the one a write-up
    said nobody was told about. `None` anywhere else.

    Asked once, here, for the figure and the sentence naming it alike: a figure
    named with no sentence to name it in, or the reverse, is the model handed a
    name for nothing.
    """
    if not isinstance(measured.engaged, NotPaged):
        return None

    return evidence.first_told


def with_every_day_said(figures: Mapping[str, Figure], day: date) -> dict[str, Figure]:
    """The figures with every instant written with its day - for a paragraph
    said where no head dates the incident, about an incident that ran across
    days: there an instant on the day it began, said as a bare time, reads as
    the day the paragraph is read.

    By what is written rather than what was given: an instant written in UTC
    without its day is one on the `day` the incident began, whichever form it
    was given in - a wire instant, a time a line of the narration said, a
    group of log lines' minutes. One written as given carries no zone, and its
    day is nobody's to say."""
    return {name: figure.model_copy(update={"written": _with_the_day_said(figure, day)})
            for name, figure in figures.items()}


def _with_the_day_said(figure: Figure, day: date) -> str:
    """A figure as written, with `day` before it where it is an instant
    written in UTC without its day - which is one on that day - or a set of
    minutes whose first is."""
    if not (_A_TIME_WITHOUT_ITS_DAY.fullmatch(figure.written)
            or (figure.a_set_of_minutes and not A_DAY_SAID.match(figure.written))):
        return figure.written

    return f"{said_as_a_day(datetime.combine(day, datetime.min.time(), UTC))}, {figure.written}"


def the_day_said_off_the_page(evidence: IncidentEvidence,
                              measured: Measurements) -> date | None:
    """The day every instant is dated against in a paragraph said off the
    page - the day the incident began, where Argus stopped on another day -
    or `None` where it stopped on that day, and a bare time misleads nobody."""
    day = the_day_it_began(evidence, measured)

    return day if evidence.ended_at.astimezone(UTC).date() != day else None


def the_day_it_began(evidence: IncidentEvidence, measured: Measurements) -> date:
    """The day the incident began, which every instant written on it leaves
    unsaid - the page dates the incident once, in its head."""
    return _the_instant_it_began(evidence, measured).astimezone(UTC).date()


def _the_instant_it_began(evidence: IncidentEvidence, measured: Measurements) -> datetime:
    """The onset where one was measured, and the alert as its sender dated it
    where none was - the instant the incident is dated from either way, here,
    in the duration (`measuring`) and in the page's head."""
    return measured.onset_at or evidence.alerted_at


def _the_detection_parts_named(lesson: DetectionLesson) -> list[tuple[DetectionPart, timedelta]]:
    """Each span the lesson's sentence names, and only those - read off the
    sentence itself, so a figure is registered exactly where it is said."""
    named: list[tuple[DetectionPart, timedelta]] = []

    def noted(part: DetectionPart, span: timedelta) -> str:
        named.append((part, span))
        return ""

    the_detection_lesson_said(lesson, noted)
    return named


def what_came_after_the_wait(evidence: IncidentEvidence,
                             measured: Measurements) -> timedelta | None:
    """How long after its rule's wait ended the alert came - below nothing
    where it came sooner than the wait allows - or `None` where there is no
    gap to take it from: no onset measured, or no wait read.

    A wait of nothing is still a wait the gap comes after: told only that the
    rule fires as soon as its condition holds, a write-up left the whole gap
    from the onset to the alert unweighed.

    One working for the figure and the brief's sentence alike, so the two
    never say different things of the same alert.
    """
    if measured.onset_at is None or measured.rule_waits is None:
        return None

    return evidence.alerted_at - measured.onset_at - measured.rule_waits


def the_alerts_figures(finding: str, day: date) -> dict[str, Figure]:
    """The figures the alert's sender wrote, named in the order it wrote them.

    Each written in exactly as the sender wrote it, except an instant, which is
    written as a reader says one, on the `day` the incident began.
    """
    return _the_figures_in(finding, _ALERT_FIGURE_PREFIX, day)


def the_finding_named(finding: str) -> str:
    """The alert's words with each figure's name after it, as the model reads
    them.

    The name sits before whatever punctuation closed the figure, so the
    sentence still reads as the sender wrote it.
    """
    return _said_with_names(finding, _ALERT_FIGURE_PREFIX)


def the_evidence_figures(cited: Sequence[CitedEvidence], day: date) -> dict[str, Figure]:
    """The figures each piece of evidence states, named after its label and
    then in the order it states them: `Gbac1.1`, `Gbac1.2`.

    Written in as the alert's are. Without a name the model could not say what
    its own evidence said - "20 connections" in digits is refused like a figure
    it invented - and the label keeps the name the same in every run the
    evidence reads the same.
    """
    return {name: figure
            for each in cited
            for name, figure in _the_figures_in(each.text, f"{each.label}.", day).items()}


def the_narration_figures(lines: Sequence[CitedEvidence], day: date) -> dict[str, Figure]:
    """The figures each line of the walk's narration states, named as the
    evidence's are.

    A time of day here is one Argus said, so an instant on a day it said: the
    one beside it ("Oct 24 19:44:24"), or else the day of the stamp the line
    opens with - a line says a time alone only on its own day. Written as a
    bare time, either read as a time of the onset's day. Nowhere else: an
    instant quoted further along is somebody else's, and so is the zone of a
    time said after it.
    """
    return {name: figure
            for each in lines
            for name, figure in _the_narrated_figures_in(each.text, f"{each.label}.",
                                                         day).items()}


def the_evidence_named(cited: CitedEvidence) -> str:
    """A piece of evidence with each figure's name after it, as the model reads
    it."""
    return _said_with_names(cited.text, f"{cited.label}.")


def the_log_group_figures(groups: Sequence[tuple[CitedEvidence, tuple[int, int]]],
                          day: date) -> dict[str, Figure]:
    """The figures each group of log lines states, named as the evidence's are.

    Each group is handed with where in its text the message it quotes sits.
    That message is in its writer's words, and written in as given, as every
    quoted figure is. The rest of the row - how often, over which minutes, how
    far each number ranged - is Argus's, said from the lines' stamps in UTC:
    there a time of day, or the start of a span of them, is on the day said
    beside it, and said bare on the day the incident began, the one day the
    row leaves unsaid. A span's end earlier on the clock than its start is on
    the day after.
    """
    return {name: figure
            for cited, quoted in groups
            for name, figure in _the_grouped_figures_in(cited.text, f"{cited.label}.", quoted,
                                                        day).items()}


def _the_grouped_figures_in(text: str, prefix: str, quoted: tuple[int, int],
                            day: date) -> dict[str, Figure]:
    figures: dict[str, Figure] = {}
    after_the_act = text.find(AFTER_ARGUS_FIRST_ACTED)
    at = 0

    for part, figure, beside in _the_words_and_days_of(text):
        if figure is not None:
            name = f"{prefix}{len(figures) + 1}"
            on = the_day_said(beside, day) if beside is not None else day
            figures[name] = (_as_the_alert_gave_it(figure, day) if quoted[0] <= at < quoted[1]
                             else _a_set_on_its_day(figure, on or day, day)
                             if 0 <= after_the_act < at and _A_SET_OF_MINUTES.fullmatch(figure)
                             else _without_its_trailing_zeros(_on_its_day(figure, on, day)))
        at += len(part)

    return figures


def _a_set_on_its_day(figure: str, on: date, day: date) -> Figure:
    """The minutes a log group was logged in after Argus first acted, written
    as a reader reads a list - each minute or span on its day as `_on_its_day`
    writes one, a minute earlier on the clock than the one before it on the
    next day, and the zone said once at the end: `23:40, 23:42–23:43 and
    23:45 UTC`."""
    written: list[str] = []
    before: datetime | None = None

    for run in figure.split(BETWEEN_THE_MINUTES_OF_A_SET):
        began, _, ended = run.partition(SPAN_DASH)
        first = _a_minute_from(began, on, before)
        last = _a_minute_from(ended, on, first) if ended else first
        said = _as_a_reader_says(first, day).removesuffix(" UTC")
        if ended:
            said += SPAN_DASH + (said_as_a_time(last) if last.date() == first.date()
                                 else _with_its_day(last).removesuffix(" UTC"))
        written.append(said)
        before = last

    listed = (f"{', '.join(written[:-1])} and {written[-1]}" if len(written) > 1
              else written[0])

    return Figure(given=figure, written=f"{listed} UTC", a_set_of_minutes=True)


def _a_minute_from(clock: str, on: date, before: datetime | None) -> datetime:
    """A time of day as the instant it is on `on` - or, where that is earlier
    than `before`, on the first day after it that is not."""
    hours, minutes = map(int, clock.split(":"))
    at = datetime(on.year, on.month, on.day, hours, minutes, tzinfo=UTC)

    while before is not None and at < before:
        at += timedelta(days=1)

    return at


def _without_its_trailing_zeros(figure: Figure) -> Figure:
    """A measurement a group of log lines said, written without the zeros that
    end its fraction - `36.00%` as `36%`, `36.50%` as `36.5%` - and shown to
    the model as given. Any other number is written as it was logged.

    The row says each value as it was logged, to however many places the
    service logs it, and the model reads it so; a reader handed "36.00%" reads
    a column of a report.
    """
    measurement = _A_MEASUREMENT.fullmatch(figure.written)

    if measurement is None:
        return figure

    whole, fraction, unit = measurement.groups()

    return Figure(given=figure.given,
                  written=f"{whole}.{fraction}{unit}" if fraction else f"{whole}{unit}")


def _the_figures_in(text: str, prefix: str, day: date) -> dict[str, Figure]:
    """Each figure the text states, named in the order it states them, and
    written in as its writer gave it: a time of day is in the writer's zone and
    on the writer's day, neither of which Argus knows."""
    return {f"{prefix}{position}": _as_the_alert_gave_it(figure, day)
            for position, (figure, _) in enumerate(_the_figures_and_days_of(text), start=1)}


def _the_narrated_figures_in(text: str, prefix: str, day: date) -> dict[str, Figure]:
    """Each figure a line of the narration states, named in the order it states
    them, with a time of day on the day said beside it or the line's own."""
    opened_on = _the_day_it_opens_on(text)

    return {f"{prefix}{position}": _on_its_day(
                figure, the_day_said(beside, day) if beside is not None else opened_on, day)
            for position, (figure, beside) in enumerate(_the_figures_and_days_of(text), start=1)}


def _the_figures_and_days_of(text: str) -> list[tuple[str, str | None]]:
    return [(word, beside) for _, word, beside in _the_words_and_days_of(text)
            if word is not None]


def _the_day_it_opens_on(text: str) -> date | None:
    """The day of the instant the text opens with, `None` where it opens with
    none."""
    opening = text.split(maxsplit=1)
    if not opening or not _AN_INSTANT.fullmatch(opening[0]):
        return None

    return parse_iso(opening[0]).astimezone(UTC).date()


def _said_with_names(text: str, prefix: str) -> str:
    said = []
    position = 0

    for part, figure, _ in _the_words_and_days_of(text):
        if figure is None:
            said.append(part)
            continue

        position += 1
        starts = part.find(figure)
        ends = starts + len(figure)
        said.append(f"{part[:ends]} {{{prefix}{position}}}{part[ends:]}")

    return "".join(said)


def an_instant_of(row: str) -> str:
    """The name of the instant a row of the evidence opens with - its first
    figure, as T3.1 is T3's."""
    return f"{row}.1"


def a_span_from_the_alert(instant: str, figures: Mapping[str, Figure]) -> str:
    """How long after the alert - or before it - the instant named `instant`
    came, as a working of the two for `with_figures_written` to write in:
    "{T13.1 - alert_raised} after the alert was raised". The larger first, as
    every span is worked out: a message a person wrote before the alert is
    before it."""
    if (_magnitude_shown(figures[instant], _Kind.INSTANT)
            < _magnitude_shown(figures[ALERT_RAISED_FIGURE], _Kind.INSTANT)):
        return f"{{{ALERT_RAISED_FIGURE} - {instant}}} before the alert was raised"

    return f"{{{instant} - {ALERT_RAISED_FIGURE}}} after the alert was raised"


def named(name: str, figure: Figure) -> str:
    """A figure as the model is shown it, with its name after it."""
    return f"{figure.given} {{{name}}}"


def names_in(prose: str) -> list[str]:
    """The figures a sentence names, in the order it names them - alone, or as
    what a working is worked out from."""
    return [name
            for naming in _A_NAMING.finditer(prose)
            for name in ([naming.group(1)] if naming.group(1) is not None
                         else [naming.group(2), naming.group(4)])]


def with_figures_written(answer: SubmittedPostmortem,
                         figures: dict[str, Figure]) -> SubmittedPostmortem:
    """The answer with every figure it names written in.

    A name no figure has is left as written, for the check to send back to the
    model (`checking`): nothing here can know which figure it meant, and a
    guess written in would be a number nobody measured. So is a working that
    cannot be worked out.
    """
    return _with_figures_written_in(answer, figures, lambda result: result)


def with_figures_written_with_every_day(answer: SubmittedPostmortem,
                                        figures: dict[str, Figure],
                                        day: date) -> SubmittedPostmortem:
    """The answer written in as `with_figures_written` writes it, with every
    instant it names dated against `day` (`with_every_day_said`) - a working's
    too: worked out from the figures as the model was shown them, an instant
    after the onset came out bare beside figures that said their day."""
    return _with_figures_written_in(answer, with_every_day_said(figures, day),
                                    lambda result: _with_the_day_said(
                                        Figure(given=result, written=result), day))


def _with_figures_written_in(answer: SubmittedPostmortem, figures: dict[str, Figure],
                             dated: Callable[[str], str]) -> SubmittedPostmortem:
    def written_in(prose: str) -> str:
        # A sentence that opens with a figure opens with a capital once it is
        # written in: "less than a second after the alert was raised" is
        # written lower case.
        opens_with_one = prose.startswith("{")
        prose = _A_WORKING_AND_A_UNIT.sub(
            lambda working: (_with_its_unit_once(dated(result), working["after"])
                             if (result := _worked_out(working, figures))
                             else working.group(0)),
            prose
        )
        prose = _A_NAME_AND_A_UNIT.sub(
            lambda name: (_with_its_unit_once(figures[name.group(1)].written, name["after"])
                          if name.group(1) in figures else name.group(0)),
            prose
        )

        return f"{prose[:1].upper()}{prose[1:]}" if opens_with_one else prose

    return answer.with_each_sentence(written_in)


def units_against_their_figures(prose: str,
                                figures: Mapping[str, Figure]) -> list[tuple[str, str]]:
    """Each figure's name or working a sentence follows with a unit that
    measures what the one it is written in with does, but is another - as
    written, and with the unit the figure is written in with - in the order the
    sentence says them.

    "{series_before} seconds" on a figure written "215 ms" misreads its scale,
    and nothing here can tell which the sentence meant. A unit said again is
    not one (`with_figures_written` writes it once), nor is a word after a
    figure written with no unit: that word is the writer's own.
    """
    written_in = [
        *((said, result) for said in _A_WORKING_AND_A_UNIT.finditer(prose)
          if (result := _worked_out(said, figures)) is not None),
        *((said, figures[said.group(1)].written) for said in _A_NAME_AND_A_UNIT.finditer(prose)
          if said.group(1) in figures)
    ]

    return [(said.group(0).strip(), _the_unit_ending(written))
            for said, written in sorted(written_in, key=lambda each: each[0].start())
            if _contradicts(written, said["after"])]


def _with_its_unit_once(written: str, after: str | None) -> str:
    """A figure written in, and what the sentence said after its name - left
    out where it is the unit the figure is written with: the word it ends in,
    or another spelling of that unit."""
    if after is None:
        return written

    said = _spelled(after)
    ends_in = _the_unit_of(written)
    if said == written.split()[-1].lower() or (ends_in is not None
                                               and ends_in == _UNITS.get(said)):
        return written

    return written + after


def _contradicts(written: str, after: str | None) -> bool:
    """Whether a unit said after a figure measures what the figure's own
    measures, but is another."""
    ends_in = _the_unit_of(written)
    said = _UNITS.get(_spelled(after)) if after is not None else None
    if ends_in is None or said is None:
        return False

    return said[1] == ends_in[1] and said[0] != ends_in[0]


def _the_unit_of(written: str) -> tuple[str, _Measure] | None:
    """The unit a figure is written in with, and what it measures - `None`
    where it ends in none this knows."""
    ending = _the_unit_ending(written)

    return _UNITS[ending] if ending else None


def _the_unit_ending(written: str) -> str:
    """The spelling a figure's written form ends in, as it spells it - nothing
    where it ends in no unit."""
    lowered = written.lower()

    for spelling in _SPELLINGS_LONGEST_FIRST:
        if (lowered.endswith(spelling) if spelling == "%"
                else lowered.endswith(f" {spelling}")):
            return spelling

    return ""


def _spelled(after: str) -> str:
    """A unit as said after a name, as `_UNITS` spells it."""
    return " ".join(after.split()).lower()


def workings_that_make_no_sense(prose: str,
                                figures: Mapping[str, Figure]) -> list[tuple[str, str]]:
    """Each working a sentence asks for that works out to nothing, as written
    and with why, in the order it asks for them.

    Three of the reasons are this run's rather than the answer's: a figure
    that is no number (a level Prometheus answered `+Inf` or `NaN` for), a
    difference below nothing and a division by nothing are read from `figures`. A working
    from a figure `figures` lacks is the name check's to refuse, not this.
    """
    return [(working.group(0), why)
            for working in _A_WORKING.finditer(prose)
            if (why := _why_it_makes_no_sense(working.group(1), working.group(2),
                                              working.group(3), figures)) is not None]


def _why_it_makes_no_sense(first: str, operation: str, second: str,
                           figures: Mapping[str, Figure]) -> str | None:
    kinds = (_kind_of(first, figures), _kind_of(second, figures))

    if (kinds[0], operation, kinds[1]) not in _WORKINGS:
        what_can_be = ", ".join(f"{one} {_OPERATIONS[asked]} {other}"
                                for one, asked, other in _WORKINGS)

        return (f"{_said_as_a_kind(first, kinds[0])} {_OPERATIONS[operation]} "
                f"{_said_as_a_kind(second, kinds[1])} works out to nothing - what can be "
                f"worked out is {what_can_be}")

    if kinds[0] is None or kinds[1] is None or first not in figures or second not in figures:
        return None

    for name, kind in ((first, kinds[0]), (second, kinds[1])):
        if not _magnitude_shown(figures[name], kind).is_finite():
            return f"{{{name}}} is no number, and nothing can be worked out from it"

    if operation == "/" and _magnitude_shown(figures[second], kinds[1]) == 0:
        return f"{{{second}}} is nothing, and nothing divides by it"

    if (operation == "-" and kinds[0] == kinds[1]
            and _magnitude_shown(figures[first], kinds[0])
            < _magnitude_shown(figures[second], kinds[1])):
        return (f"{{{first}}} is less than {{{second}}}, so it comes out below nothing - "
                f"put the larger first and let the sentence say which way it went")

    return None


def _magnitude_shown(figure: Figure, kind: _Kind) -> Decimal:
    """A figure as the model was shown it, as one number two of its kind can be
    compared by: an instant in seconds since the epoch, a span in seconds."""
    match kind:
        case _Kind.INSTANT:
            return Decimal(str(parse_iso(figure.given).timestamp()))
        case _Kind.SPAN:
            return _seconds_shown(figure)
        case _Kind.SHARE:
            return _percent_shown(figure)
        case _Kind.LEVEL:
            return _level_shown(figure)


def _said_as_a_kind(name: str, kind: _Kind | None) -> str:
    return str(kind) if kind is not None else f"{{{name}}}, which cannot be worked with,"


def _worked_out(working: re.Match[str], figures: Mapping[str, Figure]) -> str | None:
    """A working as the page writes its result, or `None` where it has none.

    From each figure as the model was shown it rather than as it was measured,
    so the result never disagrees with the figures written beside it.
    """
    first, operation, second = working.group(1, 2, 3)

    if (first not in figures or second not in figures
            or _why_it_makes_no_sense(first, operation, second, figures) is not None):
        return None

    kinds = (_kind_of(first, figures), _kind_of(second, figures))

    if kinds[0] is None or kinds[1] is None:
        return None

    return _WORKINGS[(kinds[0], operation, kinds[1])](figures[first], figures[second],
                                                      _the_day_shown(figures))


def _the_day_shown(figures: Mapping[str, Figure]) -> date | None:
    """The day the incident began, as the model was shown the instant it is
    dated from - the alert's, where nothing began - or `None` where it was
    shown none."""
    began = figures.get(BEGAN_FIGURE, figures.get(ALERT_RAISED_FIGURE))

    return parse_iso(began.given).astimezone(UTC).date() if began is not None else None


def _kind_of(name: str, figures: Mapping[str, Figure]) -> _Kind | None:
    """A figure's kind: by its name where Argus measured it, and otherwise an
    instant where it was shown as one - a line of the narration's time is an
    instant whoever wrote it - or none, where what it measures is its writer's
    to know."""
    if name in _KINDS:
        return _KINDS[name]

    if name in figures and _AN_INSTANT.fullmatch(figures[name].given):
        return _Kind.INSTANT

    return None


def _level_shown(level: Figure) -> Decimal:
    """A level as the model was shown it, without the unit it was shown in."""
    shown = _A_LEVEL_SHOWN.match(level.given)

    return Decimal(shown["number"]) if shown is not None else Decimal(level.given)


def _a_difference_of_levels(first: Figure, second: Figure) -> str:
    """One level less another, in their unit - two percentages differing by
    points, as two shares of traffic do."""
    said = said_as_a_level(float(_level_shown(first) - _level_shown(second)))
    shown = _A_LEVEL_SHOWN.match(first.given)
    unit = shown["unit"] if shown is not None else ""

    if unit == _PERCENT_SHOWN:
        return f"{said} percentage points"

    return f"{said}{unit}"


def _percent_shown(share: Figure) -> Decimal:
    """A share as the model was shown it, in percent and to the digit shown."""
    return Decimal(share.given.removesuffix("%"))


def _span_shown(span: Figure) -> timedelta:
    """A span as the model was shown it, read back out of its words."""
    return sum((timedelta(**{f"{unit}s": int(count)})
                for count, unit in _A_COUNT_OF_A_UNIT.findall(span.given)),
               timedelta())


def _seconds_shown(span: Figure) -> Decimal:
    return Decimal(_span_shown(span) // timedelta(seconds=1))


def _how_many_times(ratio: Decimal) -> str:
    """A ratio as a sentence says one, to a tenth."""
    return f"{ratio.quantize(_A_TENTH, rounding=ROUND_HALF_UP)} times"


def _the_words_and_days_of(text: str) -> Iterator[tuple[str, str | None, str | None]]:
    """Every stretch of the text in order, each with the figure it is - or
    `None` for the spaces between words and for every word that is no figure -
    and the day said right before it, where it is a time of day that day is
    said beside.

    A diff's hunk header states none: where in a file a hunk sits is no figure
    of the incident's, and named as one it is offered as one. Found by the
    layout the read tier sets a diff out in, so a patch line whose own text
    begins with `@@` keeps its figures. The values the diff changed are
    figures, since one of them can be the cause.

    Nor does a day said as narration says one beside a time ("Oct 20 20:31"):
    read word by word, the day of the month was a figure of its own, offered as
    a number the incident gave. The time beside it is one, and the day is what
    makes it an instant rather than a time of the onset's day.
    """
    for line in text.splitlines(keepends=True):
        if line.startswith(PATCH_LINE_INDENT + HUNK_HEADER):
            yield line, None, None
            continue

        said: str | None = None
        for stretch, is_a_day in _the_days_apart(line):
            if is_a_day:
                said = stretch
                yield stretch, None, None
                continue

            for part in re.split(r"(\s+)", stretch):
                word = part.strip(AROUND_A_WORD)
                figure = word if word and is_a_figure(word) else None
                yield (part, figure,
                       said if figure is not None and _is_on_a_clock(figure) else None)
                said = None if part.strip() else said


def _the_days_apart(line: str) -> Iterator[tuple[str, bool]]:
    """The line in stretches, each with whether it is a day said."""
    at = 0

    for day in A_DAY_SAID.finditer(line):
        yield line[at:day.start()], False
        yield day.group(), True
        at = day.end()

    yield line[at:], False


def _as_the_alert_gave_it(figure: str, day: date) -> Figure:
    if _AN_INSTANT.fullmatch(figure):
        return Figure(given=figure, written=_as_a_reader_says(parse_iso(figure), day))

    return Figure(given=figure, written=figure)


def _is_on_a_clock(figure: str) -> bool:
    """Whether a figure is a time of day, a span between two, or a set of
    minutes - whose day, said before it, is the first's."""
    return bool(_A_TIME_OF_DAY.fullmatch(figure) or _A_SPAN_OF_THE_CLOCK.fullmatch(figure)
                or _A_SET_OF_MINUTES.fullmatch(figure))


def _on_its_day(figure: str, on: date | None, day: date) -> Figure:
    """A time of day written as the instant it is on `on` - with its day where
    that is not the `day` the incident began, as every instant is - and a span
    between two times of that day the same way, its day said once; as it was
    given where it is neither or `on` is not known. Shown to the model as it
    was given either way.

    A span whose end reads earlier than its start ran past midnight, and its
    end is written with the day after `on`: said bare, it read as a minute of
    the day the span began."""
    if on is None:
        return _as_the_alert_gave_it(figure, day)

    if clock := _A_TIME_OF_DAY.fullmatch(figure):
        return Figure(given=figure, written=_as_a_reader_says(_at(on, clock, 1), day))

    if span := _A_SPAN_OF_THE_CLOCK.fullmatch(figure):
        began, ended = _at(on, span, 1), _at(on, span, 4)
        first = _as_a_reader_says(began, day).removesuffix(" UTC")

        if ended < began:
            return Figure(given=figure,
                          written=f"{first}{SPAN_DASH}{_with_its_day(ended + timedelta(days=1))}")

        return Figure(given=figure, written=f"{first}{SPAN_DASH}{said_as_a_time(ended)} UTC")

    return _as_the_alert_gave_it(figure, day)


def _at(on: date, clock: re.Match[str], hours: int) -> datetime:
    """The instant on `on` of the time of day whose hours, minutes and maybe
    seconds are `clock`'s groups from `hours` on."""
    return datetime(on.year, on.month, on.day, int(clock[hours]), int(clock[hours + 1]),
                    int(clock[hours + 2] or 0), tzinfo=UTC)


def _an_instant(at: datetime, day: date) -> Figure:
    return Figure(given=to_iso(at), written=_as_a_reader_says(at, day))


def _as_a_reader_says(at: datetime, day: date | None) -> str:
    """An instant as the page says one: to the minute, and to the second only
    where it has one - a minute said "20:45:00" claims a precision nothing
    measured.

    The day only where it is not the `day` the incident began: the page dates
    the incident once, in its head, and "Oct 20, 2026, 22:45 UTC" said in every
    sentence buries the time a reader is after. Never the year, which the head
    says too. In full where there is no day it began to leave unsaid.
    """
    at = at.astimezone(UTC)

    if day is None:
        return f"{said_as_a_day(at)}, {at:%Y}, {said_as_a_time(at)} UTC"

    if at.date() != day:
        return _with_its_day(at)

    return f"{said_as_a_time(at)} UTC"


def _with_its_day(at: datetime) -> str:
    """An instant with its day and without its year."""
    at = at.astimezone(UTC)

    return f"{said_as_a_day(at)}, {said_as_a_time(at)} UTC"


def _a_span(hours: float) -> Figure:
    said = said_as_a_span(timedelta(hours=hours))

    return Figure(given=said, written=said)


def _an_amount(amount: Decimal, currency: str) -> Figure:
    """Money in its currency, as the page says it."""
    said = said_as_money(amount, currency)

    return Figure(given=said, written=said)


def _a_share(rate: float) -> Figure:
    said = said_as_a_share(rate)

    return Figure(given=said, written=said)


def _a_level(level: float, unit: str | None, is_the_error_rate: bool) -> Figure:
    """A level in the unit the paging rule's series is in, where anything named
    one - given as measured, and written as a person says it: as the error
    rate is written, where the series is the error rate, since the page says
    that rate too and one figure written two ways is two to a reader."""
    written = said_as_a_share(level) if is_the_error_rate else level_said_in(level, unit)

    return Figure(given=level_given_in(level, unit), written=written)
