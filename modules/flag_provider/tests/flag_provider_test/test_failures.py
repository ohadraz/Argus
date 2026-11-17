"""What the provider's failures are to the code that catches them."""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from flag_provider import FlagProviderError, FlagProviderUnavailable, FlagWriteFailed


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure", [FlagProviderUnavailable, FlagWriteFailed], ids=["unavailable", "write failed"]
)
def test_either_failure_is_a_flag_provider_error(failure: type[FlagProviderError]) -> None:
    # A caller that only needs to know the provider did not do what was asked
    # catches one name rather than two.
    Scenario() \
        .given(failure) \
        .when(lambda: issubclass(failure, FlagProviderError)) \
        .then(the_answer_was(True))
