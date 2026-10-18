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
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from argus_core import parse_iso, to_iso
from argus_core.models import CitedEvidence
from pydantic import BaseModel

from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.measuring import Measurements

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
UNOBSERVED_FROM_FIGURE: Final = "unobserved_from"
DURATION_FIGURE: Final = "duration"
HELD_FIGURE: Final = "held"
RULE_WAITS_FIGURE: Final = "rule_waits"
CLOSED_FIGURE: Final = "closed"
ACTED_FIGURE: Final = "acted"
ERRORS_BEFORE_FIGURE: Final = "errors_before"
ERRORS_WHILE_BROKEN_FIGURE: Final = "errors_while_broken"
ERRORS_AT_WORST_FIGURE: Final = "errors_at_worst"
ERRORS_RISE_FIGURE: Final = "errors_rise"
SERIES_BEFORE_FIGURE: Final = "series_before"
SERIES_WHILE_BROKEN_FIGURE: Final = "series_while_broken"
SERIES_AT_WORST_FIGURE: Final = "series_at_worst"

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
    UNOBSERVED_FROM_FIGURE: _Kind.INSTANT,
    CLOSED_FIGURE: _Kind.INSTANT,
    ACTED_FIGURE: _Kind.INSTANT,
    DURATION_FIGURE: _Kind.SPAN,
    HELD_FIGURE: _Kind.SPAN,
    RULE_WAITS_FIGURE: _Kind.SPAN,
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

# How many figures a level is written to, as a reader compares two.
_LEVEL_FIGURES: Final = 3

# Each operation a working may ask for, as a sentence says it.
_OPERATIONS: Final = {"-": "minus", "+": "plus", "/": "divided by"}

# How each operation on two kinds is worked out, from the two figures as the
# model was shown them, into what the page writes. One missing works out to
# nothing, and is put back to the model.
#
# A difference of two shares is in points rather than a share: "rose by 32.7%"
# reads as a share of where it started. A difference of two levels is a level,
# in whatever unit the paging rule watches.
_WORKINGS: Final[dict[tuple[_Kind, str, _Kind], Callable[[Figure, Figure], str]]] = {
    (_Kind.INSTANT, "-", _Kind.INSTANT):
        lambda first, second: _said_of_a_span(parse_iso(first.given)
                                              - parse_iso(second.given)),
    (_Kind.INSTANT, "+", _Kind.SPAN):
        lambda first, second: _as_a_reader_says(parse_iso(first.given)
                                                + _span_shown(second)),
    (_Kind.INSTANT, "-", _Kind.SPAN):
        lambda first, second: _as_a_reader_says(parse_iso(first.given)
                                                - _span_shown(second)),
    (_Kind.SPAN, "+", _Kind.SPAN):
        lambda first, second: _said_of_a_span(_span_shown(first) + _span_shown(second)),
    (_Kind.SPAN, "-", _Kind.SPAN):
        lambda first, second: _said_of_a_span(_span_shown(first) - _span_shown(second)),
    (_Kind.SPAN, "/", _Kind.SPAN):
        lambda first, second: _how_many_times(_seconds_shown(first) / _seconds_shown(second)),
    (_Kind.SHARE, "-", _Kind.SHARE):
        lambda first, second: (f"{_percent_shown(first) - _percent_shown(second)} "
                               f"percentage points"),
    (_Kind.SHARE, "/", _Kind.SHARE):
        lambda first, second: _how_many_times(_percent_shown(first) / _percent_shown(second)),
    (_Kind.LEVEL, "-", _Kind.LEVEL):
        lambda first, second: _a_level(float(Decimal(first.given)
                                             - Decimal(second.given))).written,
    (_Kind.LEVEL, "/", _Kind.LEVEL):
        lambda first, second: _how_many_times(Decimal(first.given) / Decimal(second.given))
}

# A span as `span_in_words` says one, a count and its unit at a time.
_A_COUNT_OF_A_UNIT: Final = re.compile(r"(\d+) (day|hour|minute|second)s?")

