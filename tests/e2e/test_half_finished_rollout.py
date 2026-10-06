"""The incident where no revision is at fault, end to end.

A deployment landed and its rolling update was paused half-way. Three replicas
write summary-cache entries in a shape three others cannot read, so an account
page fails whenever an old replica draws an entry a new one wrote. Each revision
alone works - the fixture's own tests are green at both - and what is wrong is
that both are serving.

Three things this case pins that no other one can.

**An error-rate incident that a deployment caused.** Every other incident here
whose error rate steps was a flag's doing, and every other incident caused by a
deployment moved latency. This one steps the error rate and leaves all three
quantiles exactly where they were, which is the flag scenario's telemetry with an
empty flag history and a deploy at the onset.

**A rollback that converges rather than removes.** The revision returned to is not
a revision that was better; it is the one the lagging replicas were already on.
What ends the incident is every replica arriving on the same version, and the
case asserts the fleet converged rather than just that the call was made.

**Mitigated with nothing fixed.** The repository still declares the revision that
was rolling out, automated sync is still suspended, and a withdrawal puts the
split fleet back. What somebody is left with is not a patch but a migration
nobody staged: a version able to read both shapes had to ship before one that
wrote only the new one.

One thing is deliberately not asserted.

**That the rollout channel was read.** It records no reading, as the register and
the deployment-diff channels do not, so it leaves no receipt in the incident's
events or in the replay log. Nothing here can tell a walk that consulted it from
one that guessed. Stated rather than worked around, because the fix is a reading
for a channel with no window - which would put a windowed retrieval in the record
for a question that has none.

The second case asks no model anything: it restarts the shop itself and checks
that Argus's own recovery rule refuses to read that as a recovery. It is what
makes the first meaningful - without it, a fixture that recovered from a restart
would let a walk pass in which restarting cured a split fleet - and it is the one
part of that no walk here can show, since none of them restarts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from http import HTTPStatus as HttpStatus
from statistics import median
from typing import Any

import httpx2
import pytest
from argus_core import get_settings, utc_now
from argus_core.anomaly import find_onset, has_recovered_since
from argus_core.models import FailureMode, IncidentStatus, MetricBucket
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_HALF_FINISHED_ROLLOUT,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_took_a_rollback_of,
    argus_wrote_a_postmortem,
    cause_identified_as,
    investigation_finds_a_deployment_change,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import (
    a_scenario_was_seeded,
    argo_auto_sync_is_disabled,
    the_shops_window,
)
from tests.framework.investigating import the_configured_thresholds

# What the shop's own monitoring pages on here. The same alert the flag scenarios
# raise, and that is the point: the two are told apart by the change channels and
# never by the page.
A_FAILURE_ALERT = "HighErrorRate"

THE_SCENARIO = "half-finished-rollout"

# What the failing share is by construction: half the reads taken by the older
# side, times half the writes made by the newer, times the nine lookups in ten a
# working cache answers. Asserted as a floor well under it rather than as the
# figure, because what is being pinned is that the incident happened at all - a
# bound tight enough to pin the arithmetic belongs in the demo app's own suite,
# which reads the generator rather than a walk.
THE_INCIDENT_FAILED_AT_LEAST = 0.10

# Where the shop sits when nothing is wrong: its ordinary one percent and half a
# point of wobble. Bounded clear of that rather than at it, because the minute a
# rollback lands in is served partly each way and is nobody's evidence.
A_QUIET_MINUTE_FAILS_UNDER = 0.05

# How far the failing minutes' middle may sit from the quiet minutes' before the
# difference is a latency signal rather than sampling. Ten percent, which is five
# times what the two middles actually differ by here and a small fraction of what a
# real move would be: every latency scenario in the fixture multiplies a quantile,
# and the smallest of them more than triples it. Not a bound on a single minute -
# the generator reports whole milliseconds, so one quiet minute differs from another
# by more than this.
A_QUANTILE_MAY_DRIFT_BY = 0.10

# How the platform reports what is actually running. The manifest arrives as
# text, which is Argo CD's own shape for this response.
A_MANIFEST = "manifest"

# How much of the window has to be settled before a restart is worth judging. The
# scenario backdates its onset, so departed minutes are in the window the instant
# it is seeded - but the newest of them is the minute in progress, and a partial
# minute reports a rate taken over however many requests have arrived. Two whole
# minutes is the persistence the detector dates an onset from.
ENOUGH_MINUTES_SECONDS = 180

# How long to go on refusing a restart before calling the refusal held. The same
# bound Mitigation itself waits, because what is under test is whether the rule
# Argus actually applies refuses it, not a generous reading of that rule.
AS_LONG_AS_MITIGATION_WOULD_WAIT_SECONDS = int(
    get_settings().mitigation_verification_timeout_seconds
)


@pytest.mark.e2e
def test_a_rollout_stopped_half_way_is_ended_by_converging_the_fleet() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_FAILURE_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded(THE_SCENARIO)),
            calling(the_model_answers_from(RECORDED_HALF_FINISHED_ROLLOUT))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.IN_FLIGHT_COMPATIBILITY_BREAK),
                    investigation_finds_a_deployment_change(),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    argus_took_a_rollback_of(THE_SERVICE_NAME),
                    _the_shop_failed_and_then_stopped_failing(),
                    _no_quantile_ever_moved(),
                    _every_replica_is_on_one_revision(),
                    _the_rolling_update_is_no_longer_paused(),
                    argo_auto_sync_is_disabled(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_restart_of_a_split_fleet_is_not_read_as_a_recovery() -> None:
    """The near-miss, refused by the rule Argus judges every mitigation by.

    A restart brings the process back with the fleet still split, so nothing about
    the mixture is the process's doing. If Argus's rule ever read that as a
    recovery, this mode's near-miss would be accidentally right and every recording
    made afterwards would agree. No walk here takes it, which is why it is staged
    by hand.
    """
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(THE_SCENARIO)),
            calling(_enough_whole_minutes_have_passed)
        ) \
        .when(
            _the_shop_was_restarted
        ) \
        .then(
            _recovery_is_refused_since_the_restart()
        )


def _the_shop_failed_and_then_stopped_failing() -> Assertion[httpx2.Response]:
    """The incident is in the window, and so is its end.

    Both halves in one assertion because either alone passes against a world
    nobody would accept: a window with only the failures is a mitigation that
    never landed, and a window with only the quiet minutes is a scenario that
    never staged anything.

    The last minute is excluded. It is the minute in progress, and its rate is
    taken over however many requests have arrived so far.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        window = the_shops_window()[:-1]
        rates = [minute["error_rate"] for minute in window]

        if not any(rate >= THE_INCIDENT_FAILED_AT_LEAST for rate in rates):
            raise AssertionError(
                f"No minute in the window failed at {THE_INCIDENT_FAILED_AT_LEAST} "
                f"or worse, so the scenario staged nothing for Argus to end. "
                f"Error rates reported: {rates}."
            )

        if rates[-1] >= A_QUIET_MINUTE_FAILS_UNDER:
            raise AssertionError(
                f"The window ends at an error rate of {rates[-1]}, so whatever "
                f"Argus did to this shop did not converge the fleet. Error rates "
                f"reported: {rates}."
            )

        return True

    return assertion


