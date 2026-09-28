"""The fixture's own arithmetic, checked against the detector that will read it.

The only case in this suite that runs no walk. Nothing here triggers Argus, no
model answers, no recording is loaded and no incident is created - it seeds the
shop, reads the shop, and asks `argus_core.anomaly` what it makes of what the
shop reported. It is in `tests/e2e/` because the Target Service is only reachable
over HTTP and for no other reason.

It exists because this scenario is the first whose *shape in time* is load-bearing
rather than incidental, and because the way it can be wrong is silent.

Every other scenario here departs from its baseline and stays departed until
something ends it. A flapping autoscaler departs, returns, departs, returns, and
the detector reads that with two rules whose interaction nobody chose: an onset is
a run of departed minutes reaching `anomaly_persistence_minutes`, and a mitigation
is confirmed by a stretch since the action with a clear minute in it and no
departed run that long. A cycle whose clear stretch is as long as the persistence
therefore **confirms whatever was tried last**, on the next down-swing, whether or
not it helped. That is not a failing test somewhere; it is a green suite in which
a restart cures a flapping autoscaler, and every recording made afterwards agrees.

So the three things asserted here are the three the scenario is worthless without:

**The incident is detectable.** A cycle of two departed minutes and one clear one
reaches a persistence of two, so an onset is dated. A cycle of one and one would
not be an incident at all.

**No down-swing is a recovery.** With the cycle running, no stretch inside the
window satisfies the recovery rule, so nothing Argus does to this shop can be
confirmed by waiting.

**A pin is, and a scale-out is not.** The two act on the same number and only one
of them holds it: raising the autoscaler's floor stops the cycle from the bucket
it lands in, and setting the deployment's count directly is re-derived away by the
next minute. The second is the near-miss - the mode next door, reached by a reader
who saw pinned utilisation and stopped looking - and the fixture is what refutes
it rather than a rule in Argus.

The last of those was measured in all three phases of the cycle before it was
believed, because the position that looks worst on paper is the one where a
scale-out lands just before the cycle's own ceiling minute and so gets two clear
minutes for free. Two is not three, so it is refuted at any settling window; had
it been three, adding capacity would have been accidentally right here.

Free in both modes and needs no corpus, since no model is asked anything. Run it
whenever the generator's arithmetic or the detector's thresholds move - those are
the two changes that can break this scenario without breaking anything that
mentions it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from http import HTTPStatus as HttpStatus
from statistics import median

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

# The scenario whose live condition is a controller. Not a `RECORDED_*` name, and
# that absence is the point: those name a corpus, and this case asks no model
# anything.
A_FLAPPING_AUTOSCALER = "autoscaler-flapping"

# What the shop is declared with in `deploy/values-production.yaml`. Named rather
# than read back, because what is asserted is that the capacity *moves between*
# these two - a pair read from the platform would agree with whatever the platform
# happened to say.
THE_FLOOR_THE_CONTROLLER_FALLS_TO = 3
THE_CEILING_THE_CONTROLLER_REACHES = 6

# How the platform addresses the autoscaler, in Kubernetes' own vocabulary, and
# the patch that holds it still. The vendor's words rather than the fixture's, so
# this case exercises the same wire the write tier will.
AN_AUTOSCALER = {
    "kind": "HorizontalPodAutoscaler",
    "group": "autoscaling",
    "version": "v2",
}
A_MERGE_PATCH = "application/merge-patch+json"

# How long the cycle needs to have been running for the assertions below to have
# something to read. Four minutes is more than one full cycle, so a window over it
# holds at least one complete departed pair and one clear minute between two of
# them - which is the smallest window in which "runs of two" is a claim rather
# than a coincidence.
ENOUGH_OF_THE_CYCLE_SECONDS = 240

# How far the error rate may differ between the cycle's starved minutes and its
# comfortable ones before the difference is the incident rather than the sampling.
# One step of what a rate over a couple of hundred requests can express, which is
# also the smallest difference it can express at all - so this allows the two
# phases to disagree by the least the measurement is capable of and nothing more.
# Measured across spans of 15 to 120 minutes: the two medians differ by at most
# half a step.
THE_ERROR_RATE_MAY_DIFFER_BY = 0.005

# How long to allow a pin before calling it unconfirmed. The same bound Mitigation
# itself waits, because what is under test is whether this fixture is gradeable by
# the rules Argus actually applies rather than by a generous reading of them.
AS_LONG_AS_MITIGATION_WOULD_WAIT_SECONDS = int(
    get_settings().mitigation_verification_timeout_seconds
)


@pytest.mark.e2e
def test_a_flapping_autoscaler_is_an_incident_the_detector_can_date() -> None:
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(A_FLAPPING_AUTOSCALER))
        ) \
        .when(
            _the_cycle_has_run_a_while
        ) \
        .then(
            all_of(
                _an_onset_is_dated(),
                _the_capacity_moves_between_the_declared_bounds(),
                _no_departed_run_outlasts_the_cycle(),
                _nothing_fails_and_nothing_accumulates()
            )
        )


@pytest.mark.e2e
def test_no_minute_of_the_running_cycle_reads_as_a_recovery() -> None:
    """The property that makes every other mitigation here refutable.

    Asserted from every minute in the window rather than from one, because the
    rule is asked with a moment and the answer is allowed to differ per moment:
    Mitigation asks it from the minute after whatever it just did, and which
    minute that is depends on when it acted. A case that checked one moment would
    pass on the phase of the cycle it happened to catch.
    """
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(A_FLAPPING_AUTOSCALER))
        ) \
        .when(
            _the_cycle_has_run_a_while
        ) \
        .then(
            all_of(
                _recovery_is_refused_from_every_minute_in_the_window()
            )
        )


@pytest.mark.e2e
def test_pinning_the_floor_reads_as_a_recovery_and_scaling_out_does_not() -> None:
    """Both halves in one case, because the comparison is the assertion.

    A pin and a scale-out set the same number and differ only in whether it
    holds, so asserting them apart would leave two cases each of which could pass
    against a fixture where the other's outcome was wrong. Staged in this order
    because a scale-out is re-derived away within a minute and leaves nothing
    behind, where a pin holds - so the scale-out has to be measured first, while
    the cycle is still running.
    """
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(A_FLAPPING_AUTOSCALER)),
            calling(_the_cycle_has_run_a_while)
        ) \
        .when(
            _the_deployment_was_scaled_out_directly
        ) \
        .then(
            all_of(
                _the_controller_took_the_count_back(),
                _recovery_is_refused_from_every_minute_in_the_window()
            )
        )

    Scenario() \
        .given(
            calling(_the_cycle_has_run_a_while)
        ) \
        .when(
            _the_autoscalers_floor_was_raised_to_its_ceiling
        ) \
        .then(
            eventually(
                all_of(
                    _the_count_stopped_moving(),
                    _recovery_is_confirmed_since_the_pin()
                ),
                timeout=AS_LONG_AS_MITIGATION_WOULD_WAIT_SECONDS
            )
        )


def _the_cycle_has_run_a_while() -> bool:
    """Waits until the window holds more than one whole cycle.

    The shop backdates this scenario's onset, so the ramp and several cycles are
    already in the window the instant it is seeded - but the minutes an assertion
    about *pairs* needs are the settled ones after the ramp, and the newest of
    those is the minute in progress. So this waits for buckets rather than
    assuming them.
    """
    deadline = datetime.now(UTC) + timedelta(seconds=ENOUGH_OF_THE_CYCLE_SECONDS)

    while datetime.now(UTC) < deadline:
        try:
            if len(_the_settled_minutes()) >= 2 * _a_cycle():
                return True
        except AssertionError:
            # A window with nothing in it yet, or one too short to read a cycle
            # from, is this loop's ordinary early state rather than a failure -
            # both `the_shops_window` and `_a_cycle` refuse rather than return
            # empty, which is right for an assertion and wrong for a wait. The
            # deadline below is what turns "not yet" into "not at all", and it
            # reports what it was waiting for.
            pass

    raise AssertionError(
        f"The Target Service did not report {2 * _a_cycle()} settled minutes "
        f"within {ENOUGH_OF_THE_CYCLE_SECONDS}s of the scenario being seeded, so "
        f"there is not enough of the cycle in the window to assert its shape."
    )


def _a_cycle() -> int:
    """How many minutes one flap takes, derived from what the shop reported.

    Read off the capacity series rather than stated, so this case does not carry
    a second copy of a figure the generator owns: the cycle is however many
    minutes pass between one ceiling minute and the next.
    """
    capacities = _the_capacities_of(_the_settled_minutes())
    at_the_ceiling = [
        index for index, capacity in enumerate(capacities)
        if capacity == float(THE_CEILING_THE_CONTROLLER_REACHES)
    ]

    if len(at_the_ceiling) < 2:
        raise AssertionError(
            f"The window holds {len(at_the_ceiling)} minute(s) at the "
            f"controller's ceiling, so the length of a cycle cannot be read from "
            f"it. Capacities reported: {capacities}."
        )

    return at_the_ceiling[1] - at_the_ceiling[0]


def _an_onset_is_dated() -> Assertion[bool]:
    def assertion(dont_care_ready: bool) -> bool:
        window = _the_window()
        onset = find_onset(window, the_configured_thresholds())

        if onset is None:
            raise AssertionError(
                "The detector dated no onset in a window of a flapping "
                "autoscaler, so this incident would never start. The cycle's "
                "departed minutes must reach "
                f"{the_configured_thresholds().persistence_minutes} in a row; "
                f"p95 across the window was "
                f"{[bucket.p95_ms for bucket in window]}."
            )

        return True

    return assertion


def _the_capacity_moves_between_the_declared_bounds() -> Assertion[bool]:
    """The scenario's signature, and the one series that separates it from the
    surge - where the same figure is constant throughout."""
    def assertion(dont_care_ready: bool) -> bool:
        # The `None`s filtered out rather than carried: capacity is nullable on a
        # bucket, for the deployment that imposes no limit, and a `None` reaching
        # the message below would raise from inside the failure this is trying to
        # report - replacing the real answer with a confusing one at exactly the
        # moment the assertion is doing its job.
        reported = set(_the_capacities_of(_the_settled_minutes()))
        expected = {
            float(THE_FLOOR_THE_CONTROLLER_FALLS_TO),
            float(THE_CEILING_THE_CONTROLLER_REACHES),
        }

        if reported != expected:
            raise AssertionError(
                f"The settled minutes reported capacities {sorted(reported)}, "
                f"where a flapping controller moves between "
                f"{sorted(expected)} and nothing else. One value alone would be "
                f"demand saturation rather than this."
            )

        return True

    return assertion


def _no_departed_run_outlasts_the_cycle() -> Assertion[bool]:
    """The shape recovery is judged by, asserted on the runs that matter.

    On the runs that *reach* persistence, not on every departed minute. The ramp
    passes through merely busy on its way to saturated and a minute there can fall
    either side of the departure bar by a few milliseconds, so a lone departed
    minute in the ramp is allowed - forbidding it would assert something the
    fixture only mostly does, which is worse than asserting less.
    """
    def assertion(dont_care_ready: bool) -> bool:
        persistence = the_configured_thresholds().persistence_minutes
        runs = [
            length for length in _the_departed_runs_in(_the_window())
            if length >= persistence
        ]

        if not runs:
            raise AssertionError(
                "No run of departed minutes in the window reached the "
                f"configured persistence of {persistence}, so this incident is "
                "not detectable at all."
            )

        if max(runs) > _a_cycle() - 1:
            raise AssertionError(
                f"The window holds a departed run of {max(runs)} minutes, where "
                f"a cycle of {_a_cycle()} minutes leaves at most "
                f"{_a_cycle() - 1}. A longer run means the clear minute stopped "
                f"arriving, which is demand saturation and not a flap. Runs "
                f"found: {runs}."
            )

        return True

    return assertion


def _nothing_fails_and_nothing_accumulates() -> Assertion[bool]:
    """Borrowing either signal would blur the distinction from the leak this
    mode's neighbour already exists to draw."""
    def assertion(dont_care_ready: bool) -> bool:
        window = _the_window()
        heaps = [bucket.memory_used_bytes for bucket in window]

        # Asserted as a comparison between the cycle's own phases, not as a bound
        # on how far the series wanders. The shop has an ordinary error rate the
        # way any real service does, and that rate is *sampled*: a couple of
        # hundred requests a minute quantise it into half-percent steps, so
        # consecutive ordinary minutes report 0.0 and 0.015 with nothing having
        # happened. A bound on the worst minute therefore asserts which minutes the
        # wall clock happened to serve - it was `baseline * 1.5 + 0.005`, which at
        # a baseline of 0.005 forbids an ordinary 0.015 minute, and the case was
        # intermittently red for that reason and no other.
        #
        # What this mode must not do is *move* the rate, and moving it means the
        # starved minutes failing more requests than the comfortable ones. Medians
        # per phase say exactly that and the sampling cancels out of them: measured
        # across spans of 15 to 120 minutes the two differ by at most half a step,
        # where a scenario genuinely shedding requests under saturation would
        # separate by far more. Errors are the leak's late signal, and this is the
        # distinction the mode next door exists to draw.
        starved = _the_error_rates_at(THE_FLOOR_THE_CONTROLLER_FALLS_TO)
        comfortable = _the_error_rates_at(THE_CEILING_THE_CONTROLLER_REACHES)
        moved_by = abs(median(starved) - median(comfortable))

        if moved_by > THE_ERROR_RATE_MAY_DIFFER_BY:
            raise AssertionError(
                f"Minutes served at {THE_FLOOR_THE_CONTROLLER_FALLS_TO} replicas "
                f"failed {median(starved)} of their requests against "
                f"{median(comfortable)} at "
                f"{THE_CEILING_THE_CONTROLLER_REACHES}, a difference of "
                f"{moved_by}, so this incident moved the error rate with the cycle "
                f"- which is the leak's late signal and not this mode's. Every "
                f"request here is served, slowly."
            )

        if max(heaps) > 2 * min(heaps):
            raise AssertionError(
                f"The heap moved from {min(heaps)} to {max(heaps)} bytes across "
                f"the window, which is the leak's signal and not this one's."
            )

        return True

    return assertion