# An instant as a wire format writes one, which the alert's sender may.
_AN_INSTANT: Final = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?")


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
    """

    given: str
    written: str


def figures_of(evidence: IncidentEvidence, measured: Measurements) -> dict[str, Figure]:
    """Every figure the model may name, by its name.

    Only what was measured: a figure nobody could read has no name, so a model
    cannot write in a number the incident never had. The alert's figures come
    last, after Argus's own.
    """
    figures = {
        ALERT_RAISED_FIGURE: _an_instant(evidence.alerted_at),
        # The onset where one was measured, and the alert where none was - the
        # instant the incident is dated from either way.
        BEGAN_FIGURE: _an_instant(measured.onset_at or evidence.started_at)
    }

    if measured.back_to_normal_at is not None:
        figures[BACK_TO_NORMAL_FIGURE] = _an_instant(measured.back_to_normal_at)

    if measured.unobserved_from is not None:
        figures[UNOBSERVED_FROM_FIGURE] = _an_instant(measured.unobserved_from)

    figures[DURATION_FIGURE] = _a_span(measured.duration_in_hours)
    figures[HELD_FIGURE] = _a_span(measured.time_to_close_in_hours)
    figures[CLOSED_FIGURE] = _an_instant(evidence.ended_at)

    # A wait of nothing is said in words - the rule fires as soon as its
    # condition holds - and a span of no time is no figure to work with.
    if measured.rule_waits:
        figures[RULE_WAITS_FIGURE] = _a_span(measured.rule_waits / timedelta(hours=1))

    # Only where it is said: the service back before the action credited with
    # it, which the write-up cannot say without the action's time.
    credited = evidence.credited_action
    if measured.back_before_the_action and credited is not None:
        figures[ACTED_FIGURE] = _an_instant(credited.taken_at)

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
        figures[SERIES_BEFORE_FIGURE] = _a_level(levels.baseline)
        figures[SERIES_WHILE_BROKEN_FIGURE] = _a_level(levels.while_broken)
        figures[SERIES_AT_WORST_FIGURE] = _a_level(levels.at_its_worst)

    if evidence.alert_finding:
        figures.update(the_alerts_figures(evidence.alert_finding))

    return figures


def the_alerts_figures(finding: str) -> dict[str, Figure]:
    """The figures the alert's sender wrote, named in the order it wrote them.

    Each written in exactly as the sender wrote it, except an instant, which is
    written as a reader says one.
    """
    return _the_figures_in(finding, _ALERT_FIGURE_PREFIX)


def the_finding_named(finding: str) -> str:
    """The alert's words with each figure's name after it, as the model reads
    them.

    The name sits before whatever punctuation closed the figure, so the
    sentence still reads as the sender wrote it.
    """
    return _said_with_names(finding, _ALERT_FIGURE_PREFIX)


def the_evidence_figures(cited: Sequence[CitedEvidence]) -> dict[str, Figure]:
    """The figures each piece of evidence states, named after its label and
    then in the order it states them: `Gbac1.1`, `Gbac1.2`.

    Written in as the alert's are. Without a name the model could not say what
    its own evidence said - "20 connections" in digits is refused like a figure
    it invented - and the label keeps the name the same in every run the
    evidence reads the same.
    """
    return {name: figure
            for each in cited
            for name, figure in _the_figures_in(each.text, f"{each.label}.").items()}


def the_evidence_named(cited: CitedEvidence) -> str:
    """A piece of evidence with each figure's name after it, as the model reads
    it."""
    return _said_with_names(cited.text, f"{cited.label}.")


def _the_figures_in(text: str, prefix: str) -> dict[str, Figure]:
    figures = [word for _, word in _the_words_of(text) if word is not None]

    return {f"{prefix}{position}": _as_the_alert_gave_it(figure)
            for position, figure in enumerate(figures, start=1)}


def _said_with_names(text: str, prefix: str) -> str:
    said = []
    position = 0

    for part, figure in _the_words_of(text):
        if figure is None:
            said.append(part)
            continue

        position += 1
        starts = part.find(figure)
        ends = starts + len(figure)
        said.append(f"{part[:ends]} {{{prefix}{position}}}{part[ends:]}")

    return "".join(said)


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

    A name no figure has is left as written, for the check to put back to the
    model (`checking`): nothing here can know which figure it meant, and a
    guess written in would be a number nobody measured. So is a working that
    cannot be worked out.
    """
    def written_in(prose: str) -> str:
        prose = _A_WORKING.sub(
            lambda working: _worked_out(working, figures) or working.group(0),
            prose
        )

        return A_FIGURE_NAME.sub(
            lambda name: figures[name.group(1)].written if name.group(1) in figures
            else name.group(0),
            prose
        )

    return answer.with_each_sentence(written_in)


