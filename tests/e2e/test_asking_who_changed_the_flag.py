from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from agent_mitigation.tools import argus_changed_flag_since, set_flag
from argus_testkit import Assertion, Scenario, all_of

from .framework.flags import THE_DEMO_FLAG, THE_FALLBACK_FLAG

"""Whether Argus can recognise its own change in the provider's log.

The one question a resumed walk asks the provider, and the one thing no unit
test can answer: it turns on whether the actor Argus is configured with is the
name the provider actually records against its writes. Those two are set in
different repositories, and a drift between them switches the recognition off
silently - the failure this exists to catch.
"""

# Before anything this test does, so a change it makes cannot be missed for
# having been made a moment too early.
A_MOMENT_AGO = timedelta(seconds=30)


@pytest.mark.e2e
def test_argus_recognises_the_change_it_made_and_no_other() -> None:
    since = datetime.now(UTC) - A_MOMENT_AGO

    Scenario() \
        .given(
            _argus_changed(THE_DEMO_FLAG)
        ) \
        .when(
            argus_changed_flag_since(THE_DEMO_FLAG, since)
        ) \
        .then(all_of(
            _the_answer_is(True),
            _a_flag_argus_did_not_touch_answers(THE_FALLBACK_FLAG, since, False),
        ))


def _argus_changed(flag: str) -> Callable[[], bool]:
    """A change made through Argus's own write path, so the provider attributes
    it exactly as it would during an incident."""
    def step() -> bool:
        set_flag(flag, enabled=True)

        return True

    return step


def _the_answer_is(expected: bool) -> Assertion[Any]:
    def assertion(answered: Any) -> bool:
        if answered is not expected:
            raise AssertionError(
                f"Expected the provider's log to answer [{expected}] for a flag "
                f"Argus changed, got [{answered!r}]. `None` means the actor "
                f"Argus is configured with is not the one the provider records."
            )

        return True

    return assertion


def _a_flag_argus_did_not_touch_answers(flag: str,
                                        since: datetime,
                                        expected: bool) -> Assertion[Any]:
    def assertion(_answered: Any) -> bool:
        answered = argus_changed_flag_since(flag, since)

        if answered is not expected:
            raise AssertionError(
                f"Expected [{expected}] for [{flag}], which Argus did not touch, "
                f"got [{answered!r}]."
            )

        return True

    return assertion
