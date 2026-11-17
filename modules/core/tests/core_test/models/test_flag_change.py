"""A recorded flag toggle, and what a row stored before Argus could say whose it was
reads as.

`made_by_argus` is worked out by the provider's adapter from who the provider
says made the change. A toggle recorded before the adapter said so - in an
incident's events, which are kept - said nothing about it, and nothing is not a
"no": read as `False`, a toggle Argus made would come back as somebody else's.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from core.models import FlagChange


@pytest.mark.unit
def test_a_toggle_recorded_without_saying_whose_it_was_reads_as_nobody_can_say() -> None:
    Scenario() \
        .given(
            a_toggle_recorded_before_it_was_said := {
                "flag": "monthly-spend-feature",
                "enabled": True,
                "occurred_at": "2026-08-20T11:04:38Z",
                "actor": "dont-care-actor"
            }
        ) \
        .when(
            lambda: FlagChange.model_validate(a_toggle_recorded_before_it_was_said).made_by_argus
        ) \
        .then(
            the_answer_was(None)
        )
