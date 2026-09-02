from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from agent_postmortem import IncidentEvidence, PostmortemDocument, write_postmortem
from agent_postmortem.prompting import ROOT_CAUSE_FIELD
from agent_postmortem.sources import Engagement, EngagementAnswer, Metrics, Revenue
from argus_core.llm.client import LLMClient
from argus_core.models.metrics import MetricBucket
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import Ask, ToolResults, Transcript
from argus_core.models.turn import ToolCall, Turn
from argus_testkit import Assertion, Kept, Scenario, all_of

"""The one second chance, and the two things that earn it.

A field the model left out, and a figure it made up. They are checked
together because they are answered together: one further call naming what was
wrong with the first, and then the document is written from whatever comes
back. There is no third attempt - an incident that is over is not improved by
an agent that will not stop, and `checklist_complete` exists to say the
document is partial.

The invented figure is the subtler of the two. Columns are safe from the model
by construction, but the executive summary is published as written, so a
sentence claiming a number Argus never computed reaches the one reader least
able to check it.
"""

INCIDENT_START = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
INCIDENT_END = INCIDENT_START + timedelta(minutes=30)

DONT_CARE_INCIDENT_ID = "e5e5e5e5-0000-4000-8000-000000000005"
DONT_CARE_TOKENS_SPENT = 1_000
DONT_CARE_HOURLY_REVENUE = 4_800
DONT_CARE_REVENUE_WINDOW = timedelta(hours=1)
DONT_CARE_ENGAGED_MINUTES = 25
DONT_CARE_RESPONDERS = 2
DONT_CARE_IMPACT_WEIGHT = 0.5

# What those figures come to: 4800 an hour, half an hour, a 28% rise in
# errors, half of it on a path that carried revenue.
THE_COMPUTED_ESTIMATE = "$336"


@pytest.mark.unit
def test_an_answer_missing_a_field_is_asked_for_again_naming_what_was_missing() -> None:
    # Naming it matters as much as asking again. A model told only that its
    # answer was wrong will rewrite the part it liked least, which is rarely
    # the part that was missing.
    some_required_field = ROOT_CAUSE_FIELD
    the_mandatory_field_returned_in_the_second_time = "the checkout fallback was disabled"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_answering(
                    _an_answer_without(some_required_field),
                    _an_answer(
                        **{some_required_field: the_mandatory_field_returned_in_the_second_time}),
                    recording_into=asks))
        ) \
        .then(
            all_of(
                _was_asked_twice(asks),
                _the_correction_answered_the_call_it_rejected(asks),
                _the_correction_named(asks, some_required_field),
                _reports(some_required_field, the_mandatory_field_returned_in_the_second_time),
                _is_marked_complete()
            )
        )


@pytest.mark.unit
def test_a_second_answer_that_is_still_missing_a_field_is_written_down_anyway() -> None:
    # The terminating case. Whatever came back is the postmortem, marked for
    # what it is: a document that says it is partial is worth more than an
    # agent still trying while the incident is over.
    some_required_field = ROOT_CAUSE_FIELD
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_answering(
                    _an_answer_without(some_required_field),
                    _an_answer_without(some_required_field),
                    recording_into=asks))
        ) \
        .then(
            all_of(
                _was_asked_twice(asks),
                _is_marked_incomplete()
            )
        )


@pytest.mark.unit
def test_a_summary_naming_a_figure_argus_never_computed_is_asked_for_again() -> None:
    # The whole reason this check exists. Nothing downstream can tell that
    # "$1.2M" was invented: it is a fluent sentence in a document whose every
    # other number is measured.
    some_invented_figure = "$1,200,000"
    some_summary_without_a_figure = "checkout failed for half an hour"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_answering(
                    _an_answer(executive_summary=f"the outage cost {some_invented_figure}"),
                    _an_answer(executive_summary=some_summary_without_a_figure),
                    recording_into=asks))
        ) \
        .then(
            all_of(
                _was_asked_twice(asks),
                _the_correction_named(asks, some_invented_figure),
                _reports_executive_summary(some_summary_without_a_figure)
            )
        )


