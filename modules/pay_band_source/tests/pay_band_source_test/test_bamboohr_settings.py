"""What the HR source's settings refuse to start on.

One claim: a timeout that gives the request no time at all is refused where the
process starts. Accepted, every postmortem would report the bands unavailable,
and say so as though the HR system had been down.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, all_of, an_error_was_raised, attempting, the_error_mentioned
from pay_band_source.bamboohr_settings import BambooHrSettings
from pydantic import ValidationError

# The field the refusal is about, as a deployment's `.env` names it.
THE_TIMEOUT = "hr_timeout_seconds"


@pytest.mark.unit
@pytest.mark.parametrize("timeout_seconds", [pytest.param(0.0, id="none-at-all"),
                                             pytest.param(-1.0, id="less-than-none")])
def test_a_timeout_giving_the_request_no_time_is_refused(timeout_seconds: float) -> None:
    Scenario() \
        .given(timeout_seconds) \
        .when(attempting(lambda: BambooHrSettings(hr_timeout_seconds=timeout_seconds))) \
        .then(all_of(
            an_error_was_raised(ValidationError),
            the_error_mentioned(THE_TIMEOUT)
        ))
