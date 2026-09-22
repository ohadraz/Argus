"""The incident that is below every aggregate but one, end to end.

The cache case here is this one's mirror. That incident hides *in* the tail -
the slowest one in twenty was always a recomputed page, so losing the cache
moved the tail from one miss to another while the median stepped sevenfold.
This one hides *behind* it. Io's account page is rolling out a third figure, the
shopper's typical purchase, and the code that works it out takes the cheapest
purchase that is left over and over until the middle remains - so it walks the
history once per item and a shopper who has bought a dozen things waits more
than two seconds. The rollout is at three percent.

Three in a hundred is below the 95th percentile by arithmetic. Ninety-seven
requests in a hundred are served exactly as they were, so the median does not
move. The pages are correct - it is the same figure, worked out the long way -
so nothing fails and the error rate does not move. The one place this incident
exists is the 99th percentile, where it is several times its baseline.

Two things this case pins that no other one can.

**That the tail is a signal and not decoration.** Argus reads five series now,
and this is the only incident visible in exactly one of them. A detector reading
the other four returns no onset at all - not a late one, none - so the walk
never starts and there is nothing to mitigate. `_only_the_tail_ever_moved`
asserts both halves, because either alone proves nothing: a tail that climbed
could be any latency incident, and three flat series could be a shop nobody
disturbed.

**That a scenario costing no new mitigation still costs a diagnosis.** The mode
is `feature_flag_toggle` and the answer is the first action Argus ever had, so
nothing downstream of the hypothesis is new. What is new is reaching the
hypothesis at all from a window where four of five series say the shop is well.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run proves
the path exists - the detector reading a tail, the strategy reaching for the
flag, and the walk ending where it should. Under `nox -s e2e` a real model reads
a real window and decides for itself what a moving p99 over a flat everything
means.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx
import pytest
from argus_core.models import FailureMode, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_SLOW_CANARY_ROLLOUT,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import (
    THE_DEMO_FLAG,
    the_flag_provider_reports,
    the_service_returned_to_baseline,
)
from tests.e2e.framework.world import the_middle_of, the_shops_window
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

# What the shop's own monitoring pages on here. A latency alert, as a bad
# deployment and a misconfigured cache both raise - the three are told apart by
# the evidence and not by the page. What the summary names is the percentile,
# because a rule written against p95, which is how most latency alerting is
# written, would never fire on this at all.
A_LATENCY_ALERT = "HighLatency"

# What tells the incident's minutes from the shop's own. Measured from the
# fixture rather than guessed: the tail sits near 200ms while nothing is rolled
# out and well over a second while the rollout is. Doubling is nowhere near
# either, which is what makes it a partition and not a threshold.
THE_TAIL_AT_LEAST_DOUBLES = 2.0

# How far the other two quantiles are allowed to drift across that partition.
# Loose on purpose, and still an order of magnitude tighter than what the tail
# does: the requests the rollout takes are no longer cacheable, so the traffic
# left behind holds fewer of them and the 190th value sits a little higher in
# the same band of misses. What is being pinned is the shape - that one signal
# moved and two did not.
THE_AGGREGATES_GROW_BY_NO_MORE_THAN = 1.25

# A minute nobody would be paged for. The shop idles around one percent and
# this scenario never touches it, which is half of why no ordinary rule fires.
A_CALM_ERROR_RATE = 0.05


@pytest.mark.e2e
def test_a_rollout_slow_for_a_few_percent_is_ended_by_putting_the_flag_back() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_LATENCY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_a_slow_feature_went_out_to_a_few_percent()),
            calling(the_model_answers_from(RECORDED_SLOW_CANARY_ROLLOUT))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(
                        the_cause_was_identified_as(
                            FailureMode.FEATURE_FLAG_TOGGLE
                        ),
                        some_confidence_was_given()
                    ),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=False),
                    _only_the_tail_ever_moved(),
                    _no_request_ever_failed(),
                    the_service_returned_to_baseline()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


def _only_the_tail_ever_moved() -> Assertion[httpx.Response]:
    """The property that makes this scenario worth having, asserted both ways.

    The window is split on the tail itself, and that is not circular: what is
    being claimed is not that the tail moved - one series moving is any latency
    incident - but that *wherever* it moved, the median and the p95 did not
    follow it. Split any other way and there is nothing to compare, because the
    hit ratio dips by only the rollout's own share and no other series in the
    window knows the incident happened.

    Both halves are required to be non-empty, so a run where nothing was ever
    staged fails here rather than passing on an empty comparison.

    Compared against the window's own quiet minutes rather than figures written
    down here, because the baseline is the Target Service's to choose and a
    constant copied out of it would pass a scenario that had stopped staging
    anything.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = the_shops_window()
        the_quietest_tail = min(minute["p99_ms"] for minute in window)
        a_moved_tail = the_quietest_tail * THE_TAIL_AT_LEAST_DOUBLES

        slow = [minute for minute in window if minute["p99_ms"] > a_moved_tail]
        ordinary = [minute for minute in window if minute["p99_ms"] <= a_moved_tail]

        if not slow or not ordinary:
            raise AssertionError(
                f"Expected the window to hold both the minutes the rollout was "
                f"out over and the minutes it was not, and it holds "
                f"{len(slow)} of the first and {len(ordinary)} of the second - "
                f"so there are not two states here to compare. The quietest "
                f"tail in it is [{the_quietest_tail}]ms."
            )

        tail_before = the_middle_of(minute["p99_ms"] for minute in ordinary)
        tail_after = the_middle_of(minute["p99_ms"] for minute in slow)
        median_before = the_middle_of(minute["p50_ms"] for minute in ordinary)
        median_after = the_middle_of(minute["p50_ms"] for minute in slow)
        p95_before = the_middle_of(minute["p95_ms"] for minute in ordinary)
        p95_after = the_middle_of(minute["p95_ms"] for minute in slow)

        if median_after > median_before * THE_AGGREGATES_GROW_BY_NO_MORE_THAN:
            raise AssertionError(
                f"Expected the median to stay where it was - ninety-seven "
                f"requests in a hundred were served exactly as they always "
                f"were - and p50 went from [{median_before}]ms to "
                f"[{median_after}]ms. A median that moves this much is an "
                f"incident the cache case already covers."
            )

        if p95_after > p95_before * THE_AGGREGATES_GROW_BY_NO_MORE_THAN:
            raise AssertionError(
                f"Expected the p95 to stay where it was - three requests in a "
                f"hundred sit below the 95th percentile by arithmetic - and it "
                f"went from [{p95_before}]ms to [{p95_after}]ms. A p95 that "
                f"moves this much is an incident an ordinary latency rule would "
                f"have caught, which is not the one this case is for."
            )

        if tail_after < tail_before * THE_TAIL_AT_LEAST_DOUBLES:
            raise AssertionError(
                f"Expected the tail to climb clear of its baseline while the "
                f"rollout was out, and p99 went from [{tail_before}]ms to "
                f"[{tail_after}]ms - so the one series this incident lives in "
                f"is not reporting it."
            )

        return True

    return assertion


def _no_request_ever_failed() -> Assertion[httpx.Response]:
    """The other half of why no ordinary rule fires on this.

    The pages the rollout reaches are correct - it is the same figure worked out
    the long way - so nothing throws and the error rate never leaves the shop's
    own idle. Asserted across the whole window rather than at its end, because
    a rate that moved and came back would mean the scenario was staging a
    failure it is not supposed to have.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        worst = max(minute["error_rate"] for minute in the_shops_window())

        if worst > A_CALM_ERROR_RATE:
            raise AssertionError(
                f"Expected every page to render correctly however long it took, "
                f"and the worst minute in the window failed [{worst:.1%}] of its "
                f"requests - so this incident is visible in the error rate, and "
                f"the case it is for is one that is not."
            )

        return True

    return assertion


def _a_slow_feature_went_out_to_a_few_percent() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "slow-canary-rollout"},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
