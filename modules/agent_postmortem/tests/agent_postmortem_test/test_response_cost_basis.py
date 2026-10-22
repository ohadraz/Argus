"""How the response cost was arrived at, kept beside the figure and never shown.

The postmortem shows no pay: its readers are the people it would price. The
figure is still computed and stored for the executive report, and a figure is
only as honest as the steps between the source and it - a working year the
bands were divided by, a band a title was priced at, a title nothing could
price. Those steps are what this says, for whoever is shown the figure.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from agent_postmortem import (
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
)
from agent_postmortem.responder_cost import ResponderCost
from agent_postmortem.response_cost_basis import response_cost_basis
from agent_postmortem.sources import EngagedResponder, PayBand
from argus_testkit import Assertion, Scenario, all_of

from agent_postmortem_test.framework.builders import (
    DONT_CARE_WORKING_YEAR,
    SOME_CURRENCY,
    a_measured_incident,
    an_engagement_of,
)

SOME_TITLE = "Senior Kuki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"
SOME_WORKING_YEAR_IN_HOURS = 2000.0
SOME_ENGAGED_MINUTES = 30

SOME_BAND = PayBand(
    minimum=Decimal(60_000),
    midpoint=Decimal(120_000),
    maximum=Decimal(240_000),
    currency=SOME_CURRENCY
)

# A cost that was published, for the tests about what a published one has to
# disclose. Its figures are never read - what is under test is the sentences
# that accompany them.
DONT_CARE_PUBLISHED_COST = ResponderCost(midpoint=Decimal(1),
                                         minimum=Decimal(1),
                                         maximum=Decimal(1),
                                         currency=SOME_CURRENCY)


@pytest.mark.unit
def test_a_published_cost_discloses_the_working_year_and_the_bands_it_used() -> None:
    # Both halves of the arithmetic, because neither is measured. The working
    # year is a convention somebody configured, and the band is a range
    # collapsed to a point - a reader who cannot see either is being asked to
    # take the figure on trust.
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_incident_whose_response_was_priced := a_measured_incident(
                engaged=an_engagement_of([a_responder]),
                bands={SOME_TITLE: SOME_BAND},
                cost=DONT_CARE_PUBLISHED_COST)
        ) \
        .when(
            lambda: response_cost_basis(an_incident_whose_response_was_priced,
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
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_incident_whose_response_was_priced := a_measured_incident(
                engaged=an_engagement_of([a_responder]),
                bands={SOME_TITLE: SOME_BAND},
                cost=DONT_CARE_PUBLISHED_COST)
        ) \
        .when(
            lambda: response_cost_basis(an_incident_whose_response_was_priced,
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
def test_a_title_two_people_held_is_disclosed_once() -> None:
    # Two people can hold one title, and both are paid for - but a reader
    # checking the figure needs the band once. The same sentence twice reads as
    # a figure that priced something twice.
    two_responders_holding_one_title = [
        EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE),
        EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)
    ]

    Scenario() \
        .given(
            an_incident_two_people_of_one_title_responded_to := a_measured_incident(
                engaged=an_engagement_of(two_responders_holding_one_title),
                bands={SOME_TITLE: SOME_BAND},
                cost=DONT_CARE_PUBLISHED_COST)
        ) \
        .when(
            lambda: response_cost_basis(an_incident_two_people_of_one_title_responded_to,
                                        DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names_a_line_mentioning_exactly_once(PAY_BAND_ASSUMPTION_LABEL, SOME_TITLE)
        )


@pytest.mark.unit
def test_an_unpriced_title_is_named_where_no_cost_could_be_published() -> None:
    # An absent figure is only honest while it can say which title left it
    # absent. "No cost available" with nothing beside it reads as a bug in
    # Argus rather than as a band nobody configured.
    a_responder_no_band_covers = EngagedResponder(minutes=SOME_ENGAGED_MINUTES,
                                                  job_title=SOME_TITLE_NO_BAND_COVERS)

    Scenario() \
        .given(
            an_incident_nobody_could_price := a_measured_incident(
                engaged=an_engagement_of([a_responder_no_band_covers]),
                bands={SOME_TITLE: SOME_BAND},
                cost=None)
        ) \
        .when(
            lambda: response_cost_basis(an_incident_nobody_could_price, DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names_a_line_mentioning(UNPRICED_TITLE_ASSUMPTION_LABEL,
                                     SOME_TITLE_NO_BAND_COVERS)
        )


@pytest.mark.unit
def test_a_responder_with_no_title_is_said_to_have_none() -> None:
    # "no pay band covers [(no title recorded)]" blames a band for a title
    # nobody recorded; what stopped the figure is the missing title.
    a_responder_with_no_title = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=None)

    Scenario() \
        .given(
            an_incident_nobody_could_price := a_measured_incident(
                engaged=an_engagement_of([a_responder_with_no_title]),
                bands={SOME_TITLE: SOME_BAND},
                cost=None)
        ) \
        .when(
            lambda: response_cost_basis(an_incident_nobody_could_price, DONT_CARE_WORKING_YEAR)
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
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_incident_whose_responders_could_not_be_priced := a_measured_incident(
                engaged=an_engagement_of([a_responder]),
                bands=None,
                cost=None)
        ) \
        .when(
            lambda: response_cost_basis(an_incident_whose_responders_could_not_be_priced,
                                        DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names(PAY_BANDS_UNAVAILABLE_ASSUMPTION)
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


def _names_a_line_mentioning_exactly_once(label: str,
                                          detail: str) -> Assertion[list[str]]:
    def assertion(basis: list[str]) -> bool:
        said = [stated for stated in basis if label in stated and detail in stated]

        if len(said) != 1:
            raise AssertionError(
                f"Expected [{label}] to mention [{detail}] exactly once, got {said}.")

        return True

    return assertion


def _says_nothing_about(unexpected: str) -> Assertion[list[str]]:
    def assertion(basis: list[str]) -> bool:
        if any(unexpected in stated for stated in basis):
            raise AssertionError(
                f"Expected no line of the basis about [{unexpected}], got {basis}.")

        return True

    return assertion
