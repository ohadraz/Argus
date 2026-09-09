from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from agent_postmortem import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
    ONSET_UNKNOWN_ASSUMPTION,
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
)
from agent_postmortem.assumptions import assumptions_of
from agent_postmortem.prompting import ASSUMPTIONS_FIELD
from agent_postmortem.responder_cost import ResponderCost
from agent_postmortem.sources import EngagedResponder, PayBand, RateTable
from argus_testkit import Assertion, Scenario, all_of

from agent_postmortem_test.framework.builders import (
    DONT_CARE_BASELINE_REVENUE,
    DONT_CARE_WORKING_YEAR,
    ONSET,
    SOME_CURRENCY,
    SOME_OTHER_CURRENCY,
    SOME_UNPRICED_CURRENCY,
    a_measured_incident,
    an_engagement_of,
)

"""What the document admits to having assumed rather than measured.

Two kinds of line, arriving from opposite directions. One is the model's own:
asked what else a reader should know it took rather than measured, it answers
in prose, and that answer has to reach the page - dropped, it would leave a
document claiming more certainty than the thing that wrote it had.

The other is Argus's, and it is here because a figure is only as honest as the
steps between the source and the page. A rate applied, a band a title was
priced at, a working year the bands were divided by: none of those is a
measurement, and a reader who cannot see them is being asked to take the
figures on trust.

An absence gets a line too, and it is the half most worth testing. A figure
that is missing and a figure that is zero look identical on a page unless the
document says which it is - and each absence has its own sentence, because
"nobody responded" and "the on-call system could not be reached" are different
findings that would otherwise leave the same blank.

Nothing here reads a source. Everything was read while the incident was being
measured, so this takes a measured incident and the one setting the figures
were produced under, and turns them into sentences.
"""

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

# An answer the model gave that says nothing about assumptions, for the tests
# whose subject is one of Argus's own disclosures.
DONT_CARE_ANSWER: dict[str, Any] = {}

# A cost that was published, for the tests about what a published one has to
# disclose. Its figures are never read - what is under test is the sentences
# that accompany them.
DONT_CARE_PUBLISHED_COST = ResponderCost(midpoint=Decimal(1),
                                         minimum=Decimal(1),
                                         maximum=Decimal(1),
                                         currency=SOME_CURRENCY)


@pytest.mark.unit
def test_what_the_model_says_it_assumed_is_carried_through() -> None:
    # The model is asked for anything else it took rather than measured, and
    # what it answers has to reach the page. Dropped, it would leave a document
    # claiming more certainty than the thing that wrote it had.
    some_assumption = "the log lines shown were the whole of the failing traffic"

    Scenario() \
        .given(
            an_answer := {ASSUMPTIONS_FIELD: [some_assumption]}
        ) \
        .when(
            lambda: assumptions_of(an_answer,
                                   a_measured_incident(),
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names(some_assumption)
        )


@pytest.mark.unit
def test_a_published_cost_discloses_the_working_year_and_the_bands_it_used() -> None:
    # Both halves of the arithmetic, because neither is measured. The working
    # year is a convention somebody configured, and the band is a range this
    # document collapsed to a point - a reader who cannot see either is being
    # asked to take the figure on trust.
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_incident_whose_response_was_priced := a_measured_incident(
                engaged=an_engagement_of([a_responder]),
                bands={SOME_TITLE: SOME_BAND},
                cost=DONT_CARE_PUBLISHED_COST)
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_whose_response_was_priced,
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
def test_a_title_two_people_held_is_disclosed_once() -> None:
    # Two people can hold one title, and both are paid for - but a reader
    # checking the figure needs the band once. The same sentence twice reads as
    # a document that priced something twice.
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
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_two_people_of_one_title_responded_to,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names_a_line_mentioning_exactly_once(PAY_BAND_ASSUMPTION_LABEL, SOME_TITLE)
        )


@pytest.mark.unit
def test_an_unpriced_title_is_named_where_no_cost_could_be_published() -> None:
    # An absent figure is only honest while the document can say which title
    # left it absent. "No cost available" with nothing beside it reads as a bug
    # in Argus rather than as a band nobody configured.
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
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_nobody_could_price,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names_a_line_mentioning(UNPRICED_TITLE_ASSUMPTION_LABEL,
                                     SOME_TITLE_NO_BAND_COVERS)
        )


@pytest.mark.unit
def test_every_conversion_is_disclosed_with_its_rate_and_the_day_it_was_published() -> None:
    # The only step between the money the provider reported and the figure
    # published. Rates move and an estimate is written afterwards, so a reader
    # checking the arithmetic needs both the number and which day's number it
    # was - a figure converted at a rate nobody can see is a figure nobody can
    # check.
    some_rate = Decimal("0.80")
    some_rate_date = ONSET.date()

    Scenario() \
        .given(
            an_incident_costed_from_money_taken_abroad := a_measured_incident(
                takings={SOME_OTHER_CURRENCY: Decimal("800")},
                rates=RateTable(base=SOME_CURRENCY,
                                on=some_rate_date,
                                per_unit={SOME_OTHER_CURRENCY: some_rate}))
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_costed_from_money_taken_abroad,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            all_of(
                _names_a_line_mentioning(EXCHANGE_RATE_ASSUMPTION_LABEL, str(some_rate)),
                _names_a_line_mentioning(EXCHANGE_RATE_ASSUMPTION_LABEL,
                                         some_rate_date.isoformat())
            )
        )