def _recovery_is_refused_from_every_minute_in_the_window() -> Assertion[bool]:
    def assertion(dont_care_ready: bool) -> bool:
        window = _the_window()
        thresholds = the_configured_thresholds()
        confirmed = [
            bucket.bucket_id for bucket in window
            if has_recovered_since(window, bucket.bucket_id, thresholds)
        ]

        if confirmed:
            raise AssertionError(
                f"The detector reads the minutes from {confirmed[0]} onwards as "
                f"a recovery while the cycle is still running, so any action "
                f"taken here would be confirmed by waiting - including one that "
                f"changed nothing. {len(confirmed)} of {len(window)} minutes "
                f"read that way."
            )

        return True

    return assertion


def _the_controller_took_the_count_back() -> Assertion[bool]:
    """A scale-out is re-derived away, which is what makes adding capacity the
    wrong answer here and refutable rather than merely unhelpful."""
    def assertion(dont_care_ready: bool) -> bool:
        capacity_now = _the_capacity_of(_the_settled_minutes()[-1])

        if capacity_now != float(THE_FLOOR_THE_CONTROLLER_FALLS_TO):
            return _still_within_one_cycle_of_the_scale_out(capacity_now)

        return True

    return assertion


def _still_within_one_cycle_of_the_scale_out(capacity_now: float) -> bool:
    """Allows the scale-out's own minute and the one ceiling minute that may
    follow it, and nothing beyond that.

    Two clear minutes is the most a directly-set count ever buys - its own bucket,
    plus the cycle's next ceiling minute where it lands just before one. Three
    would mean the count survived the controller, which is the one outcome that
    would make a scale-out confirmable here.
    """
    settled = _the_settled_minutes()
    trailing = 0

    for bucket in reversed(settled):
        if _the_capacity_of(bucket) != float(THE_CEILING_THE_CONTROLLER_REACHES):
            break

        trailing += 1

    if trailing >= _a_cycle():
        raise AssertionError(
            f"The window ends with {trailing} consecutive minutes at the "
            f"controller's ceiling, so the count Argus set directly outlasted a "
            f"whole cycle of {_a_cycle()} minutes. A scale-out that holds is a "
            f"scale-out this scenario would confirm, which is the wrong answer "
            f"being accidentally right. Capacity now: {capacity_now}."
        )

    return True


