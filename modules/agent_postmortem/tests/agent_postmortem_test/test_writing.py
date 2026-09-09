from __future__ import annotations

from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_postmortem import PostmortemDocument, write_postmortem
from agent_postmortem.assumptions import assumptions_of
from agent_postmortem.conversation import answer_worth_writing
from agent_postmortem.measuring import Measurements, measure
from agent_postmortem.responder_cost import ResponderCost
from agent_postmortem.sources import EngagedResponder
from argus_testkit import Assertion, Scenario, all_of

from agent_postmortem_test.framework.assertions import (
    estimates_a_loss_of,
    is_marked_complete,
    is_marked_incomplete,
    reports_a_cost_ranging_from,
    reports_a_responder_cost_of,
    reports_engineer_minutes,
    reports_executive_summary,
    reports_no_engineer_minutes,
    reports_no_responder_cost,
    reports_no_root_cause,
    reports_responders,
    reports_root_cause,
    reports_the_cost_in,
    reports_the_titles,
    reports_tokens_spent,
    states_the_estimate_is_in,
)
from agent_postmortem_test.framework.builders import (
    SOME_CURRENCY,
    a_measured_incident,
    an_answer,
    an_engagement_of,
    an_evidence_bundle,
    some_sources,
)

"""Arrangement, and nothing else.

Three collaborators do the work - one measures the incident, one asks the model
for prose, one turns both into the sentences the document discloses - and this
module puts what they return onto a page. So all three are mocked here, and
what is asserted is that each was given what it needs and that what it answered
reached the document unaltered.

None of the figures are recomputed here. `test_measuring` says what the numbers
are, `test_assumptions` says what the disclosures are, `test_conversation` says
what a usable answer is, and `component/test_postmortem` runs the three for
real against a document. Asserting an exchange rate in this file would be
testing `measuring` through two layers of indirection, and it would still pass
if `writing` put the figure in the wrong column.

The one judgement `writing` makes is what an unusable answer means: faults do
not stop a document being written, they make it say on its face that it is
partial.
"""

SOME_TITLE = "Senior Kuki"
SOME_OTHER_TITLE = "Site Reliability Engineer"

DONT_CARE_WORKING_YEAR = 2080.0


@pytest.mark.unit
def test_the_prose_the_model_wrote_is_what_the_document_says() -> None:
    # The two fields Argus does not compute, and the only two the model is
    # asked for. They cross unaltered or the document is not the answer that
    # was checked.
    some_root_cause = "the checkout fallback was disabled by a flag toggle at 12:04"
    some_summary = "Checkout failed for half an hour after a flag change; reverted."

    Scenario() \
        .given(
            a_model_that_answered := _asking_that_answers(
                an_answer(root_cause=some_root_cause,
                          executive_summary=some_summary))
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=a_model_that_answered,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                reports_root_cause(some_root_cause),
                reports_executive_summary(some_summary)
            )
        )


@pytest.mark.unit
def test_a_field_the_answer_never_carried_is_absent_rather_than_empty() -> None:
    # An answer nothing could be read out of - a model that wrote prose, or
    # called the wrong tool. The document is still written, and the field it
    # could not fill has to be absent: an empty string on a page reads as a
    # root cause somebody wrote and left blank.
    Scenario() \
        .given(
            an_answer_carrying_nothing := _asking_that_answers({})
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=an_answer_carrying_nothing,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            reports_no_root_cause()
        )