def _no_quantile_ever_moved() -> Assertion[httpx2.Response]:
    """Latency is where it was, throughout, which is half of what makes this hard.

    A page that cannot read a cache entry fails immediately, so nothing waits.

    Partitioned by the error rate and compared as two populations, rather than
    bounding every minute against the window's middle. The generator reports each
    quantile as a whole millisecond, so a 26ms p50 differs by more than a tenth of
    itself between two quiet minutes - an assertion tight enough to catch a moved
    quantile minute by minute is one the jitter breaks first, and this window holds
    six failing minutes against three hundred and fifty quiet ones.

    Comparing the middles instead says the thing the case means: the minutes that
    failed were served as fast as the minutes that did not. Every latency scenario
    in this fixture multiplies a quantile and the smallest of them more than
    triples it, so a real move clears this bound many times over.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        window = the_shops_window()[:-1]
        during = [
            minute for minute in window
            if minute["error_rate"] >= THE_INCIDENT_FAILED_AT_LEAST
        ]
        quiet = [
            minute for minute in window
            if minute["error_rate"] < A_QUIET_MINUTE_FAILS_UNDER
        ]

        if not during or not quiet:
            raise AssertionError(
                f"The window has {len(during)} failing minutes and {len(quiet)} "
                f"quiet ones, so there is nothing to compare: latency cannot be "
                f"shown to have held across an incident the metrics do not show."
            )

        moved = []

        for series in ("p50_ms", "p95_ms", "p99_ms"):
            failing_middle = median(float(minute[series]) for minute in during)
            quiet_middle = median(float(minute[series]) for minute in quiet)

            if abs(failing_middle - quiet_middle) > quiet_middle * A_QUANTILE_MAY_DRIFT_BY:
                moved.append((series, quiet_middle, failing_middle))

        if moved:
            raise AssertionError(
                f"Latency moved during an incident that is meant to live in the "
                f"error rate alone: {moved} as (series, the quiet minutes' middle, "
                f"the failing minutes'). A reader of these metrics would have a "
                f"signal this scenario never staged, and the collision with a flag "
                f"toggle that makes this mode hard would be gone."
            )

        return True

    return assertion


def _every_replica_is_on_one_revision() -> Assertion[httpx2.Response]:
    """The fleet converged, which is what the rollback actually achieved.

    Asserted rather than inferred from the call having been made, because this is
    the one mode where the action's *effect* is the diagnosis: returning the
    deployment removed nothing that was wrong, and what ended the incident is
    that one version is now reading and writing one shape.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        manifest = _the_running_deployment()
        status: dict[str, Any] = manifest.get("status", {})
        serving = status.get("replicas")
        updated = status.get("updatedReplicas")

        if serving != updated:
            raise AssertionError(
                f"The platform reports {updated} of {serving} replicas on the "
                f"newest revision, so the fleet is still split and the incident "
                f"is still happening whatever the record says."
            )

        return True

    return assertion