def workings_that_make_no_sense(prose: str,
                                figures: Mapping[str, Figure]) -> list[tuple[str, str]]:
    """Each working a sentence asks for that works out to nothing, as written
    and with why, in the order it asks for them.

    Two of the reasons are this run's rather than the answer's: a difference
    below nothing and a division by nothing are read from `figures`. A working
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
            return Decimal(figure.given)


def _said_as_a_kind(name: str, kind: _Kind | None) -> str:
    return str(kind) if kind is not None else f"{{{name}}}, which cannot be worked with,"


def _worked_out(working: re.Match[str], figures: dict[str, Figure]) -> str | None:
    """A working as the page writes its result, or `None` where it has none.

    From each figure as the model was shown it rather than as it was measured,
    so the result never disagrees with the figures written beside it.
    """
    first, operation, second = working.groups()

    if (first not in figures or second not in figures
            or _why_it_makes_no_sense(first, operation, second, figures) is not None):
        return None

    kinds = (_kind_of(first, figures), _kind_of(second, figures))

    if kinds[0] is None or kinds[1] is None:
        return None

    return _WORKINGS[(kinds[0], operation, kinds[1])](figures[first], figures[second])


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


def span_in_words(hours: float) -> str:
    """A span as a reader says one: days, hours, minutes and seconds, naming
    only the units it has.

    Never a fraction of an hour. "0.10 hours" is six minutes a reader has to
    work out, and a model handed it either works it out or repeats the figure.
    Exact to the second, like every instant the model reads: what it is given
    is the measurement, not a rounding of it.
    """
    return _said_of_a_span(timedelta(hours=hours))


def _said_of_a_span(span: timedelta) -> str:
    """A span as `span_in_words` says one, from the span itself rather than a
    count of hours that cannot hold every second exactly."""
    seconds = span // timedelta(seconds=1)

    if seconds < 1:
        return "less than a second"

    days, seconds = divmod(seconds, 24 * 60 * 60)
    whole_hours, seconds = divmod(seconds, 60 * 60)
    minutes, seconds = divmod(seconds, 60)

    return " ".join(f"{count} {unit}{'s' if count != 1 else ''}"
                    for count, unit in ((days, "day"), (whole_hours, "hour"),
                                        (minutes, "minute"), (seconds, "second"))
                    if count)


def _the_words_of(text: str) -> Iterator[tuple[str, str | None]]:
    """Every stretch of the text in order, each with the figure it is - or
    `None` for the spaces between words and for every word that is no figure."""
    for part in re.split(r"(\s+)", text):
        word = part.strip(AROUND_A_WORD)
        yield part, word if word and is_a_figure(word) else None


def _as_the_alert_gave_it(figure: str) -> Figure:
    if _AN_INSTANT.fullmatch(figure):
        return Figure(given=figure, written=_as_a_reader_says(parse_iso(figure)))

    return Figure(given=figure, written=figure)


def _an_instant(at: datetime) -> Figure:
    return Figure(given=to_iso(at), written=_as_a_reader_says(at))


def _as_a_reader_says(at: datetime) -> str:
    """An instant as the page says one, to the second."""
    return f"{at.astimezone(UTC):%b %d, %Y, %H:%M:%S} UTC"


def _a_span(hours: float) -> Figure:
    said = span_in_words(hours)

    return Figure(given=said, written=said)


def _a_share(rate: float) -> Figure:
    said = f"{rate:.1%}"

    return Figure(given=said, written=said)


def _a_level(level: float) -> Figure:
    """A level plain, in whatever unit the paging rule watches - only the rule
    knows it - given as measured, and written as a person says it."""
    return Figure(given=f"{Decimal(str(level)).normalize():f}", written=_as_said(level))


def _as_said(level: float) -> str:
    """A level to three figures, the way a reader compares two levels - and
    never fewer than its whole part has, since "1230" reads as an exact count.
    Never in exponent form."""
    exact = Decimal(str(level))
    if exact == 0:
        return "0"

    places = max(_LEVEL_FIGURES - exact.adjusted() - 1, 0)
    rounded = exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)

    return f"{rounded.normalize():f}"