@pytest.mark.unit
def test_the_figures_measured_are_the_figures_published() -> None:
    # Every column the document carries about money and people, taken from one
    # measured incident. What makes this worth asserting is not the arithmetic -
    # it is that each figure lands in its own column, and a document that put
    # the minimum where the midpoint goes would be wrong in a way no reader
    # could see.
    some_loss = Decimal("1234.56")
    some_minutes = 25
    some_responders = 2
    some_cost = ResponderCost(midpoint=Decimal("30"),
                              minimum=Decimal("15"),
                              maximum=Decimal("60"),
                              currency=SOME_CURRENCY)

    Scenario() \
        .given(
            a_fully_measured_incident := a_measured_incident(
                loss=some_loss,
                engaged=an_engagement_of([
                    EngagedResponder(minutes=15, job_title=SOME_TITLE),
                    EngagedResponder(minutes=10, job_title=SOME_OTHER_TITLE)
                ]),
                cost=some_cost)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle(),
                some_sources(),
                _dont_care_llm(),
                measure=_measuring_that_returns(a_fully_measured_incident),
                ask=_asking_that_answers(an_answer()),
                disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                estimates_a_loss_of(some_loss),
                states_the_estimate_is_in(SOME_CURRENCY),
                reports_engineer_minutes(some_minutes),
                reports_responders(some_responders),
                reports_the_titles(SOME_TITLE, SOME_OTHER_TITLE),
                reports_a_responder_cost_of(some_cost.midpoint),
                reports_a_cost_ranging_from(some_cost.minimum, some_cost.maximum),
                reports_the_cost_in(SOME_CURRENCY)
            )
        )


@pytest.mark.unit
def test_an_incident_nobody_could_measure_reports_no_response() -> None:
    # The absence has to survive the arrangement. A document defaulting the
    # minutes to zero because nobody answered would report an incident that
    # took nobody's night, out of a source Argus failed to reach.
    Scenario() \
        .given(
            an_incident_nobody_could_say_who_worked_on := a_measured_incident(
                engaged=None, cost=None)
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle(),
                some_sources(),
                _dont_care_llm(),
                measure=_measuring_that_returns(
                    an_incident_nobody_could_say_who_worked_on),
                ask=_asking_that_answers(an_answer()),
                disclose=_disclosing_that_returns([]))
        ) \
        .then(
            all_of(
                reports_no_engineer_minutes(),
                reports_no_responder_cost()
            )
        )


@pytest.mark.unit
def test_the_disclosures_produced_are_the_disclosures_listed() -> None:
    # In the order they were produced, and nothing added on the way past. The
    # order is the disclosure module's, and a document that sorted them or
    # deduplicated them would be editing what the page admits to.
    some_disclosures = ["the first thing assumed", "the second thing assumed"]

    Scenario() \
        .given(
            a_disclosure_of_two_things := _disclosing_that_returns(some_disclosures)
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(an_answer()),
                                     disclose=a_disclosure_of_two_things)
        ) \
        .then(
            _lists_exactly(some_disclosures)
        )


@pytest.mark.unit
def test_an_answer_nothing_was_wrong_with_is_written_down_as_complete() -> None:
    Scenario() \
        .given(
            an_answer_with_no_faults := _asking_that_answers(an_answer(), faults=[])
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=an_answer_with_no_faults,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            is_marked_complete()
        )


@pytest.mark.unit
def test_an_answer_still_carrying_a_fault_is_written_down_as_incomplete() -> None:
    # The one judgement this module makes. The faults do not stop a document
    # being written - the incident is over and a partial account is worth more
    # than none - so the document says on its face what it is.
    Scenario() \
        .given(
            an_answer_still_wrong := _asking_that_answers(
                an_answer(), faults=["the field [root_cause] was missing"])
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=an_answer_still_wrong,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            is_marked_incomplete()
        )


@pytest.mark.unit
def test_the_tokens_the_incident_spent_come_from_its_evidence() -> None:
    # Not from this call. What the walk spent was counted while it was
    # happening, and the postmortem's own tokens are not part of what the
    # incident cost to handle.
    some_tokens_spent = 48_120

    Scenario() \
        .given(
            evidence := an_evidence_bundle(tokens_spent=some_tokens_spent)
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(
                                         a_measured_incident()),
                                     ask=_asking_that_answers(an_answer()),
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            reports_tokens_spent(some_tokens_spent)
        )


