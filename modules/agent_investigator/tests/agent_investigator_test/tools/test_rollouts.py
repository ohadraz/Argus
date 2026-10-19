"""The channel that says whether the deployment finished arriving.

The Investigator's sixth, and the third that is not a window over time. Whether
a rollout converged is a fact about the deployment running now, so there is
nothing to date, nothing to widen and no reading to record - and, like the
register, nothing for a model to name: the service is the incident's.

The read tier answers with a value - the counts, the revision going out and the
one before it - and the words the model reads are this channel's. They describe
and do not judge: a deployment part way through a rollout is the ordinary
condition of every deployment for a minute or two, and whether this one has
been too long is the reader's to weigh against an onset the channel has never
seen.

Its silence is not evidence, so it reports rather than raises, and here that
matters more than anywhere else in the tier. The answer this channel gives most
often is that the deployment converged, which *rules a mode out* - so a failure
that arrived looking like an answer would not merely be a gap, it would be read
as the finding that sends a walk back to blame the revision.

What came back is published too, as the value it is, so the account of the
incident says it in its own words rather than in these.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_investigator.retrieval import RolloutFetcher
from agent_investigator.tools.rollouts import ROLLOUT_TOOL, read_the_rollout
from argus_core import new_id
from argus_core.events import IncidentEvent, Narrator, RolloutRead
from argus_core.mcp_transport import McpToolError
from argus_core.models import ChangeEvent, ChangeKind, RolloutAccount, RolloutProgress, ToolCall
from argus_testkit import Assertion, Scenario, all_of

SOME_SERVICE = "io-shop"
SOME_CALL = ToolCall(id="call-1", name=ROLLOUT_TOOL, arguments={})
DONT_CARE_NARRATOR = Narrator(new_id())

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
        .given(platform := a_platform_reporting(a_split_fleet())) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
        .then(all_of(
            _the_answer_mentions("not converged"),
            _the_answer_mentions(THE_REVISION_BEING_ROLLED_OUT),
            _the_answer_mentions(THE_REVISION_STILL_SERVING),
            _the_answer_mentions(f"{HALF_OF_IT} of {SOME_FLEET_SIZE}"),
            _it_was_served()
        ))


@pytest.mark.unit
def test_a_converged_deployment_is_said_as_the_model_has_always_read_it() -> None:
    # The ordinary answer, and evidence rather than a blank: a reader weighing a
    # deploy at the onset has been told it is not half-applied, which rules the
    # mode out and leaves the revision itself as the subject. Pinned whole,
    # because these are the words every recorded walk was answered in, and a
    # rewording is a re-record.
    Scenario() \
        .given(platform := a_platform_reporting(a_converged_fleet())) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
        .then(all_of(
            _the_answer_is(
                f"Deployment of {SOME_SERVICE} has converged: all {SOME_FLEET_SIZE} "
                f"replicas are running revision [{THE_REVISION_BEING_ROLLED_OUT}], "
                f"deployed at {WHEN_IT_LANDED}."),
            _it_was_served()
        ))


@pytest.mark.unit
def test_a_converged_deployment_with_no_deploy_on_record_names_no_revision() -> None:
    # Every replica runs the same revision and the history holds none to name
    # it by - said, rather than a revision guessed at.
    Scenario() \
        .given(platform := a_platform_reporting(RolloutAccount(
            progress=a_converged_progress(), going_out=None, before_it=None))) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
        .then(all_of(
            _the_answer_mentions("has converged"),
            _the_answer_mentions("nothing here names which")
        ))


@pytest.mark.unit
def test_a_paused_rolling_update_is_reported_as_paused() -> None:
    # Why it is not progressing, which is a different fact from that it has not
    # progressed - and the one that says a person stopped it rather than that
    # the platform is slow.
    Scenario() \
        .given(platform := a_platform_reporting(a_split_fleet(paused=True))) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
        .then(_the_answer_mentions("paused"))


@pytest.mark.unit
def test_the_answer_says_when_the_deployment_landed() -> None:
    # Said rather than counted from: the tier has no clock, and a reader
    # holding an onset can do the arithmetic. Without it a split fleet is a
    # state with no duration, which reads the same two minutes and two hours
    # into a rollout.
    Scenario() \
        .given(platform := a_platform_reporting(a_split_fleet())) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
        .then(_the_answer_mentions(WHEN_IT_LANDED))


@pytest.mark.unit
def test_a_split_fleet_with_nothing_deployed_before_it_says_the_older_revision_is_unknown() -> None:
    # The replicas that have not updated are running *something*. Said rather
    # than left out: a reader told only about the new revision would read the
    # split as a count with no second subject.
    Scenario() \
        .given(platform := a_platform_reporting(RolloutAccount(
            progress=a_half_updated_progress(), going_out=a_deploy_being_rolled_out(),
            before_it=None))) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
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
        .given(platform := a_platform_reporting(a_split_fleet(paused=True))) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
        .then(_the_answer_reaches_no_verdict())


@pytest.mark.unit
def test_a_platform_nobody_can_reach_is_reported_rather_than_ending_the_walk() -> None:
    # The register's case rather than the change channel's: a rollout nobody
    # could read supports no conclusion either way, and the model can still
    # answer - at a lower confidence, or by naming the distinction it could not
    # draw. Ending the investigation over it would throw away everything already
    # retrieved to avoid a gap the model is able to report.
    Scenario() \
        .given(platform := a_platform_nobody_can_reach()) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
        .then(all_of(
            _it_was_not_served(),
            _the_answer_mentions("rollout")
        ))


@pytest.mark.unit
def test_the_channel_records_no_reading() -> None:
    # Every windowed channel records one, and a reading is what says which
    # minutes are already in front of the model. There are no minutes here, so a
    # reading would put a windowed retrieval in the record for a question that
    # has no window.
    Scenario() \
        .given(platform := a_platform_reporting(a_converged_fleet())) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform, DONT_CARE_NARRATOR)) \
        .then(_nothing_was_recorded_as_read())


@pytest.mark.unit
def test_what_the_tier_answered_is_published_as_the_value_it_is() -> None:
    # The account of the incident says the rollout too - on the page, in Slack,
    # to the postmortem's writer - and in its own words, which it can only
    # write from the value: these sentences are the model's.
    published: list[IncidentEvent] = []
    the_answer = a_split_fleet()

    Scenario() \
        .given(platform := a_platform_reporting(the_answer)) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform,
                                       Narrator(new_id(), published.append))) \
        .then(_it_published(published, the_answer))


@pytest.mark.unit
def test_a_platform_nobody_can_reach_publishes_nothing_read() -> None:
    # A rollout nobody could read, published as one, would be a deployment the
    # account says something about that nobody found out.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(platform := a_platform_nobody_can_reach()) \
        .when(lambda: read_the_rollout(SOME_CALL, SOME_SERVICE, platform,
                                       Narrator(new_id(), published.append))) \
        .then(_nothing_read_was_published(published))


def a_half_updated_progress(paused: bool = False) -> RolloutProgress:
    """Six replicas, three on the revision being rolled out."""
    return RolloutProgress(replicas_wanted=SOME_FLEET_SIZE,
                           replicas_serving=SOME_FLEET_SIZE,
                           replicas_updated=HALF_OF_IT,
                           is_paused=paused)


def a_converged_progress() -> RolloutProgress:
    """Every replica on the revision that was deployed."""
    return RolloutProgress(replicas_wanted=SOME_FLEET_SIZE,
                           replicas_serving=SOME_FLEET_SIZE,
                           replicas_updated=SOME_FLEET_SIZE)


def a_deploy_being_rolled_out() -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.DEPLOY, occurred_at=WHEN_IT_LANDED,
                       reference=THE_REVISION_BEING_ROLLED_OUT, summary="dont care")


def a_deploy_still_serving() -> ChangeEvent:
    return ChangeEvent(kind=ChangeKind.DEPLOY, occurred_at=WHEN_THE_ONE_BEFORE_IT_LANDED,
                       reference=THE_REVISION_STILL_SERVING, summary="dont care")


def a_split_fleet(paused: bool = False) -> RolloutAccount:
    """Half the fleet on the revision going out, half on the one before it."""
    return RolloutAccount(progress=a_half_updated_progress(paused=paused),
                          going_out=a_deploy_being_rolled_out(),
                          before_it=a_deploy_still_serving())


def a_converged_fleet() -> RolloutAccount:
    """Every replica on the revision going out."""
    return RolloutAccount(progress=a_converged_progress(),
                          going_out=a_deploy_being_rolled_out(),
                          before_it=a_deploy_still_serving())


def a_platform_reporting(account: RolloutAccount) -> Any:
    platform = create_autospec(RolloutFetcher, instance=True)
    platform.return_value = account

    return platform


def a_platform_nobody_can_reach() -> Any:
    platform = create_autospec(RolloutFetcher, instance=True)
    platform.side_effect = McpToolError("nobody answered")

    return platform


def _the_answer_is(expected: str) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer.result.content != expected:
            raise AssertionError(
                f"Expected the model to be shown [{expected}], and it is shown "
                f"[{answer.result.content}]."
            )

        return True

    return assertion


def _the_answer_mentions(expected: str) -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if expected not in answer.result.content:
            raise AssertionError(
                f"Expected the answer to mention [{expected}], and what the "
                f"model is shown is: {answer.result.content}"
            )

        return True

    return assertion


def _the_answer_reaches_no_verdict() -> Assertion[Any]:
    """Nothing in the answer calls the rollout anything."""
    def assertion(answer: Any) -> bool:
        said = answer.result.content.lower()
        judged = [verdict for verdict in VERDICTS_IT_MAY_NOT_REACH if verdict in said]

        if judged:
            raise AssertionError(
                f"The answer calls the rollout {sorted(judged)}, which is a "
                f"conclusion drawn from a replica count and a timestamp - and "
                f"it belongs to whoever weighs causes, who has the onset this "
                f"channel has never seen. It says: {answer.result.content}"
            )

        return True

    return assertion


def _it_was_served() -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer.result.failed:
            raise AssertionError(
                f"Expected the call to be served as evidence, and it came back "
                f"marked failed: {answer.result.content}"
            )

        return True

    return assertion


def _it_was_not_served() -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if not answer.result.failed:
            raise AssertionError(
                "A rollout that could not be read was served as evidence about "
                "the incident, so the model cannot tell a deployment it has been "
                "told about from one nobody could ask about."
            )

        return True

    return assertion


def _nothing_was_recorded_as_read() -> Assertion[Any]:
    def assertion(answer: Any) -> bool:
        if answer.reading is not None:
            raise AssertionError(
                f"Expected no reading for a channel with no window, and one was "
                f"recorded: {answer.reading}."
            )

        return True

    return assertion


def _it_published(published: list[IncidentEvent],
                  expected: RolloutAccount) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        read = [event.account for event in published if isinstance(event, RolloutRead)]

        if read != [expected]:
            raise AssertionError(
                f"Expected the tier's answer published once as it came back, "
                f"[{expected!r}], and what was published is {read!r}."
            )

        return True

    return assertion


def _nothing_read_was_published(published: list[IncidentEvent]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        read = [event for event in published if isinstance(event, RolloutRead)]

        if read:
            raise AssertionError(
                f"Expected nothing published as read about a rollout nobody "
                f"could read, and it published {read!r}."
            )

        return True

    return assertion