@pytest.mark.unit
def test_a_summary_naming_the_computed_figure_is_accepted() -> None:
    # The check is on figures Argus did not arrive at, not on figures. A
    # summary forbidden to mention what the incident cost would be a summary
    # written for nobody.
    some_computed_figure = THE_COMPUTED_ESTIMATE
    some_summary_stating_the_figure = f"the outage cost roughly {some_computed_figure}"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_answering(
                    _an_answer(executive_summary=some_summary_stating_the_figure),
                    recording_into=asks))
        ) \
        .then(
            all_of(
                _was_asked_once(asks),
                _reports_executive_summary(some_summary_stating_the_figure)
            )
        )


@pytest.mark.unit
def test_a_summary_naming_any_figure_at_all_is_challenged_when_nothing_was_computed() -> None:
    # With no estimate there is nothing for a figure to agree with, so every
    # figure is invented by definition - and this is the common case today,
    # since no revenue source exists yet.
    asks: Kept[Transcript] = Kept()
    some_figure = "$4,000"

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: write_postmortem(
                an_evidence_bundle,
                revenue=_a_revenue_source_that_cannot_answer(),
                engagement=_an_engagement_source_reporting(),
                metrics=_metrics_showing_a_rise(),
                llm=_a_model_answering(
                    _an_answer(executive_summary=f"the outage cost {some_figure}"),
                    _an_answer(executive_summary="checkout failed for half an hour"),
                    recording_into=asks))
        ) \
        .then(
            all_of(
                _was_asked_twice(asks),
                _the_correction_named(asks, some_figure)
            )
        )


@pytest.mark.unit
def test_a_model_that_ignored_the_tool_is_asked_again_from_the_beginning() -> None:
    # There is no call to answer, so the correction cannot be a tool result:
    # a rejection has to be attached to something the model submitted, and
    # this model submitted a paragraph. The whole incident goes again.
    some_required_field = ROOT_CAUSE_FIELD
    the_mandatory_field_returned_in_the_second_time = "the checkout fallback was disabled"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_answering_in_prose_then(
                    _an_answer(**{
                        some_required_field: the_mandatory_field_returned_in_the_second_time}),
                    recording_into=asks))
        ) \
        .then(
            all_of(
                _was_asked_twice(asks),
                _the_correction_was_a_fresh_ask(asks),
                _reports(some_required_field, the_mandatory_field_returned_in_the_second_time),
                _is_marked_complete()
            )
        )


@pytest.mark.unit
def test_a_model_that_ignores_the_tool_twice_is_written_down_as_incomplete() -> None:
    # The terminating case for the other shape of bad answer. Two paragraphs
    # is not one attempt away from a document.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            an_evidence_bundle := _an_evidence_bundle()
        ) \
        .when(
            lambda: _a_postmortem_written_with(
                an_evidence_bundle,
                llm=_a_model_answering_in_prose_then(recording_into=asks))
        ) \
        .then(
            all_of(
                _was_asked_twice(asks),
                _is_marked_incomplete()
            )
        )


def _a_postmortem_written_with(evidence: IncidentEvidence,
                               llm: LLMClient) -> PostmortemDocument:
    return write_postmortem(
        evidence,
        revenue=_a_revenue_source_reporting(DONT_CARE_HOURLY_REVENUE),
        engagement=_an_engagement_source_reporting(),
        metrics=_metrics_showing_a_rise(),
        llm=llm
    )


def _an_evidence_bundle() -> IncidentEvidence:
    return IncidentEvidence(
        incident_id=DONT_CARE_INCIDENT_ID,
        started_at=INCIDENT_START,
        ended_at=INCIDENT_END,
        alert_summary="dont care",
        timeline=["dont care"],
        candidates=["dont care"],
        actions=["dont care"],
        log_lines=["dont care"],
        tokens_spent=DONT_CARE_TOKENS_SPENT
    )


