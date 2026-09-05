from __future__ import annotations

from decimal import Decimal

import pytest
from agent_postmortem.responder_cost import ResponderCost, responder_cost, unpriced_titles
from agent_postmortem.sources import EngagedResponder, PayBand
from argus_testkit import Assertion, Scenario, all_of

"""What the response cost, out of minutes already measured and bands already
published.

The headline is the midpoint, because that is the figure a reader puts beside
the customer loss. The range is beside it, because a band is a range: the same
incident with the same people costs meaningfully more at the top of it, and a
midpoint published alone claims a precision the source does not have.

The numbers here are chosen to divide exactly. A working year of 2000 hours is
120,000 minutes, so a band of 120,000 a year is worth one unit a minute - and
an arithmetic slip shows up as a different figure rather than as a rounding
argument.
"""

MINUTES_PER_HOUR = 60
SOME_WORKING_YEAR_IN_HOURS = 2000.0
SOME_WORKING_YEAR_IN_MINUTES = Decimal(SOME_WORKING_YEAR_IN_HOURS) * MINUTES_PER_HOUR

SOME_TITLE = "Senior Kuki"
SOME_OTHER_TITLE = "Junior Buki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"


SOME_CURRENCY = "USD"

# 60,000 / 120,000 / 240,000 a year over a 120,000-minute year: half a unit, one
# unit and two units a minute.
SOME_BAND = PayBand(
    minimum=Decimal(60_000),
    midpoint=Decimal(120_000),
    maximum=Decimal(240_000),
    currency=SOME_CURRENCY
)

# Twice the first band at every point, so a figure built from one band applied
# to both responders is a different number rather than a coincidence.
SOME_OTHER_BAND = PayBand(
    minimum=Decimal(120_000),
    midpoint=Decimal(240_000),
    maximum=Decimal(480_000),
    currency=SOME_CURRENCY
)


@pytest.mark.unit
def test_a_responders_minutes_are_priced_at_their_bands() -> None:
    # One person, one band, and the two figures a document carries: what it
    # cost, and how much that figure could move without anybody being wrong.
    some_minutes = 30
    cost_at_midpoint = SOME_BAND.midpoint * some_minutes / SOME_WORKING_YEAR_IN_MINUTES
    cost_at_minimum = SOME_BAND.minimum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES
    cost_at_maximum = SOME_BAND.maximum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES
    an_engaged_responder = EngagedResponder(minutes=some_minutes, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_engaged_responder
        ) \
        .when(
            lambda: responder_cost(
                [an_engaged_responder],
                bands={SOME_TITLE: SOME_BAND},
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_cost_was(cost_at_midpoint),
            _the_range_was(cost_at_minimum, cost_at_maximum),
            _the_currency_was(SOME_CURRENCY)
        ))


@pytest.mark.unit
def test_two_responders_on_different_bands_are_priced_separately() -> None:
    # The reason the minutes arrive per person. One rate over the total would
    # charge a junior's hour at a senior's band, or the other way round, and
    # the total is the same either way - so only two different bands can tell
    # the arithmetic apart.
    some_minutes = 30
    some_other_minutes = 45
    cost_at_midpoint = (
        SOME_BAND.midpoint * some_minutes / SOME_WORKING_YEAR_IN_MINUTES
        + SOME_OTHER_BAND.midpoint * some_other_minutes / SOME_WORKING_YEAR_IN_MINUTES
    )
    cost_at_minimum = (
        SOME_BAND.minimum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES
        + SOME_OTHER_BAND.minimum * some_other_minutes / SOME_WORKING_YEAR_IN_MINUTES
    )
    cost_at_maximum = (
        SOME_BAND.maximum * some_minutes / SOME_WORKING_YEAR_IN_MINUTES
        + SOME_OTHER_BAND.maximum * some_other_minutes / SOME_WORKING_YEAR_IN_MINUTES
    )
    an_engaged_responder = EngagedResponder(
        minutes=some_minutes, job_title=SOME_TITLE)
    another_engaged_responder = EngagedResponder(
        minutes=some_other_minutes, job_title=SOME_OTHER_TITLE)

    Scenario() \
        .given(
            an_engaged_responder,
            another_engaged_responder
        ) \
        .when(
            lambda: responder_cost(
                [an_engaged_responder, another_engaged_responder],
                bands={SOME_TITLE: SOME_BAND, SOME_OTHER_TITLE: SOME_OTHER_BAND},
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_cost_was(cost_at_midpoint),
            _the_range_was(cost_at_minimum, cost_at_maximum)
        ))


