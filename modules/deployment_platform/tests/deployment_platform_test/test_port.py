"""The deployment platform's port, as every adapter of it answers.

What the port promises, asked of each adapter over one seed: the Argo CD adapter
against an in-process Argo CD (`framework.argo_world`), and the in-memory double
(`deployment_platform_double`). A promise one of them keeps and the other does
not fails here, so the double cannot drift from the port, and the port names
nothing only Argo CD's wire could answer.

The promises and nothing beyond them. What lands later than the answer - a
rollback's history entry, a restart's new processes - is read only once the
platform has been told to finish what it was asked, so "at once" is never part
of the port. How each answer travels is `test_argocd.py`'s.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx2
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    the_answer_was,
)
from core.models import PodPlacement, RolloutProgress
from deployment_platform import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentPlatformError,
    DeploymentPlatformWrites,
    DeploymentRecord,
    Mark,
    MarkedObject,
    MarkFound,
    PlatformRefused,
    PlatformUnreachable,
    SyncOperations,
)
from deployment_platform.argocd import ArgoCd
from deployment_platform_double import (
    ApplicationState,
    AutoscalerState,
    Container,
    HistoryEntry,
    InMemoryPlatform,
    Node,
    PlatformState,
    Pod,
    Rendering,
)

from deployment_platform_test.framework import ArgoWorld, argo_cd_settings

SOME_APPLICATION = "io-shop"
NO_SUCH_APPLICATION = "kuki-shop"

# The account Argus is configured to recognise as its own, and the one the
# platform records Argus's syncs under - the same account, spelled in another
# case, which is the drift telling them apart exists to survive.
THE_ACCOUNT_ARGUS_SIGNS_IN_AS = "Argus"
AS_THE_PLATFORM_RECORDS_IT = "argus"
SOMEBODY_ELSE = "buki"

# The platform's clock, read to the millisecond so that a moment said to the
# second is seen to be cut there - and that moment, cut.
SOME_MOMENT = datetime(2026, 11, 25, 9, 30, 15, 417000, tzinfo=UTC)
THE_MOMENT_TO_THE_SECOND = SOME_MOMENT.replace(microsecond=0)
# That moment as the platform spells one it records.
THE_MOMENT_AS_RECORDED = "2026-11-25T09:30:15Z"

# Two revisions, the earlier one deployed first, and what each renders.
SOME_EARLIER_REVISION = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
SOME_REVISION = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
SOME_REPOSITORY = "https://github.com/ohadraz/io-shop"
SOME_PATH = "deploy/io-shop"
THE_EARLIER_ENTRY = HistoryEntry(history_id=8, revision=SOME_EARLIER_REVISION,
                                 deployed_at="2026-11-25T08:05:00Z",
                                 repo_url=SOME_REPOSITORY, path=SOME_PATH,
                                 initiated_by=SOMEBODY_ELSE)
THE_ENTRY_RUNNING = HistoryEntry(history_id=9, revision=SOME_REVISION,
                                 deployed_at="2026-11-25T09:05:00Z",
                                 repo_url=SOME_REPOSITORY, path=SOME_PATH,
                                 initiated_by=SOMEBODY_ELSE)
THE_IMAGES_RUNNING = {SOME_APPLICATION: "io-shop:0d8e826",
                      "migrate": "io-shop-migrations:0d8e826"}
THE_EARLIER_IMAGES = {SOME_APPLICATION: "io-shop:544cef3",
                      "migrate": "io-shop-migrations:544cef3"}
SOME_RENDERINGS = (
    Rendering(revision=SOME_EARLIER_REVISION, containers=(
        Container(name=SOME_APPLICATION, image=THE_EARLIER_IMAGES[SOME_APPLICATION]),
        Container(name="migrate", image=THE_EARLIER_IMAGES["migrate"], init=True)
    )),
    Rendering(revision=SOME_REVISION, containers=(
        Container(name=SOME_APPLICATION, image=THE_IMAGES_RUNNING[SOME_APPLICATION]),
        Container(name="migrate", image=THE_IMAGES_RUNNING["migrate"], init=True)
    ))
)
A_REVISION_RENDERING_NOTHING = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
# What somebody set on the Deployment by hand, over what the revision renders.
SOME_IMAGES_SET_BY_HAND = {SOME_APPLICATION: "io-shop:hotfix-1",
                           "migrate": "io-shop-migrations:hotfix-1"}
SOME_CONTAINERS_SET_BY_HAND = (
    Container(name=SOME_APPLICATION, image=SOME_IMAGES_SET_BY_HAND[SOME_APPLICATION]),
    Container(name="migrate", image=SOME_IMAGES_SET_BY_HAND["migrate"], init=True)
)

# Nodes, one carrying a card and one carrying none, and pods on them.
SOME_NODE = "gpu-node-1"
SOME_OTHER_NODE = "cpu-node-1"
SOME_CARD = "Tesla-V100-SXM2-16GB"
SOME_OTHER_CARD = "NVIDIA-A100-SXM4-40GB"
SOME_NODES = (Node(name=SOME_NODE, card=SOME_CARD), Node(name=SOME_OTHER_NODE))
AN_EARLIER_START = datetime(2026, 11, 25, 9, 6, 2, tzinfo=UTC)
A_LATER_START = datetime(2026, 11, 25, 9, 7, 41, tzinfo=UTC)
# Each start between two seconds, which the platform says as the second it
# began in.
AN_EARLIER_START_MID_SECOND = AN_EARLIER_START.replace(microsecond=652000)
A_LATER_START_MID_SECOND = A_LATER_START.replace(microsecond=208000)

SOME_AUTOSCALER = Autoscaler(name="io-shop-hpa", namespace="production")
SOME_OTHER_AUTOSCALER = Autoscaler(name="kuki-hpa", namespace="production")
SOME_BOUNDS = AutoscalerBounds(floor=2, ceiling=8)
SOME_FLOOR = 8
SOME_COUNT = 3
SOME_OTHER_COUNT = 6

# The mark a write is made under, to the millisecond, and as it is read back.
SOME_MARK = Mark(action_id="6f1c1d2e-0000-4000-8000-0000000000a1",
                 written_at=datetime(2026, 11, 25, 9, 30, 1, 417000, tzinfo=UTC))
THE_MARK_FOUND = MarkFound(action_id=SOME_MARK.action_id,
                           written_at=SOME_MARK.written_at.replace(microsecond=0))
SOME_OTHER_MARK = Mark(action_id="6f1c1d2e-0000-4000-8000-0000000000a2",
                       written_at=datetime(2026, 11, 25, 9, 30, 9, tzinfo=UTC))


@dataclass(frozen=True)
class _Standing:
    """A platform an adapter answers for, and how to tell it to finish what it
    was asked - a step that does nothing where everything landed at once."""

    platform: DeploymentPlatformWrites
    finished: Callable[[], None]


class _StandsUp(Protocol):
    def __call__(self,
                 state: PlatformState,
                 *,
                 argus_account: str | None = ...,
                 clock: Callable[[], datetime] = ...,
                 unreachable: bool = ...) -> _Standing:
        ...


def _in_memory(state: PlatformState,
               *,
               argus_account: str | None = THE_ACCOUNT_ARGUS_SIGNS_IN_AS,
               clock: Callable[[], datetime] = lambda: SOME_MOMENT,
               unreachable: bool = False) -> _Standing:
    platform = InMemoryPlatform(state, argus_account=argus_account, clock=clock,
                                unreachable=unreachable)

    return _Standing(platform=platform, finished=lambda: None)


def _argo_cd(state: PlatformState,
             *,
             argus_account: str | None = THE_ACCOUNT_ARGUS_SIGNS_IN_AS,
             clock: Callable[[], datetime] = lambda: SOME_MOMENT,
             unreachable: bool = False) -> _Standing:
    world = ArgoWorld(state, clock=clock, unreachable=unreachable)
    platform = ArgoCd(argo_cd_settings(argus_account), transport=httpx2.MockTransport(world))

    return _Standing(platform=platform, finished=world.finished)


EVERY_ADAPTER = pytest.mark.parametrize("stand_up", [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_argo_cd, id="argo-cd")
])

# Every way whose a deployment is gets told: the account configured as Argus's,
# the one the platform recorded, and what is said of it.
EVERY_WAY_WHOSE_A_CHANGE_IS_TOLD = [
    pytest.param(THE_ACCOUNT_ARGUS_SIGNS_IN_AS, THE_ACCOUNT_ARGUS_SIGNS_IN_AS, True,
                 id="argus-s-own"),
    pytest.param(THE_ACCOUNT_ARGUS_SIGNS_IN_AS, AS_THE_PLATFORM_RECORDS_IT, True,
                 id="in-another-case"),
    pytest.param(THE_ACCOUNT_ARGUS_SIGNS_IN_AS, SOMEBODY_ELSE, False, id="somebody-else-s"),
    pytest.param(THE_ACCOUNT_ARGUS_SIGNS_IN_AS, None, None, id="nobody-named"),
    pytest.param(None, THE_ACCOUNT_ARGUS_SIGNS_IN_AS, None, id="no-account-configured")
]

# Every write the platform answers with when it answered, on its own clock, and
# the read that asks it the time.
EVERY_DATED_WRITE = [
    pytest.param(lambda platform: platform.scale(SOME_APPLICATION, SOME_COUNT, SOME_MARK),
                 id="scale"),
    pytest.param(lambda platform: platform.pin_to_accelerator(SOME_APPLICATION, SOME_CARD,
                                                              SOME_MARK),
                 id="pin"),
    pytest.param(lambda platform: platform.set_autoscaler_floor(SOME_APPLICATION,
                                                                SOME_AUTOSCALER,
                                                                SOME_FLOOR, SOME_MARK),
                 id="floor"),
    pytest.param(lambda platform: platform.roll_back(SOME_APPLICATION,
                                                     THE_EARLIER_ENTRY.history_id),
                 id="rollback"),
    pytest.param(lambda platform: platform.now(SOME_APPLICATION), id="now")
]

# A read and a write, for the failures that are the same whatever was asked.
A_READ_AND_A_WRITE = [
    pytest.param(lambda platform, application: platform.deployments_of(application),
                 id="a read"),
    pytest.param(lambda platform, application: platform.scale(application, SOME_COUNT,
                                                              SOME_MARK),
                 id="a write")
]


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_history_is_every_deployment_in_the_order_the_platform_serves_it(
    stand_up: _StandsUp
) -> None:
    # Ids out of order: the order is the platform's, never the ids'. The last
    # entry names no source and nobody who started it.
    some_lower_id = THE_EARLIER_ENTRY.history_id - 4
    some_later_deployment = "2026-11-25T09:15:00Z"
    later_but_numbered_lower = HistoryEntry(history_id=some_lower_id, revision=SOME_REVISION,
                                            deployed_at=some_later_deployment)

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(
            history=(THE_EARLIER_ENTRY, THE_ENTRY_RUNNING, later_but_numbered_lower)
        )))) \
        .when(lambda: standing.platform.deployments_of(SOME_APPLICATION)) \
        .then(the_answer_was([
            _as_recorded(THE_EARLIER_ENTRY, made_by_argus=False),
            _as_recorded(THE_ENTRY_RUNNING, made_by_argus=False),
            _as_recorded(later_but_numbered_lower, made_by_argus=None)
        ]))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("configured", "recorded", "made_by_argus"),
                         EVERY_WAY_WHOSE_A_CHANGE_IS_TOLD)
def test_whose_a_deployment_is_is_told_by_the_account_that_started_it(
    stand_up: _StandsUp, configured: str | None, recorded: str | None,
    made_by_argus: bool | None
) -> None:
    started = HistoryEntry(history_id=THE_ENTRY_RUNNING.history_id, revision=SOME_REVISION,
                           deployed_at=THE_ENTRY_RUNNING.deployed_at, initiated_by=recorded)

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(history=(started,))),
                                    argus_account=configured)) \
        .when(lambda: standing.platform.deployments_of(SOME_APPLICATION)[0].made_by_argus) \
        .then(the_answer_was(made_by_argus))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_rollout_is_read_as_far_as_the_platform_says_it_has_got(
    stand_up: _StandsUp
) -> None:
    # Three counts apart, so no one is read as another.
    some_updated_count = SOME_COUNT - 2

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(
            replicas=SOME_OTHER_COUNT, serving=SOME_COUNT, updated=some_updated_count,
            paused=True, has_failed=True
        )))) \
        .when(lambda: standing.platform.rollout_of(SOME_APPLICATION)) \
        .then(the_answer_was(RolloutProgress(replicas_wanted=SOME_OTHER_COUNT,
                                             replicas_serving=SOME_COUNT,
                                             replicas_updated=some_updated_count,
                                             is_paused=True,
                                             has_failed=True)))


@pytest.mark.unit
@EVERY_ADAPTER
def test_each_placed_pod_runs_on_its_node_with_its_node_s_card(stand_up: _StandsUp) -> None:
    # A pod waiting for a node is placed nowhere, and left out rather than
    # guessed at; a node carrying no card says none; a start between two
    # seconds is said as the second it began in.
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(pods=(
            Pod(name="io-shop-1", node=SOME_NODE, started_at=AN_EARLIER_START_MID_SECOND),
            Pod(name="io-shop-2", node=SOME_OTHER_NODE, started_at=AN_EARLIER_START),
            Pod(name="io-shop-3", node=None, started_at=A_LATER_START)
        ))))) \
        .when(lambda: standing.platform.placements_of(SOME_APPLICATION)) \
        .then(the_answer_was([
            PodPlacement(pod="io-shop-1", node=SOME_NODE, accelerator=SOME_CARD,
                         started_at=AN_EARLIER_START),
            PodPlacement(pod="io-shop-2", node=SOME_OTHER_NODE, accelerator=None,
                         started_at=AN_EARLIER_START)
        ]))


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_images_running_are_the_running_revision_s_init_containers_among_them(
    stand_up: _StandsUp
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application()))) \
        .when(lambda: standing.platform.images_running(SOME_APPLICATION)) \
        .then(the_answer_was(THE_IMAGES_RUNNING))


@pytest.mark.unit
@EVERY_ADAPTER
def test_images_set_by_hand_are_what_runs_whatever_the_revision_renders(
    stand_up: _StandsUp
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(
            running=SOME_CONTAINERS_SET_BY_HAND
        )))) \
        .when(lambda: standing.platform.images_running(SOME_APPLICATION)) \
        .then(the_answer_was(SOME_IMAGES_SET_BY_HAND))


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_images_at_a_revision_are_what_the_platform_renders_it_as(
    stand_up: _StandsUp
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application()))) \
        .when(lambda: standing.platform.images_at(SOME_APPLICATION, SOME_EARLIER_REVISION)) \
        .then(the_answer_was(THE_EARLIER_IMAGES))


@pytest.mark.unit
@EVERY_ADAPTER
def test_suspended_and_resumed_the_platform_stops_and_starts_syncing_itself_marked(
    stand_up: _StandsUp
) -> None:
    def suspended_then_resumed() -> tuple[bool, bool, MarkFound | None]:
        standing.platform.suspend_sync(SOME_APPLICATION, SOME_OTHER_MARK)
        after_suspending = standing.platform.is_syncing_itself(SOME_APPLICATION)
        standing.platform.resume_sync(SOME_APPLICATION, SOME_MARK)

        return (after_suspending,
                standing.platform.is_syncing_itself(SOME_APPLICATION),
                standing.platform.mark_on(SOME_APPLICATION, MarkedObject.APPLICATION))

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application()))) \
        .when(suspended_then_resumed) \
        .then(the_answer_was((False, True, THE_MARK_FOUND)))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_scale_is_the_count_the_deployment_is_then_asked_for_marked(
    stand_up: _StandsUp
) -> None:
    def scaled() -> tuple[int, MarkFound | None]:
        standing.platform.scale(SOME_APPLICATION, SOME_OTHER_COUNT, SOME_MARK)

        return (standing.platform.rollout_of(SOME_APPLICATION).replicas_wanted,
                standing.platform.mark_on(SOME_APPLICATION, MarkedObject.DEPLOYMENT))

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(replicas=SOME_COUNT)))) \
        .when(scaled) \
        .then(the_answer_was((SOME_OTHER_COUNT, THE_MARK_FOUND)))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_pin_holds_the_pods_to_a_card_and_its_release_to_none_marked(
    stand_up: _StandsUp
) -> None:
    def pinned_then_released() -> tuple[str | None, str | None, MarkFound | None]:
        standing.platform.pin_to_accelerator(SOME_APPLICATION, SOME_CARD, SOME_OTHER_MARK)
        pinned = standing.platform.accelerator_pin_of(SOME_APPLICATION)
        standing.platform.pin_to_accelerator(SOME_APPLICATION, None, SOME_MARK)

        return (pinned,
                standing.platform.accelerator_pin_of(SOME_APPLICATION),
                standing.platform.mark_on(SOME_APPLICATION, MarkedObject.DEPLOYMENT))

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(
            accelerator_pin=SOME_OTHER_CARD
        )))) \
        .when(pinned_then_released) \
        .then(the_answer_was((SOME_CARD, None, THE_MARK_FOUND)))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_floor_raises_the_autoscaler_s_and_nothing_else_of_it_marked(
    stand_up: _StandsUp
) -> None:
    def floor_raised() -> tuple[AutoscalerBounds, MarkFound | None]:
        standing.platform.set_autoscaler_floor(SOME_APPLICATION, SOME_AUTOSCALER, SOME_FLOOR,
                                               SOME_MARK)

        return (standing.platform.autoscaler_bounds(SOME_APPLICATION, SOME_AUTOSCALER),
                standing.platform.mark_on(SOME_APPLICATION, MarkedObject.AUTOSCALER))

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(
            autoscaler=AutoscalerState(autoscaler=SOME_AUTOSCALER, bounds=SOME_BOUNDS)
        )))) \
        .when(floor_raised) \
        .then(the_answer_was((AutoscalerBounds(floor=SOME_FLOOR, ceiling=SOME_BOUNDS.ceiling),
                              THE_MARK_FOUND)))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("dated", EVERY_DATED_WRITE)
def test_the_platform_answers_with_when_it_answered_by_its_own_clock_to_the_second(
    stand_up: _StandsUp, dated: Callable[[DeploymentPlatformWrites], datetime | None]
) -> None:
    # What a change's way back is dated by. A platform that does not sync the
    # application itself, so that a rollback is answered rather than refused.
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(
            syncs_itself=False,
            autoscaler=AutoscalerState(autoscaler=SOME_AUTOSCALER, bounds=SOME_BOUNDS)
        )))) \
        .when(lambda: dated(standing.platform)) \
        .then(the_answer_was(THE_MOMENT_TO_THE_SECOND))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("kind", list(MarkedObject))
def test_an_object_nobody_marked_carries_no_mark(
    stand_up: _StandsUp, kind: MarkedObject
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(
            autoscaler=AutoscalerState(autoscaler=SOME_AUTOSCALER, bounds=SOME_BOUNDS)
        )))) \
        .when(lambda: standing.platform.mark_on(SOME_APPLICATION, kind)) \
        .then(the_answer_was(None))


@pytest.mark.unit
@EVERY_ADAPTER
def test_an_application_with_no_autoscaler_has_no_mark_on_one(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(autoscaler=None))),
               calling(lambda: standing.platform.scale(SOME_APPLICATION, SOME_COUNT,
                                                       SOME_MARK))) \
        .when(lambda: standing.platform.mark_on(SOME_APPLICATION, MarkedObject.AUTOSCALER)) \
        .then(the_answer_was(None))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("held", "found"), [
    pytest.param(AutoscalerState(autoscaler=SOME_AUTOSCALER, bounds=SOME_BOUNDS),
                 SOME_AUTOSCALER, id="one"),
    pytest.param(None, None, id="none")
])
def test_an_application_s_autoscaler_is_the_one_the_platform_holds(
    stand_up: _StandsUp, held: AutoscalerState | None, found: Autoscaler | None
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(autoscaler=held)))) \
        .when(lambda: standing.platform.autoscaler_of(SOME_APPLICATION)) \
        .then(the_answer_was(found))


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_newest_start_counts_a_process_still_waiting_for_a_node(
    stand_up: _StandsUp
) -> None:
    # The state right after a restart: the new process is the newest, and is
    # not placed yet.
    # A start between two seconds, said as the second it began in.
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(pods=(
            Pod(name="io-shop-1", node=SOME_NODE, started_at=AN_EARLIER_START),
            Pod(name="io-shop-2", node=None, started_at=A_LATER_START_MID_SECOND)
        ))))) \
        .when(lambda: standing.platform.newest_pod_started_at(SOME_APPLICATION)) \
        .then(the_answer_was(A_LATER_START.timestamp()))


@pytest.mark.unit
@EVERY_ADAPTER
def test_an_application_running_nothing_has_no_newest_start(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(pods=())))) \
        .when(lambda: standing.platform.newest_pod_started_at(SOME_APPLICATION)) \
        .then(the_answer_was(None))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_rollback_while_the_platform_syncs_the_application_itself_is_refused(
    stand_up: _StandsUp
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(syncs_itself=True)))) \
        .when(attempting(lambda: standing.platform.roll_back(SOME_APPLICATION,
                                                             THE_EARLIER_ENTRY.history_id))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _known_not_applied()
        ))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_rollback_to_an_entry_the_history_does_not_hold_is_refused(
    stand_up: _StandsUp
) -> None:
    no_such_entry = THE_ENTRY_RUNNING.history_id + 100

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(syncs_itself=False)))) \
        .when(attempting(lambda: standing.platform.roll_back(SOME_APPLICATION, no_such_entry))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _known_not_applied()
        ))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_finished_rollback_is_recorded_as_argus_s_and_runs_what_it_returned_to(
    stand_up: _StandsUp
) -> None:
    # Recorded under the account Argus signs in as, spelled as the platform
    # spells it - which is still told as Argus's. What was set by hand is
    # rendered over by the revision returned to.
    def rolled_back() -> tuple[DeploymentRecord, dict[str, str]]:
        standing.platform.suspend_sync(SOME_APPLICATION, SOME_MARK)
        standing.platform.roll_back(SOME_APPLICATION, THE_EARLIER_ENTRY.history_id)
        standing.finished()

        return (standing.platform.deployments_of(SOME_APPLICATION)[-1],
                standing.platform.images_running(SOME_APPLICATION))

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(
            _an_application(syncs_itself=True, running=SOME_CONTAINERS_SET_BY_HAND),
            signed_in_as=AS_THE_PLATFORM_RECORDS_IT
        ))) \
        .when(rolled_back) \
        .then(the_answer_was((
            DeploymentRecord(history_id=THE_ENTRY_RUNNING.history_id + 1,
                             revision=SOME_EARLIER_REVISION,
                             deployed_at=THE_MOMENT_AS_RECORDED,
                             repo_url=SOME_REPOSITORY,
                             path=SOME_PATH,
                             initiated_by=AS_THE_PLATFORM_RECORDS_IT,
                             made_by_argus=True),
            THE_EARLIER_IMAGES
        )))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_finished_restart_leaves_no_process_from_before_it(stand_up: _StandsUp) -> None:
    def restarted() -> tuple[float | None, list[datetime]]:
        standing.platform.restart(SOME_APPLICATION)
        standing.finished()

        return (standing.platform.newest_pod_started_at(SOME_APPLICATION),
                [placed.started_at
                 for placed in standing.platform.placements_of(SOME_APPLICATION)])

    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(pods=(
            Pod(name="io-shop-1", node=SOME_NODE, started_at=AN_EARLIER_START),
            Pod(name="io-shop-2", node=SOME_OTHER_NODE, started_at=A_LATER_START)
        ))))) \
        .when(restarted) \
        .then(_every_process_started_at_or_after(THE_MOMENT_TO_THE_SECOND,
                                                 newer_than=A_LATER_START))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("asked", A_READ_AND_A_WRITE)
def test_an_application_the_platform_does_not_hold_is_refused_as_never_applied(
    stand_up: _StandsUp, asked: Callable[[DeploymentPlatformWrites, str], Any]
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application()))) \
        .when(attempting(lambda: asked(standing.platform, NO_SUCH_APPLICATION))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _known_not_applied()
        ))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("asked", A_READ_AND_A_WRITE)
def test_a_platform_nothing_reaches_is_unreachable_and_applied_nothing(
    stand_up: _StandsUp, asked: Callable[[DeploymentPlatformWrites, str], Any]
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application()), unreachable=True)) \
        .when(attempting(lambda: asked(standing.platform, SOME_APPLICATION))) \
        .then(all_of(
            an_error_was_raised(PlatformUnreachable),
            _known_not_applied()
        ))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_revision_rendering_no_deployment_is_refused(stand_up: _StandsUp) -> None:
    # Compared with nothing, every image running would read as somebody else's.
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application()))) \
        .when(attempting(lambda: standing.platform.images_at(SOME_APPLICATION,
                                                             A_REVISION_RENDERING_NOTHING))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _known_not_applied()
        ))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize("asked", [
    pytest.param(lambda platform: platform.autoscaler_bounds(SOME_APPLICATION,
                                                             SOME_OTHER_AUTOSCALER),
                 id="its bounds"),
    pytest.param(lambda platform: platform.set_autoscaler_floor(SOME_APPLICATION,
                                                                SOME_OTHER_AUTOSCALER,
                                                                SOME_FLOOR, SOME_MARK),
                 id="its floor")
])
def test_an_autoscaler_the_platform_does_not_hold_is_refused(
    stand_up: _StandsUp, asked: Callable[[DeploymentPlatformWrites], Any]
) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application(
            autoscaler=AutoscalerState(autoscaler=SOME_AUTOSCALER, bounds=SOME_BOUNDS)
        )))) \
        .when(attempting(lambda: asked(standing.platform))) \
        .then(all_of(
            an_error_was_raised(PlatformRefused),
            _known_not_applied()
        ))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_platform_at_rest_has_no_sync_asked_for_or_run(stand_up: _StandsUp) -> None:
    Scenario() \
        .given(standing := stand_up(_a_platform_holding(_an_application()))) \
        .when(lambda: standing.platform.sync_operations_of(SOME_APPLICATION)) \
        .then(the_answer_was(SyncOperations(requested=None, last_run=None)))


def _an_application(**changed: Any) -> ApplicationState:
    """`SOME_APPLICATION` as the platform holds it, running `SOME_REVISION` -
    with whatever a case says differently."""
    return ApplicationState(**{
        "name": SOME_APPLICATION,
        "history": (THE_EARLIER_ENTRY, THE_ENTRY_RUNNING),
        "renderings": SOME_RENDERINGS,
        "replicas": SOME_COUNT,
        "pods": (Pod(name="io-shop-1", node=SOME_NODE, started_at=AN_EARLIER_START),),
        **changed
    })


def _as_recorded(entry: HistoryEntry, *, made_by_argus: bool | None) -> DeploymentRecord:
    """`entry` as the port says a deployment, told as `made_by_argus` says."""
    return DeploymentRecord(history_id=entry.history_id,
                            revision=entry.revision,
                            deployed_at=entry.deployed_at,
                            repo_url=entry.repo_url,
                            path=entry.path,
                            initiated_by=entry.initiated_by,
                            made_by_argus=made_by_argus)


def _a_platform_holding(*applications: ApplicationState,
                       signed_in_as: str | None = THE_ACCOUNT_ARGUS_SIGNS_IN_AS
                       ) -> PlatformState:
    return PlatformState(applications=applications, nodes=SOME_NODES,
                         signed_in_as=signed_in_as)


def _known_not_applied() -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if not isinstance(error, DeploymentPlatformError) or not error.known_not_applied:
            raise AssertionError(
                f"Expected a failure known not to have applied anything, got "
                f"[{type(error).__name__}: {error}]."
            )

        return True

    return assertion


def _every_process_started_at_or_after(moment: datetime, *, newer_than: datetime
                                       ) -> Assertion[tuple[float | None, list[datetime]]]:
    def assertion(restarted: tuple[float | None, list[datetime]]) -> bool:
        newest, placed = restarted
        from_before = [started for started in placed if started < moment]

        if newest is None or newest <= newer_than.timestamp() or not placed or from_before:
            raise AssertionError(
                f"Expected every process started at or after [{moment}] and the newest later "
                f"than [{newer_than}], got the newest at [{newest}] and the processes "
                f"started at {placed}."
            )

        return True

    return assertion
