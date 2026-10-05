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
one the lagging replicas are still running.

Nothing here judges. A deployment part way through a rollout is the ordinary
condition of every deployment for a minute or two, and a channel that called one
stuck would be deciding, on a timing it cannot know, something that belongs to
whoever weighs causes.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_core.models import RolloutProgress
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from read_mcp_server.rollouts import (
    CONDITION_FALSE,
    CONDITION_STATUS,
    CONDITION_TRUE,
    CONDITION_TYPE,
    PROGRESSING_CONDITION,
    REPLICA_FAILURE_CONDITION,
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

# Kubernetes' words for the conditions these cases stage, which the tier reads
# by type and status and never by reason - so they are this file's to say, not
# vocabulary the module shares.
CONDITION_UNKNOWN = "Unknown"
FAILED_CREATE_REASON = "FailedCreate"
PROGRESS_DEADLINE_EXCEEDED_REASON = "ProgressDeadlineExceeded"
DEPLOYMENT_PAUSED_REASON = "DeploymentPaused"


@pytest.mark.unit
def test_a_rollout_that_has_not_finished_names_both_revisions_and_the_split() -> None:
    # The answer the mode turns on. A reader holding it can say that neither
    # revision is the subject - both are serving - which no other channel can
    # tell them.
    Scenario() \
        .when(
            lambda: how_the_rollout_is_going(
                SOME_SERVICE,
                fetch_deployment=a_fleet_half_updated(),
                fetch=an_application_deployed_twice()
            )
        ) \
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
        .when(
            lambda: how_the_rollout_is_going(
                SOME_SERVICE,
                fetch_deployment=a_converged_fleet(),
                fetch=an_application_deployed_twice()
            )
        ) \
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
        .when(
            lambda: how_the_rollout_is_going(
                SOME_SERVICE,
                fetch_deployment=a_fleet_half_updated(paused=True),
                fetch=an_application_deployed_twice()
            )
        ) \
        .then(_the_answer_mentions("paused"))


@pytest.mark.unit
def test_the_answer_says_when_the_deployment_landed() -> None:
    # Said rather than counted from: this tier has no clock, and a reader
    # holding an onset can do the arithmetic. Without it a split fleet is a
    # state with no duration, which reads the same two minutes and two hours
    # into a rollout.
    Scenario() \
        .when(
            lambda: how_the_rollout_is_going(
                SOME_SERVICE,
                fetch_deployment=a_fleet_half_updated(),
                fetch=an_application_deployed_twice()
            )
        ) \
        .then(_the_answer_mentions(WHEN_IT_LANDED))


@pytest.mark.unit
def test_the_live_deployment_is_read_and_not_only_the_history() -> None:
    # The history cannot answer this question: it records syncs that completed.
    # A channel that derived convergence from it would answer about a past
    # event and call it the present one.
    dont_care_history = an_application_deployed_twice()
    live = a_fleet_half_updated()

    Scenario() \
        .given(live) \
        .when(
            lambda: how_the_rollout_is_going(
                SOME_SERVICE, fetch_deployment=live, fetch=dont_care_history
            )
        ) \
        .then(_the_live_deployment_was_read(live))


@pytest.mark.unit
def test_a_platform_that_cannot_be_reached_is_not_reported_as_converged() -> None:
    # The one answer that must never be produced by a failure. "It converged"
    # rules the mode out, so an outage read as convergence sends a walk to
    # blame a revision that is not at fault.
    Scenario() \
        .when(
            attempting(
                lambda: how_the_rollout_is_going(
                    SOME_SERVICE,
                    fetch_deployment=a_platform_that_cannot_be_reached(),
                    fetch=an_application_deployed_twice()
                )
            )
        ) \
        .then(an_error_was_raised(RolloutUnreadable))


@pytest.mark.unit
def test_a_deployment_the_platform_reports_no_progress_for_reads_as_converged() -> None:
    # A Deployment whose manifest carries no rollout status is one nothing says
    # any replica is lagging on. Refusing to answer would leave every scenario
    # but one with an unhelpful line, and guessing a split would invent an
    # incident.
    Scenario() \
        .when(
            lambda: how_the_rollout_is_going(
                SOME_SERVICE,
                fetch_deployment=a_fleet_reporting_no_status(),
                fetch=an_application_deployed_twice()
            )
        ) \
        .then(_the_answer_mentions("converged"))


@pytest.mark.unit
def test_a_split_fleet_with_nothing_deployed_before_it_says_the_older_revision_is_unknown() -> None:
    # An application whose history holds one entry has no earlier revision to
    # name, and the replicas that have not updated are running *something*. Said
    # rather than left out: a reader told only about the new revision would read
    # the split as a count with no second subject.
    Scenario() \
        .when(
            lambda: how_the_rollout_is_going(
                SOME_SERVICE,
                fetch_deployment=a_fleet_half_updated(),
                fetch=an_application_deployed_once()
            )
        ) \
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
        .when(
            lambda: how_the_rollout_is_going(
                SOME_SERVICE,
                fetch_deployment=a_fleet_half_updated(paused=True),
                fetch=an_application_deployed_twice()
            )
        ) \
        .then(_the_answer_reaches_no_verdict())


@pytest.mark.unit
def test_how_far_the_rollout_has_got_counts_the_replicas_for_a_caller() -> None:
    # The same two reads as the lines above, answered as a value. The lines exist
    # for a model and must keep existing: §16's channel describes rather than
    # judges, and the Investigator hands those sentences to one. What a *caller*
    # needs is the count, and Mitigation finding it by searching prose for a
    # number would be the wire-vocabulary mistake this repo refuses, one layer in.
    #
    # Why Mitigation needs it at all: until every replica is on the revision it
    # rolled back to, a minute of metrics is a minute the old code was still
    # serving, and a recovery judged off those minutes is a recovery judged of the
    # wrong deployment. So the count is what says when the judging may begin.
    #
    # No history is read here, and that is the difference from the lines. Which
    # revisions are involved is what a reader wants named; whether the change has
    # arrived is answered by the counts alone, so asking the application's history
    # would be a second read bought for nothing.
    Scenario() \
        .when(
            lambda: how_far_the_rollout_has_got(
                SOME_SERVICE, fetch_deployment=a_fleet_half_updated()
            )
        ) \
        .then(all_of(
            _it_counted(serving=SOME_FLEET_SIZE, updated=HALF_OF_IT),
            _it_has_converged(False)
        ))


@pytest.mark.unit
def test_a_fleet_whose_replicas_all_arrived_is_reported_as_converged() -> None:
    # The answer Mitigation waits for, and the moment its own clock may start.
    Scenario() \
        .when(
            lambda: how_far_the_rollout_has_got(
                SOME_SERVICE, fetch_deployment=a_converged_fleet()
            )
        ) \
        .then(all_of(
            _it_counted(serving=SOME_FLEET_SIZE, updated=SOME_FLEET_SIZE),
            _it_has_converged(True)
        ))


@pytest.mark.unit
def test_a_platform_that_cannot_be_reached_is_not_counted_as_converged() -> None:
    # The same refusal the lines make, and it matters more here. A caller told
    # "converged" starts judging a recovery immediately, so a platform outage read
    # as arrival would have Mitigation measure the minutes before its own change
    # landed and confirm or refute an action on them. Raising leaves the caller
    # with something to handle rather than a figure to act on.
    Scenario() \
        .when(
            attempting(
                lambda: how_far_the_rollout_has_got(
                    SOME_SERVICE, fetch_deployment=a_platform_that_cannot_be_reached()
                )
            )
        ) \
        .then(an_error_was_raised(RolloutUnreadable))


@pytest.mark.unit
def test_a_deployment_that_cannot_create_its_replicas_is_counted_as_failed() -> None:
    # What a scale-out that ran into the namespace's quota looks like, and the
    # platform says it at once rather than at a deadline: the ReplicaSet could not
    # create the pods, and the Deployment carries that as a condition of its own.
    # A state the platform reports, so reading it is not the judgement §16 keeps
    # off this side - and it is the only thing that ends a scale-out's wait, since
    # the controller goes on scaling a paused Deployment.
    Scenario() \
        .when(
            lambda: how_far_the_rollout_has_got(
                SOME_SERVICE,
                fetch_deployment=a_fleet_half_updated(
                    _a_condition(
                        REPLICA_FAILURE_CONDITION, CONDITION_TRUE,
                        FAILED_CREATE_REASON
                    )
                )
            )
        ) \
        .then(_it_has_failed(True))


@pytest.mark.unit
def test_a_deployment_past_its_progress_deadline_is_counted_as_failed() -> None:
    # The other way a Deployment fails: no progress within the deadline it
    # declares, which Kubernetes defaults to ten minutes. The platform measured
    # that against a figure the Deployment itself carries and said so - nobody on
    # this side chose how long is too long.
    Scenario() \
        .when(
            lambda: how_far_the_rollout_has_got(
                SOME_SERVICE,
                fetch_deployment=a_fleet_half_updated(
                    _a_condition(
                        PROGRESSING_CONDITION, CONDITION_FALSE,
                        PROGRESS_DEADLINE_EXCEEDED_REASON
                    )
                )
            )
        ) \
        .then(_it_has_failed(True))


@pytest.mark.unit
def test_a_paused_deployment_has_not_failed() -> None:
    # A paused rollout reports `Progressing` too, at `Unknown` - Kubernetes does
    # not measure the deadline while a Deployment is paused. A rule that read
    # anything short of `True` as failure would fail every held rollout, which is
    # a state of its own and already said by `is_paused`.
    Scenario() \
        .when(
            lambda: how_far_the_rollout_has_got(
                SOME_SERVICE,
                fetch_deployment=a_fleet_half_updated(
                    _a_condition(
                        PROGRESSING_CONDITION, CONDITION_UNKNOWN,
                        DEPLOYMENT_PAUSED_REASON
                    ),
                    paused=True
                )
            )
        ) \
        .then(_it_has_failed(False))


def _it_counted(serving: int, updated: int) -> Assertion[RolloutProgress]:
    """That the counts came back off the live Deployment unchanged."""
    def it_counted(progress: RolloutProgress) -> bool:
        if (progress.replicas_serving, progress.replicas_updated) != (serving, updated):
            raise AssertionError(
                f"Expected [{updated}] of [{serving}] replicas updated, and it "
                f"counted [{progress.replicas_updated}] of "
                f"[{progress.replicas_serving}]."
            )

        return True

    return it_counted


def _it_has_converged(expected: bool) -> Assertion[RolloutProgress]:
    """That the value's own answer about arrival came back this way.

    Asserted beside the counts rather than instead of them, because a function
    returning the right boolean off wrong counts would pass a test about either
    one alone - and the counts are what a reader is shown while a wait is still
    going.
    """
    def it_has_converged(progress: RolloutProgress) -> bool:
        if progress.has_converged is not expected:
            raise AssertionError(
                f"Expected converged [{expected}], and it answered "
                f"[{progress.has_converged}]."
            )

        return True

    return it_has_converged


def _it_has_failed(expected: bool) -> Assertion[RolloutProgress]:
    """That the platform's own word on whether it can finish came through."""
    def it_has_failed(progress: RolloutProgress) -> bool:
        if progress.has_failed is not expected:
            raise AssertionError(
                f"Expected failed [{expected}], and it answered "
                f"[{progress.has_failed}]."
            )

        return True

    return it_has_failed


def a_fleet_half_updated(*conditions: dict[str, str], paused: bool = False) -> Any:
    """Six replicas, three on the revision being rolled out, carrying whatever
    conditions the platform is reporting."""
    return _a_live_deployment(
        replicas=SOME_FLEET_SIZE, updated=HALF_OF_IT, paused=paused,
        conditions=list(conditions)
    )


def a_converged_fleet() -> Any:
    """Every replica on the revision that was deployed."""
    return _a_live_deployment(
        replicas=SOME_FLEET_SIZE, updated=SOME_FLEET_SIZE, paused=False
    )


def a_fleet_reporting_no_status() -> Any:
    """A manifest carrying a size and no rollout status at all."""
    return _a_live_deployment(replicas=SOME_FLEET_SIZE, updated=None, paused=False)


def a_platform_that_cannot_be_reached() -> Any:
    """A live read that fails, as the tier's own fetcher fails."""
    fetch = create_autospec(_a_live_deployment_signature)
    fetch.side_effect = RolloutUnreadable("could not read what [io-shop] is running")

    return fetch


def _a_condition(kind: str, status: str, reason: str) -> dict[str, str]:
    """One entry of a Deployment's `status.conditions`, as Kubernetes writes it."""
    return {CONDITION_TYPE: kind, CONDITION_STATUS: status, "reason": reason}


def _a_live_deployment(replicas: int,
                       updated: int | None,
                       paused: bool,
                       conditions: list[dict[str, str]] | None = None) -> Any:
    """Argo CD's managed-resource answer, whose manifest is carried as text.

    A string rather than an object, because that is the vendor's own shape for
    this response - the resource is passed through and the caller parses it - and
    a double answering with a parsed object would be an easier thing to write
    against than the one the adapter meets.
    """
    manifest: dict[str, Any] = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": SOME_SERVICE, "namespace": "production"},
        "spec": {"replicas": replicas}
    }

    if paused:
        manifest["spec"]["paused"] = True

    if updated is not None:
        manifest["status"] = {"replicas": replicas, "updatedReplicas": updated}

        if conditions:
            manifest["status"]["conditions"] = conditions

    fetch = create_autospec(_a_live_deployment_signature)
    fetch.return_value = {"manifest": json.dumps(manifest)}

    return fetch