def _the_count_stopped_moving() -> Assertion[datetime]:
    def assertion(pinned_at: datetime) -> bool:
        since = _the_minutes_since(pinned_at)
        capacities = set(_the_capacities_of(since))

        if capacities != {float(THE_CEILING_THE_CONTROLLER_REACHES)}:
            raise AssertionError(
                f"The minutes since the floor was raised reported capacities "
                f"{sorted(capacities)}, where a pinned controller has nowhere "
                f"left to scale down to and every minute is served at "
                f"{THE_CEILING_THE_CONTROLLER_REACHES} cores."
            )

        return True

    return assertion


def _recovery_is_confirmed_since_the_pin() -> Assertion[datetime]:
    """Measured from the minute *after* the pin, as Mitigation measures it.

    The shop truncates a pin to the bucket it lands in, so that bucket is already
    wholly at the new floor and a case reading from it would be asserting the best
    the fixture allows rather than what Argus will see. Mitigation reads from the
    first whole minute after its own action, on the ground that the minute an
    action falls inside is aggregated over seconds either side of it.
    """
    def assertion(pinned_at: datetime) -> bool:
        window = _the_window()
        first_whole_minute = _to_minute(pinned_at + timedelta(minutes=1))

        if not has_recovered_since(
            window, first_whole_minute, the_configured_thresholds()
        ):
            raise AssertionError(
                f"The detector does not read the minutes from "
                f"{first_whole_minute} as a recovery, so a pin that genuinely "
                f"stopped the flapping would be refuted and put back. p95 since "
                f"then: "
                f"{[bucket.p95_ms for bucket in _the_minutes_since(pinned_at)]}."
            )

        return True

    return assertion


