"""A level said as a person says it: to three figures, and never fewer than
its whole part has.

One rule in one place, because the postmortem's prose and its impact cards
each write the series a paging rule watches, and a level written two ways is
two figures to a reader comparing them.

And in its unit, where the rule's panel or its metric's name says one - said the
one way both of them say it, a share of one as the percentage a reader reads.
"""

from __future__ import annotations

import pytest
from argus_core import level_given_in, level_said_in, said_as_a_level, said_as_a_share
from argus_testkit import Scenario, the_answer_was


@pytest.mark.unit
@pytest.mark.parametrize(("level", "said"), [
    (0.594083, "0.594"),
    (0.000123456, "0.000123"),
    (0.92, "0.92"),
    (1234.5, "1235"),
    (0.5943428571, "0.594"),
    (0.0, "0")
], ids=["a-ratio", "a-small-one", "already-short", "a-whole-number-and-a-half",
        "a-mean-of-several-minutes", "nothing"])
def test_a_level_is_said_to_three_figures_and_never_fewer_than_its_whole_part(
        level: float, said: str) -> None:
    # Six places of a ratio read as a precision nobody measured it to: three
    # figures are what a reader compares two levels by - and never fewer than
    # a whole number has, since "1230" reads as an exact count.
    Scenario() \
        .when(
            lambda: said_as_a_level(level)
        ) \
        .then(
            the_answer_was(said)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("level", "unit", "said"), [
    (600.0, "ms", "600 ms"),
    (0.6, "s", "0.6 s"),
    (0.899, "percentunit", "89.9%"),
    (0.4456789, "percentunit", "44.6%"),
    (12.5, "percent", "12.5%"),
    (2048.0, "bytes", "2048 bytes"),
    (3.0, "reqps", "3 reqps"),
    (600.0, None, "600")
], ids=["milliseconds", "seconds", "a-share-of-one", "a-share-to-three-figures",
        "already-a-percentage", "bytes", "a-unit-said-as-grafana-names-it", "no-unit"])
def test_a_level_is_said_in_its_unit(level: float, unit: str | None, said: str) -> None:
    # A bare number beside an alert that says "80%" is two scales on one page.
    # A share of one is said as the percentage, scaled exactly before it is cut
    # to three figures; a unit nothing named is no unit, rather than a guess.
    Scenario() \
        .when(
            lambda: level_said_in(level, unit)
        ) \
        .then(
            the_answer_was(said)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("rate", "said"), [
    (0.0102, "1.0%"),
    (0.284, "28.4%"),
    (0.0, "0.0%")
], ids=["a-baseline", "while-broken", "nothing"])
def test_a_share_of_requests_is_said_as_a_percentage_to_one_place(rate: float, said: str) -> None:
    # The error rate before the onset read 1.0% in the summary and 1.02% in the
    # card and the cause beside it, where the rule's series was the error rate
    # itself: one figure written two ways. A share is said one way, here.
    Scenario() \
        .when(
            lambda: said_as_a_share(rate)
        ) \
        .then(
            the_answer_was(said)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("level", "said"), [
    (float("inf"), "+Inf"),
    (float("-inf"), "-Inf"),
    (float("nan"), "NaN")
], ids=["infinity", "below-infinity", "not-a-number"])
def test_a_level_that_is_no_number_is_said_as_prometheus_writes_it(level: float,
                                                                   said: str) -> None:
    # Prometheus answers a ratio over nothing with NaN and one over nothing
    # but its numerator with +Inf, and a metrics page with such a minute on it
    # raised where it should have shown one. There are no figures to cut.
    Scenario() \
        .when(
            lambda: said_as_a_level(level)
        ) \
        .then(
            the_answer_was(said)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("level", "unit", "said"), [
    (float("inf"), "ms", "+Inf ms"),
    (float("nan"), "percentunit", "NaN%")
], ids=["in-its-unit", "as-a-share-of-one"])
def test_a_level_that_is_no_number_is_said_in_its_unit(level: float, unit: str,
                                                       said: str) -> None:
    Scenario() \
        .when(
            lambda: level_said_in(level, unit)
        ) \
        .then(
            the_answer_was(said)
        )


@pytest.mark.unit
def test_a_level_that_is_no_number_is_given_to_the_model_as_prometheus_writes_it() -> None:
    # Not `Infinity`, a spelling the model has seen nowhere in what it reads.
    Scenario() \
        .when(
            lambda: level_given_in(float("inf"), "ms")
        ) \
        .then(
            the_answer_was("+Inf ms")
        )


@pytest.mark.unit
def test_a_share_that_is_no_number_is_said_as_prometheus_writes_it() -> None:
    # Not `nan%`, and as a level that is a share of one says it: one share
    # written two ways is two to a reader.
    Scenario() \
        .when(
            lambda: said_as_a_share(float("nan"))
        ) \
        .then(
            the_answer_was("NaN%")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("level", "unit", "given"), [
    (0.4456789, "percentunit", "44.56789%"),
    (600.0, "ms", "600 ms"),
    (0.1 + 0.2, "s", "0.30000000000000004 s"),
    (600.0, None, "600")
], ids=["a-share-of-one", "milliseconds", "as-measured", "no-unit"])
def test_a_level_is_given_to_the_model_exactly_in_its_unit(level: float,
                                                           unit: str | None,
                                                           given: str) -> None:
    # What the model is handed is reformatted, never rounded: a share of one
    # moves its point two places and loses no digit of what was measured.
    Scenario() \
        .when(
            lambda: level_given_in(level, unit)
        ) \
        .then(
            the_answer_was(given)
        )
