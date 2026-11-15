"""A level said as a person says it: to three figures, and never fewer than
its whole part has.

One rule in one place, because the postmortem's prose and its impact cards
each write the series a paging rule watches, and a level written two ways is
two figures to a reader comparing them.

And in its unit, where the rule's panel or its metric's name says one. A unit
is named as Grafana names it, and two of Grafana's are percentages: a share of
one, which is said moved two places so it reads as the alert that pages on it
reads, and a percentage already. Any other is written after the number as
Grafana spells it; none is no unit, never a guess at one.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

# How many figures a level is written to, as a reader compares two.
_LEVEL_FIGURES: Final = 3

# Grafana's unit ids for a percentage: of one, and of a hundred.
PERCENT_OF_ONE_UNIT: Final = "percentunit"
PERCENT_UNIT: Final = "percent"
_PERCENT_SIGN: Final = "%"
_A_HUNDRED: Final = Decimal(100)

# Grafana's unit id for milliseconds, which a latency is measured in.
MILLISECONDS_UNIT: Final = "ms"

# A reading that is no number, as Prometheus writes one: its arithmetic is IEEE
# 754's, so 0 / 0 answers NaN and 3 / 0 answers +Inf.
_POSITIVE_INFINITY: Final = "+Inf"
_NEGATIVE_INFINITY: Final = "-Inf"
_NOT_A_NUMBER: Final = "NaN"


def said_as_a_level(level: float) -> str:
    """A level to three figures, the way a reader compares two levels - and
    never fewer than its whole part has, since "1230" reads as an exact count.
    Never in exponent form."""
    return _to_three_figures(Decimal(str(level)))


def said_as_a_share(rate: float) -> str:
    """A share of requests as the percentage it is, to one place - the error
    rate's own way, and a series that is the error rate's too, so one figure
    is never written two ways on one page."""
    exact = Decimal(str(rate))
    if not exact.is_finite():
        return f"{_plainly(exact)}{_PERCENT_SIGN}"

    return f"{rate:.1%}"


def level_said_in(level: float, unit: str | None) -> str:
    """A level to three figures, in its unit - a share of one as the
    percentage it is, scaled exactly before it is cut."""
    exact = Decimal(str(level))

    if unit == PERCENT_OF_ONE_UNIT:
        return f"{_to_three_figures(exact * _A_HUNDRED)}{_PERCENT_SIGN}"

    return _in(_to_three_figures(exact), unit)


def level_given_in(level: float, unit: str | None) -> str:
    """A level as measured, in its unit: reformatted, never rounded - a share
    of one moves its point two places and loses no digit."""
    exact = Decimal(str(level))

    if unit == PERCENT_OF_ONE_UNIT:
        return f"{_plainly(exact * _A_HUNDRED)}{_PERCENT_SIGN}"

    return _in(_plainly(exact), unit)


def _in(number: str, unit: str | None) -> str:
    if unit is None:
        return number

    if unit == PERCENT_UNIT:
        return f"{number}{_PERCENT_SIGN}"

    return f"{number} {unit}"


def _to_three_figures(exact: Decimal) -> str:
    """Cut to three figures - a reading that is no number is said as it came,
    since there are no figures to cut."""
    if exact == 0:
        return "0"

    if not exact.is_finite():
        return _plainly(exact)

    places = max(_LEVEL_FIGURES - exact.adjusted() - 1, 0)
    rounded = exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)

    return _plainly(rounded)


def _plainly(exact: Decimal) -> str:
    """Never in exponent form, and with no trailing zeros - and a reading that
    is no number as Prometheus writes it, never as `Infinity`."""
    if exact.is_nan():
        return _NOT_A_NUMBER

    if exact.is_infinite():
        return _POSITIVE_INFINITY if exact > 0 else _NEGATIVE_INFINITY

    return f"{exact.normalize():f}"
