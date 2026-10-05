"""How far a rollout has got, as the three parties that name it agree to say it.

A contract rather than a value one module keeps to itself: the read tier counts
the replicas off the live Deployment, the read client carries them across, and
Mitigation waits on them to learn that the change it made has actually arrived.
Spec §16 places the counting with the channel and the judging with whoever weighs
causes, and this model is where that line is drawn - it reports how many replicas
there are, how many have reached the revision going out, and how many were asked
for, and the only things it concludes are the two that are arithmetic.

Two questions, because two actions arrive differently. A rollback has arrived when
every replica is on the revision it returned to. A scale-out has arrived when
every replica it asked for is running. Both are counts reaching targets, and
neither is the question *stuck* - a rollout part way through is the ordinary
condition of every deployment for a minute or two, so how long either may take is
a judgement nothing here makes.
"""
from __future__ import annotations

import pytest
from argus_core.models.rollout import RolloutProgress
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from pydantic import ValidationError

SOME_FLEET_SIZE = 6
HALF_OF_IT = 3


@pytest.mark.unit
def test_a_fleet_whose_every_replica_arrived_has_converged() -> None:
    # The answer a rollback waits for. Until it comes, a minute the service spent
    # still running the revision being rolled back is a minute the action had not
    # taken effect in, and judging a recovery off it would judge the old code.
    Scenario() \
        .given(
            every_replica_updated := SOME_FLEET_SIZE
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=SOME_FLEET_SIZE,
                replicas_serving=SOME_FLEET_SIZE,
                replicas_updated=every_replica_updated
            )
        ) \
        .then(all_of(
            _it_reports_converged(True),
            _it_reports_outstanding(0)
        ))


@pytest.mark.unit
def test_a_fleet_with_replicas_still_on_the_old_revision_has_not_converged() -> None:
    # The split §16 exists to report, and the state an action is still arriving
    # in. Three of six replicas on the new revision is also the point at which an
    # in-flight incompatibility fails the most requests, so this is the shape a
    # caller must not read as finished.
    Scenario() \
        .given(
            only_half_of_them_updated := HALF_OF_IT
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=SOME_FLEET_SIZE,
                replicas_serving=SOME_FLEET_SIZE,
                replicas_updated=only_half_of_them_updated
            )
        ) \
        .then(all_of(
            _it_reports_converged(False),
            _it_reports_outstanding(SOME_FLEET_SIZE - HALF_OF_IT)
        ))


@pytest.mark.unit
def test_more_replicas_updated_than_serving_has_still_converged() -> None:
    # Reached its target rather than matched it, and the difference is not
    # pedantry. A platform scaling a deployment up reports the new replicas as
    # updated before it reports them as serving, so a rule written as equality
    # would read a fleet that is wholly on the new revision as still arriving -
    # and would do so for as long as the scale-up took, which is exactly when a
    # scale-out mitigation is waiting to be judged.
    Scenario() \
        .given(
            more_updated_than_are_serving := SOME_FLEET_SIZE + 2
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=SOME_FLEET_SIZE,
                replicas_serving=SOME_FLEET_SIZE,
                replicas_updated=more_updated_than_are_serving
            )
        ) \
        .then(all_of(
            _it_reports_converged(True),
            _it_reports_outstanding(0)
        ))


@pytest.mark.unit
def test_a_deployment_still_short_of_the_replicas_it_was_told_to_run() -> None:
    # The other arrival, and the one a scale-out waits for. Doubling a fleet from
    # six to twelve is accepted the moment the count is written, and the six new
    # replicas take as long as they take to start. A caller measuring in between
    # is measuring a service that has not yet been given the capacity - so a
    # recovery read off those minutes is read off the shortage the action was
    # meant to end.
    #
    # Separate from `has_converged`, because they are different comparisons and a
    # single answer would be wrong for one action or the other: every replica here
    # is on the right revision, so a rollback would be finished, and a scale-out
    # is only half done.
    Scenario() \
        .given(
            it_was_told_to_double := SOME_FLEET_SIZE * 2
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=it_was_told_to_double,
                replicas_serving=SOME_FLEET_SIZE,
                replicas_updated=SOME_FLEET_SIZE
            )
        ) \
        .then(all_of(
            _it_has_every_replica_it_asked_for(False),
            _it_reports_converged(True)
        ))


