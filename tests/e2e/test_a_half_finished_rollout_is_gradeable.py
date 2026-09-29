"""The fixture's own arithmetic, checked against the detector that will read it.

The second case in this suite that runs no walk. Nothing here triggers Argus, no
model answers, no recording is loaded and no incident is created - it seeds the
shop, reads the shop, and asks `argus_core.anomaly` what it makes of what the
shop reported. It is in `tests/e2e/` because the Target Service is only reachable
over HTTP and for no other reason.

Three things are asserted, and the scenario is worthless without any of them.

**The incident is detectable, and only in the error rate.** A rollout stopped
half-way fails about one request in five and costs the survivors nothing, so the
error rate departs and the quantiles do not move at all. That shape is the flag
scenario's exactly - which is the difficulty this mode exists to pose, and is
also the thing a fixture can get wrong invisibly. A generator that let latency
drift would hand the model a second signal and quietly make the incident easy.

**A restart is refuted.** The fleet is still split when the process comes back,
so nothing about the mixture is the process's doing. If a restart ever read as a
recovery here, the mode's near-miss would be accidentally right and every
recording made afterwards would agree.

**A rollback is confirmed.** Returning the deployment converges every replica
onto one revision, and one version reading and writing one shape works. This is
the half that says the scenario is gradeable at all.

Unlike the flapping case, none of this depends on a shape in time: the incident
departs and stays departed until something ends it, which is the ordinary
arrangement here. What is load-bearing instead is the *narrowness* of the
departure - one series and no other - so that is what the first case measures.

Free in both modes and needs no corpus, since no model is asked anything. Run it
whenever the generator's arithmetic or the detector's thresholds move - those are
the two changes that can break this scenario without breaking anything that
mentions it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from http import HTTPStatus as HttpStatus
from statistics import median
from typing import Any

import httpx
import pytest
from argus_core import get_settings
from argus_core.anomaly import find_onset, has_recovered_since
from argus_core.models import MetricBucket
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
)
from tests.e2e.framework.world import a_scenario_was_seeded, the_shops_window
from tests.framework.investigating import the_configured_thresholds

# The scenario whose live condition is a rollout nobody finished. Not a
# `RECORDED_*` name, and that absence is the point: those name a corpus, and this
# case asks no model anything.
A_HALF_FINISHED_ROLLOUT = "half-finished-rollout"

THE_APPLICATION = "io-shop"

# How much of the window has to be settled before the assertions have something
# to read. The scenario backdates its onset, so departed minutes are in the
# window the instant it is seeded - but the newest of them is the minute in
# progress, and a partial minute reports a rate taken over however many requests
# have arrived. Two whole minutes is the persistence the detector dates an onset
# from, so it is also the least this case can assert anything about.
ENOUGH_MINUTES_SECONDS = 180

# How far a quantile may differ between the quiet minutes and the departed ones
# before the difference is the incident rather than the sampling. Ten percent,
# which is several times the generator's own wobble on the median and the tail
# and a small fraction of what a real move here would be: every other latency
# scenario in the fixture multiplies a quantile, and the smallest of those is
# more than four times its baseline. So this is loose enough not to fail on
# sampling and tight enough that a latency signal arriving in this scenario by
# accident would not slip through.
A_QUANTILE_MAY_DRIFT_BY = 0.10

# How long to allow a mitigation before calling it unconfirmed, and how long to
# go on refusing the one that should never be confirmed. The same bound
# Mitigation itself waits, because what is under test is whether this fixture is
# gradeable by the rules Argus actually applies rather than by a generous reading
# of them.
AS_LONG_AS_MITIGATION_WOULD_WAIT_SECONDS = int(
    get_settings().mitigation_verification_timeout_seconds
)

# Suspending the platform's own reconciliation, in the shape the write tier sends
# it: Argo CD spells "not automated" as the *absence* of the key rather than as a
# flag set to false, and the stand-in refuses a rollback while sync is on exactly
# as the real platform does. Sent here rather than routed around, so this case
# exercises the same wire a mitigation will.
NOTHING_RECONCILES_IT: dict[str, Any] = {"syncPolicy": {}}


@pytest.mark.e2e
def test_a_half_finished_rollout_is_an_incident_the_detector_can_date() -> None:
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(A_HALF_FINISHED_ROLLOUT))
        ) \
        .when(
            _enough_whole_minutes_have_passed
        ) \
        .then(
            all_of(
                _an_onset_is_dated(),
                _the_error_rate_departed(),
                _no_quantile_moved(),
                _the_capacity_held_one_value()
            )
        )


@pytest.mark.e2e
def test_a_restart_is_refused_and_a_rollback_is_confirmed() -> None:
    """Both halves in one case, because the comparison is the assertion.

    Asserting them apart would leave two cases each of which could pass against a
    fixture where the other's outcome was wrong - a shop that recovered from
    anything would pass the rollback case, and a shop that recovered from nothing
    would pass the restart one.

    Staged in this order because a rollback ends the incident and a restart
    leaves it exactly where it was. The refutation therefore has to be measured
    first, while there is still something to refute.
    """
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(A_HALF_FINISHED_ROLLOUT)),
            calling(_enough_whole_minutes_have_passed)
        ) \
        .when(
            _the_shop_was_restarted
        ) \
        .then(
            _recovery_is_refused_since_the_restart()
        )

    Scenario() \
        .when(
            _the_deployment_was_rolled_back
        ) \
        .then(
            eventually(
                _recovery_is_confirmed_since(),
                timeout=AS_LONG_AS_MITIGATION_WOULD_WAIT_SECONDS
            )
        )


def _enough_whole_minutes_have_passed() -> bool:
    """Waits until the window holds whole minutes to read rather than a partial one.

    The shop backdates this scenario's onset, so departed minutes are already in
    the window the instant it is seeded - but the newest is the minute in
    progress, whose rate is taken over however many requests have arrived so far.
    So this waits for buckets rather than assuming them.
    """
    deadline = datetime.now(UTC) + timedelta(seconds=ENOUGH_MINUTES_SECONDS)
    wanted = the_configured_thresholds().persistence_minutes + 1

    while datetime.now(UTC) < deadline:
        try:
            if len(_the_departed_minutes()) >= wanted:
                return True
        except AssertionError:
            # A window with nothing in it yet is this loop's ordinary early state
            # rather than a failure - `the_shops_window` refuses rather than
            # returning empty, which is right for an assertion and wrong for a
            # wait. The deadline below is what turns "not yet" into "not at all".
            pass

    raise AssertionError(
        f"The Target Service did not report {wanted} departed minutes within "
        f"{ENOUGH_MINUTES_SECONDS}s of the scenario being seeded, so there is "
        f"not enough of the incident in the window to assert anything about it. "
        f"Error rates reported: {[bucket.error_rate for bucket in _the_window()]}."
    )


def _an_onset_is_dated() -> Assertion[bool]:
    """The detector finds a start for this incident.

    Asserted before anything about mitigation, because an incident nothing dates
    is one no walk ever begins: the Investigator returns without asking a model
    anything when `find_onset` answers `None`.
    """
    def assertion(dont_care: bool) -> bool:
        window = _the_window()
        onset = find_onset(window, the_configured_thresholds())

        if onset is None:
            raise AssertionError(
                f"The detector dated no onset in a window the scenario has been "
                f"running through, so no walk would ever start. Error rates "
                f"reported: {[bucket.error_rate for bucket in window]}."
            )

        return True

    return assertion


def _the_error_rate_departed() -> Assertion[bool]:
    """The one series this incident lives in actually moved.

    Measured against the window's own quiet minutes rather than a figure copied
    from the generator: what is claimed is that the shop got worse, and a
    constant here would keep passing after the generator's baseline moved while
    measuring something else.
    """
    def assertion(dont_care: bool) -> bool:
        departed = _the_departed_minutes()
        quiet = _the_quiet_minutes()

        if not quiet:
            raise AssertionError(
                "The window holds no quiet minutes before the onset, so there is "
                "nothing to say the error rate departed *from*. The scenario's "
                "backdating is what is meant to leave them in view."
            )

        worst_quiet = max(bucket.error_rate for bucket in quiet)
        least_departed = min(bucket.error_rate for bucket in departed)

        if least_departed <= worst_quiet:
            raise AssertionError(
                f"The departed minutes report error rates as low as "
                f"{least_departed}, which is no worse than the quiet minutes' "
                f"{worst_quiet} - so the two are not separable and the incident "
                f"the detector dated is sampling rather than the rollout."
            )

        return True

    return assertion


def _no_quantile_moved() -> Assertion[bool]:
    """Latency is where it was, which is half of what makes this mode hard.

    A page that cannot read a cache entry fails immediately, so nothing waits. A
    fixture that moved latency here would hand the model a second signal and turn
    an incident that has to be told from a flag toggle into one that announces
    itself - and it would do that without failing anything.
    """
    def assertion(dont_care: bool) -> bool:
        quiet = _the_quiet_minutes()
        departed = _the_departed_minutes()
        moved = [
            (name, before, after)
            for name, before, after in (
                (name, _the_median_of(quiet, name), _the_median_of(departed, name))
                for name in ("p50_ms", "p95_ms", "p99_ms")
            )
            if abs(after - before) > before * A_QUANTILE_MAY_DRIFT_BY
        ]

        if moved:
            raise AssertionError(
                f"Latency moved during an incident that is meant to live in the "
                f"error rate alone: {moved} as (series, quiet, departed). A "
                f"reader of these metrics would have a signal this scenario "
                f"never staged."
            )

        return True

    return assertion


def _the_capacity_held_one_value() -> Assertion[bool]:
    """Nothing resized the deployment, which separates this from the capacity pair.

    Cheap to assert and worth asserting: `cpu_limit_cores` taking a second value
    is what says a controller is moving the capacity, and a rollout that surges
    replicas could plausibly be mistaken for one by a fixture as much as by a
    reader.
    """
    def assertion(dont_care: bool) -> bool:
        reported = {
            bucket.cpu_limit_cores for bucket in _the_window()
            if bucket.cpu_limit_cores is not None
        }

        if len(reported) > 1:
            raise AssertionError(
                f"The capacity took more than one value across the window - "
                f"{sorted(reported)} - which is the signature of the mode next "
                f"door. Nothing in this scenario resizes the deployment."
            )

        return True

    return assertion


def _recovery_is_refused_since_the_restart() -> Assertion[datetime]:
    """A restart changes nothing, and goes on changing nothing.

    Waited out for as long as Mitigation would wait rather than checked once.
    What makes a wrong answer refutable is that it is still wrong when the
    verification window closes, and a single early read would pass against a
    fixture that recovered a minute later.
    """
    def assertion(restarted_at: datetime) -> bool:
        deadline = datetime.now(UTC) + timedelta(
            seconds=AS_LONG_AS_MITIGATION_WOULD_WAIT_SECONDS
        )

        while datetime.now(UTC) < deadline:
            if has_recovered_since(
                _the_window(), _to_minute(restarted_at), the_configured_thresholds()
            ):
                raise AssertionError(
                    f"A restart read as a recovery, so the near-miss for this "
                    f"mode is accidentally right and nothing refutes it. Error "
                    f"rates since the restart: "
                    f"{[bucket.error_rate for bucket in _the_minutes_since(restarted_at)]}."
                )

        return True

    return assertion


def _recovery_is_confirmed_since() -> Assertion[datetime]:
    def assertion(rolled_back_at: datetime) -> bool:
        if not has_recovered_since(
            _the_window(), _to_minute(rolled_back_at), the_configured_thresholds()
        ):
            raise AssertionError(
                f"A rollback did not read as a recovery within "
                f"{AS_LONG_AS_MITIGATION_WOULD_WAIT_SECONDS}s, so the one action "
                f"that answers this mode is ungradeable. Error rates since the "
                f"rollback: "
                f"{[bucket.error_rate for bucket in _the_minutes_since(rolled_back_at)]}."
            )

        return True

    return assertion


def _the_shop_was_restarted() -> datetime:
    """Brings the process back, the way the restart mitigation does."""
    response = httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/restart",
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    if response.status_code != HttpStatus.OK:
        raise AssertionError(
            f"The shop refused to restart: {response.status_code} {response.text}."
        )

    return datetime.now(UTC)


def _the_deployment_was_rolled_back() -> datetime:
    """Returns the deployment to the revision before it, through the platform.

    Two requests, because the platform's own rules make it two: Argo CD refuses a
    rollback while it is reconciling the application, so suspending that is part
    of performing one rather than a separate concern. The same two the write tier
    makes, in the same order.

    Addressed to the *second-newest* history entry. The newest is the revision
    being rolled out, and the platform reads a rollback aimed at that as a
    withdrawal - which is the direction that puts the split fleet back.
    """
    suspended = httpx.put(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_APPLICATION}/spec",
        json=NOTHING_RECONCILES_IT,
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    if suspended.status_code != HttpStatus.OK:
        raise AssertionError(
            f"The platform refused to suspend automated sync: "
            f"{suspended.status_code} {suspended.text}."
        )

    response = httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_APPLICATION}/rollback",
        json={"id": _the_entry_before_the_newest()},
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    if response.status_code != HttpStatus.OK:
        raise AssertionError(
            f"The platform refused to roll the deployment back: "
            f"{response.status_code} {response.text}."
        )

    return datetime.now(UTC)


def _the_entry_before_the_newest() -> int:
    """Which history entry a rollback is addressed to.

    Read from the platform rather than stated, because the id is the platform's
    to assign and a literal here would be a number this case had guessed.
    """
    response = httpx.get(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_APPLICATION}",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    history: list[dict[str, Any]] = response.json()["status"]["history"]

    if len(history) < 2:
        raise AssertionError(
            f"The application's history holds {len(history)} entry(ies), so "
            f"there is no earlier revision to roll back to. This scenario stages "
            f"a deployment and the revision before it."
        )

    return int(history[-2]["id"])


def _the_window() -> list[MetricBucket]:
    return [MetricBucket.model_validate(minute) for minute in the_shops_window()]


def _the_departed_minutes() -> list[MetricBucket]:
    """The minutes at or past the onset the detector dated.

    Split by the detector's own answer rather than by a threshold this file
    chose, so that "departed" means here what it means to everything downstream.
    """
    window = _the_window()
    onset = find_onset(window, the_configured_thresholds())

    if onset is None:
        raise AssertionError(
            f"The detector dated no onset, so the window cannot be split into "
            f"quiet and departed minutes. Error rates reported: "
            f"{[bucket.error_rate for bucket in window]}."
        )

    return [bucket for bucket in window if bucket.bucket_id >= onset]


def _the_quiet_minutes() -> list[MetricBucket]:
    window = _the_window()
    onset = find_onset(window, the_configured_thresholds())

    return [bucket for bucket in window if onset is None or bucket.bucket_id < onset]


def _the_minutes_since(moment: datetime) -> list[MetricBucket]:
    since = _to_minute(moment)

    return [bucket for bucket in _the_window() if bucket.bucket_id >= since]


def _the_median_of(buckets: Sequence[MetricBucket], series: str) -> float:
    """The middle value of one series, over the minutes handed in.

    A median rather than a mean, for the reason the generator wobbles every
    figure it reports: one unusual minute should not decide whether a quantile
    moved, and with a wobble either side of a baseline the middle is the
    baseline.
    """
    if not buckets:
        raise AssertionError(
            f"Asked for the median {series} of no minutes at all, which is the "
            f"window having been split wrongly rather than a measurement."
        )

    return float(median(getattr(bucket, series) for bucket in buckets))


def _to_minute(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:00Z")