@pytest.mark.unit
def test_an_incident_nobody_engaged_with_cost_nothing() -> None:
    # Zero, not absent. An incident that resolved with no person on it really
    # did cost nothing in people's time, and that is a measurement - the same
    # distinction the loss estimate makes between a window read and one that
    # could not be.
    Scenario() \
        .when(
            lambda: responder_cost(
                [],
                bands={SOME_TITLE: SOME_BAND},
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_cost_was(Decimal(0)),
            _the_range_was(Decimal(0), Decimal(0)),
            _the_currency_was(None)
        ))


@pytest.mark.unit
def test_one_title_no_band_covers_leaves_the_whole_figure_absent() -> None:
    # Not the priced responder's share on its own. A cost covering one of two
    # people is not a smaller cost, it is a wrong one - and it is wrong in the
    # direction that flatters the response, which is the one nobody questions.
    dont_care_minutes = 30
    a_priced_responder = EngagedResponder(
        minutes=dont_care_minutes, job_title=SOME_TITLE)
    a_responder_no_band_covers = EngagedResponder(
        minutes=dont_care_minutes, job_title=SOME_TITLE_NO_BAND_COVERS)

    Scenario() \
        .given(
            a_priced_responder,
            a_responder_no_band_covers
        ) \
        .when(
            lambda: responder_cost(
                [a_priced_responder, a_responder_no_band_covers],
                bands={SOME_TITLE: SOME_BAND},
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _nothing_was_priced()
        ))


@pytest.mark.unit
def test_the_title_no_band_covers_is_named() -> None:
    # An absent figure is only honest while the document can say which title
    # left it absent. "No cost available" with nothing beside it reads as a bug
    # in Argus rather than as a band nobody configured.
    dont_care_minutes = 30
    a_responder_no_band_covers = EngagedResponder(
        minutes=dont_care_minutes, job_title=SOME_TITLE_NO_BAND_COVERS)

    Scenario() \
        .given(
            a_responder_no_band_covers
        ) \
        .when(
            lambda: unpriced_titles(
                [a_responder_no_band_covers], bands={SOME_TITLE: SOME_BAND})
        ) \
        .then(all_of(
            _the_titles_that_could_not_be_priced_were([SOME_TITLE_NO_BAND_COVERS])
        ))


@pytest.mark.unit
def test_a_responder_the_source_held_no_title_for_leaves_the_figure_absent() -> None:
    # The case the on-call source really produces: a provider that would not
    # say what somebody was. They spent the minutes all the same, and no band
    # can match a title nobody knows - so the figure goes, exactly as it does
    # for a title no band covers. Pricing the rest would charge the incident
    # for one person and quietly not for the other.
    dont_care_minutes = 30
    a_responder_with_no_title = EngagedResponder(
        minutes=dont_care_minutes, job_title=None)

    Scenario() \
        .given(
            a_responder_with_no_title
        ) \
        .when(
            lambda: responder_cost(
                [a_responder_with_no_title],
                bands={SOME_TITLE: SOME_BAND},
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _nothing_was_priced()
        ))


@pytest.mark.unit
def test_a_responder_with_no_title_is_named_as_such_rather_than_omitted() -> None:
    # The document has to say why it published no cost, and "one responder's
    # title was not recorded" is a different sentence from "Principal Buki has
    # no band". A reason that omitted them entirely would read as a figure
    # missing for no reason.
    dont_care_minutes = 30
    a_responder_with_no_title = EngagedResponder(
        minutes=dont_care_minutes, job_title=None)

    Scenario() \
        .given(
            a_responder_with_no_title
        ) \
        .when(
            lambda: unpriced_titles(
                [a_responder_with_no_title], bands={SOME_TITLE: SOME_BAND})
        ) \
        .then(all_of(
            _some_title_was_reported_as_unrecorded()
        ))


