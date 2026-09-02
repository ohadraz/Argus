from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from tests.e2e.framework.argus import REQUEST_TIMEOUT_SECONDS, TARGET_SERVICE_BASE_URL
from tests.e2e.framework.flags import (
    only_the_boot_flags_were_left_in_the_provider,
    the_boot_flags_were_put_back,
    the_flag_provider_forgot_every_change,
)


@pytest.fixture(autouse=True)
def a_world_each_case_leaves_as_it_found_it() -> Iterator[None]:
    """Puts the Target Environment back the way the stack starts it.

    Every case, not only the ones that obviously dirty something. Argus now
    changes the world it investigates - it turns flags off, turns them on, and
    puts them back when a mitigation is refuted - so the state a case ends in
    is rarely the state it arranged, and rarely something the case itself can
    predict.

    The state being restored is the one a fresh stack boots into, which is not
    "quiet" but a specific pair of flag states and an empty toggle history: the
    shop's feature flag off, the kill switch on, and nothing recorded as having
    been switched. Four things are undone, and the order is the point:

    - the Target Service's scenario is reset, which ends whatever condition it
      was staging and has the last word on the flags it owns;
    - both boot flags are put back where the stack starts them. Healthy is not
      the same state for the two of them, so this restores each to its own -
      switching everything off would leave the kill switch withdrawn and the
      shop failing for a reason nothing in the history explains;
    - every flag the environment did not boot with is deleted. The provider is
      shared with the demo, and a flag a case brought into existence is one
      somebody would have to explain in front of an audience;
    - the provider's record of which flags changed is erased. This is the one
      that would otherwise couple the cases to their order: a flag toggled in
      one case is evidence in the next, whatever state the flag itself was left
      in. It goes last because every step above is itself a change the provider
      records.

    Teardown rather than setup, so a failing case leaves nothing behind for a
    human to clear before rerunning.
    """
    yield

    _the_target_service_scenario_was_reset()
    the_boot_flags_were_put_back()
    only_the_boot_flags_were_left_in_the_provider()
    the_flag_provider_forgot_every_change()


def _the_target_service_scenario_was_reset() -> None:
    httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/reset", timeout=REQUEST_TIMEOUT_SECONDS
    )