def _an_answer(root_cause: str = "dont care",
               executive_summary: str = "dont care") -> dict[str, Any]:
    return {
        "root_cause": root_cause,
        "executive_summary": executive_summary,
        "impact_weight": DONT_CARE_IMPACT_WEIGHT,
        "impact_weight_reason": "dont care",
        "assumptions": []
    }


def _an_answer_without(field: str) -> dict[str, Any]:
    answer = _an_answer()
    del answer[field]

    return answer


def _a_model_answering(*answers: dict[str, Any],
                       recording_into: Kept[Transcript]) -> LLMClient:
    """Answers each call from the list in turn, keeping what it was asked.

    A model that ran out of answers has been called more times than the test
    allows for, which is itself a failure - so it says so rather than
    repeating its last one, where an extra call would look like a pass.
    """
    class InTurn:
        def __init__(self) -> None:
            self._remaining = list(answers)

        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            recording_into.take(transcript)

            if not self._remaining:
                raise AssertionError("the model was called more times than the test expected")

            return Turn(
                text="",
                tool_calls=[ToolCall(id="call_1",
                                     name=tools[0].name,
                                     arguments=self._remaining.pop(0))],
                input_tokens=0,
                output_tokens=0
            )

    return InTurn()


def _a_model_answering_in_prose_then(*answers: dict[str, Any],
                                     recording_into: Kept[Transcript]) -> LLMClient:
    """Writes a paragraph first, then whatever it was given - or another one.

    A model that ignored the tool it was offered. It answered, and answered
    uselessly: nothing in a paragraph can be read into a field.
    """
    class ProseFirst:
        def __init__(self) -> None:
            self._still_to_come = list(answers)
            self._has_written_prose = False

        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int = 4096) -> Turn:
            recording_into.take(transcript)

            if not self._has_written_prose:
                self._has_written_prose = True

                return Turn(text="The incident was caused by a feature flag.",
                            tool_calls=[], input_tokens=0, output_tokens=0)

            if not self._still_to_come:
                return Turn(text="It was definitely a feature flag.",
                            tool_calls=[], input_tokens=0, output_tokens=0)

            return Turn(
                text="",
                tool_calls=[ToolCall(id="call_1",
                                     name=tools[0].name,
                                     arguments=self._still_to_come.pop(0))],
                input_tokens=0,
                output_tokens=0
            )

    return ProseFirst()


def _a_revenue_source_reporting(amount: float) -> Revenue:
    def revenue_between(window_start: datetime, window_end: datetime) -> Decimal | None:
        return Decimal(amount * (window_end - window_start) / DONT_CARE_REVENUE_WINDOW)

    return revenue_between


def _a_revenue_source_that_cannot_answer() -> Revenue:
    def revenue_between(dont_care_start: datetime, dont_care_end: datetime) -> Decimal | None:
        return None

    return revenue_between


def _an_engagement_source_reporting() -> Engagement:
    def engagement_for(dont_care_incident_id: str) -> EngagementAnswer | None:
        return EngagementAnswer(minutes=DONT_CARE_ENGAGED_MINUTES,
                                responders=DONT_CARE_RESPONDERS)

    return engagement_for


def _metrics_showing_a_rise() -> Metrics:
    def metrics_between(dont_care_start: datetime, dont_care_end: datetime) -> list[MetricBucket]:
        return [
            _a_bucket(at=INCIDENT_START - timedelta(minutes=1), error_rate=0.02),
            _a_bucket(at=INCIDENT_START + timedelta(minutes=5), error_rate=0.30)
        ]

    return metrics_between


def _a_bucket(at: datetime, error_rate: float) -> MetricBucket:
    return MetricBucket(
        bucket_id=at.strftime("%Y-%m-%dT%H:%M"),
        error_rate=error_rate,
        p50_ms=20,
        p95_ms=40,
        request_volume=1_000
    )


