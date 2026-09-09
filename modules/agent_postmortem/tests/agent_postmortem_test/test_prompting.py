from __future__ import annotations

import pytest
from agent_postmortem.prompting import (
    ASSUMPTIONS_FIELD,
    EXECUTIVE_SUMMARY_FIELD,
    REQUIRED_FIELDS,
    ROOT_CAUSE_FIELD,
    SUBMIT_POSTMORTEM,
    SUBMIT_TOOL_NAME,
    opening_ask,
    opening_ask_again,
    rejecting,
)
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, ToolResults, Transcript
from argus_core.models.turn import Turn
from argus_testkit import Assertion, Scenario, all_of

from agent_postmortem_test.framework.builders import (
    a_measured_incident,
    a_submission_of,
    an_answer,
    an_evidence_bundle,
)

"""What the model is asked, and the one shape its answer may take.

The model is handed the incident and the figures Argus already computed, and
asked only for the parts prose can carry. Handed half an incident it will
explain the half it was shown, fluently, and nothing downstream can tell that
from an explanation of the whole.

It is asked for no number at all. Every figure in the document is measured, and
a model's arithmetic about a measurement is not a second opinion - it is a
second answer nobody can tell apart from the first.

The three asks are separate functions because they are separate situations. The
opening one states the incident. A refusal rides on the tool call it refuses,
because a provider that has seen a call expects its result next. And where
there was no call to refuse, the incident is put again from the start - the
only shape left, and the one this file exists to keep distinct from the other.
"""

SOME_FAULT = "the field [root_cause] was missing from your answer"


@pytest.mark.unit
def test_the_model_is_told_everything_the_walk_produced() -> None:
    # A model asked to explain an incident it was shown half of will explain
    # the half it was shown, confidently.
    some_alert = "checkout error rate above threshold"
    some_timeline_line = "mitigating at 12:12"
    some_candidate = "flag toggle on checkout-fallback - confirmed"
    some_action = "disabled checkout-fallback restored - confirmed"
    some_log_line = "12:04 ERROR checkout: fallback unavailable"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(alert_summary=some_alert,
                                           timeline=[some_timeline_line],
                                           candidates=[some_candidate],
                                           actions=[some_action],
                                           log_lines=[some_log_line])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says(some_alert, some_timeline_line, some_candidate, some_action,
                  some_log_line)
        )


@pytest.mark.unit
def test_the_model_is_told_how_long_the_incident_ran() -> None:
    # The duration is context for the prose rather than a figure the model may
    # restate as its own. It is stated to two decimal places, because a summary
    # saying "half an hour" about 0.5 hours is the sentence this is for.
    some_duration_in_hours = 1.25

    Scenario() \
        .given(
            an_incident_of_known_length := a_measured_incident(
                duration_in_hours=some_duration_in_hours)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_of_known_length)
        ) \
        .then(
            _says(f"{some_duration_in_hours:.2f}")
        )


@pytest.mark.unit
def test_the_model_is_told_how_far_the_errors_rose() -> None:
    # Stated as a share of traffic, which is what the measurement is. A model
    # given a bare number writes prose about a bare number.
    some_rise = 0.28

    Scenario() \
        .given(
            an_incident_whose_errors_rose := a_measured_incident(
                error_rate_delta=some_rise)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_errors_rose)
        ) \
        .then(
            _says(f"{some_rise:.1%}")
        )


@pytest.mark.unit
def test_a_rise_nobody_could_measure_is_said_to_be_unknown_rather_than_flat() -> None:
    # The prompt has to say which of the two happened. An incident whose
    # metrics could not be read, described to the model as one where nothing
    # rose, gets prose explaining why a service that was fine had an outage -
    # and the prose will be fluent, because it always is.
    Scenario() \
        .given(
            an_incident_whose_metrics_could_not_be_read := a_measured_incident(
                error_rate_delta=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(),
                                an_incident_whose_metrics_could_not_be_read)
        ) \
        .then(
            _says("not known")
        )


@pytest.mark.unit
def test_the_model_is_asked_for_no_figure_of_its_own() -> None:
    # Every column is measured, so there is nothing here for a model to
    # compute. A tool that accepted a number would be offering it the one
    # opportunity the whole design exists to withhold.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM
        ) \
        .then(
            all_of(
                _asks_only_for(ROOT_CAUSE_FIELD, EXECUTIVE_SUMMARY_FIELD,
                               ASSUMPTIONS_FIELD),
                _requires(*REQUIRED_FIELDS),
                _accepts_no_number()
            )
        )