def _the_autoscalers_floor_was_raised_to_its_ceiling() -> datetime:
    """Holds the count still, through the controller rather than around it.

    A patch of the live autoscaler and not a scale of the Deployment, which is
    the whole of what separates this mitigation from the near-miss above: the
    controller owns the replica count, so the only write that holds it is one that
    changes what the controller is allowed to do.
    """
    response = httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/argocd/io-shop/resource",
        params={**AN_AUTOSCALER, "patchType": A_MERGE_PATCH},
        content=json.dumps(
            {"spec": {"minReplicas": THE_CEILING_THE_CONTROLLER_REACHES}}
        ),
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    if response.status_code != HttpStatus.OK:
        raise AssertionError(
            f"The platform refused to raise the autoscaler's floor: "
            f"{response.status_code} {response.text}."
        )

    return datetime.now(UTC)


def _the_deployment_was_scaled_out_directly() -> bool:
    """Sets the replica count the way a scale-out does, through the Deployment.

    The near-miss, performed exactly as the mode next door would perform it, so
    what refutes it is the fixture putting the count back rather than anything
    this case arranges.
    """
    response = httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/argocd/io-shop/resource/actions/v2",
        json={
            "action": "scale",
            "resourceActionParameters": [
                {
                    "name": "replicas",
                    "value": str(THE_CEILING_THE_CONTROLLER_REACHES),
                }
            ],
        },
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    if response.status_code != HttpStatus.OK:
        raise AssertionError(
            f"The platform refused to scale the deployment: "
            f"{response.status_code} {response.text}."
        )

    return True