def _the_rolling_update_is_no_longer_paused() -> Assertion[httpx2.Response]:
    """The thing that held the fleet apart is gone.

    Separate from the count because the two can disagree and the disagreement is
    informative: a paused rollout that happens to be converged is a deployment
    one sync away from splitting again.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        paused = _the_running_deployment().get("spec", {}).get("paused")

        if paused:
            raise AssertionError(
                "The rolling update is still paused after the rollback, so the "
                "platform is still holding the fleet where it was."
            )

        return True

    return assertion


def _the_running_deployment() -> dict[str, Any]:
    """What the platform says is actually running, parsed out of its wrapper.

    The live resource and not the values file: git holds what was asked for, and
    this holds what a rollback made true. The manifest is carried as a string,
    which is Argo CD's own shape for this response.
    """
    response = httpx2.get(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}/resource",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    manifest: dict[str, Any] = json.loads(response.json()[A_MANIFEST])

    return manifest


def _recovery_is_refused_since_the_restart() -> Assertion[datetime]:
    """A restart changes nothing, and goes on changing nothing.

    Waited out for as long as Mitigation would wait rather than checked once.
    What makes a wrong answer refutable is that it is still wrong when the
    verification window closes, and a single early read would pass against a
    fixture that recovered a minute later.
    """
    def assertion(restarted_at: datetime) -> bool:
        deadline = utc_now() + timedelta(
            seconds=AS_LONG_AS_MITIGATION_WOULD_WAIT_SECONDS
        )

        while utc_now() < deadline:
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


def _enough_whole_minutes_have_passed() -> bool:
    """Waits until the window holds whole minutes to read rather than a partial one.

    The shop backdates this scenario's onset, so departed minutes are already in
    the window the instant it is seeded - but the newest is the minute in
    progress, whose rate is taken over however many requests have arrived so far.
    So this waits for buckets rather than assuming them.
    """
    deadline = utc_now() + timedelta(seconds=ENOUGH_MINUTES_SECONDS)
    wanted = the_configured_thresholds().persistence_minutes + 1

    while utc_now() < deadline:
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


def _the_shop_was_restarted() -> datetime:
    """Brings the process back, the way the restart mitigation does."""
    response = httpx2.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/restart",
        timeout=REQUEST_TIMEOUT_SECONDS
    )

    if response.status_code != HttpStatus.OK:
        raise AssertionError(
            f"The shop refused to restart: {response.status_code} {response.text}."
        )

    return utc_now()


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


def _the_minutes_since(moment: datetime) -> list[MetricBucket]:
    since = _to_minute(moment)

    return [bucket for bucket in _the_window() if bucket.bucket_id >= since]


def _to_minute(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:00Z")
