"""The exchange rates a source last published, kept and found again through the
cache's role, on the connection the source reads on."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from argus_testkit import Scenario, calling, the_answer_was
from core.models import PublishedRates
from incident_record import rates_cache_on
from postgres import connect_from_env

SOME_BASE = "USD"
A_BASE_NEVER_KEPT = "JPY"
SOME_DAY = date(2026, 11, 20)
SOME_RATES = PublishedRates(base=SOME_BASE, on=SOME_DAY,
                            per_unit={"EUR": Decimal("0.92"), "GBP": Decimal("0.79")})


@pytest.mark.component
def test_rates_kept_are_the_latest_for_their_base() -> None:
    with connect_from_env() as conn:
        cache = rates_cache_on(conn)

        Scenario() \
            .given(calling(lambda: cache.keep(SOME_RATES))) \
            .when(lambda: cache.latest_for(SOME_BASE)) \
            .then(the_answer_was(SOME_RATES))


@pytest.mark.component
def test_a_base_never_kept_has_no_rates() -> None:
    with connect_from_env() as conn:
        Scenario() \
            .when(lambda: rates_cache_on(conn).latest_for(A_BASE_NEVER_KEPT)) \
            .then(the_answer_was(None))