@pytest.mark.unit
def test_a_deployment_running_every_replica_it_was_told_to_has_them_all() -> None:
    # What a scale-out's clock starts on. More than asked for also counts, for the
    # reason more updated than serving counts: a controller that overshot while
    # settling has still given the service the capacity, and a rule written as
    # equality would wait out a surge that already answered the question.
    Scenario() \
        .given(
            one_more_than_it_asked_for := SOME_FLEET_SIZE + 1
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=SOME_FLEET_SIZE,
                replicas_serving=one_more_than_it_asked_for,
                replicas_updated=one_more_than_it_asked_for
            )
        ) \
        .then(
            _it_has_every_replica_it_asked_for(True)
        )


@pytest.mark.unit
def test_a_rolling_update_the_platform_has_stopped_says_so() -> None:
    # The third thing a caller needs, and the one that gives the wait an end
    # without anybody naming a length. Waiting for a change to arrive has to stop
    # somewhere: a deployment nobody is converging never satisfies either count
    # above, so a caller holding only those would poll until its lease expired and
    # leave the change applied for another worker to find.
    #
    # Paused is a state and not a duration, which is the whole reason this is the
    # right signal. "How long is too long for a rollout" is a judgement §16 keeps
    # out of the read tier precisely because it cannot be made from a replica
    # count and a timestamp - but "the platform has stopped converging this" is
    # something the platform states, and reading it is the same move as reading
    # the replica count instead of guessing at convergence.
    #
    # Neither count is satisfied here, and that is the point rather than an
    # accident of the fixture: three of six replicas updated and three short of
    # the six asked for. Both answers stay False and the caller still learns that
    # waiting is over.
    Scenario() \
        .given(
            the_platform_has_stopped_converging_it := True
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=SOME_FLEET_SIZE,
                replicas_serving=HALF_OF_IT,
                replicas_updated=HALF_OF_IT,
                is_paused=the_platform_has_stopped_converging_it
            )
        ) \
        .then(all_of(
            _it_is_paused(True),
            _it_reports_converged(True),
            _it_has_every_replica_it_asked_for(False)
        ))


@pytest.mark.unit
def test_a_rollout_nobody_stopped_is_not_reported_as_paused() -> None:
    # Defaulted rather than required, and the default is the ordinary state. The
    # read tier answers this off `spec.paused`, which is absent from a manifest
    # nobody has interrupted - so "the field was not there" and "the rollout is
    # running" have to be the same answer, or every deployment in the estate would
    # read as stopped.
    Scenario() \
        .given(
            nobody_has_touched_it := SOME_FLEET_SIZE
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=nobody_has_touched_it,
                replicas_serving=nobody_has_touched_it,
                replicas_updated=nobody_has_touched_it
            )
        ) \
        .then(
            _it_is_paused(False)
        )


@pytest.mark.unit
def test_a_deployment_the_platform_cannot_finish_says_so() -> None:
    # The other state that ends a wait without a figure, and the only one a
    # scale-out can be given. A pause says nothing about the replicas a scale-out
    # asked for - the deployment controller goes on scaling a paused Deployment -
    # but a platform that cannot create them, or has run past the deadline the
    # Deployment declares, says so in its own words. Kubernetes calls that a
    # failed Deployment.
    #
    # Separate from paused rather than folded into it, because the two end
    # different waits: a rollback is held by either, a scale-out only by this.
    Scenario() \
        .given(
            the_platform_cannot_finish_it := True
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=SOME_FLEET_SIZE,
                replicas_serving=HALF_OF_IT,
                replicas_updated=HALF_OF_IT,
                has_failed=the_platform_cannot_finish_it
            )
        ) \
        .then(all_of(
            _it_has_failed(True),
            _it_is_paused(False)
        ))


