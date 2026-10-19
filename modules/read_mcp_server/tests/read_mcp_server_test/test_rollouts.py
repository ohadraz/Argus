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

Answered as a value, never as prose. Two readers say it - the Investigator's
model and the account of the incident - and each says it in its own words;
words written here would leave the second to search the first's for a revision
and a time. What the model reads is the Investigator's, and pinned in its suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.models import RolloutAccount, RolloutProgress
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


@pytest.mark.unit
def test_the_account_carries_the_platform_s_counts_unchanged() -> None:
    # The counts are the platform's, and the split, the pause and the failure
    # are all in them. Nothing here reads them for a verdict: a rollout part
    # way through is the ordinary condition of every deployment for a minute
    # or two.
    the_fleet = a_fleet_half_updated(paused=True)

    Scenario() \
        .given(platform := _a_platform(the_fleet, deployed_twice())) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(_it_counts(the_fleet))


@pytest.mark.unit
def test_the_account_names_the_revision_going_out_and_the_one_before_it() -> None:
    # The two revisions a split fleet is serving, each with when it was
    # deployed - said rather than counted from, since this tier has no clock and
    # a reader holding an onset can do the arithmetic.
    Scenario() \
        .given(platform := _a_platform(a_fleet_half_updated(), deployed_twice())) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(all_of(
            _the_one_going_out_is(THE_REVISION_BEING_ROLLED_OUT, deployed_at=WHEN_IT_LANDED),
            _the_one_before_it_is(THE_REVISION_STILL_SERVING,
                                  deployed_at=WHEN_THE_ONE_BEFORE_IT_LANDED)
        ))


@pytest.mark.unit
def test_a_history_with_one_deployment_names_nothing_before_it() -> None:
    # The replicas that have not updated are running *something*, and the
    # history cannot say what. None rather than a guess, so whoever says it
    # can say it is unknown.
    Scenario() \
        .given(platform := _a_platform(a_fleet_half_updated(), deployed_once())) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(all_of(
            _the_one_going_out_is(THE_REVISION_BEING_ROLLED_OUT, deployed_at=WHEN_IT_LANDED),
            _nothing_is_named_before_it()
        ))


@pytest.mark.unit
def test_a_history_with_nothing_in_it_names_no_revision() -> None:
    # A fleet can be counted with no deploy on record - one the history has
    # lost, or never held - and the counts are still the platform's answer.
    Scenario() \
        .given(platform := _a_platform(a_converged_fleet(), [])) \
        .when(lambda: how_the_rollout_is_going(SOME_SERVICE, platform=platform)) \
        .then(all_of(
            _it_counts(a_converged_fleet()),
            _nothing_is_named_going_out(),
            _nothing_is_named_before_it()
        ))


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
def test_how_far_the_rollout_has_got_is_the_platforms_answer_for_a_caller() -> None:
    # The counts alone, for a caller that waits on them. Why Mitigation needs
    # it at all: until every replica is on the revision it rolled back to, a
    # minute of metrics is a minute the old code was still serving, and a
    # recovery judged off those minutes is a recovery judged of the wrong
    # deployment. So the count is what says when the judging may begin.
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
    # The same refusal the account makes, and it matters more here. A caller
    # told "converged" starts judging a recovery immediately, so a platform
    # outage read as arrival would have Mitigation measure the minutes before
    # its own change landed and confirm or refute an action on them. Raising
    # leaves the caller with something to handle rather than a figure to act on.
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


def _it_counts(expected: RolloutProgress) -> Assertion[RolloutAccount]:
    """The platform's counts, carried in the account unchanged."""
    def assertion(account: RolloutAccount) -> bool:
        if account.progress != expected:
            raise AssertionError(
                f"Expected the account to carry the platform's counts "
                f"[{expected!r}], and it carries [{account.progress!r}]."
            )

        return True

    return assertion


def _the_one_going_out_is(revision: str, *, deployed_at: str) -> Assertion[RolloutAccount]:
    def assertion(account: RolloutAccount) -> bool:
        named = ((account.going_out.reference, account.going_out.occurred_at)
                 if account.going_out is not None else None)

        if named != (revision, deployed_at):
            raise AssertionError(
                f"Expected the revision going out to be [{revision}], deployed at "
                f"[{deployed_at}], and the account names {named}."
            )

        return True

    return assertion


def _the_one_before_it_is(revision: str, *, deployed_at: str) -> Assertion[RolloutAccount]:
    def assertion(account: RolloutAccount) -> bool:
        named = ((account.before_it.reference, account.before_it.occurred_at)
                 if account.before_it is not None else None)

        if named != (revision, deployed_at):
            raise AssertionError(
                f"Expected the revision before it to be [{revision}], deployed at "
                f"[{deployed_at}], and the account names {named}."
            )

        return True

    return assertion


def _nothing_is_named_going_out() -> Assertion[RolloutAccount]:
    def assertion(account: RolloutAccount) -> bool:
        if account.going_out is not None:
            raise AssertionError(
                f"Expected no revision going out from a history with nothing in "
                f"it, and the account names [{account.going_out}]."
            )

        return True

    return assertion


def _nothing_is_named_before_it() -> Assertion[RolloutAccount]:
    def assertion(account: RolloutAccount) -> bool:
        if account.before_it is not None:
            raise AssertionError(
                f"Expected nothing named before the revision going out, and the "
                f"account names [{account.before_it}]."
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