def _the_capacity_of(bucket: MetricBucket) -> float:
    """What the minute was served with, refusing a bucket that reports nothing.

    `cpu_limit_cores` is nullable on a bucket, for the deployment that imposes no
    limit - and this scenario's deployment always imposes one, so a `None` here is
    the fixture having stopped reporting capacity rather than a case this file has
    to handle. Refused where the field is read, so every assertion downstream takes
    a `float` and a reader added later cannot reintroduce the question.

    Raised rather than filtered. A filter would drop the minute silently and leave
    an assertion about the *shape* of a window quietly reasoning about fewer minutes
    than it was given, which is the failure that looks like a pass.
    """
    if bucket.cpu_limit_cores is None:
        raise AssertionError(
            f"Minute [{bucket.bucket_id}] reported no capacity at all, where this "
            f"scenario's deployment always has one. The fixture has stopped "
            f"reporting `cpu_limit_cores`, and every assertion here about the "
            f"capacity moving is meaningless until it does again."
        )

    return bucket.cpu_limit_cores


def _the_capacities_of(buckets: Sequence[MetricBucket]) -> list[float]:
    """Every minute's capacity, in order, each refused if absent."""
    return [_the_capacity_of(bucket) for bucket in buckets]


def _the_error_rates_at(replicas: int) -> list[float]:
    """What the minutes served by this many replicas failed.

    Selected by capacity rather than by latency, so the two groups are the cycle's
    own phases and not a restatement of the symptom being measured. Refuses an
    empty group: a comparison between phases means nothing if one of them is not
    in the window, and returning an empty list would make `median` raise somewhere
    less informative than here.
    """
    rates = [
        bucket.error_rate for bucket in _the_settled_minutes()
        if _the_capacity_of(bucket) == float(replicas)
    ]

    if not rates:
        raise AssertionError(
            f"No minute in the window was served by {replicas} replicas, so the "
            f"error rate at that phase of the cycle cannot be compared with the "
            f"other. Capacities reported: "
            f"{sorted(set(_the_capacities_of(_the_settled_minutes())))}."
        )

    return rates