@pytest.mark.unit
def test_money_taken_in_the_reporting_currency_discloses_no_conversion() -> None:
    # A window needing no conversion has no assumption to disclose. A document
    # about a shop trading in dollars must not recite thirty rates it never
    # used, or the disclosures stop being read at all.
    Scenario() \
        .given(
            an_incident_costed_from_money_taken_at_home := a_measured_incident(
                takings={SOME_CURRENCY: DONT_CARE_BASELINE_REVENUE})
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_costed_from_money_taken_at_home,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _says_nothing_about(EXCHANGE_RATE_ASSUMPTION_LABEL)
        )


@pytest.mark.unit
def test_a_currency_left_out_of_the_figure_is_named_with_the_reason() -> None:
    # The figure covers what could be converted, so the document has to say
    # what it does not cover. Silently dropping the rest would publish a number
    # that looks like all the money and is not.
    Scenario() \
        .given(
            an_incident_whose_figure_is_partial := a_measured_incident(
                left_out=[SOME_UNPRICED_CURRENCY])
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_whose_figure_is_partial,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names_a_line_mentioning(EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
                                     SOME_UNPRICED_CURRENCY)
        )


@pytest.mark.unit
def test_an_incident_with_no_onset_says_so() -> None:
    # The document is still dated, from the alert, and the alert is late by
    # however long the rule took to trip. A reader comparing this incident's
    # duration with another's is comparing two different measurements unless
    # the page says which one this is.
    Scenario() \
        .given(
            an_incident_nothing_measured_an_onset_for := a_measured_incident(
                onset_at=None)
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_nothing_measured_an_onset_for,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names(ONSET_UNKNOWN_ASSUMPTION)
        )


@pytest.mark.unit
def test_a_revenue_source_that_could_not_be_read_says_so() -> None:
    # Otherwise the document carries a blank where its headline figure goes,
    # and a blank reads as nothing having been lost.
    Scenario() \
        .given(
            an_incident_nobody_could_cost := a_measured_incident(
                baseline_revenue=None)
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_nobody_could_cost,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names(REVENUE_UNAVAILABLE_ASSUMPTION)
        )


@pytest.mark.unit
def test_an_engagement_source_that_could_not_be_read_says_so() -> None:
    # An unanswered question rather than an incident nobody worked on. The two
    # leave the same blank, and only one of them is a measurement.
    Scenario() \
        .given(
            an_incident_nobody_could_say_who_worked_on := a_measured_incident(
                engaged=None)
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_nobody_could_say_who_worked_on,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
        )


@pytest.mark.unit
def test_an_incident_nobody_responded_to_apologises_for_nothing() -> None:
    # The case the distinction exists for. A source that answered "nobody" has
    # measured something: Argus handled it alone. That must not carry the same
    # sentence as a source nobody could reach.
    Scenario() \
        .given(
            an_incident_argus_handled_alone := a_measured_incident(
                engaged=an_engagement_of([]))
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_argus_handled_alone,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _says_nothing_about(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
        )


@pytest.mark.unit
def test_bands_that_could_not_be_read_are_disclosed_where_somebody_responded() -> None:
    # Two absences with one consequence, and they are not the same sentence: a
    # response nobody could measure is already disclosed as such, and adding
    # "no pay bands either" to it would apologise twice for one gap.
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_incident_whose_responders_could_not_be_priced := a_measured_incident(
                engaged=an_engagement_of([a_responder]),
                bands=None,
                cost=None)
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_whose_responders_could_not_be_priced,
                                   DONT_CARE_WORKING_YEAR)
        ) \
        .then(
            _names(PAY_BANDS_UNAVAILABLE_ASSUMPTION)
        )


def _names(expected: str) -> Assertion[list[str]]:
    def assertion(assumptions: list[str]) -> bool:
        if not any(expected in stated for stated in assumptions):
            raise AssertionError(
                f"expected an assumption mentioning [{expected}], got {assumptions}")

        return True

    return assertion


def _names_a_line_mentioning(label: str, detail: str) -> Assertion[list[str]]:
    """One line carrying both the label and what it is about.

    Both in the same line rather than both somewhere in the list: a disclosure
    that labelled one assumption and detailed another has disclosed neither.
    """
    def assertion(assumptions: list[str]) -> bool:
        if not any(label in stated and detail in stated for stated in assumptions):
            raise AssertionError(
                f"expected an assumption mentioning [{label}] and [{detail}], "
                f"got {assumptions}")

        return True

    return assertion


def _names_a_line_mentioning_exactly_once(label: str,
                                          detail: str) -> Assertion[list[str]]:
    def assertion(assumptions: list[str]) -> bool:
        said = [stated for stated in assumptions
                if label in stated and detail in stated]

        if len(said) != 1:
            raise AssertionError(
                f"expected [{label}] to mention [{detail}] exactly once, got {said}")

        return True

    return assertion


def _says_nothing_about(unexpected: str) -> Assertion[list[str]]:
    def assertion(assumptions: list[str]) -> bool:
        if any(unexpected in stated for stated in assumptions):
            raise AssertionError(
                f"expected no assumption about [{unexpected}], got {assumptions}")

        return True

    return assertion