@pytest.mark.unit
def test_a_deployment_nobody_reported_failing_has_not_failed() -> None:
    # Defaulted for the reason paused is: the read tier answers this off the
    # Deployment's conditions, and a Deployment nothing has gone wrong with
    # carries none that say so. "Nothing reported" and "nothing failed" have to be
    # one answer, or every deployment in the estate would read as failed.
    Scenario() \
        .given(
            nobody_has_touched_it := SOME_FLEET_SIZE
        ) \
        .when(
            lambda: RolloutProgress(
                replicas_wanted=nobody_has_touched_it,
                replicas_serving=nobody_has_touched_it,
                replicas_updated=nobody_has_touched_it
            )
        ) \
        .then(
            _it_has_failed(False)
        )


@pytest.mark.unit
def test_a_count_the_platform_gave_as_negative_is_refused() -> None:
    # Nothing a platform reports should be negative, and the answer that must
    # never be reached by arithmetic on nonsense is that the change arrived.
    # Refusing here is how a malformed count becomes an error a caller handles
    # rather than a confirmation it acts on.
    Scenario() \
        .given(
            a_count_that_cannot_be := -1
        ) \
        .when(
            attempting(
                lambda: RolloutProgress(
                    replicas_wanted=SOME_FLEET_SIZE,
                    replicas_serving=SOME_FLEET_SIZE,
                    replicas_updated=a_count_that_cannot_be
                )
            )
        ) \
        .then(
            an_error_was_raised(ValidationError)
        )


def _it_is_paused(expected: bool) -> Assertion[RolloutProgress]:
    """That the model reports whether the platform has stopped converging it."""
    def it_is_paused(progress: RolloutProgress) -> bool:
        if progress.is_paused is not expected:
            raise AssertionError(
                f"Expected paused [{expected}], and it answered "
                f"[{progress.is_paused}]."
            )

        return True

    return it_is_paused


def _it_has_failed(expected: bool) -> Assertion[RolloutProgress]:
    """That the model reports whether the platform says it cannot finish."""
    def it_has_failed(progress: RolloutProgress) -> bool:
        if progress.has_failed is not expected:
            raise AssertionError(
                f"Expected failed [{expected}], and it answered "
                f"[{progress.has_failed}]."
            )

        return True

    return it_has_failed


def _it_reports_converged(expected: bool) -> Assertion[RolloutProgress]:
    """That the model's answer about the revision arriving came back this way."""
    def it_reports_converged(progress: RolloutProgress) -> bool:
        if progress.has_converged is not expected:
            raise AssertionError(
                f"Expected converged [{expected}] for "
                f"[{progress.replicas_updated}] of [{progress.replicas_serving}] "
                f"replicas updated, and it answered [{progress.has_converged}]."
            )

        return True

    return it_reports_converged


def _it_has_every_replica_it_asked_for(expected: bool) -> Assertion[RolloutProgress]:
    """That the model's answer about the capacity arriving came back this way.

    A different question from `_it_reports_converged` and asserted separately,
    because the two can disagree on one window - a fleet wholly on the new
    revision and still short of the count it was told to run is both finished and
    unfinished, depending on which action is waiting.
    """
    def it_has_every_replica_it_asked_for(progress: RolloutProgress) -> bool:
        if progress.has_every_replica_it_asked_for is not expected:
            raise AssertionError(
                f"Expected [{expected}] for [{progress.replicas_serving}] of "
                f"[{progress.replicas_wanted}] replicas running, and it answered "
                f"[{progress.has_every_replica_it_asked_for}]."
            )

        return True

    return it_has_every_replica_it_asked_for


def _it_reports_outstanding(expected: int) -> Assertion[RolloutProgress]:
    """That it says how many replicas have not reached the revision yet.

    Asserted beside `has_converged` rather than instead of it, because the two
    are what a caller needs at different moments - whether to keep waiting, and
    what to say while waiting - and a model that got the boolean right off a
    wrong count would pass a test about the boolean alone.
    """
    def it_reports_outstanding(progress: RolloutProgress) -> bool:
        if progress.replicas_outstanding != expected:
            raise AssertionError(
                f"Expected [{expected}] replicas outstanding, and it reported "
                f"[{progress.replicas_outstanding}]."
            )

        return True

    return it_reports_outstanding
