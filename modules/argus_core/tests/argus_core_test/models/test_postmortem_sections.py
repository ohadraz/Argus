"""The sections a postmortem has beyond its figures, and what each refuses to
hold.

The shape is the agent's to fill, so the cases here are the states no section
may be written in - a pair of fields that say two things nobody could have
measured together.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import Detection
from argus_testkit import Scenario, an_error_was_raised, attempting
from pydantic import ValidationError

DONT_CARE_MOMENT = datetime(2026, 10, 19, 0, 12, tzinfo=UTC)


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
