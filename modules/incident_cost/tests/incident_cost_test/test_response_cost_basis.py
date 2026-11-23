"""How the response cost was arrived at, kept beside the figure.

The postmortem shows no pay: its readers are the people it would price. The
figure is priced for the executive synopsis, and a figure is only as honest as
the steps between the source and it - a working year the bands were divided
by, a band a title was priced at, a title nothing could price. Those steps are
what this says, for whoever is shown the figure.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from argus_testkit import Assertion, Scenario, all_of
from incident_cost.response_cost_basis import (
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
    response_cost_basis,
)
from incident_cost.sources import PayBand

from incident_cost_test.framework.builders import DONT_CARE_WORKING_YEAR, SOME_CURRENCY, Share

SOME_TITLE = "Senior Kuki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"
SOME_WORKING_YEAR_IN_HOURS = 2000.0
DONT_CARE_MINUTES = 30

SOME_BAND = PayBand(
    minimum=Decimal(60_000),
    midpoint=Decimal(120_000),
    maximum=Decimal(240_000),
    currency=SOME_CURRENCY
)


@pytest.mark.unit
def test_a_published_cost_discloses_the_working_year_and_the_bands_it_used() -> None:
    # Both halves of the arithmetic, because neither is measured. The working
    # year is a convention somebody configured, and the band is a range
    # collapsed to a point - a reader who cannot see either is being asked to
    # take the figure on trust.
    Scenario() \
        .given(
            a_response_priced := [Share(title=SOME_TITLE, minutes=DONT_CARE_MINUTES)]
        ) \
        .when(
            lambda: response_cost_basis(a_response_priced,
                                        {SOME_TITLE: SOME_BAND},
                                        SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(
            all_of(
                _names_a_line_mentioning(WORKING_YEAR_ASSUMPTION_LABEL,
                                         str(int(SOME_WORKING_YEAR_IN_HOURS))),
                _names_a_line_mentioning(PAY_BAND_ASSUMPTION_LABEL, SOME_TITLE)
            )
        )


@pytest.mark.unit
def test_a_published_cost_names_no_figure_of_the_band_it_used() -> None:
    # Whoever is shown the figure is shown that a midpoint was used, not the
    # band's own figures: a band is not a reader's to be handed.
    Scenario() \
        .given(
            a_response_priced := [Share(title=SOME_TITLE, minutes=DONT_CARE_MINUTES)]
        ) \
        .when(
            lambda: response_cost_basis(a_response_priced,
                                        {SOME_TITLE: SOME_BAND},
                                        SOME_WORKING_YEAR_IN_HOURS)
        ) \
        .then(
            all_of(
                _names_a_line_mentioning(PAY_BAND_ASSUMPTION_LABEL, "midpoint"),
                _says_nothing_about(str(SOME_BAND.minimum)),
                _says_nothing_about(str(SOME_BAND.midpoint)),
                _says_nothing_about(str(SOME_BAND.maximum))
            )
        )


@pytest.mark.unit
def test_an_unpriced_title_is_named_where_no_cost_could_be_published() -> None:
    # An absent figure is only honest while it can say which title left it
    # absent. "No cost available" with nothing beside it reads as a bug in
    # Argus rather than as a band nobody configured.
    Scenario() \
        .given(
            a_response_nobody_could_price := [Share(title=SOME_TITLE_NO_BAND_COVERS,
                                                    minutes=DONT_CARE_MINUTES)]
        ) \
        .when(
            lambda: response_cost_basis(a_response_nobody_could_price,
                                        {SOME_TITLE: SOME_BAND},
                                        DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names_a_line_mentioning(UNPRICED_TITLE_ASSUMPTION_LABEL,
                                     SOME_TITLE_NO_BAND_COVERS)
        )


@pytest.mark.unit
def test_a_responder_with_no_title_is_said_to_have_none() -> None:
    # "no pay band covers [(no title recorded)]" blames a band for a title
    # nobody recorded; what stopped the figure is the missing title.
    Scenario() \
        .given(
            a_response_nobody_could_price := [Share(title=None, minutes=DONT_CARE_MINUTES)]
        ) \
        .when(
            lambda: response_cost_basis(a_response_nobody_could_price,
                                        {SOME_TITLE: SOME_BAND},
                                        DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names_a_line_mentioning(UNPRICED_TITLE_ASSUMPTION_LABEL,
                                     "no title was recorded for a responder, so no pay "
                                     "band could price them")
        )


@pytest.mark.unit
def test_bands_that_could_not_be_read_are_disclosed_where_somebody_responded() -> None:
    # Somebody spent the minutes and nothing could price them: the gap is the
    # source, and saying so keeps it from reading as nobody having responded.
    Scenario() \
        .given(
            a_response_no_band_could_be_read_for := [Share(title=SOME_TITLE,
                                                           minutes=DONT_CARE_MINUTES)]
        ) \
        .when(
            lambda: response_cost_basis(a_response_no_band_could_be_read_for,
                                        None,
                                        DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names(PAY_BANDS_UNAVAILABLE_ASSUMPTION)
        )


@pytest.mark.unit
def test_a_response_nobody_made_has_no_basis() -> None:
    # There is no response to price, so nothing to say of how it was priced -
    # not even that the bands could not be read.
    Scenario() \
        .when(
            lambda: response_cost_basis([], None, DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _is_empty()
        )


def _names(expected: str) -> Assertion[list[str]]:
    def assertion(basis: list[str]) -> bool:
        if not any(expected in stated for stated in basis):
            raise AssertionError(
                f"Expected a line of the basis mentioning [{expected}], got {basis}.")

        return True

    return assertion


def _names_a_line_mentioning(label: str, detail: str) -> Assertion[list[str]]:
    """One line carrying both the label and what it is about.

    Both in the same line rather than both somewhere in the list: a line that
    labelled one step and detailed another has disclosed neither.
    """
    def assertion(basis: list[str]) -> bool:
        if not any(label in stated and detail in stated for stated in basis):
            raise AssertionError(
                f"Expected a line of the basis mentioning [{label}] and [{detail}], "
                f"got {basis}.")

        return True

    return assertion


def _says_nothing_about(unexpected: str) -> Assertion[list[str]]:
    def assertion(basis: list[str]) -> bool:
        if any(unexpected in stated for stated in basis):
            raise AssertionError(
                f"Expected no line of the basis about [{unexpected}], got {basis}.")

        return True

    return assertion


def _is_empty() -> Assertion[list[str]]:
    def assertion(basis: list[str]) -> bool:
        if basis:
            raise AssertionError(f"Expected no basis, got {basis}.")

        return True

    return assertion