def _the_window() -> list[MetricBucket]:
    """The shop's own metrics, as the detector reads them.

    Built into `MetricBucket` rather than read as dictionaries, because what is
    under test is the arithmetic Argus will do - and the model it does that
    arithmetic over is the one place the two sides have to agree about field
    names.
    """
    return [MetricBucket(**bucket) for bucket in the_shops_window()]


def _the_settled_minutes() -> list[MetricBucket]:
    """The window past its ramp, where the cycle is what it will stay.

    Taken as the minutes whose capacity is one of the declared bounds, which is
    every minute the controller has acted on. The ramp's own minutes are in there
    too and belong there - what this excludes is nothing, today, and it is written
    as a filter rather than a slice so that a ramp which one day reports a third
    capacity does not silently become part of the cycle.
    """
    return [
        bucket for bucket in _the_window()
        if _the_capacity_of(bucket) in (
            float(THE_FLOOR_THE_CONTROLLER_FALLS_TO),
            float(THE_CEILING_THE_CONTROLLER_REACHES),
        )
    ]


def _the_minutes_since(moment: datetime) -> list[MetricBucket]:
    since = _to_minute(moment)

    return [bucket for bucket in _the_window() if bucket.bucket_id >= since]


def _the_departed_runs_in(window: Sequence[MetricBucket]) -> list[int]:
    """How long each stretch of elevated minutes was, in minutes.

    Elevated against the window's own quiet half rather than against a figure
    stated here, so this does not become a second copy of the detector's
    arithmetic that can disagree with it. The bar is the median of the calmest
    minutes plus the rise to the worst of them, halved - which is a coarser rule
    than `find_onset`'s and is the right one here: what is being counted is the
    *shape*, and a rule that tracked the detector exactly would assert the
    detector against itself.
    """
    latencies = [float(bucket.p95_ms) for bucket in window]
    quiet = sorted(latencies)[:len(latencies) // 2]
    bar = (sorted(quiet)[len(quiet) // 2] + max(latencies)) / 2
    runs: list[int] = []
    run = 0

    for latency in latencies:
        if latency >= bar:
            run += 1
            continue

        if run:
            runs.append(run)

        run = 0

    if run:
        runs.append(run)

    return runs


def _to_minute(moment: datetime) -> str:
    return moment.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
