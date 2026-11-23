"""The sections a postmortem has beyond its figures, and what each refuses to
hold.

The shape is the agent's to fill, so the cases here are the states no section
may be written in - a pair of fields that say two things nobody could have
measured together - and the few things a section says of itself, which every
place showing it has to say alike.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_testkit import Scenario, an_error_was_raised, attempting, the_answer_was
from core.models import (
    CandidateConsidered,
    ChainStep,
    Detection,
    DetectionLesson,
    DetectionMeasuredFrom,
    HypothesisConsidered,
    NoVerdict,
    RuleSeriesHarm,
    TimelineEntry,
    Unit,
    Verdict,
    WhatBecame,
    within_what_was_accounted_for,
)
from pydantic import ValidationError

DONT_CARE_MOMENT = datetime(2026, 10, 19, 0, 12, tzinfo=UTC)
SOME_WHY = "the gate held its test back"


@pytest.mark.unit
def test_a_timeline_line_stored_before_it_said_whether_it_may_rule_out_is_not_known_never_to(
) -> None:
    # A document written before lines said so is still read, and nothing on its
    # lines says they rule nothing out - so a rule-out resting on one stays the
    # model's to say, as it did when the document was written.
    Scenario() \
        .when(
            lambda: TimelineEntry.model_validate(
                {"at": DONT_CARE_MOMENT, "who": None, "text": "dont care"}).may_rule_out
        ) \
        .then(
            the_answer_was(True)
        )


@pytest.mark.unit
def test_a_chain_step_stored_before_it_carried_what_was_ruled_out_rules_out_nothing() -> None:
    # A document written before the list existed is still read: its steps say
    # nothing of what was ruled out, which is an empty list, not a fault.
    Scenario() \
        .when(
            lambda: ChainStep.model_validate({"text": "dont care", "cites": []}).ruled_out
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
def test_detection_holding_a_rule_s_wait_and_saying_it_could_not_be_read_is_refused() -> None:
    # A wait that was read is not one that could not be: the page would say
    # both, and a reader could believe neither.
    Scenario() \
        .when(
            attempting(
                lambda: Detection(alerted_at=DONT_CARE_MOMENT, rule="dont care", onset_at=None,
                                  gap=None, rule_waits=timedelta(minutes=5),
                                  rule_wait_unread=True)
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_a_merged_candidate_not_the_one_tested_has_the_result_as_the_tested_one_s() -> None:
    # The page and the brief both say it, and in one spelling: two wordings of
    # one fact read as two facts.
    Scenario() \
        .given(
            hypothesis := _a_merged_hypothesis(result="confirmed", decided_by="C1")
        ) \
        .when(
            lambda: hypothesis.result_of(hypothesis.members[1])
        ) \
        .then(
            the_answer_was("confirmed, as tested for C1")
        )


@pytest.mark.parametrize(("decided_by", "result"), [("C1", "confirmed"),
                                                    (None, "never tried")])
@pytest.mark.unit
def test_a_merged_candidate_tested_itself_or_where_none_was_has_the_result_bare(
        decided_by: str | None, result: str) -> None:
    # Its own test is no other's to credit, and with no test there is none.
    Scenario() \
        .given(
            hypothesis := _a_merged_hypothesis(result=result, decided_by=decided_by)
        ) \
        .when(
            lambda: hypothesis.result_of(hypothesis.members[0])
        ) \
        .then(
            the_answer_was(result)
        )


# Each the words the brief carried before what became of a cause was a value,
# spelled out here rather than read off the members: the model's input is pinned
# by these bytes, and a test reading them from the code under test would pass
# whatever the code came to say.
@pytest.mark.parametrize(("became", "words"), [
    (WhatBecame(verdict=Verdict.CONFIRMED), "confirmed"),
    (WhatBecame(verdict=Verdict.REFUTED), "refuted"),
    (WhatBecame(no_verdict=NoVerdict.NEVER_TRIED), "never tried"),
    (WhatBecame(no_verdict=NoVerdict.NEVER_TRIED, why=SOME_WHY), f"never tried: {SOME_WHY}"),
    (WhatBecame(no_verdict=NoVerdict.ACTION_NOT_TAKEN), "action not taken"),
    (WhatBecame(no_verdict=NoVerdict.ACTION_NOT_TAKEN, why=SOME_WHY),
     f"action not taken: {SOME_WHY}"),
    (WhatBecame(no_verdict=NoVerdict.TRIED_NOT_JUDGED), "tried, not judged"),
    (WhatBecame(no_verdict=NoVerdict.TRIED_NO_VERDICT_RECORDED), "tried, no verdict recorded"),
    (WhatBecame(no_verdict=NoVerdict.NOT_KNOWN_WHETHER_TRIED), "not known whether tried"),
    (WhatBecame(no_verdict=NoVerdict.NO_VERDICT_RECORDED), "no verdict recorded")
], ids=["confirmed", "refuted", "never-tried", "never-tried-and-why", "action-not-taken",
        "action-not-taken-and-why", "tried-not-judged", "tried-no-verdict-recorded",
        "not-known-whether-tried", "no-verdict-recorded"])
@pytest.mark.unit
def test_what_became_of_a_cause_is_said_in_the_words_the_brief_always_carried(
        became: WhatBecame, words: str) -> None:
    Scenario() \
        .when(
            lambda: became.said
        ) \
        .then(
            the_answer_was(words)
        )


@pytest.mark.parametrize(("became", "never_tried"), [
    (WhatBecame(no_verdict=NoVerdict.NEVER_TRIED), True),
    (WhatBecame(no_verdict=NoVerdict.ACTION_NOT_TAKEN, why=SOME_WHY), True),
    (WhatBecame(no_verdict=NoVerdict.TRIED_NOT_JUDGED), False),
    (WhatBecame(no_verdict=NoVerdict.TRIED_NO_VERDICT_RECORDED), False),
    (WhatBecame(no_verdict=NoVerdict.NOT_KNOWN_WHETHER_TRIED), False),
    (WhatBecame(no_verdict=NoVerdict.NO_VERDICT_RECORDED), False),
    (WhatBecame(verdict=Verdict.REFUTED), False)
], ids=["never-tried", "action-not-taken", "tried-not-judged", "tried-no-verdict-recorded",
        "not-known-whether-tried", "no-verdict-recorded", "refuted"])
@pytest.mark.unit
def test_a_cause_was_never_tried_only_where_nobody_reached_it_or_its_action_was_not_taken(
        became: WhatBecame, never_tried: bool) -> None:
    # A cause whose action may have changed the service, or did, was tried, or
    # may have been - and a review counting it as never tried would say none was.
    Scenario() \
        .when(
            lambda: became.was_never_tried
        ) \
        .then(
            the_answer_was(never_tried)
        )


@pytest.mark.parametrize("fields", [
    {},
    {"verdict": Verdict.CONFIRMED, "no_verdict": NoVerdict.NEVER_TRIED},
    {"verdict": Verdict.REFUTED, "why": SOME_WHY},
    {"no_verdict": NoVerdict.TRIED_NOT_JUDGED, "why": SOME_WHY}
], ids=["neither", "both", "a-verdict-with-why", "tried-with-why"])
@pytest.mark.unit
def test_what_became_of_a_cause_is_one_thing_and_says_why_only_where_it_was_never_tried(
        fields: dict[str, object]) -> None:
    # Two things at once, or nothing, is a row the page and the review read
    # differently; and a why is the gate's or a tier's words for a test held
    # back, which nothing tried or judged has.
    Scenario() \
        .when(
            attempting(lambda: WhatBecame.model_validate(fields))
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_a_row_saying_one_thing_of_a_cause_that_came_to_another_is_refused() -> None:
    # The words are what the page shows and the value is what the review
    # decides by: apart, the two say different things of one row.
    Scenario() \
        .when(
            attempting(lambda: HypothesisConsidered(
                summary="dont care", confidence=None, label="C1",
                result="confirmed", became=WhatBecame(verdict=Verdict.REFUTED)))
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


@pytest.mark.unit
def test_a_row_stored_before_what_became_of_its_cause_was_a_value_is_read_without_one() -> None:
    # A document written before it was carried is still read, its words whole.
    Scenario() \
        .when(
            lambda: HypothesisConsidered.model_validate(
                {"summary": "dont care", "confidence": None, "result": "never tried",
                 "label": "C1"}).became
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.parametrize(("gap", "within"), [
    (timedelta(minutes=7, seconds=30), True),
    (timedelta(minutes=7, seconds=31), False)
], ids=["at-what-was-accounted-for", "a-second-past-it"])
@pytest.mark.unit
def test_an_alert_is_within_what_was_accounted_for_to_the_second(
        gap: timedelta, within: bool) -> None:
    Scenario() \
        .when(
            lambda: within_what_was_accounted_for(DetectionLesson(
                gap=gap, measured_from=DetectionMeasuredFrom.LINE_PASSED,
                rule_waits=timedelta(minutes=5), rule_looks_back=timedelta(0),
                rule_evaluated_every=timedelta(minutes=1),
                scraping_and_storing=timedelta(seconds=30)))
        ) \
        .then(
            the_answer_was(within)
        )


@pytest.mark.unit
@pytest.mark.parametrize("unit", [Unit.MILLISECONDS, None], ids=["named", "unnamed"])
def test_the_harm_to_the_paging_rule_s_series_carries_its_unit(unit: Unit | None) -> None:
    # The page says the levels in it, as the brief does; unnamed is unknown,
    # which a document written before the unit was carried reads as.
    Scenario() \
        .when(
            lambda: RuleSeriesHarm(before=120.0, while_broken=640.0, at_its_worst=910.0,
                                   worse_when="above", unit=unit).unit
        ) \
        .then(
            the_answer_was(unit)
        )


def _a_merged_hypothesis(result: str, decided_by: str | None) -> HypothesisConsidered:
    return HypothesisConsidered(
        summary="dont care", confidence=None, result=result, label="C1", also=["C2"],
        members=[CandidateConsidered(label="C1", summary="dont care", confidence=None,
                                     failure_mode=None),
                 CandidateConsidered(label="C2", summary="dont care", confidence=None,
                                     failure_mode=None)],
        decided_by=decided_by)
