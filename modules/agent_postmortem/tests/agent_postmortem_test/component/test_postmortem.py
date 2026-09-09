from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from agent_postmortem import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    ONSET_UNKNOWN_ASSUMPTION,
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
)
from agent_postmortem.prompting import ROOT_CAUSE_FIELD
from agent_postmortem.sources import EngagedResponder, PayBand, Revenue
from argus_testkit import Scenario, all_of

from agent_postmortem_test.framework.assertions import (
    discloses_an_assumption_mentioning,
    discloses_an_assumption_naming,
    discloses_no_assumption_about,
    discloses_the_assumption,
    estimates_a_loss_of,
    estimates_nothing,
    is_marked_complete,
    is_marked_incomplete,
    reports_a_responder_cost_of,
    reports_engineer_minutes,
    reports_engineer_minutes_across,
    reports_executive_summary,
    reports_no_responder_cost,
    reports_root_cause,
    reports_the_titles,
    reports_tokens_spent,
    states_the_estimate_is_in,
)
from agent_postmortem_test.framework.builders import (
    ENDED_AT,
    ONSET,
    SOME_CURRENCY,
    SOME_OTHER_CURRENCY,
    a_band_source_pricing,
    a_band_source_that_cannot_answer,
    a_model_answering,
    a_model_answering_in_prose_then,
    a_postmortem_written_with,
    a_revenue_source_that_cannot_answer,
    an_answer_without,
    an_engagement_source_reporting,
    an_engagement_source_reporting_each,
    an_engagement_source_that_cannot_answer,
    an_evidence_bundle,
    rates_published,
    revenue_that_was,
    some_sources,
)

"""The whole agent, end to end, with nothing faked but its sources and the model.

Every collaborator inside runs for real: the incident is measured, the model is
asked, the disclosures are written, and the three land on one document. That is
what makes this a component test rather than a unit one, and it is the only
place the arithmetic is asserted against an actual page.

The unit suites each say what one module does, and every one of them would keep
passing if `writing` put the minimum where the midpoint goes, asked the model
about the wrong incident's figures, or disclosed a working year the cost was not
computed under. The cases here are chosen for what spans two modules or more:
money converted in one and disclosed in another, an absence that has to travel
from a source through a measurement to a sentence, and an answer refused twice
that still has to produce a document.

The numbers are chosen so each figure can only come out right one way. The shop
takes 1200 an hour when it is well, the incident ran half an hour from its
onset, and 100 came in while it was broken - so a loss of 500 is the only
arithmetic that lands, and 600 or 400 would each name the mistake that produced
it.
"""

SOME_CALM_HOURLY_REVENUE = 1_200
SOME_REVENUE_DURING_THE_INCIDENT = Decimal("100.00")

SOME_TITLE = "Senior Kuki"
SOME_TITLE_NO_BAND_COVERS = "Principal Buki"
SOME_ENGAGED_MINUTES = 30

# A 2000-hour year is 120,000 minutes, so a midpoint of 120,000 is worth one
# unit a minute and an arithmetic slip shows as a different figure rather than
# as a rounding argument.
SOME_WORKING_YEAR_IN_HOURS = 2000.0
SOME_WORKING_YEAR_IN_MINUTES = Decimal(120_000)

SOME_BAND = PayBand(
    minimum=Decimal(60_000),
    midpoint=Decimal(120_000),
    maximum=Decimal(240_000),
    currency=SOME_CURRENCY
)


@pytest.mark.component
def test_a_postmortem_reports_the_model_s_prose_and_its_own_arithmetic() -> None:
    # The shape of the whole thing, fixed before any of its parts are worth
    # arguing about: what the agent is handed, what it asks for, and what comes
    # back on one page. The minutes are person-minutes as the source answers
    # them - two people, their spans already added - because a document that
    # multiplied by the count again would charge every minute to everybody.
    some_engaged_person_minutes = 25
    some_responders = 2
    some_root_cause = "the checkout fallback was disabled by a flag toggle at 12:04"
    some_summary = "Checkout failed for half an hour after a flag change; reverted."
    some_tokens_spent = 48_120
    expected_loss = (
        Decimal(SOME_CALM_HOURLY_REVENUE) * Decimal(str(_hours_between(ONSET, ENDED_AT)))
        - SOME_REVENUE_DURING_THE_INCIDENT
    )

    Scenario() \
        .given(
            evidence := an_evidence_bundle(tokens_spent=some_tokens_spent)
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering(root_cause=some_root_cause,
                                      executive_summary=some_summary),
                sources=some_sources(
                    revenue=_takings_that_were_normal_until_the_onset(),
                    engagement=an_engagement_source_reporting(
                        minutes=some_engaged_person_minutes,
                        responders=some_responders)))
        ) \
        .then(
            all_of(
                reports_root_cause(some_root_cause),
                reports_executive_summary(some_summary),
                estimates_a_loss_of(expected_loss),
                states_the_estimate_is_in(SOME_CURRENCY),
                reports_engineer_minutes_across(minutes=some_engaged_person_minutes,
                                                responders=some_responders),
                reports_tokens_spent(some_tokens_spent),
                is_marked_complete()
            )
        )


