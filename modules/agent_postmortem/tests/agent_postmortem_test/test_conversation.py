from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from agent_postmortem.conversation import answer_worth_writing
from agent_postmortem.prompting import EXECUTIVE_SUMMARY_FIELD, ROOT_CAUSE_FIELD
from argus_core.models.transcript import Ask, ToolResults, Transcript
from argus_core.models.turn import Turn
from argus_testkit import Assertion, Kept, Scenario, all_of

from agent_postmortem_test.framework.builders import (
    a_measured_incident,
    a_model_answering_in_prose_then,
    a_model_answering_in_turn,
    a_model_calling,
    an_answer,
    an_answer_without,
    an_evidence_bundle,
)

"""The one second chance, and the two things that earn it.

A field the model left out, and a figure it made up. They are answered
together: one further call naming what was wrong with the first, and then
whatever comes back is what the document is written from. There is no third
attempt - an incident that is over is not improved by an agent that will not
stop, and the faults are handed back so the caller can mark the document
partial.

The invented figure is the subtler of the two. Columns are safe from the model
by construction, but the executive summary is published as written, so a
sentence claiming a number Argus never computed reaches the one reader least
able to check it.

The shape of the second ask is the other half of this file, and it is not a
detail of wording. A submission is refused through the result of the call that
made it, because a provider that has seen a tool call expects its result next -
but a model that made no call submitted nothing there is anything to refuse, so
that one is asked again from the start. Getting it wrong produces a
conversation a provider will not accept, or one the model cannot make sense of.
"""

# The figure this file's incident was measured at, and the same figure as a
# summary would write it. A stated amount is only checkable against a computed
# one, so the two have to be the same number said two ways.
SOME_COMPUTED_LOSS = Decimal("500")
SOME_SUMMARY_STATING_THE_FIGURE = "the outage cost roughly $500"

SOME_INVENTED_FIGURE = "$1,200,000"
SOME_SUMMARY_WITHOUT_A_FIGURE = "checkout failed for half an hour"

type Reading = tuple[dict[str, Any], list[str]]


@pytest.mark.unit
def test_an_answer_missing_a_field_is_asked_for_again_naming_what_was_missing() -> None:
    # Naming it matters as much as asking again. A model told only that its
    # answer was wrong will rewrite the part it liked least, which is rarely
    # the part that was missing.
    some_root_cause = "the checkout fallback was disabled"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_forgot_the_root_cause := a_model_answering_in_turn(
                an_answer_without(ROOT_CAUSE_FIELD),
                an_answer(root_cause=some_root_cause),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_forgot_the_root_cause,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, ROOT_CAUSE_FIELD),
                _the_correction_answered_the_call_it_rejected(asks),
                _answered_with(ROOT_CAUSE_FIELD, some_root_cause),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_second_answer_that_is_still_missing_a_field_is_handed_back_anyway() -> None:
    # The terminating case. Whatever came back is the postmortem, and the
    # faults come back with it: a document that says it is partial is worth
    # more than an agent still trying while the incident is over.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_forgets_twice := a_model_answering_in_turn(
                an_answer_without(ROOT_CAUSE_FIELD),
                an_answer_without(ROOT_CAUSE_FIELD),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_forgets_twice,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_a_summary_naming_a_figure_argus_never_computed_is_asked_for_again() -> None:
    # The whole reason this check exists. Nothing downstream can tell that
    # "$1.2M" was invented: it is a fluent sentence in a document whose every
    # other number is measured.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_invented_a_figure := a_model_answering_in_turn(
                an_answer(executive_summary=f"the outage cost {SOME_INVENTED_FIGURE}"),
                an_answer(executive_summary=SOME_SUMMARY_WITHOUT_A_FIGURE),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_invented_a_figure,
                                         an_evidence_bundle(),
                                         a_measured_incident(loss=SOME_COMPUTED_LOSS))
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, SOME_INVENTED_FIGURE),
                _answered_with(EXECUTIVE_SUMMARY_FIELD, SOME_SUMMARY_WITHOUT_A_FIGURE)
            )
        )


