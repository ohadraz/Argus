"""The incident whose only evidence is the deploy history, end to end.

Io shipped a revision that derives a shopper's lifetime average from their
purchases instead of the total the account already carries, and does it once per
purchase. The figure is the one it always was and takes ten times as long to
produce. The shop runs without a summary cache, so every request computes its own
and every request pays.

What that looks like is the whole case. The median, the 95th and the 99th
percentile all climb by the same multiple, because the revision that is running is
the revision every request runs - there is no cohort to hide in and no tail to
hide behind. Nothing fails, so the error rate never stirs. And no log line mentions
a release: the deploy exists in exactly one place, the Argo CD history the read
tier fetches, which is what makes the change channel load-bearing here rather than
corroborating.

Three things this case pins that no other one can.

**A latency incident that moved every percentile together.** The misconfigured
cache moves the median and leaves the tail; the slow canary moves the tail and
leaves the median. This moves all three at once, and that shape is the only thing
in the telemetry that says "a deployment" rather than "something in the serving
path".

**A cause in the source that is still answered by a rollback.** The repository
holds the slower code and Argus wrote nothing to it. What ended the incident is the
platform returning the deployment to the revision it ran before - a revision that
was reviewed and ran before, which is what admits the action unasked.

**Mitigated, with the fault where it was.** The branch still carries the quadratic
average and automated sync is still suspended, because a run that put the sync
policy back would have handed the incident straight to itself. `mitigated` is the
only honest word for that.

What is deliberately not asserted is which of the two deployment modes the model
named. Both reach the same strategy - a revision carries the code and the
configuration it shipped with - so the action is the thing under test and the label
is measured by `nox -s eval`, over fifty samples, against thresholds. A case here
that pinned it would fail whenever a re-recording changed the model's mind, and
would be reporting on judgement with the one instrument in this repository that
cannot measure it.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run proves
the path exists - the change channel answering, the strategy reaching for a
rollback, the write tier suspending sync before it asks, the shop coming back.
Under `nox -s e2e` a real model reads a real deploy history and decides for itself
what it is looking at.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from argus_core.models import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_BAD_DEPLOYMENT,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_read_a_change_event,
    argus_took_a_rollback_of,
    argus_wrote_a_postmortem,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import a_scenario_was_seeded, the_middle_of, the_shops_window
from tests.framework.assertions import some_confidence_was_given

# What the shop's own monitoring pages on here. The same alert the misconfigured
# cache raises, and that is the point: the two are told apart by the evidence and
# never by the page.
A_LATENCY_ALERT = "HighLatency"

THE_SCENARIO = "bad-deployment"

# How the window is cut into the minutes the slower revision was running and the
# minutes it was not. Both are read off the window's own quickest minute rather
# than from a figure copied out of the Target Service, because the baseline is its
# to choose and a constant written down here would pass a scenario that had stopped
# staging anything.
#
# A gap between the two on purpose. The revision lands partway through a minute and
# is rolled back partway through another, so those two minutes are partly served
# each way and belong to neither group - a single threshold would file them
# somewhere and weaken whichever side it put them on.
THE_QUIET_MINUTES_ARE_WITHIN = 2.0
THE_SLOW_MINUTES_ARE_BEYOND = 5.0

# What every percentile does across the change. The scenario stages a tenfold
# slowdown; asserted loosely because what is being pinned is the shape - that all
# three moved, and moved together - and a bound tight enough to pin the figures
# would fail on a scenario nobody had broken.
EVERY_PERCENTILE_AT_LEAST_TRIPLES = 3.0

# Nothing fails here, so the error rate stays at the shop's ordinary 1% and its
# half-point of wobble. Bounded well clear of that: what this refuses is an
# incident whose error rate moved, which would be diagnosable without reading the
# deploy history at all - and that is the one thing this scenario exists to require.
THE_ERROR_RATE_STAYS_UNDER = 0.05


@pytest.mark.e2e
def test_a_revision_that_slowed_every_page_is_ended_by_rolling_the_deployment_back() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_LATENCY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded(THE_SCENARIO)),
            calling(the_model_answers_from(RECORDED_BAD_DEPLOYMENT))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(some_confidence_was_given()),
                    argus_read_a_change_event(),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    argus_took_a_rollback_of(THE_SERVICE_NAME),
                    _every_percentile_moved_together(),
                    _nothing_ever_failed(),
                    _the_shop_is_quick_again(),
                    _the_application_no_longer_syncs_itself(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _every_percentile_moved_together() -> Assertion[httpx.Response]:
    """The shape that makes this a deployment, asserted across all three.

    Any one of them on its own is just a latency incident. What is only true when
    the running revision is the fault is that the median moved as far as the tail:
    a cohort would leave the median alone and a cache would leave the tail alone,
    and each of those is a case of its own in this suite.

    Compared between the window's own quiet and slow minutes rather than against
    written-down figures, and told apart by the median alone - the one signal that
    is unambiguous here - so that the multiple each percentile moved by is measured
    rather than assumed.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = the_shops_window()
        quickest = min(minute["p50_ms"] for minute in window)
        quiet = [
            minute for minute in window
            if minute["p50_ms"] <= quickest * THE_QUIET_MINUTES_ARE_WITHIN
        ]
        slow = [
            minute for minute in window
            if minute["p50_ms"] >= quickest * THE_SLOW_MINUTES_ARE_BEYOND
        ]

        if not quiet or not slow:
            raise AssertionError(
                f"Expected the window to hold both the minutes the shop ran the "
                f"earlier revision and the minutes it ran the slower one, and it "
                f"holds {len(quiet)} of the first and {len(slow)} of the second - "
                f"so there are not two states here to compare."
            )

        moved_by = {
            percentile: the_middle_of(minute[percentile] for minute in slow)
            / the_middle_of(minute[percentile] for minute in quiet)
            for percentile in ("p50_ms", "p95_ms", "p99_ms")
        }
        stayed_put = {
            percentile: multiple for percentile, multiple in moved_by.items()
            if multiple < EVERY_PERCENTILE_AT_LEAST_TRIPLES
        }

        if stayed_put:
            raise AssertionError(
                f"Expected every percentile to climb together, as they do when "
                f"the revision that is running is the one every request runs, "
                f"and {sorted(stayed_put)} moved by {stayed_put} - less than the "
                f"[{EVERY_PERCENTILE_AT_LEAST_TRIPLES}x] this scenario stages. "
                f"All three moved by {moved_by}."
            )

        return True

    return assertion