@pytest.mark.unit
def test_the_model_is_asked_about_the_incident_that_was_measured() -> None:
    # The whole reason the measuring happens first. A model handed figures from
    # anything but this incident writes fluent prose about a different one, and
    # the document reads perfectly either way.
    measured = a_measured_incident()
    asking = _asking_that_answers(an_answer())

    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(evidence,
                                     some_sources(),
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(measured),
                                     ask=asking,
                                     disclose=_disclosing_that_returns([]))
        ) \
        .then(
            _was_asked_about(asking, evidence.incident_id, measured)
        )


@pytest.mark.unit
def test_the_disclosures_are_written_from_what_was_measured_and_configured() -> None:
    # The disclosure module reads no source of its own, so everything it needs
    # has to arrive here: the incident as measured, and the working year the
    # bands were divided by. Handed a different working year from the one the
    # cost was computed under, it would publish a divisor that does not explain
    # the figure beside it.
    measured = a_measured_incident()
    disclosing = _disclosing_that_returns([])
    some_working_year = 1_900.0

    Scenario() \
        .given(
            sources := some_sources(working_hours_a_year=some_working_year)
        ) \
        .when(
            lambda: write_postmortem(an_evidence_bundle(),
                                     sources,
                                     _dont_care_llm(),
                                     measure=_measuring_that_returns(measured),
                                     ask=_asking_that_answers(an_answer()),
                                     disclose=disclosing)
        ) \
        .then(
            _disclosed_from(disclosing, measured, some_working_year)
        )


def _measuring_that_returns(measured: Measurements) -> MagicMock:
    measuring = create_autospec(measure)
    measuring.return_value = measured

    return cast(MagicMock, measuring)


def _asking_that_answers(answer: dict[str, object],
                         faults: list[str] | None = None) -> MagicMock:
    asking = create_autospec(answer_worth_writing)
    asking.return_value = (answer, faults if faults is not None else [])

    return cast(MagicMock, asking)


def _disclosing_that_returns(assumptions: list[str]) -> MagicMock:
    disclosing = create_autospec(assumptions_of)
    disclosing.return_value = assumptions

    return cast(MagicMock, disclosing)


def _dont_care_llm() -> MagicMock:
    """A model nothing here ever reaches.

    Every test in this file mocks the asking, so the client is carried and not
    called - which is itself worth a double rather than a `None`, since a
    module that reached past its collaborator to the model would then fail
    here rather than in production.
    """
    return cast(MagicMock, create_autospec(_dont_care_llm))


def _lists_exactly(expected: list[str]) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.assumptions != expected:
            raise AssertionError(
                f"expected the document to list {expected}, got {document.assumptions}")

        return True

    return assertion


def _was_asked_about(asking: MagicMock,
                     incident_id: str,
                     measured: Measurements) -> Assertion[PostmortemDocument]:
    """The model was put this incident, with these figures beside it."""
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        _, evidence, put_to_it = asking.call_args.args

        if evidence.incident_id != incident_id:
            raise AssertionError(
                f"expected the model to be asked about incident [{incident_id}], "
                f"got [{evidence.incident_id}]")

        if put_to_it is not measured:
            raise AssertionError(
                f"expected the model to be given the incident as measured, got "
                f"[{put_to_it}]")

        return True

    return assertion


def _disclosed_from(disclosing: MagicMock,
                    measured: Measurements,
                    working_hours_a_year: float) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        _, disclosed_from, under = disclosing.call_args.args

        if disclosed_from is not measured:
            raise AssertionError(
                f"expected the disclosures to be written from the incident as "
                f"measured, got [{disclosed_from}]")

        if under != working_hours_a_year:
            raise AssertionError(
                f"expected the disclosures to be written under a working year of "
                f"[{working_hours_a_year}], got [{under}]")

        return True

    return assertion