@pytest.mark.unit
def test_a_summary_naming_the_computed_figure_is_accepted() -> None:
    # The check is on figures Argus did not arrive at, not on figures. A
    # summary forbidden to mention what the incident cost would be a summary
    # written for nobody.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_stating_the_computed_figure := a_model_answering_in_turn(
                an_answer(executive_summary=SOME_SUMMARY_STATING_THE_FIGURE),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_stating_the_computed_figure,
                                         an_evidence_bundle(),
                                         a_measured_incident(loss=SOME_COMPUTED_LOSS))
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _answered_with(EXECUTIVE_SUMMARY_FIELD,
                               SOME_SUMMARY_STATING_THE_FIGURE),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_summary_naming_any_figure_at_all_is_challenged_when_nothing_was_computed() -> None:
    # With no estimate there is nothing for a figure to agree with, so every
    # figure is invented by definition - which is the case whenever the payment
    # provider or the rate source could not be read.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_incident_nobody_could_cost := a_measured_incident(
                baseline_revenue=None)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_answering_in_turn(
                    an_answer(
                        executive_summary=f"the outage cost {SOME_INVENTED_FIGURE}"),
                    an_answer(executive_summary=SOME_SUMMARY_WITHOUT_A_FIGURE),
                    recording_into=asks),
                an_evidence_bundle(),
                an_incident_nobody_could_cost)
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, SOME_INVENTED_FIGURE)
            )
        )


@pytest.mark.unit
def test_a_model_that_ignored_the_tool_is_asked_again_from_the_beginning() -> None:
    # There is no call to answer, so the correction cannot be a tool result: a
    # rejection has to be attached to something the model submitted, and this
    # model submitted a paragraph. The whole incident goes again.
    some_root_cause = "the checkout fallback was disabled"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_wrote_prose_first := a_model_answering_in_prose_then(
                an_answer(root_cause=some_root_cause), recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_wrote_prose_first,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_was_a_fresh_ask(asks),
                _answered_with(ROOT_CAUSE_FIELD, some_root_cause),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_model_that_ignores_the_tool_twice_answers_nothing() -> None:
    # The terminating case for the other shape of bad answer. Two paragraphs is
    # not one attempt away from a document, and nothing in a paragraph can be
    # read into a field.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_only_writes_prose := a_model_answering_in_prose_then(
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_only_writes_prose,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _answered_nothing(),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_an_answer_calling_some_other_tool_is_read_as_no_answer() -> None:
    # Not the same failure as answering in prose, though it lands in the same
    # place: this model did reach for a tool, and reached for the wrong one.
    # Reading its arguments anyway would fill the document from a call that was
    # never the postmortem - fields with the right names, about something else
    # entirely.
    some_other_tool = "get_log_lines"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_calling_the_wrong_tool := a_model_calling(some_other_tool,
                                                              recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_calling_the_wrong_tool,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _answered_nothing(),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_a_model_that_answers_completely_is_asked_once() -> None:
    # The second call belongs to the checklist and to nothing else. An agent
    # that asked twice as a matter of course would double the cost of every
    # postmortem to improve none of them.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_answering_completely := a_model_answering_in_turn(
                an_answer(), recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_answering_completely,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _found_no_fault()
            )
        )


def _was_asked(asks: Kept[Transcript], times: int = 1) -> Assertion[Reading]:
    """How many times the model was put the question.

    Once by default, because once is what a good answer costs and every extra
    call is a postmortem paying twice to improve nothing.
    """
    def assertion(dont_care_reading: Reading) -> bool:
        if len(asks.taken) != times:
            raise AssertionError(
                f"expected the model to be asked [{times}] time(s), got "
                f"[{len(asks.taken)}]")

        return True

    return assertion


