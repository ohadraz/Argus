"""Whether a deployment converged, as the read tier answers it (spec §16).

The sixth retrieval channel, and the one that reads a deployment as a stretch
rather than as an instant. Every channel before it - the metrics, the logs, the
flag provider, the deploy history and the diff - describes something that
happened at a moment; the history in particular records that a revision was
deployed and is silent about whether it finished arriving. A rollout that
stopped part way is therefore invisible to all five, and it is the whole of what
separates a revision that is wrong from two revisions serving at once.

Two reads meet here and neither leaves the tier. The live Deployment says how
many replicas have reached the new revision and whether the rolling update is
paused; the application's history names the revision being converged on and the
one the lagging replicas are still running. How either is read off the platform -
the manifest, its conditions, a status nobody filled in - is the adapter's, and
pinned in its own suite.

Nothing here judges. A deployment part way through a rollout is the ordinary
condition of every deployment for a minute or two, and a channel that called one
stuck would be deciding, on a timing it cannot know, something that belongs to
whoever weighs causes.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.models import RolloutProgress
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformReads,
    DeploymentRecord,
    PlatformRefused,
    PlatformUnreachable,
)
from read_mcp_server.rollouts import (
    RolloutUnreadable,
    how_far_the_rollout_has_got,
    how_the_rollout_is_going,
)

SOME_SERVICE = "io-shop"

THE_REVISION_BEING_ROLLED_OUT = "9c1f0ab2d4e6f8a0b2c4d6e8fa0b2c4d6e8fa0b2"
THE_REVISION_STILL_SERVING = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"

WHEN_IT_LANDED = "2026-08-20T11:05:00Z"
WHEN_THE_ONE_BEFORE_IT_LANDED = "2026-08-20T10:05:00Z"

# Six replicas, three of them updated: the split this channel exists to report,
# and the point at which an in-flight incompatibility fails the most requests.
SOME_FLEET_SIZE = 6
HALF_OF_IT = 3

# Words a channel that had drawn a conclusion would use. Asserted against
# rather than for, because the failure this guards is an answer that reads as a
# verdict - and a verdict here would be one reached from a replica count and a
# timestamp.
VERDICTS_IT_MAY_NOT_REACH = ("fault", "stuck", "wrong", "unhealthy", "dangerous")


@pytest.mark.unit
def test_a_rollout_that_has_not_finished_names_both_revisions_and_the_split() -> None:
    # The answer the mode turns on. A reader holding it can say that neither
    # revision is the subject - both are serving - which no other channel can
    # tell them.
    Scenario() \
        .given(platform := _a_platform(a_fleet_half_updated(), deployed_twice())) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(all_of(
            _the_answer_mentions("not converged"),
            _the_answer_mentions(THE_REVISION_BEING_ROLLED_OUT),
            _the_answer_mentions(THE_REVISION_STILL_SERVING),
            _the_answer_mentions(str(HALF_OF_IT)),
            _the_answer_mentions(str(SOME_FLEET_SIZE))
        ))


@pytest.mark.unit
def test_a_converged_deployment_says_so_and_names_the_revision_every_replica_runs() -> None:
    # Twelve of the thirteen scenarios answer this way, and the answer is
    # evidence rather than a blank: a reader weighing a deploy at the onset has
    # been told the deploy is not half-applied, which rules the new mode out.
    Scenario() \
        .given(platform := _a_platform(a_converged_fleet(), deployed_twice())) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(all_of(
            _the_answer_mentions("converged"),
            _the_answer_mentions(THE_REVISION_BEING_ROLLED_OUT)
        ))


@pytest.mark.unit
def test_a_paused_rolling_update_is_reported_as_paused() -> None:
    # Why it is not progressing, which is a different fact from that it has not
    # progressed - and the one that says a person stopped it rather than that
    # the platform is slow.
    Scenario() \
        .given(platform := _a_platform(
            a_fleet_half_updated(paused=True), deployed_twice()
        )) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(_the_answer_mentions("paused"))


@pytest.mark.unit
def test_the_answer_says_when_the_deployment_landed() -> None:
    # Said rather than counted from: this tier has no clock, and a reader
    # holding an onset can do the arithmetic. Without it a split fleet is a
    # state with no duration, which reads the same two minutes and two hours
    # into a rollout.
    Scenario() \
        .given(platform := _a_platform(a_fleet_half_updated(), deployed_twice())) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(_the_answer_mentions(WHEN_IT_LANDED))


@pytest.mark.unit
def test_the_live_deployment_is_read_and_not_only_the_history() -> None:
    # The history cannot answer this question: it records syncs that completed.
    # A channel that derived convergence from it would answer about a past
    # event and call it the present one.
    Scenario() \
        .given(platform := _a_platform(a_fleet_half_updated(), deployed_twice())) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(lambda _: _the_live_deployment_was_read(platform))


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [PlatformUnreachable("platform is down"), PlatformRefused("not this answer")],
    ids=["unreachable", "refused"]
)
def test_a_platform_that_did_not_answer_is_not_reported_as_converged(
    failure: DeploymentPlatformError
) -> None:
    # The one answer that must never be produced by a failure. "It converged"
    # rules the mode out, so an outage read as convergence sends a walk to
    # blame a revision that is not at fault.
    Scenario() \
        .given(platform := _a_platform_failing_with(failure)) \
        .when(attempting(
            lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)
        )) \
        .then(an_error_was_raised(RolloutUnreadable))


@pytest.mark.unit
def test_a_split_fleet_with_nothing_deployed_before_it_says_the_older_revision_is_unknown() -> None:
    # An application whose history holds one entry has no earlier revision to
    # name, and the replicas that have not updated are running *something*. Said
    # rather than left out: a reader told only about the new revision would read
    # the split as a count with no second subject.
    Scenario() \
        .given(platform := _a_platform(a_fleet_half_updated(), deployed_once())) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(all_of(
            _the_answer_mentions("not converged"),
            _the_answer_mentions("no earlier deployment")
        ))


@pytest.mark.unit
def test_a_rollout_in_progress_is_described_and_not_judged() -> None:
    # Every deployment is part way through for a minute or two. Whether this one
    # has been too long is the reader's judgement, made against an onset this
    # channel has never seen.
    Scenario() \
        .given(platform := _a_platform(
            a_fleet_half_updated(paused=True), deployed_twice()
        )) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(_the_answer_reaches_no_verdict())


@pytest.mark.unit
def test_how_far_the_rollout_has_got_is_the_platforms_answer_for_a_caller() -> None:
    # The same read as the lines above, answered as a value. The lines exist for
    # a model and must keep existing: §16's channel describes rather than judges,
    # and the Investigator hands those sentences to one. What a *caller* needs is
    # the count, and Mitigation finding it by searching prose for a number would
    # be the wire-vocabulary mistake this repo refuses, one layer in.
    #
    # Why Mitigation needs it at all: until every replica is on the revision it
    # rolled back to, a minute of metrics is a minute the old code was still
    # serving, and a recovery judged off those minutes is a recovery judged of the
    # wrong deployment. So the count is what says when the judging may begin.
    the_fleet = a_fleet_half_updated()

    Scenario() \
        .given(platform := _a_platform(the_fleet, deployed_twice())) \
        .when(lambda: how_far_the_rollout_has_got(SOME_SERVICE, platform=platform)) \
        .then(_it_is(the_fleet))


@pytest.mark.unit
def test_how_far_the_rollout_has_got_reads_no_history() -> None:
    # Which revisions are involved is what a reader wants named; whether the
    # change has arrived is answered by the counts alone, so asking the history
    # would be a second read bought for nothing.
    Scenario() \
        .given(platform := _a_platform(a_converged_fleet(), deployed_twice())) \
        .when(lambda: how_far_the_rollout_has_got(SOME_SERVICE, platform=platform)) \
        .then(lambda _: _the_history_was_not_read(platform))


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    [PlatformUnreachable("platform is down"), PlatformRefused("not this answer")],
    ids=["unreachable", "refused"]
)
def test_a_platform_that_did_not_answer_is_not_counted_as_converged(
    failure: DeploymentPlatformError
) -> None:
    # The same refusal the lines make, and it matters more here. A caller told
    # "converged" starts judging a recovery immediately, so a platform outage read
    # as arrival would have Mitigation measure the minutes before its own change
    # landed and confirm or refute an action on them. Raising leaves the caller
    # with something to handle rather than a figure to act on.
    Scenario() \
        .given(platform := _a_platform_failing_with(failure)) \
        .when(attempting(
            lambda: how_far_the_rollout_has_got(SOME_SERVICE, platform=platform)
        )) \
        .then(an_error_was_raised(RolloutUnreadable))


def a_fleet_half_updated(paused: bool = False) -> RolloutProgress:
    """Six replicas, three on the revision being rolled out."""
    return RolloutProgress(
        replicas_wanted=SOME_FLEET_SIZE,
        replicas_serving=SOME_FLEET_SIZE,
        replicas_updated=HALF_OF_IT,
        is_paused=paused,
        has_failed=False
    )


def a_converged_fleet() -> RolloutProgress:
    """Every replica on the revision that was deployed."""
    return RolloutProgress(
        replicas_wanted=SOME_FLEET_SIZE,
        replicas_serving=SOME_FLEET_SIZE,
        replicas_updated=SOME_FLEET_SIZE,
        is_paused=False,
        has_failed=False
    )


def deployed_once() -> list[DeploymentRecord]:
    """A history with one entry: nothing was deployed before it."""
    return [_a_deployment_of(THE_REVISION_BEING_ROLLED_OUT, at=WHEN_IT_LANDED)]


def deployed_twice() -> list[DeploymentRecord]:
    """The ordinary case: the revision going out, and the one it is replacing."""
    return [
        _a_deployment_of(THE_REVISION_STILL_SERVING, at=WHEN_THE_ONE_BEFORE_IT_LANDED),
        _a_deployment_of(THE_REVISION_BEING_ROLLED_OUT, at=WHEN_IT_LANDED)
    ]


def _a_deployment_of(revision: str, at: str) -> DeploymentRecord:
    return DeploymentRecord(
        history_id=1,
        revision=revision,
        deployed_at=at,
        repo_url=None,
        path=None,
        initiated_by=None
    )


def _a_platform(rollout: RolloutProgress, deployed: list[DeploymentRecord]) -> Any:
    platform = create_autospec(DeploymentPlatformReads, instance=True)
    platform.rollout_of.return_value = rollout
    platform.deployments_of.return_value = deployed
    return platform


def _a_platform_failing_with(failure: DeploymentPlatformError) -> Any:
    platform = create_autospec(DeploymentPlatformReads, instance=True)
    platform.rollout_of.side_effect = failure
    platform.deployments_of.return_value = deployed_twice()
    return platform


def _it_is(expected: RolloutProgress) -> Assertion[RolloutProgress]:
    """The platform's counts, reaching the caller unchanged."""
    def assertion(progress: RolloutProgress) -> bool:
        if progress != expected:
            raise AssertionError(
                f"Expected the platform's own answer [{expected!r}], and the "
                f"caller got [{progress!r}]."
            )

        return True

    return assertion