def _nothing_ever_failed() -> Assertion[httpx.Response]:
    """The half of the shape a reader would otherwise diagnose from.

    An incident whose error rate moved is one somebody could explain without ever
    opening the deploy history, and the history being the only evidence is the
    whole reason this scenario is here. So a shop that started failing has staged
    a different incident from the one under test, however slow it also got.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = the_shops_window()
        worst = max(minute["error_rate"] for minute in window)

        if worst > THE_ERROR_RATE_STAYS_UNDER:
            raise AssertionError(
                f"Expected the shop to go on serving every request while it was "
                f"slow, and its worst minute failed [{worst:.1%}] of them - an "
                f"incident diagnosable without the deploy history, which is not "
                f"the one this case is for."
            )

        return True

    return assertion


def _the_shop_is_quick_again() -> Assertion[httpx.Response]:
    """The incident genuinely ended, and the minutes it lasted are still there.

    Both halves in one window, for the reason the leak case asserts its climb
    alongside its drop: a fixture that dropped the stretch on rollback would erase
    the incident at the moment it was mitigated, and this case would then pass
    against a shop that had never been slow at all.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = the_shops_window()
        quickest = min(minute["p50_ms"] for minute in window)
        slowest = max(minute["p50_ms"] for minute in window)

        if slowest < quickest * THE_SLOW_MINUTES_ARE_BEYOND:
            raise AssertionError(
                f"Expected the window to still hold the minutes the shop was slow, "
                f"and its median ran from [{quickest}]ms to [{slowest}]ms - so the "
                f"incident has been erased from the record a mitigation is judged "
                f"against."
            )

        if window[-1]["p50_ms"] > quickest * THE_QUIET_MINUTES_ARE_WITHIN:
            raise AssertionError(
                f"Expected the shop to be quick again once the deployment was put "
                f"back on the earlier revision, and its last minute reports a "
                f"median of [{window[-1]['p50_ms']}]ms against a quickest of "
                f"[{quickest}]ms."
            )

        return True

    return assertion


def _the_application_no_longer_syncs_itself() -> Assertion[httpx.Response]:
    """What makes this mitigated rather than over.

    The rollback moved what is deployed and touched nothing in the repository, so
    the branch still holds the revision that derives the average the expensive way.
    The one thing standing between the shop and the same incident is that the
    application has stopped reconciling itself - and a run that tidily put the sync
    policy back would have handed the incident straight back, while looking in
    every other respect like a success.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        response = httpx.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        spec: dict[str, Any] = response.json()["spec"]
        automated = spec["syncPolicy"].get("automated")

        if automated is not None:
            raise AssertionError(
                f"Expected automated sync to still be suspended after the "
                f"rollback, and the application reports [{automated}] - so the "
                f"next reconciliation puts the shop back on the slower revision."
            )

        return True

    return assertion