@pytest.mark.component
def test_money_taken_abroad_is_converted_on_the_page_and_disclosed_beside_it() -> None:
    # Two modules meeting. The conversion happens while the incident is
    # measured and the rate is disclosed while the assumptions are written, so
    # only a whole document can show that the figure a reader sees and the rate
    # they are told it was converted at are the same conversion.
    some_calm_hourly_revenue_abroad = 800
    some_revenue_abroad_during_the_incident = Decimal("200.00")
    some_rate = Decimal("0.80")
    some_rate_date = ONSET.date()
    expected_loss = (
        Decimal(some_calm_hourly_revenue_abroad) / some_rate
        * Decimal(str(_hours_between(ONSET, ENDED_AT)))
        - some_revenue_abroad_during_the_incident / some_rate
    )

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering(),
                sources=some_sources(
                    revenue=revenue_that_was(
                        per_hour={
                            SOME_OTHER_CURRENCY: some_calm_hourly_revenue_abroad
                        },
                        until=ONSET,
                        and_then={
                            SOME_OTHER_CURRENCY: some_revenue_abroad_during_the_incident
                        }),
                    rates=rates_published(on=some_rate_date,
                                          per_unit={SOME_OTHER_CURRENCY: some_rate},
                                          base=SOME_CURRENCY)))
        ) \
        .then(
            all_of(
                estimates_a_loss_of(expected_loss),
                states_the_estimate_is_in(SOME_CURRENCY),
                discloses_an_assumption_naming(EXCHANGE_RATE_ASSUMPTION_LABEL),
                discloses_an_assumption_naming(str(some_rate)),
                discloses_an_assumption_naming(some_rate_date.isoformat())
            )
        )


@pytest.mark.component
def test_a_revenue_source_that_cannot_be_read_leaves_the_page_saying_why() -> None:
    # The absence travelling the whole way: a port that answered nothing, a
    # measurement that stayed absent rather than becoming zero, and a sentence
    # on the page saying which question went unanswered. Any one of the three
    # losing it produces a document telling an executive the outage was free.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering(),
                sources=some_sources(revenue=a_revenue_source_that_cannot_answer()))
        ) \
        .then(
            all_of(
                estimates_nothing(),
                discloses_the_assumption(REVENUE_UNAVAILABLE_ASSUMPTION)
            )
        )


@pytest.mark.component
def test_an_incident_with_no_onset_is_dated_from_the_alert_and_says_so() -> None:
    # No onset means no measured incident to attribute a loss to, and the
    # document has to be honest about which instant it was dated from - the
    # alert is late by however long the rule took to trip.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None)
        ) \
        .when(
            lambda: a_postmortem_written_with(evidence, llm=a_model_answering())
        ) \
        .then(
            all_of(
                estimates_nothing(),
                discloses_the_assumption(ONSET_UNKNOWN_ASSUMPTION)
            )
        )


@pytest.mark.component
def test_an_engagement_source_that_cannot_be_read_apologises_on_the_page() -> None:
    # An unanswered question rather than an incident nobody worked on. The two
    # leave the same blank where the minutes go, and the sentence beside it is
    # the only thing telling a reader which one this was.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering(),
                sources=some_sources(
                    engagement=an_engagement_source_that_cannot_answer()))
        ) \
        .then(
            discloses_the_assumption(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
        )


@pytest.mark.component
def test_an_incident_nobody_responded_to_apologises_for_nothing() -> None:
    # The other half of the same distinction, and the reason it is worth a page
    # of its own. A source that answered "nobody" measured something: Argus
    # handled it alone. Zero minutes, and no apology beside them.
    nobody = 0

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering(),
                sources=some_sources(
                    engagement=an_engagement_source_reporting(minutes=nobody,
                                                              responders=nobody)))
        ) \
        .then(
            all_of(
                reports_engineer_minutes(nobody),
                discloses_no_assumption_about(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
            )
        )


@pytest.mark.component
def test_the_response_is_priced_on_the_page_and_the_arithmetic_disclosed() -> None:
    # The second cost, all the way through: minutes from one port, bands from
    # another, priced while the incident is measured and explained while the
    # assumptions are written. The working year and the band have to be the
    # ones the figure beside them was computed from.
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)
    cost_at_midpoint = (SOME_BAND.midpoint * SOME_ENGAGED_MINUTES
                        / SOME_WORKING_YEAR_IN_MINUTES)

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering(),
                sources=some_sources(
                    engagement=an_engagement_source_reporting_each([a_responder]),
                    bands=a_band_source_pricing({SOME_TITLE: SOME_BAND}),
                    working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS))
        ) \
        .then(
            all_of(
                reports_engineer_minutes(SOME_ENGAGED_MINUTES),
                reports_a_responder_cost_of(cost_at_midpoint),
                reports_the_titles(SOME_TITLE),
                discloses_an_assumption_mentioning(
                    WORKING_YEAR_ASSUMPTION_LABEL,
                    str(int(SOME_WORKING_YEAR_IN_HOURS))),
                discloses_an_assumption_mentioning(PAY_BAND_ASSUMPTION_LABEL, SOME_TITLE)
            )
        )