def _the_answer_mentions(wanted: str) -> Assertion[list[str]]:
    """Something a model has to be able to read in the answer."""
    def assertion(answered: list[str]) -> bool:
        if not any(wanted in line for line in answered):
            raise AssertionError(
                f"Expected the answer to mention [{wanted}], and it says "
                f"{answered}."
            )

        return True

    return assertion


def _the_live_deployment_was_read(platform: Any) -> bool:
    """The live resource was asked about, and asked about by name."""
    asked = [call.args for call in platform.rollout_of.call_args_list]

    if asked != [(SOME_SERVICE,)]:
        raise AssertionError(
            f"Expected the live Deployment of [{SOME_SERVICE}] to be read once, "
            f"and the platform was asked {asked}."
        )

    return True


def _the_history_was_not_read(platform: Any) -> bool:
    if platform.deployments_of.called:
        raise AssertionError(
            f"Expected no history to be read for a count, and it was asked "
            f"{platform.deployments_of.call_args_list}."
        )

    return True


def _the_answer_reaches_no_verdict() -> Assertion[list[str]]:
    """Nothing in the answer calls the rollout anything."""
    def assertion(answered: list[str]) -> bool:
        judged = [
            verdict for verdict in VERDICTS_IT_MAY_NOT_REACH
            if any(verdict in line.lower() for line in answered)
        ]

        if judged:
            raise AssertionError(
                f"The answer calls the rollout {sorted(judged)}, which is a "
                f"conclusion drawn from a replica count and a timestamp - and "
                f"it belongs to whoever weighs causes, who has the onset this "
                f"channel has never seen. It says {answered}."
            )

        return True

    return assertion
