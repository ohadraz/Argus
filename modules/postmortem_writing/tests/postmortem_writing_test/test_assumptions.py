"""What the document admits to having assumed rather than measured.

Two kinds of line, arriving from opposite directions. One is the model's own:
asked what else a reader should know it took rather than measured, it answers
in prose, and that answer has to reach the page - dropped, it would leave a
document claiming more certainty than the thing that wrote it had.

The other is Argus's, and it is here because a figure is only as honest as the
steps between the source and the page. A rate applied, a currency left out, a
shortfall within what the shop varies by: none of those is a measurement, and
a reader who cannot see them is being asked to take the figures on trust.

An absence gets a line too, and it is the half most worth testing. A figure
that is missing and a figure that is zero look identical on a page unless the
document says which it is - and each absence has its own sentence, because
"nobody responded" and "the on-call system could not be reached" are different
findings that would otherwise leave the same blank.

Nothing here reads a source. Everything was read while the incident was being
measured, so this takes a measured incident and turns it into sentences.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from argus_testkit import Assertion, Scenario, all_of
from incident_cost import (
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    NO_RATE_PUBLISHED_REASON,
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    RATES_UNAVAILABLE_REASON,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
    RateTable,
)
from postmortem_writing import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
    NORMAL_VARIATION_ASSUMPTION_LABEL,
    NOTHING_READ_ASSUMPTION,
    ONSET_UNKNOWN_ASSUMPTION,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    SHARED_PAGE_ASSUMPTION_LABEL,
    EngagedResponder,
)
from postmortem_writing.answer import SubmittedPostmortem
from postmortem_writing.assumptions import assumptions_of
from postmortem_writing.estimate import Unmeasured
from postmortem_writing.measuring import Measurements
from postmortem_writing.sources import NotPaged

from postmortem_writing_test.framework.builders import (
    DONT_CARE_BASELINE_REVENUE,
    ONSET,
    SOME_CURRENCY,
    SOME_OTHER_CURRENCY,
    SOME_UNPRICED_CURRENCY,
    a_measured_incident,
    an_engagement_of,
)

SOME_TITLE = "Senior Kuki"
SOME_ENGAGED_MINUTES = 30

# An answer the model gave that says nothing about assumptions, for the tests
# whose subject is one of Argus's own disclosures.
DONT_CARE_ANSWER = SubmittedPostmortem()


@pytest.mark.unit
def test_what_the_model_says_it_assumed_is_carried_through() -> None:
    # The model is asked for anything else it took rather than measured, and
    # what it answers has to reach the page. Dropped, it would leave a document
    # claiming more certainty than the thing that wrote it had.
    some_assumption = "the log lines shown were the whole of the failing traffic"

    Scenario() \
        .given(
            an_answer := SubmittedPostmortem(assumptions=[some_assumption])
        ) \
        .when(
            lambda: assumptions_of(an_answer,
                                   a_measured_incident())
        ) \
        .then(
            _names(some_assumption)
        )


@pytest.mark.unit
def test_pay_is_no_assumption_of_the_postmortem() -> None:
    # The postmortem is read by the people it would price. How their minutes
    # are priced - or why they could not be - is the executive synopsis's to
    # say, and nothing this document assumed.
    Scenario() \
        .given(
            an_incident := a_measured_incident(
                engaged=an_engagement_of([EngagedResponder(minutes=SOME_ENGAGED_MINUTES,
                                                           job_title=SOME_TITLE)]))
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER, an_incident)
        ) \
        .then(all_of(
            _says_nothing_about(WORKING_YEAR_ASSUMPTION_LABEL),
            _says_nothing_about(PAY_BAND_ASSUMPTION_LABEL),
            _says_nothing_about(UNPRICED_TITLE_ASSUMPTION_LABEL),
            _says_nothing_about(PAY_BANDS_UNAVAILABLE_ASSUMPTION)
        ))


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
                                   an_incident_costed_from_money_taken_abroad)
        ) \
        .then(
            all_of(
                _names_a_line_mentioning(EXCHANGE_RATE_ASSUMPTION_LABEL, str(some_rate)),
                _names_a_line_mentioning(EXCHANGE_RATE_ASSUMPTION_LABEL,
                                         some_rate_date.isoformat()),
                _names_a_line_mentioning(EXCHANGE_RATE_ASSUMPTION_LABEL,
                                         f"{SOME_OTHER_CURRENCY.upper()} converted at "
                                         f"{some_rate} per {SOME_CURRENCY.upper()}")
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
                                   an_incident_costed_from_money_taken_at_home)
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
                                   an_incident_whose_figure_is_partial)
        ) \
        .then(
            all_of(
                _names_a_line_mentioning(EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
                                         SOME_UNPRICED_CURRENCY),
                _names_a_line_mentioning(EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
                                         NO_RATE_PUBLISHED_REASON)
            )
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
                                   an_incident_nothing_measured_an_onset_for)
        ) \
        .then(
            _names(ONSET_UNKNOWN_ASSUMPTION)
        )


@pytest.mark.unit
def test_an_incident_none_of_whose_metrics_could_be_read_says_so_not_that_none_departed() -> None:
    # "No minute departed from the baseline" says of a window nobody saw that
    # it was looked at and found calm.
    Scenario() \
        .given(
            an_incident_nothing_could_be_read_for := a_measured_incident(
                onset_at=None).model_copy(
                    update={"error_rates_unmeasured": Unmeasured.NOTHING_READ})
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_nothing_could_be_read_for)
        ) \
        .then(all_of(
            _names(NOTHING_READ_ASSUMPTION),
            _says_nothing_about(ONSET_UNKNOWN_ASSUMPTION)
        ))


@pytest.mark.unit
def test_a_revenue_source_that_could_not_be_read_says_so() -> None:
    # Otherwise the document carries a blank where its headline figure goes,
    # and a blank reads as nothing having been lost.
    Scenario() \
        .given(
            an_incident_nobody_could_cost := a_measured_incident(
                baseline_revenue=None, takings=None)
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_nobody_could_cost)
        ) \
        .then(
            _names(REVENUE_UNAVAILABLE_ASSUMPTION)
        )


@pytest.mark.unit
def test_an_incident_with_no_onset_owes_no_apology_for_takings_never_asked_for() -> None:
    # Without an onset no loss is counted, so the takings are never read - and
    # said to be unreadable, a provider nobody asked reads as one that was down.
    Scenario() \
        .given(
            an_incident_nothing_measured_an_onset_for := a_measured_incident(
                onset_at=None, loss=None, baseline_revenue=None, takings=None, rates=None)
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_nothing_measured_an_onset_for)
        ) \
        .then(
            _says_nothing_about(REVENUE_UNAVAILABLE_ASSUMPTION)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("an_incident", "label"), [
    pytest.param(a_measured_incident(
        loss=None,
        takings={SOME_OTHER_CURRENCY: Decimal("800")},
        rates=RateTable(base=SOME_CURRENCY,
                        on=ONSET.date(),
                        per_unit={SOME_OTHER_CURRENCY: Decimal("0.80")})),
        EXCHANGE_RATE_ASSUMPTION_LABEL, id="a conversion"),
    pytest.param(a_measured_incident(loss=None, left_out=[SOME_UNPRICED_CURRENCY]),
                 EXCLUDED_CURRENCY_ASSUMPTION_LABEL, id="a currency left out")
])
def test_takings_no_loss_was_made_of_disclose_nothing_of_their_money(an_incident: Measurements,
                                                                    label: str) -> None:
    # A rate disclosed beside "no loss estimated" names a conversion no figure
    # was made by, and a currency left out of a figure nobody computed is left
    # out of nothing.
    Scenario() \
        .given(
            an_incident
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER, an_incident)
        ) \
        .then(
            _says_nothing_about(label)
        )


@pytest.mark.unit
def test_a_currency_left_out_because_no_table_arrived_says_which() -> None:
    # Two reasons a currency is missing from the figure, and they send a reader
    # to two different places: a provider publishing no rate for a currency is a
    # fact about the currency, and a table nobody could fetch is a fact about the
    # read. Told the first when the second happened, a reader goes hunting for a
    # currency the provider covers perfectly well.
    Scenario() \
        .given(
            an_incident_no_table_arrived_for := a_measured_incident(
                rates=None, left_out=[SOME_OTHER_CURRENCY])
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_no_table_arrived_for)
        ) \
        .then(
            all_of(
                _names_a_line_mentioning(EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
                                         RATES_UNAVAILABLE_REASON),
                _says_nothing_about(NO_RATE_PUBLISHED_REASON)
            )
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
                                   an_incident_nobody_could_say_who_worked_on)
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
                                   an_incident_argus_handled_alone)
        ) \
        .then(
            _says_nothing_about(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
        )


@pytest.mark.unit
def test_a_page_other_incidents_shared_is_disclosed_with_how_many() -> None:
    # Argus said it mitigated the first incident and the alarm went on, so a
    # second followed - while the on-call platform kept one page open across
    # both. Its minutes are that page's whole response, reported in full on
    # each write-up, and a reader adding the write-ups up counts them twice
    # unless each says so.
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_incident_whose_page_two_others_shared := a_measured_incident(
                engaged=an_engagement_of([a_responder]).model_copy(
                    update={"shared_with": 2}))
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_whose_page_two_others_shared)
        ) \
        .then(
            _names_a_line_mentioning(SHARED_PAGE_ASSUMPTION_LABEL, "2 other incidents")
        )


@pytest.mark.unit
def test_a_page_one_other_incident_shared_is_said_in_the_singular() -> None:
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_incident_whose_page_one_other_shared := a_measured_incident(
                engaged=an_engagement_of([a_responder]).model_copy(
                    update={"shared_with": 1}))
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_whose_page_one_other_shared)
        ) \
        .then(
            all_of(
                _names_a_line_mentioning(SHARED_PAGE_ASSUMPTION_LABEL, "1 other incident"),
                _says_nothing_about("1 other incidents")
            )
        )


@pytest.mark.unit
def test_a_page_this_incident_had_alone_needs_no_such_disclosure() -> None:
    a_responder = EngagedResponder(minutes=SOME_ENGAGED_MINUTES, job_title=SOME_TITLE)

    Scenario() \
        .given(
            an_incident_paged_alone := a_measured_incident(
                engaged=an_engagement_of([a_responder]))
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_paged_alone)
        ) \
        .then(
            _says_nothing_about(SHARED_PAGE_ASSUMPTION_LABEL)
        )


@pytest.mark.unit
def test_a_shortfall_within_what_the_shop_varies_by_is_disclosed_as_no_loss() -> None:
    # A zero beside an incident that plainly took less reads as a figure nobody
    # computed. Said with both amounts, it is a finding a reader can check -
    # each in the one spelling money has on the page, half a cent up and in its
    # currency, since an amount said two ways reads as two amounts.
    Scenario() \
        .given(
            an_incident_within_the_shop_s_variation := a_measured_incident(
                loss=Decimal(0)
            ).model_copy(update={"shortfall": Decimal("1200.005"),
                                 "variation": Decimal("1300")})
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_within_the_shop_s_variation)
        ) \
        .then(
            all_of(
                _names_a_line_mentioning(NORMAL_VARIATION_ASSUMPTION_LABEL, "1,200.01 USD"),
                _names_a_line_mentioning(NORMAL_VARIATION_ASSUMPTION_LABEL, "1,300.00 USD")
            )
        )


@pytest.mark.unit
def test_a_loss_beyond_what_the_shop_varies_by_needs_no_such_disclosure() -> None:
    Scenario() \
        .given(
            an_incident_that_lost_money := a_measured_incident(
                loss=Decimal("500.00")
            ).model_copy(update={"shortfall": Decimal("500.00"),
                                 "variation": Decimal("40.00")})
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident_that_lost_money)
        ) \
        .then(
            _says_nothing_about(NORMAL_VARIATION_ASSUMPTION_LABEL)
        )


@pytest.mark.unit
@pytest.mark.parametrize("an_incident", [
    pytest.param(a_measured_incident(onset_at=None), id="no onset"),
    pytest.param(a_measured_incident(
        takings={SOME_OTHER_CURRENCY: Decimal("800")},
        rates=RateTable(base=SOME_CURRENCY,
                        on=ONSET.date(),
                        per_unit={SOME_OTHER_CURRENCY: Decimal("0.80")})),
        id="a conversion"),
    pytest.param(a_measured_incident(left_out=[SOME_UNPRICED_CURRENCY]),
                 id="a currency left out"),
    pytest.param(a_measured_incident(loss=Decimal(0)).model_copy(
        update={"shortfall": Decimal("200.00"), "variation": Decimal("300.00")}),
        id="a shortfall within the shop's variation"),
    pytest.param(a_measured_incident(baseline_revenue=None, takings=None),
                 id="no revenue"),
    pytest.param(a_measured_incident(engaged=None), id="no engagement"),
    pytest.param(a_measured_incident().model_copy(update={"engaged": NotPaged()}),
                 id="nobody paged"),
    pytest.param(a_measured_incident(
        engaged=an_engagement_of([EngagedResponder(minutes=SOME_ENGAGED_MINUTES,
                                                   job_title=SOME_TITLE)]).model_copy(
            update={"shared_with": 1})),
        id="a shared page")
])


def test_every_disclosure_argus_writes_begins_with_a_capital(an_incident: Measurements) -> None:
    # Each is a line of its own on the page, read as a sentence. The model's
    # own lines already open with a capital; Argus's beside them in lower case
    # read as fragments of something cut off.
    Scenario() \
        .given(
            an_incident
        ) \
        .when(
            lambda: assumptions_of(DONT_CARE_ANSWER,
                                   an_incident)
        ) \
        .then(
            _every_line_begins_with_a_capital()
        )


def _names(expected: str) -> Assertion[list[str]]:
    def assertion(assumptions: list[str]) -> bool:
        if not any(expected in stated for stated in assumptions):
            raise AssertionError(
                f"Expected an assumption mentioning [{expected}], got {assumptions}")

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
                f"Expected an assumption mentioning [{label}] and [{detail}], "
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
                f"Expected [{label}] to mention [{detail}] exactly once, got {said}")

        return True

    return assertion


def _says_nothing_about(unexpected: str) -> Assertion[list[str]]:
    def assertion(assumptions: list[str]) -> bool:
        if any(unexpected in stated for stated in assumptions):
            raise AssertionError(
                f"Expected no assumption about [{unexpected}], got {assumptions}")

        return True

    return assertion


def _every_line_begins_with_a_capital() -> Assertion[list[str]]:
    def assertion(assumptions: list[str]) -> bool:
        if not assumptions:
            raise AssertionError("Expected at least one assumption, got none.")

        in_lower_case = [stated for stated in assumptions if not stated[:1].isupper()]
        if in_lower_case:
            raise AssertionError(
                f"Expected every assumption to begin with a capital, got {in_lower_case}")

        return True

    return assertion