def _answered_with(field: str, expected: str) -> Assertion[Reading]:
    def assertion(reading: Reading) -> bool:
        answer, _ = reading

        if answer.get(field) != expected:
            raise AssertionError(
                f"expected [{field}] to be [{expected}], got [{answer.get(field)}]")

        return True

    return assertion


def _answered_nothing() -> Assertion[Reading]:
    """An answer in a shape nothing can be read out of.

    Empty rather than absent: the caller writes a document either way, and what
    it writes is a document that says on its face that it is partial.
    """
    def assertion(reading: Reading) -> bool:
        answer, _ = reading

        if answer:
            raise AssertionError(
                f"expected nothing to be read out of an answer in the wrong shape, "
                f"got {answer}")

        return True

    return assertion


def _found_no_fault() -> Assertion[Reading]:
    def assertion(reading: Reading) -> bool:
        _, faults = reading

        if faults:
            raise AssertionError(
                f"expected an answer nothing was wrong with, got {faults}")

        return True

    return assertion


def _found_a_fault() -> Assertion[Reading]:
    def assertion(reading: Reading) -> bool:
        _, faults = reading

        if not faults:
            raise AssertionError(
                "expected the faults to come back with the answer, so the caller "
                "can mark the document partial, and none did")

        return True

    return assertion


def _the_correction_named(asks: Kept[Transcript], expected: str) -> Assertion[Reading]:
    def assertion(dont_care_reading: Reading) -> bool:
        said = _what_was_said_to_the_model(asks.taken[1])

        if expected not in said:
            raise AssertionError(
                f"expected the correction to name [{expected}], and it did not: {said}")

        return True

    return assertion


def _the_correction_answered_the_call_it_rejected(
        asks: Kept[Transcript]) -> Assertion[Reading]:
    """The correction is the tool call's result, not a second conversation.

    A provider that has seen a tool call expects its result next, and the result
    is where a rejection belongs: the model sees what it submitted, is told what
    was wrong with it, and answers in the same exchange - rather than being
    handed the whole incident again as though it had never answered at all.
    """
    def assertion(dont_care_reading: Reading) -> bool:
        submitted = [entry for entry in asks.taken[1] if isinstance(entry, Turn)]
        answered = [entry for entry in asks.taken[1] if isinstance(entry, ToolResults)]

        if not submitted or not answered:
            raise AssertionError(
                "expected the correction to carry the model's own turn and the "
                "result of the call it made, and it carried "
                f"{len(submitted)} turn(s) and {len(answered)} result(s)")

        expected_call_id = submitted[0].tool_calls[0].id
        answering = [result.call_id for result in answered[0].results]

        if answering != [expected_call_id]:
            raise AssertionError(
                f"expected the result to answer call [{expected_call_id}], "
                f"got {answering}")

        if not answered[0].results[0].failed:
            raise AssertionError(
                "expected the rejected submission to be marked failed, so the model "
                "reads it as something to fix rather than as evidence")

        return True

    return assertion


def _the_correction_was_a_fresh_ask(asks: Kept[Transcript]) -> Assertion[Reading]:
    """Asked again from the start, with nothing to answer.

    The counterpart to `_the_correction_answered_the_call_it_rejected`: where
    there was a submission the correction rides on it, and where there was none
    it cannot.
    """
    def assertion(dont_care_reading: Reading) -> bool:
        carried = [entry for entry in asks.taken[1]
                   if isinstance(entry, Turn | ToolResults)]

        if carried:
            raise AssertionError(
                f"expected the correction to be a fresh ask, and it carried {carried}")

        return True

    return assertion


def _what_was_said_to_the_model(transcript: Transcript) -> str:
    """Everything Argus put in front of the model, in whichever shape.

    A fault can arrive as prose in an ask or as the result of the tool call it
    rejects. Which one it is is the code's business; this file asserts that
    choice separately, and here only cares that the model was told.
    """
    said: list[str] = []

    for entry in transcript:
        if isinstance(entry, Ask):
            said.append(entry.text)
        elif isinstance(entry, ToolResults):
            said.extend(result.content for result in entry.results)

    return "\n".join(said)
