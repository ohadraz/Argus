"""The deliverer's loop, which never returns and so is driven through its sleep.

What one pass delivers is asserted against a real store and database in this
module's component tests. What belongs here is the loop's one decision: a pass
that failed is said and slept off, because the records it did not deliver are
still waiting and the next pass is the retry.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit import Scenario, attempting, one_record_was_logged
from incident_memory.delivering import Pass, deliver_forever

DONT_CARE_INTERVAL_SECONDS = 2.0


@pytest.mark.unit
def test_a_pass_that_failed_is_logged_as_a_warning_and_slept_off(
    caplog: pytest.LogCaptureFixture
) -> None:
    # A warning rather than an error: nobody has to act. The records are still
    # waiting when the loop next wakes, and nothing a walk waits on is behind
    # them.
    Scenario() \
        .when(
            attempting(
                lambda: deliver_forever(
                    DONT_CARE_INTERVAL_SECONDS,
                    _a_pass_that_fails_with(ConnectionError("connection refused")),
                    sleep=_a_sleep_that_ends_the_loop()
                )
            )
        ) \
        .then(
            one_record_was_logged(caplog, "incident_memory.delivering", logging.WARNING,
                                  "delivery pass failed",
                                  failure=ConnectionError)
        )


def _a_pass_that_fails_with(error: Exception) -> Any:
    return create_autospec(Pass, instance=True, side_effect=error)


class _TheLoopWasEnded(Exception):
    """Raised from the loop's first sleep, which is the only way out of it."""


def _a_sleep_that_ends_the_loop() -> Any:
    """A sleep that never waits, and ends a loop that would otherwise not."""
    def sleep(dont_care_seconds: float) -> None:
        raise _TheLoopWasEnded()

    return sleep
