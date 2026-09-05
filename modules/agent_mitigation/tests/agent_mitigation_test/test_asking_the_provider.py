from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agent_mitigation.tools import argus_changed_flag_since
from argus_core.models.flag_change import FlagChange

"""Asking the flag provider whether a half-finished action actually landed.

A worker that died between taking an action and recording what came of it
leaves a claim with no outcome. Only the provider knows whether the change was
made, and this is the one place Argus asks it that question about itself.
"""

SOME_FLAG = "monthly-spend-feature"
THE_MOMENT_IT_WAS_CLAIMED = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)


@pytest.mark.unit
def test_a_provider_that_cannot_be_reached_answers_nothing() -> None:
    # The case that must not read as "no change was made": an unreachable
    # provider would then send the walk off to act a second time on an action
    # that may already have been taken.
    def fetch_that_fails(since: str) -> list[FlagChange]:
        raise ConnectionError("the write tier is down")

    assert argus_changed_flag_since(
        SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, fetch=fetch_that_fails
    ) is None


@pytest.mark.unit
def test_the_provider_is_asked_from_the_moment_the_action_was_claimed() -> None:
    # A change to the same flag before the claim belongs to whoever caused the
    # incident. Only one after it can be the attempt that stopped halfway.
    asked_from: list[str] = []

    def fetch_recording_its_window(since: str) -> list[FlagChange]:
        asked_from.append(since)

        return []

    argus_changed_flag_since(
        SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, fetch=fetch_recording_its_window
    )

    assert asked_from == ["2026-09-04T22:15:00Z"]
