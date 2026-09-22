"""The incident a monitor watching the tail cannot see, end to end.

Every other latency case here moves p95, because that is what a fault in the
serving path does. This one does not, and that is the case rather than a detail.
Io's account page reads a shopper's spend figure from a cache before working it
out; a configuration change moved the cache's port, so every lookup now dials an
address nothing is listening on and every page recomputes. The page is still
*correct* - the fallback is designed behaviour - so no request fails and the
error rate never stirs.

What moves is the median, and only the median. Nine requests in ten used to be
served from cache and now none are, so p50 climbs sevenfold; the slowest one in
twenty was always a recomputed page, so p95 barely notices. With the median
hidden the detector returns no onset at all - a tail-watching monitor never sees
this incident happen.

Three things this case pins that no other one can.

**A cause that is in neither the code nor a flag.** Nothing in the source
changed, no switch was thrown, and a restart brings back a shop reading the same
configuration. The fault is a value in a file that was deployed, which is what
separates `config_induced_failure` from a bad deployment - the revision is fine,
and what is wrong is what it was told.

**A mitigation that has to suspend something first.** Argo CD refuses a rollback
while an application syncs itself, because the next reconciliation would undo
it. So the write tier reads the sync policy, suspends it, and only then rolls
back - and what is asserted below is that the shop ended on the earlier
configuration *and* that automated sync is still suspended, because a run that
put the policy back would have handed the incident straight back to itself.

**Mitigated with the cause untouched, in the plainest form the system has.** The
values file still names the port that broke this. The symptom is gone, the fault
is exactly where it was, and `mitigated` is the only honest word for that - the
status that says something is still owed.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run proves
the path exists - the detector reading a median, the strategy reaching for a
rollback, the write tier suspending sync before it asks, and the walk ending
where it should. Under `nox -s e2e` a real model reads a real misconfiguration
and decides for itself what it is looking at.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx
import pytest
from argus_core.events import ActionTaken
from argus_core.models import ROLL_BACK_CONFIGURATION, FailureMode, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_CACHE_MISCONFIGURED,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import the_incidents_events, the_middle_of, the_shops_window
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

# What the shop's own monitoring pages on here. A latency alert, as a bad
# deployment raises - the two are told apart by the evidence and not by the page,
# which is the point: the summary names the median, and nothing else about the
# alert says which of the two this is.
A_LATENCY_ALERT = "HighLatency"

# What the two latencies do across the change, measured from the fixture
# rather than guessed: p50 grows about sevenfold and p95 about six percent. The
# bounds are loose in both directions on purpose - what is being pinned is the
# shape, that one signal moved and the other did not, and a bound tight enough
# to pin the figures would fail on a scenario nobody had broken.
THE_MEDIAN_AT_LEAST_TRIPLES = 3.0
THE_TAIL_GROWS_BY_NO_MORE_THAN = 1.25

# What the cache carried before the port moved. The scenario's healthy ratio is
# around nine in ten; asserted as "most of them" because the exact figure is the
# Target Service's to choose and this only has to tell a working cache from one
# nothing reaches.
THE_CACHE_CARRIED_MOST_OF_THEM = 0.5


@pytest.mark.e2e
def test_a_cache_nobody_can_reach_is_ended_by_rolling_the_configuration_back() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_LATENCY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_the_cache_was_moved_out_of_reach()),
            calling(the_model_answers_from(RECORDED_CACHE_MISCONFIGURED))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(
                        the_cause_was_identified_as(
                            FailureMode.CONFIG_INDUCED_FAILURE
                        ),
                        some_confidence_was_given()
                    ),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _the_action_taken_was_a_rollback_of(THE_SERVICE_NAME),
                    _only_the_median_ever_moved(),
                    _the_shop_is_reaching_its_cache_again(),
                    _the_application_no_longer_syncs_itself(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_action_taken_was_a_rollback_of(application: str) -> Assertion[httpx.Response]:
    """Read from the incident's own account rather than from the platform.

    What the platform was asked is a fact about the fixture; what Argus decided
    to do is the thing under test. A rollback has no direction - there is no
    switch to have been thrown, and where it went is "the revision before" by
    construction - so the event says so by leaving it absent, and one claiming a
    direction would describe a different action from the one taken.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        taken = [
            event for event in the_incidents_events(incident_id)
            if isinstance(event, ActionTaken)
        ]

        if not taken:
            raise AssertionError(
                f"Incident [{incident_id}] took no action at all, so nothing "
                f"was ever put to the question."
            )

        rollbacks = [
            event for event in taken
            if event.action_type == ROLL_BACK_CONFIGURATION
            and event.subject == application
        ]

        if not rollbacks:
            raise AssertionError(
                f"Expected a rollback of [{application}], and what was taken "
                f"was {[(event.action_type, event.subject) for event in taken]}."
            )

        if rollbacks[-1].enabled is not None:
            raise AssertionError(
                f"Expected a rollback to carry no direction, and it reported "
                f"[{rollbacks[-1].enabled}] - which tells a later round a "
                f"switch was thrown."
            )

        return True

    return assertion