@pytest.mark.unit
def test_a_refusal_rides_on_the_call_it_refuses() -> None:
    # A provider that has seen a tool call expects its result next, and the
    # result is where a refusal belongs: the model sees what it submitted, is
    # told what was wrong with it, and corrects that - rather than writing a
    # fresh document from an instruction that arrived out of nowhere.
    #
    # Marked failed, which is how a tool result says "this is something to fix"
    # rather than "this is what I found out".
    asked = opening_ask(an_evidence_bundle(), a_measured_incident())

    Scenario() \
        .given(
            submitted := a_submission_of(an_answer(), SUBMIT_TOOL_NAME)
        ) \
        .when(
            lambda: rejecting(asked, submitted, [SOME_FAULT])
        ) \
        .then(
            all_of(
                _carries_the_submission(submitted),
                _answers_the_call(submitted.tool_calls[0].id),
                _refuses_it(),
                _says(SOME_FAULT)
            )
        )


@pytest.mark.unit
def test_a_model_that_submitted_nothing_is_asked_again_from_the_start() -> None:
    # The last resort, reachable only when there is no submission to refuse. It
    # repeats what was asked rather than referring back to it, because a
    # conversation the model did not take part in the shape of is not a
    # conversation to continue.
    asked = opening_ask(an_evidence_bundle(), a_measured_incident())

    Scenario() \
        .given(
            asked
        ) \
        .when(
            lambda: opening_ask_again(asked, [SOME_FAULT])
        ) \
        .then(
            all_of(
                _carries_no_submission(),
                _says(SOME_FAULT, SUBMIT_TOOL_NAME)
            )
        )


def _says(*expected: str) -> Assertion[Transcript]:
    """Everything Argus put in front of the model, in whichever shape.

    An ask and a tool result are different entries and the same act: the model
    is being told something. Which one carries it is asserted separately, by
    the tests about the shape of the second attempt.
    """
    def assertion(transcript: Transcript) -> bool:
        said = _what_was_said(transcript)

        missing = [wanted for wanted in expected if wanted not in said]
        if missing:
            raise AssertionError(
                f"expected the model to be told {missing}, and it was not: {said}")

        return True

    return assertion


def _carries_the_submission(submitted: Turn) -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        if submitted not in transcript:
            raise AssertionError(
                "expected the model's own submission to be carried back to it, "
                "and it was not")

        return True

    return assertion


def _carries_no_submission() -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        carried = [entry for entry in transcript
                   if isinstance(entry, Turn | ToolResults)]

        if carried:
            raise AssertionError(
                f"expected a fresh ask with nothing to answer, and it carried "
                f"{carried}")

        return True

    return assertion


def _answers_the_call(expected: str) -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        answering = [result.call_id
                     for entry in transcript if isinstance(entry, ToolResults)
                     for result in entry.results]

        if answering != [expected]:
            raise AssertionError(
                f"expected the result to answer call [{expected}], got {answering}")

        return True

    return assertion


def _refuses_it() -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        refused = [result.failed
                   for entry in transcript if isinstance(entry, ToolResults)
                   for result in entry.results]

        if refused != [True]:
            raise AssertionError(
                "expected the rejected submission to be marked failed, so the model "
                f"reads it as something to fix rather than as evidence, got {refused}")

        return True

    return assertion


def _asks_only_for(*expected: str) -> Assertion[ToolDefinition]:
    def assertion(tool: ToolDefinition) -> bool:
        if sorted(tool.properties) != sorted(expected):
            raise AssertionError(
                f"expected the tool to ask for {sorted(expected)}, got "
                f"{sorted(tool.properties)}")

        return True

    return assertion


def _requires(*expected: str) -> Assertion[ToolDefinition]:
    def assertion(tool: ToolDefinition) -> bool:
        if sorted(tool.required) != sorted(expected):
            raise AssertionError(
                f"expected the tool to require {sorted(expected)}, got "
                f"{sorted(tool.required)}")

        return True

    return assertion


def _accepts_no_number() -> Assertion[ToolDefinition]:
    """No field the model could answer with a figure.

    Not a matter of the prompt asking nicely: a field typed `number` is an
    invitation, and a model handed one fills it in.
    """
    def assertion(tool: ToolDefinition) -> bool:
        numeric = [field for field, described in tool.properties.items()
                   if described.get("type") in ("number", "integer")]

        if numeric:
            raise AssertionError(
                f"expected the model to be asked for no figure of its own, and it "
                f"was asked for {numeric}")

        return True

    return assertion


def _what_was_said(transcript: Transcript) -> str:
    said: list[str] = []

    for entry in transcript:
        if isinstance(entry, Ask):
            said.append(entry.text)
        elif isinstance(entry, ToolResults):
            said.extend(result.content for result in entry.results)

    return "\n".join(said)