def _a_live_deployment_signature(application: str) -> dict[str, Any]:
    """What asking the platform what one application is running looks like."""
    raise NotImplementedError


def an_application_deployed_once() -> Any:
    """A history with one entry: nothing was deployed before it."""
    return _a_history_of((THE_REVISION_BEING_ROLLED_OUT, WHEN_IT_LANDED))


def an_application_deployed_twice() -> Any:
    """The ordinary case: the revision going out, and the one it is replacing."""
    return _a_history_of(
        (THE_REVISION_STILL_SERVING, WHEN_THE_ONE_BEFORE_IT_LANDED),
        (THE_REVISION_BEING_ROLLED_OUT, WHEN_IT_LANDED)
    )


def _a_history_of(*deployed: tuple[str, str]) -> Any:
    """Argo CD's answer for one application, carrying the entries named."""
    argocd = create_autospec(_an_application_signature)
    argocd.return_value = {
        "status": {
            "history": [
                {"revision": revision, "deployedAt": moment}
                for revision, moment in deployed
            ]
        }
    }

    return argocd


def _an_application_signature(application: str) -> dict[str, Any]:
    """What asking the deployment history for one application looks like."""
    raise NotImplementedError


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


def _the_live_deployment_was_read(fetch: Any) -> Assertion[list[str]]:
    """The live resource was asked about, and asked about by name."""
    def assertion(dont_care_answer: list[str]) -> bool:
        fetch.assert_called_once_with(SOME_SERVICE)

        return True

    return assertion


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