def _only_the_median_ever_moved() -> Assertion[httpx.Response]:
    """The property that makes this scenario worth having, asserted both ways.

    One half on its own proves nothing. A median that climbed could be any
    latency incident, and a tail that stayed flat could be a shop nobody
    disturbed; what is only true here is the two at once - and it is what a
    detector reading p95 alone would miss entirely.

    Compared against the window's own earlier minutes rather than a figure
    written down here, because the baseline is the Target Service's to choose
    and a constant copied out of it would pass a scenario that had stopped
    staging anything.

    The two halves are told apart by the hit ratio rather than by a count of
    minutes, and that is not a detail. The outage is backdated by a *setting*
    when the scenario is seeded and then goes on for however long the walk
    takes, so the stretch it covers is neither a fixed length nor a fixed
    fraction of the window. Slicing the last N minutes would pin this to a
    number that was never the point and would read mostly healthy minutes on a
    fast run.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = the_shops_window()
        served = [
            minute for minute in window
            if (minute["cache_hit_ratio"] or 0.0) > THE_CACHE_CARRIED_MOST_OF_THEM
        ]
        starved = [
            minute for minute in window if minute["cache_hit_ratio"] == 0.0
        ]

        if not served or not starved:
            raise AssertionError(
                f"Expected the window to hold both the minutes the shop was "
                f"served from cache and the minutes it reached nothing, and it "
                f"holds {len(served)} of the first and {len(starved)} of the "
                f"second - so there are not two states here to compare."
            )

        median_before = the_middle_of(minute["p50_ms"] for minute in served)
        median_after = the_middle_of(minute["p50_ms"] for minute in starved)
        tail_before = the_middle_of(minute["p95_ms"] for minute in served)
        tail_after = the_middle_of(minute["p95_ms"] for minute in starved)

        if median_after < median_before * THE_MEDIAN_AT_LEAST_TRIPLES:
            raise AssertionError(
                f"Expected the median to climb clear of its baseline once every "
                f"page was being recomputed, and it went from [{median_before}]ms "
                f"to [{median_after}]ms - less than the "
                f"[{THE_MEDIAN_AT_LEAST_TRIPLES}x] this scenario stages."
            )

        if tail_after > tail_before * THE_TAIL_GROWS_BY_NO_MORE_THAN:
            raise AssertionError(
                f"Expected the tail to barely stir - the slowest requests were "
                f"always recomputed pages - and p95 went from [{tail_before}]ms "
                f"to [{tail_after}]ms. A tail that moves this much is an "
                f"incident an ordinary p95 rule would have caught, which is not "
                f"the one this case is for."
            )

        return True

    return assertion


def _the_shop_is_reaching_its_cache_again() -> Assertion[httpx.Response]:
    """The incident genuinely ended, and the minutes it lasted are still there.

    Both halves in one window, for the reason the leak case asserts its climb
    alongside its drop: a fixture that reset its history on rollback would erase
    the incident at the moment it was mitigated, and this case would then pass
    against a shop whose cache had never been unreachable at all.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = the_shops_window()
        ratios = [
            minute["cache_hit_ratio"] for minute in window
            if minute["cache_hit_ratio"] is not None
        ]

        if not ratios:
            raise AssertionError(
                "The shop reported no cache hit ratio on any minute, so there "
                "is no telling whether it ever reached its cache."
            )

        if min(ratios) > 0.0:
            raise AssertionError(
                f"Expected the window to still hold the minutes the shop could "
                f"reach nothing, and its lowest hit ratio was [{min(ratios)}] - "
                f"so the outage has been erased from the record that a "
                f"mitigation is judged against."
            )

        if ratios[-1] <= THE_CACHE_CARRIED_MOST_OF_THEM:
            raise AssertionError(
                f"Expected the shop to be served from cache again once the "
                f"configuration was rolled back, and its last minute reports a "
                f"hit ratio of [{ratios[-1]}]."
            )

        return True

    return assertion


def _the_application_no_longer_syncs_itself() -> Assertion[httpx.Response]:
    """What makes this mitigated rather than over.

    The rollback moved the running configuration and touched nothing in the
    repository, so the values file still names the port that broke this. The one
    thing standing between the shop and the same incident is that the
    application has stopped reconciling itself - and a run that tidily put the
    sync policy back would have handed the incident straight back, while looking
    in every other respect like a success.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        response = httpx.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        automated = response.json()["spec"]["syncPolicy"].get("automated")

        if automated is not None:
            raise AssertionError(
                f"Expected automated sync to still be suspended after the "
                f"rollback, and the application reports [{automated}] - so the "
                f"next reconciliation puts the shop back on the port nothing "
                f"is listening on."
            )

        return True

    return assertion


def _the_cache_was_moved_out_of_reach() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "cache-misconfigured"},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
