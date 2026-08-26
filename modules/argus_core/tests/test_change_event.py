from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.timestamps import to_iso_minute
from pydantic import ValidationError


@pytest.mark.unit
def test_a_deploy_event_carries_what_changed_and_when() -> None:
    some_moment = to_iso_minute(datetime(2026, 8, 20, 11, 5, tzinfo=UTC))
    some_revision = "9f4c1e7b2a"

    change = a_deploy_at(some_moment, reference=some_revision)

    assert change.kind == ChangeKind.DEPLOY
    assert change.occurred_at == some_moment
    assert change.reference == some_revision


@pytest.mark.unit
def test_a_change_event_needs_no_actor() -> None:
    # A source that does not say who triggered a change still reports a real
    # change - dropping it for want of a name would lose the evidence.
    dont_care_moment = an_iso_minute()
    dont_care_reference = "9f4c1e7b2a"
    dont_care_summary = "deployed something"

    change = ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=dont_care_moment,
        reference=dont_care_reference,
        summary=dont_care_summary
    )

    assert change.actor is None
    assert change.source is None


@pytest.mark.unit
def test_a_change_event_without_a_time_is_rejected() -> None:
    # The whole channel exists to answer "what changed *before* this started",
    # which an undated change cannot answer.
    #
    # Validated from a dict rather than constructed: this is what arrives from
    # a vendor's response, where nothing has checked the shape yet. Calling the
    # constructor with a field missing would not type-check, which is the
    # point - the failure being guarded against can only come from outside.
    dont_care_reference = "9f4c1e7b2a"
    dont_care_summary = "deployed something"

    a_change_with_no_time = {
        "kind": ChangeKind.DEPLOY,
        "reference": dont_care_reference,
        "summary": dont_care_summary
    }

    with pytest.raises(ValidationError, match="occurred_at"):
        ChangeEvent.model_validate(a_change_with_no_time)


@pytest.mark.unit
def test_a_kind_outside_the_taxonomy_is_rejected() -> None:
    # The kind is a closed set for the same reason `CauseType` is: a model
    # weighing a deploy against a flag flip needs the two to be distinct
    # values, not free text that happens to differ.
    dont_care_reference = "9f4c1e7b2a"
    dont_care_summary = "deployed something"
    some_kind_of_non_ChangeKind_type = "kukibuki"

    a_change_of_no_known_kind = {
        "kind": some_kind_of_non_ChangeKind_type,
        "occurred_at": an_iso_minute(),
        "reference": dont_care_reference,
        "summary": dont_care_summary
    }

    with pytest.raises(ValidationError, match="kind"):
        ChangeEvent.model_validate(a_change_of_no_known_kind)


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