@pytest.mark.component
def test_a_title_no_band_covers_leaves_the_minutes_and_takes_the_cost() -> None:
    # The minutes were measured and the cost was not, so only one of them goes.
    # Publishing the priced responder's share alone would charge the incident
    # for one person and quietly not for the other, and the page has to name
    # the title that stopped it or the gap reads as a bug in Argus.
    a_priced_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES,
                                          job_title=SOME_TITLE)
    a_responder_no_band_covers = EngagedResponder(minutes=SOME_ENGAGED_MINUTES,
                                                  job_title=SOME_TITLE_NO_BAND_COVERS)

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering(),
                sources=some_sources(
                    engagement=an_engagement_source_reporting_each(
                        [a_priced_responder, a_responder_no_band_covers]),
                    bands=a_band_source_pricing({SOME_TITLE: SOME_BAND}),
                    working_hours_a_year=SOME_WORKING_YEAR_IN_HOURS))
        ) \
        .then(
            all_of(
                reports_engineer_minutes(SOME_ENGAGED_MINUTES * 2),
                reports_no_responder_cost(),
                discloses_an_assumption_mentioning(UNPRICED_TITLE_ASSUMPTION_LABEL,
                                                   SOME_TITLE_NO_BAND_COVERS)
            )
        )


@pytest.mark.component
def test_a_band_source_that_cannot_be_read_costs_nothing_but_the_figure() -> None:
    # An HR system Argus could not reach is not evidence that the response was
    # free. The incident is over by the time this runs, so the document is
    # written without the figure rather than not written.
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering(),
                sources=some_sources(
                    engagement=an_engagement_source_reporting_each([a_responder]),
                    bands=a_band_source_that_cannot_answer()))
        ) \
        .then(
            all_of(
                reports_engineer_minutes(SOME_ENGAGED_MINUTES),
                reports_no_responder_cost(),
                discloses_the_assumption(PAY_BANDS_UNAVAILABLE_ASSUMPTION)
            )
        )


@pytest.mark.component
def test_an_answer_refused_twice_still_produces_a_document_that_says_it_is_partial() -> None:
    # The conversation's terminating case reaching a page. Whatever came back
    # is the postmortem, and every figure Argus measured for itself is on it -
    # a model that would not answer costs the document its prose and none of
    # its arithmetic.
    expected_loss = (
        Decimal(SOME_CALM_HOURLY_REVENUE) * Decimal(str(_hours_between(ONSET, ENDED_AT)))
        - SOME_REVENUE_DURING_THE_INCIDENT
    )

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: a_postmortem_written_with(
                evidence,
                llm=a_model_answering_in_prose_then(
                    an_answer_without(ROOT_CAUSE_FIELD)),
                sources=some_sources(
                    revenue=_takings_that_were_normal_until_the_onset()))
        ) \
        .then(
            all_of(
                is_marked_incomplete(),
                estimates_a_loss_of(expected_loss)
            )
        )


def _takings_that_were_normal_until_the_onset() -> Revenue:
    """The shop this file's arithmetic is worked out against.

    1200 an hour while it is well, and 100 over the whole incident once it is
    not - so a half-hour outage lost 500, and no other reading of the numbers
    lands there.
    """
    return revenue_that_was(
        per_hour={SOME_CURRENCY: SOME_CALM_HOURLY_REVENUE},
        until=ONSET,
        and_then={SOME_CURRENCY: SOME_REVENUE_DURING_THE_INCIDENT})


def _hours_between(start: datetime, end: datetime) -> float:
    """The span, worked out here rather than asked of the agent.

    A test computing its expectation the way the code does would agree with it
    however wrong both were.
    """
    return (end - start) / timedelta(hours=1)
