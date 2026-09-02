from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from tests.e2e.framework.argus import REQUEST_TIMEOUT_SECONDS, TARGET_SERVICE_BASE_URL
from tests.e2e.framework.flags import (
    every_flag_was_switched_off,
    only_the_shops_own_flag_was_left_in_the_provider,
    the_flag_provider_forgot_every_change,
)


@pytest.fixture(autouse=True)
def a_world_each_case_leaves_as_it_found_it() -> Iterator[None]:
    """Puts the Target Environment back after every e2e case.

    Every case, not only the ones that obviously dirty something. Argus now
    changes the world it investigates - it turns flags off, turns them on, and
    puts them back when a mitigation is refuted - so the state a case ends in
    is rarely the state it arranged, and rarely something the case itself can
    predict.

    Four things are undone, and the order is the point:

    - every flag left on goes off, which clears anything a case created for
      itself;
    - the Target Service's scenario is reset, which has the last word on the
      flags it owns. Healthy is not the same state for both of them - the
      feature flag is well off and the fallback flag is well on - and the
      service is the thing that knows which, so it is asked rather than
      second-guessed here;
    - every flag but the shop's own is deleted. The provider is shared with the
      demo, and a flag a case brought into existence is one somebody would have
      to explain in front of an audience. After the reset above, so the service
      is done with whatever it was staging before its flag is taken away;
    - the provider's record of which flags changed is erased. This is the one
      that would otherwise couple the cases to their order: a flag toggled in
      one case is evidence in the next, whatever state the flag itself was left
      in. It goes last because every step above is itself a change the provider
      records.

    Teardown rather than setup, so a failing case leaves nothing behind for a
    human to clear before rerunning.
    """
    yield

    every_flag_was_switched_off()
    _the_target_service_scenario_was_reset()
    only_the_shops_own_flag_was_left_in_the_provider()
    the_flag_provider_forgot_every_change()


def _the_target_service_scenario_was_reset() -> None:
    httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=REQUEST_TIMEOUT_SECONDS
    )
