from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from tests.e2e.framework.argus import TARGET_SERVICE_BASE_URL
from tests.e2e.framework.flags import (
    every_flag_was_switched_off,
    the_flag_provider_forgot_every_change,
)

REQUEST_TIMEOUT_SECONDS = 10.0


@pytest.fixture(autouse=True)
def a_world_each_case_leaves_as_it_found_it() -> Iterator[None]:
    """Puts the Target Environment back after every e2e case.

    Every case, not only the ones that obviously dirty something. Argus now
    changes the world it investigates - it turns flags off, turns them on, and
    puts them back when a mitigation is refuted - so the state a case ends in
    is rarely the state it arranged, and rarely something the case itself can
    predict.

    Three things are undone, and the order is the point:

    - every flag left on goes off, which clears anything a case created for
      itself;
    - the Target Service's scenario is reset, which has the last word on the
      flags it owns. Healthy is not the same state for both of them - the
      feature flag is well off and the fallback flag is well on - and the
      service is the thing that knows which, so it is asked rather than
      second-guessed here;
    - the provider's record of which flags changed is erased. This is the one
      that would otherwise couple the cases to their order: a flag toggled in
      one case is evidence in the next, whatever state the flag itself was left
      in. It goes last because both steps above are themselves changes the
      provider records.

    Teardown rather than setup, so a failing case leaves nothing behind for a
    human to clear before rerunning.
    """
    yield

    every_flag_was_switched_off()
    _the_target_service_scenario_was_reset()
    the_flag_provider_forgot_every_change()


def _the_target_service_scenario_was_reset() -> None:
    httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=REQUEST_TIMEOUT_SECONDS
    )