def _was_asked_once(asks: Kept[Transcript]) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        if len(asks.taken) != 1:
            raise AssertionError(f"expected one model call, got [{len(asks.taken)}]")

        return True

    return assertion


def _was_asked_twice(asks: Kept[Transcript]) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        if len(asks.taken) != 2:
            raise AssertionError(f"expected two model calls, got [{len(asks.taken)}]")

        return True

    return assertion


def _the_correction_named(asks: Kept[Transcript], expected: str) -> Assertion[PostmortemDocument]:
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        said = _what_was_said_to_the_model(asks.taken[1])

        if expected not in said:
            raise AssertionError(
                f"expected the correction to name [{expected}], and it did not: {said}")

        return True

    return assertion


def _the_correction_was_a_fresh_ask(asks: Kept[Transcript]) -> Assertion[PostmortemDocument]:
    """Asked again from the start, with nothing to answer.

    The counterpart to `_the_correction_answered_the_call_it_rejected`: where
    there was a submission the correction rides on it, and where there was
    none it cannot.
    """
    def assertion(dont_care_document: PostmortemDocument) -> bool:
        carried = [entry for entry in asks.taken[1]
                   if isinstance(entry, Turn | ToolResults)]

        if carried:
            raise AssertionError(
                f"expected the correction to be a fresh ask, and it carried {carried}")

        return True

    return assertion

def _reports_root_cause(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.root_cause != expected:
            raise AssertionError(
                f"expected the root cause [{expected}], got [{document.root_cause}]")

        return True

    return assertion


def _reports_executive_summary(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.executive_summary != expected:
            raise AssertionError(
                f"expected the summary [{expected}], got [{document.executive_summary}]")

        return True

    return assertion


def _reports(field: str, expected: str) -> Assertion[PostmortemDocument]:
    """The document's field of that name, whichever field the test is about.

    Leans on the tool's field names and the document's being the same words -
    which they are, deliberately: a document whose fields were named
    differently from the answer they come from would need a mapping nobody
    would keep correct.
    """
    def assertion(document: PostmortemDocument) -> bool:
        actual = getattr(document, field)

        if actual != expected:
            raise AssertionError(f"expected [{field}] to be [{expected}], got [{actual}]")

        return True

    return assertion


def _is_marked_complete() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if not document.checklist_complete:
            raise AssertionError("expected a complete document to be marked complete")

        return True

    return assertion


def _is_marked_incomplete() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.checklist_complete:
            raise AssertionError("expected a document still missing a field to say so")

        return True

    return assertion


def _what_was_said_to_the_model(transcript: Transcript) -> str:
    """Everything Argus put in front of the model, in whichever shape.

    A fault can arrive as prose in an ask or as the result of the tool call it
    rejects. Which one it is is the code's business; this file only cares that
    the model was told.
    """
    said: list[str] = []

    for entry in transcript:
        if isinstance(entry, Ask):
            said.append(entry.text)
        elif isinstance(entry, ToolResults):
            said.extend(result.content for result in entry.results)

    return "\n".join(said)


def _the_correction_answered_the_call_it_rejected(
        asks: Kept[Transcript]) -> Assertion[PostmortemDocument]:
    """The correction is the tool call's result, not a second conversation.

    A provider that has seen a tool call expects its result next, and the
    result is where a rejection belongs: the model sees what it submitted, is
    told what was wrong with it, and answers in the same exchange - rather
    than being handed the whole incident again as though it had never
    answered at all.
    """
    def assertion(dont_care_document: PostmortemDocument) -> bool:
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
                f"expected the result to answer call [{expected_call_id}], got {answering}")

        if not answered[0].results[0].failed:
            raise AssertionError(
                "expected the rejected submission to be marked failed, so the model "
                "reads it as something to fix rather than as evidence")

        return True

    return assertion
