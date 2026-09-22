"""Something that changed before the incident did, and how little it may say.

The third retrieval channel, and the only one whose rows Argus does not
produce: a deploy pipeline or a flag provider reports them, each in its own
shape and its own level of detail. So the rules here divide into what a source
may omit and still be believed, and what it may not.

It may omit who. A pipeline that does not name the person who triggered a
release still reports a real release, and dropping it for want of a name would
lose the evidence the channel exists for.

It may not omit when, nor invent a kind. The channel answers "what changed
*before* this started", which an undated change cannot answer at all - and a
model weighing a deploy against a flag flip needs those to be two distinct
values rather than two spellings that happen to differ.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.timestamps import to_iso_minute
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    the_error_mentioned,
)
from pydantic import ValidationError

DONT_CARE_REFERENCE = "9f4c1e7b2a"
DONT_CARE_SUMMARY = "deployed something"


@pytest.mark.unit
def test_a_deploy_event_carries_what_changed_and_when() -> None:
    some_moment = to_iso_minute(datetime(2026, 8, 20, 11, 5, tzinfo=UTC))
    some_revision = "9f4c1e7b2a"

    Scenario() \
        .given(
            some_deploy := (some_moment, some_revision)
        ) \
        .when(
            lambda: a_deploy_at(some_deploy[0], reference=some_deploy[1])
        ) \
        .then(
            _it_recorded(
                kind=ChangeKind.DEPLOY, occurred_at=some_moment, reference=some_revision
            )
        )


@pytest.mark.unit
def test_a_change_event_needs_no_actor() -> None:
    # A source that does not say who triggered a change still reports a real
    # change - dropping it for want of a name would lose the evidence.
    Scenario() \
        .given(
            dont_care_moment := an_iso_minute()
        ) \
        .when(
            lambda: ChangeEvent(
                kind=ChangeKind.DEPLOY,
                occurred_at=dont_care_moment,
                reference=DONT_CARE_REFERENCE,
                summary=DONT_CARE_SUMMARY
            )
        ) \
        .then(
            _nothing_was_assumed_about("actor", "source")
        )


@pytest.mark.unit
def test_a_change_event_without_a_time_is_rejected() -> None:
    # The whole channel exists to answer "what changed *before* this started",
    # which an undated change cannot answer.
    #
    # Validated from a dict rather than constructed: this is what arrives from
    # a vendor's response, where nothing has checked the shape yet. Calling the
    # constructor with a field missing would not type-check, which is the
    # point - the failure being guarded against can only come from outside.
    Scenario() \
        .given(
            a_change_with_no_time := {
                "kind": ChangeKind.DEPLOY,
                "reference": DONT_CARE_REFERENCE,
                "summary": DONT_CARE_SUMMARY
            }
        ) \
        .when(
            attempting(lambda: ChangeEvent.model_validate(a_change_with_no_time))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("occurred_at")
            )
        )


@pytest.mark.unit
def test_a_kind_outside_the_taxonomy_is_rejected() -> None:
    # The kind is a closed set for the same reason `FailureMode` is: a model
    # weighing a deploy against a flag flip needs the two to be distinct
    # values, not free text that happens to differ.
    some_kind_of_non_ChangeKind_type = "kukibuki"

    Scenario() \
        .given(
            a_change_of_no_known_kind := {
                "kind": some_kind_of_non_ChangeKind_type,
                "occurred_at": an_iso_minute(),
                "reference": DONT_CARE_REFERENCE,
                "summary": DONT_CARE_SUMMARY
            }
        ) \
        .when(
            attempting(lambda: ChangeEvent.model_validate(a_change_of_no_known_kind))
        ) \
        .then(
            all_of(
                an_error_was_raised(ValidationError),
                the_error_mentioned("kind")
            )
        )


def an_iso_minute() -> str:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 0
    return to_iso_minute(datetime(
        some_year, some_month, some_day, some_hour, some_minute, tzinfo=UTC))


def a_deploy_at(occurred_at: str, reference: str) -> ChangeEvent:
    some_summary = f"deployed {reference}"
    some_actor = "kuki"
    some_source = "https://github.com/kuki/k8s-configs"

    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=occurred_at,
        reference=reference,
        summary=some_summary,
        actor=some_actor,
        source=some_source
    )


def _it_recorded(kind: ChangeKind,
                 occurred_at: str,
                 reference: str) -> Assertion[ChangeEvent]:
    """The three fields that make a change usable as evidence, together.

    Together rather than one at a time, because what a reader does with a
    change is weigh all three at once - a row with the right revision at the
    wrong minute is worse than no row, and a run of assertions that stopped at
    the first failure would report whichever happened to be checked first.
    """
    def assertion(change: ChangeEvent) -> bool:
        wanted = {"kind": kind, "occurred_at": occurred_at, "reference": reference}
        wrong = {
            field: (expected, getattr(change, field))
            for field, expected in wanted.items()
            if getattr(change, field) != expected
        }
        if wrong:
            raise AssertionError(
                f"Expected the change to record {wanted}, and {wrong} differed "
                f"(expected, got)."
            )

        return True

    return assertion


def _nothing_was_assumed_about(*fields: str) -> Assertion[ChangeEvent]:
    """That each named field came back `None` rather than filled in.

    Named together rather than checked one at a time, because the claim is
    about the model's posture towards what the source did not say - and a
    field that quietly grew a default would pass a test written about its
    neighbour.
    """
    def assertion(change: ChangeEvent) -> bool:
        assumed = {field: getattr(change, field) for field in fields}
        filled = {field: value for field, value in assumed.items() if value is not None}

        if filled:
            raise AssertionError(f"Expected nothing assumed, got {filled}.")

        return True

    return assertion