@pytest.mark.unit
def test_two_responders_holding_the_same_title_are_both_paid_for() -> None:
    # A band is looked up by title, and two people can hold one. Pricing the
    # title once - deduplicating on the way to the bands, or keying the
    # responders by what they were - charges the incident for one of them and
    # halves a figure nobody would think to question.
    some_minutes = 30
    some_other_minutes = 45
    cost_at_midpoint = (
        SOME_BAND.midpoint * (some_minutes + some_other_minutes)
        / SOME_WORKING_YEAR_IN_MINUTES
    )
    a_responder = EngagedResponder(minutes=some_minutes, job_title=SOME_TITLE)
    another_responder_holding_the_same_title = EngagedResponder(
        minutes=some_other_minutes, job_title=SOME_TITLE)

    Scenario() \
        .given(
            a_responder,
            another_responder_holding_the_same_title
        ) \
        .when(
            lambda: responder_cost(
                [a_responder, another_responder_holding_the_same_title],
                bands={SOME_TITLE: SOME_BAND},
                working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(all_of(
            _the_cost_was(cost_at_midpoint)
        ))


@pytest.mark.unit
def test_the_working_year_a_band_is_divided_by_changes_the_figure() -> None:
    # The divisor is configuration, so it has to be honoured rather than
    # assumed. A shorter working year means each minute of it is worth more of
    # the same salary - and an implementation that hardcoded 2080 would pass
    # every other test in this file.
    some_minutes = 30
    some_shorter_working_year_in_hours = SOME_WORKING_YEAR_IN_HOURS / 2
    cost_over_a_shorter_year = (
        SOME_BAND.midpoint * some_minutes
        / (SOME_WORKING_YEAR_IN_MINUTES / 2)
    )
    an_engaged_responder = EngagedResponder(
        minutes=some_minutes, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_engaged_responder
        ) \
        .when(
            lambda: responder_cost(
                [an_engaged_responder],
                bands={SOME_TITLE: SOME_BAND},
                working_hours_a_year=some_shorter_working_year_in_hours)
        ) \
        .then(all_of(
            _the_cost_was(cost_over_a_shorter_year)
        ))


def _some_title_was_reported_as_unrecorded() -> Assertion[list[str]]:
    def assertion(named: list[str]) -> bool:
        if len(named) != 1:
            raise AssertionError(
                f"Expected exactly one unpriced responder to be named, got "
                f"{named}.")

        return True

    return assertion


def _the_cost_was(expected: Decimal) -> Assertion[ResponderCost]:
    def assertion(cost: ResponderCost) -> bool:
        if cost is None:
            raise AssertionError(
                f"Expected a cost of [{expected}], but the response was not "
                f"priced at all.")

        if cost.midpoint != expected:
            raise AssertionError(
                f"Expected a cost of [{expected}], got [{cost.midpoint}].")

        return True

    return assertion


def _the_range_was(minimum: Decimal, maximum: Decimal) -> Assertion[ResponderCost]:
    def assertion(cost: ResponderCost) -> bool:
        if (cost.minimum, cost.maximum) != (minimum, maximum):
            raise AssertionError(
                f"Expected the cost to range from [{minimum}] to [{maximum}], "
                f"got [{cost.minimum}] to [{cost.maximum}].")

        return True

    return assertion


def _the_currency_was(expected: str | None) -> Assertion[ResponderCost]:
    def assertion(cost: ResponderCost) -> bool:
        if cost.currency != expected:
            raise AssertionError(
                f"Expected the cost in [{expected}], got [{cost.currency}].")

        return True

    return assertion


def _nothing_was_priced() -> Assertion[ResponderCost | None]:
    def assertion(cost: ResponderCost | None) -> bool:
        if cost is not None:
            raise AssertionError(
                f"Expected no cost at all, because one responder's title has "
                f"no band, but got [{cost.midpoint}].")

        return True

    return assertion


def _the_titles_that_could_not_be_priced_were(expected: list[str]) -> Assertion[list[str]]:
    def assertion(named: list[str]) -> bool:
        if named != expected:
            raise AssertionError(
                f"Expected the unpriced titles to be {expected}, got {named}.")

        return True

    return assertion
