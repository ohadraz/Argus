"""Performing the action the gate admitted, and recording what came of it.

The node reports the verdict it measured and never a status: where the incident
stands as a result is a conclusion drawn from it one place further out, and
drawing it here is how the same verdict came to mean two different statuses in
two places.

The other half is what a resumed walk does. The claim on an action is written
before the action and outlives the worker that wrote it, so a walk refused the
claim is a walk that has been resumed inside this node - and what it does next
depends on how far the row says the earlier attempt got: an outcome on file is
reported; a claim and nothing more is asked of the estate, on its own plan,
whether its change was made, and carried on from whatever that finds; a change
told as made is asked whether it is still Argus's and watched; one owed back is
put back; one nobody could account for is handed over.

Before either, the action is planned: the change it will make, worked out by the
write tier from the estate as it stands, is written onto the claim, and the
action is taken on it. A plan the tier refuses is recorded as the attempt, as
the same refusal from the write was.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
)
from core import RunLost
from core.autonomy import Admitted
from core.events import (
    ActionRefused,
    ActionTaken,
    IncidentEvent,
    MitigationResumed,
    PlatformUnavailable,
    Publisher,
    VerdictReached,
    nobody,
)
from core.mcp_transport import LostAfterSending
from core.models import (
    DEPLOYMENT_PLATFORM,
    FLAG_PROVIDER,
    AcceleratorPinUndo,
    Action,
    ActionProgress,
    AlarmClaim,
    Alert,
    AlreadyClaimed,
    AutoscalerUndo,
    ChangeFound,
    Claimed,
    DeploymentRollbackUndo,
    DiscardCacheEntries,
    EstablishedOnset,
    FlagUndo,
    HowTheMinuteIsKnown,
    Hypothesis,
    IncidentStatus,
    Made,
    NotMade,
    Outcome,
    Ownership,
    PinAutoscaler,
    PinToAccelerator,
    Planned,
    Refusal,
    ReplicaUndo,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
    ServiceDependency,
    SubjectOpen,
    UndoDescriptor,
    Undone,
    UnreadVerdict,
    Verdict,
    the_actions_through,
    the_service_addressed_by,
    the_subject_of,
    why_it_was_refused,
)
from incident_record import IsStillWanted
from mitigation import ChangeMade, NobodyCanSay, Performed, PutBackOwed
from orchestrator.walk import ports
from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.mitigating import mitigation_node, route_after_mitigation
from orchestrator.walk.routes import ESCALATED_ROUTE, FIXING_ROUTE, NEXT_CANDIDATE_ROUTE
from orchestrator.walk.state import IncidentState

from orchestrator_test.framework.assertions import the_route_is
from orchestrator_test.framework.builders import (
    a_determined_hypothesis,
    a_random_id,
    an_incident_state,
)

DONT_CARE_FLAG = "dont-care-flag"
SOME_FLAG_THE_CANDIDATE_BLAMES = "monthly-spend-feature"
SOME_MOMENT_THE_CLAIM_WAS_WRITTEN = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
SOME_ONSET_THE_ALERT_STATED = datetime(2026, 9, 4, 21, 48, tzinfo=UTC)
SOME_ACCELERATOR = "Tesla-V100-SXM2-16GB"
SOME_APPLICATION = "io-shop"
DONT_CARE_MOMENT_IT_WAS_TAKEN = datetime(2026, 9, 4, 22, 16, tzinfo=UTC)
# The walk's clock as it records the change made, and as it announces
# it after - two readings, in that order, as today's announcement is dated.
SOME_MOMENT_IT_WAS_MADE = SOME_MOMENT_THE_CLAIM_WAS_WRITTEN + timedelta(seconds=4)
SOME_MOMENT_IT_WAS_ANNOUNCED = SOME_MOMENT_IT_WAS_MADE + timedelta(milliseconds=3)
# What the watch found that left a change owing its put-back, in its words.
SOME_FINDING = "the rule that fired was still firing when the time it allows ran out"
# What a write refused for a lost run says.
A_NEWER_CLAIM_HOLDS_THE_RUN = "a newer claim holds this run"

# How a resumed walk hands over a claim nobody can account for, in the words a
# person reads.
A_CHANGE_NOBODY_CAN_ACCOUNT_FOR = ("an earlier attempt claimed this action and nothing "
                                   "can say whether it was carried out")
# And a row that says its change was made and keeps nothing to go on with it.
A_CHANGE_MADE_AND_NEVER_RECORDED = ("an earlier attempt carried out this action and stopped "
                                    "before recording what came of it")
# And the way this walk hands one over when the tier was asked, never answered,
# and could not be asked again without doing the thing twice.
A_CHANGE_LOST_AFTER_IT_WAS_ASKED_FOR = ("this action was asked for and its answer never came "
                                        "back, so nothing can say whether it was carried out")
# What the transport says of a call it sent and got no answer to.
DONT_CARE_WHAT_THE_TRANSPORT_SAID = "the call was sent and its answer never came back"

# The action rows a claim answers with: the one this walk writes, and the one a
# worker that is gone wrote before it.
THE_ACTION_THIS_WALK_CLAIMED = "6f1c1d2e-0000-4000-8000-0000000000a1"
THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED = "6f1c1d2e-0000-4000-8000-0000000000a0"

# When the write tier read the state a plan was worked out from: before the
# claim, which is the whole of what this moment says.
SOME_MOMENT_THE_PLAN_WAS_READ = SOME_MOMENT_THE_CLAIM_WAS_WRITTEN - timedelta(seconds=2)
# A plan nothing in a case reads, for the cases about something else.
DONT_CARE_PLAN = Planned(descriptor=FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True),
                         since=SOME_MOMENT_THE_PLAN_WAS_READ)
# A refusal the write tier raised at the plan, in its own words.
SOME_REFUSAL_AT_THE_PLAN = (
    f"[{SOME_APPLICATION}] is running [12] replicas, which is as large as Argus may make it"
)


class _Acting:
    """Acts for whichever action it is handed, and notes into `happened` when
    each began and ended - beside whatever else a case notes there."""

    def __init__(self, happened: list[str] | None = None) -> None:
        self.happened = happened if happened is not None else []

    @contextmanager
    def __call__(self, action_id: str) -> Generator[None]:
        self.happened.append(f"acting for {action_id}")

        try:
            yield
        finally:
            self.happened.append(f"no longer acting for {action_id}")


@pytest.fixture
def record_action() -> MagicMock:
    """A claim this walk wins, unless a case says an earlier attempt won it."""
    claimed = cast(MagicMock, create_autospec(ports.RecordAction, instance=True))
    claimed.return_value = Claimed(action_id=THE_ACTION_THIS_WALK_CLAIMED)

    return claimed


@pytest.fixture
def acting_for() -> _Acting:
    return _Acting()


@pytest.fixture
def complete_action() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.CompleteAction, instance=True))


@pytest.fixture
def take() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.TakeAction, instance=True))


@pytest.fixture
def already_taken() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.ActionAlreadyTaken, instance=True))


@pytest.fixture
def still_wanted() -> MagicMock:
    wanted = cast(MagicMock, create_autospec(IsStillWanted, instance=True))
    wanted.return_value = True

    return wanted


@pytest.fixture
def resuming() -> ports.Resuming:
    """What a resumed walk reads and carries on with, each answering as a claim
    that nothing landed and a change still Argus's would - until a case says
    otherwise."""
    return _resuming_nobody_checks()


@pytest.fixture
def advance_action() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.AdvanceAction, instance=True))


@pytest.fixture
def owe_a_put_back() -> MagicMock:
    return cast(MagicMock, create_autospec(ports.OweAPutBack, instance=True))


@pytest.mark.unit
def test_a_confirmed_action_reports_the_verdict_it_measured(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_verdict_reported_is(Verdict.CONFIRMED))


@pytest.mark.unit
@pytest.mark.parametrize("verdict", [Verdict.CONFIRMED, Verdict.REFUTED])
def test_the_verdict_an_action_reached_is_logged(
    verdict: Verdict,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock,
    caplog: pytest.LogCaptureFixture
) -> None:
    # What an experiment on production found. A refuted one moves no status -
    # the walk goes on to the next candidate - so without this line nothing
    # says the change was made, measured and found wanting.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            calling(lambda: _the_action_came_back(take, verdict)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            one_record_was_logged(caplog, "orchestrator.walk.mitigating", logging.INFO,
                                  "verdict reached", values={"verdict": verdict})
        )


@pytest.mark.unit
def test_what_is_recorded_is_what_the_action_acted_on_not_what_the_candidate_called_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The candidate describes the fault in prose - "io-shop process heap
    # (memory_used_bytes / heap of 2048MiB limit)" is one a model wrote - and
    # the row is the account of what was changed. Recording the description
    # there leaves the write-up quoting something nobody did, and leaves the
    # per-subject cap counting a phrase that comes out different every round,
    # so a restart loop would never reach it.
    some_restarted_service = "kuki-service"
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=RestartService(service=some_restarted_service),
                about=_a_candidate_blaming(
                    "kuki heap (memory_used_bytes / heap of 2048MiB limit)"
                )
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_subject_recorded_is(
            some_restarted_service, record_action, published
        ))


@pytest.mark.unit
def test_the_claim_is_dated_on_the_walks_clock_before_the_action_is_announced(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The claim is written before the agent taking the action is called in,
    # and the announcement after. Dated by one reading taken at the claim, the
    # announcement put the roll-back before the agent that took it. A clock
    # that moves on every reading tells the two apart.
    published: list[IncidentEvent] = []
    readings = count()

    def a_clock_that_moves() -> datetime:
        return SOME_MOMENT_THE_CLAIM_WAS_WRITTEN + timedelta(milliseconds=400 * next(readings))

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append,
                                      now=a_clock_that_moves)) \
        .then(_the_claim_is_dated_before_the_announcement(record_action, published))


@pytest.mark.unit
def test_a_refuted_action_carries_what_the_wait_judged_for_the_next_round(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # A later round is told each attempt and why it did not help. "The rule
    # kept firing" and "nothing in the window ever departed" are different
    # evidence about the cause, and the walk is the only thing between the
    # wait that judged it and the round that reads it.
    some_reason = (
        "the rule that fired was still firing when the time it allows ran out"
    )

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED, because=some_reason)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_reason_reported_is(some_reason))


@pytest.mark.unit
def test_a_refuted_action_reports_the_verdict_it_measured(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_verdict_reported_is(Verdict.REFUTED))


@pytest.mark.unit
def test_an_escalated_outcome_is_reported_as_the_verdict_it_is(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.ESCALATED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_verdict_reported_is(Verdict.ESCALATED))


@pytest.mark.unit
def test_an_unavailable_platform_is_published_where_the_walk_learnt_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Here because here is where it was learnt, and before the candidate that
    # follows. The stream is read as a story in the order it happened, so an
    # event explaining why later candidates went untried is only an explanation
    # if it stands before them.
    #
    # Published by the walk rather than by the tier whose call failed: the tier
    # reported a failed call, which is not yet the fact that a platform is
    # unavailable to *this incident*, and a tier publishing against an incident
    # would be publishing about work it cannot see the shape of.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(
                take, Verdict.PLATFORM_UNREACHABLE
            )),
            a_rollback_taking_incident := _a_mitigating_incident(
                proposing=_a_rollback_action()
            )
        ) \
        .when(lambda: mitigation_node(a_rollback_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_platform_was_published_as_unavailable(
            DEPLOYMENT_PLATFORM, the_actions_through(DEPLOYMENT_PLATFORM), published
        ))


@pytest.mark.unit
def test_an_escalated_action_publishes_nothing_about_a_platform(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The half that keeps the claim above honest. A walk that published this on
    # every failure would tell a reader four actions went away whenever one call
    # was refused, and the record would be wrong about the only thing this event
    # exists to say.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.ESCALATED)),
            a_rollback_taking_incident := _a_mitigating_incident(
                proposing=_a_rollback_action()
            )
        ) \
        .when(lambda: mitigation_node(a_rollback_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_no_platform_was_published_as_unavailable(published))


@pytest.mark.unit
def test_an_unreachable_platform_is_recorded_against_the_walk(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The one fact this verdict carries that no other does, and the walk cannot
    # re-derive it later: by the time the next candidate is chosen, all that is
    # left of the attempt is a verdict, and a verdict does not say which platform
    # failed to answer. So it is written down where it was learnt.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(
                take, Verdict.PLATFORM_UNREACHABLE
            )),
            a_rollback_taking_incident := _a_mitigating_incident(
                proposing=_a_rollback_action()
            )
        ) \
        .when(lambda: mitigation_node(a_rollback_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_verdict_reported_is(Verdict.PLATFORM_UNREACHABLE),
            _the_platforms_recorded_as_unreachable([DEPLOYMENT_PLATFORM])
        ))


@pytest.mark.unit
def test_the_platform_recorded_is_the_one_the_action_acted_through(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Derived from the action, not named. The same verdict off a flag revert means
    # the flag provider is what did not answer, and a node that wrote the
    # deployment platform either way would have the walk pass over three
    # candidates that were never affected - and keep reaching for the one that
    # was.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(
                take, Verdict.PLATFORM_UNREACHABLE
            )),
            a_flag_reverting_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(a_flag_reverting_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_platforms_recorded_as_unreachable([FLAG_PROVIDER]))


@pytest.mark.unit
def test_an_escalated_action_says_nothing_about_any_platform(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The half that keeps the two above honest. A node that recorded a platform on
    # every failure would write one off whenever a single call was refused, and
    # four mitigations would go out of reach on the strength of one rejection.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.ESCALATED)),
            a_rollback_taking_incident := _a_mitigating_incident(
                proposing=_a_rollback_action()
            )
        ) \
        .when(lambda: mitigation_node(a_rollback_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_nothing_was_recorded_as_unreachable())


@pytest.mark.unit
def test_the_action_row_records_the_undo_descriptor_the_write_returned(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The descriptor the write tier returned, not the one proposed: it is the
    # record of what actually changed, and it is what a human reading the
    # incident afterwards would have to act on.
    some_undo_descriptor = FlagUndo(flag=SOME_FLAG_THE_CANDIDATE_BLAMES,
                                          was_enabled=False,
                                          environment="production")

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take,
                                                  Verdict.CONFIRMED,
                                                  some_undo_descriptor)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_action_row_records_the_way_back(some_undo_descriptor,
                                                   complete_action))


@pytest.mark.unit
@pytest.mark.parametrize("performed", [True, False], ids=["performed", "never-performed"])
def test_the_action_row_records_whether_the_action_was_performed(
    performed: bool,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # What says the candidate was tried where nothing was judged: a person's
    # ending stops a test before the write and during the wait alike, and only
    # the second tried the candidate.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.STOPPED, judged=False,
                                                  performed=performed)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_determined_hypothesis(a_random_id())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_action_row_records_whether_it_was_performed(performed, complete_action))


@pytest.mark.unit
@pytest.mark.parametrize("left_behind_known", [True, False], ids=["known", "not-known"])
def test_the_action_row_records_whether_what_the_attempt_left_is_known(
    left_behind_known: bool,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # What tells a refusal that asked for no change from one whose answer was
    # lost: both are not performed, both may carry nothing, and only the first
    # may be written up as having changed nothing.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.ESCALATED, judged=False,
                                                  performed=False,
                                                  left_behind_known=left_behind_known)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_determined_hypothesis(a_random_id())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_action_row_records_whether_what_it_left_is_known(left_behind_known,
                                                                    complete_action))


@pytest.mark.unit
def test_a_candidate_passed_over_untested_keeps_why_on_its_row_and_its_line(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The tier had nowhere to take the action, so nothing was tested - and the
    # tier's own sentence is the one thing a reader of the list or the line has
    # for why this explanation was never tried. Untested, so no verdict on it.
    some_candidate = a_determined_hypothesis(a_random_id())
    some_reason = "[io-shop] has no revision before the one it is running"

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.NOT_ATTEMPTED, judged=False,
                                                  performed=False,
                                                  not_performed_because=some_reason)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=some_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_candidate_was_left_untested_because(some_candidate, some_reason,
                                                     record_outcome),
            _the_verdict_s_line_says_why_it_was_not_performed(some_reason, complete_action)
        ))


@pytest.mark.unit
def test_the_action_row_and_its_line_keep_what_putting_it_back_did(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The row, so the cleanup after the incident does not put it back a second
    # time; the line, because nothing else live says the flag went back.
    some_flag_put_back = "was put back ON"

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED,
                                                  undo_descriptor=FlagUndo(
                                                      flag=DONT_CARE_FLAG, was_enabled=True
                                                  ),
                                                  undone=Undone.RESTORED,
                                                  undone_detail=some_flag_put_back)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_determined_hypothesis(a_random_id())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            _putting_it_back_was_kept_as(Undone.RESTORED, some_flag_put_back, complete_action)
        )


@pytest.mark.unit
def test_a_candidate_abandoned_mid_verification_is_not_recorded_as_tested(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Withdrawn is not a verdict about the hypothesis. The action was taken and
    # then abandoned, so nothing was measured - and marking the candidate tested
    # would leave the incident claiming an explanation was ruled out by an
    # experiment that never finished.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.STOPPED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_determined_hypothesis(a_random_id())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_candidate_learned_nothing(record_outcome))


@pytest.mark.unit
def test_a_candidate_nothing_was_measured_for_is_not_recorded_as_tested(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The same claim as the test above it, arriving under a word that does not
    # say so. An action whose window ran out with the service never once read
    # escalates - and so does a refutation whose change could not be put back,
    # which watched the service and found it still bad. One verdict, two
    # opposite experiments, and only the second tested anything.
    #
    # So the row is decided on what the outcome says was judged rather than on
    # the verdict. Marked tested, this candidate would be an explanation the
    # incident claims to have ruled out on no reading at all - and what reads it
    # afterwards is the memory that orders a later incident's candidates.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(
                take, Verdict.ESCALATED, judged=False
            )),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_determined_hypothesis(a_random_id())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_candidate_learned_nothing(record_outcome))


@pytest.mark.unit
def test_an_abandoned_action_still_records_what_would_put_it_back(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The candidate learns nothing, but the action row must: the flag is still
    # changed, and the undo descriptor is the only record of what would restore
    # it. Without it the withdrawal has nothing to unwind.
    some_undo_descriptor = FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True)

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take,
                                                  Verdict.STOPPED,
                                                  some_undo_descriptor)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_determined_hypothesis(a_random_id())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_row_records_the_outcome((str(Verdict.STOPPED)), complete_action),
                     _the_action_row_records_the_way_back(some_undo_descriptor,
                                                          complete_action)))


@pytest.mark.unit
def test_the_candidate_that_was_acted_on_records_what_the_attempt_settled(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # An action was taken and the service was measured afterwards, so this
    # candidate was genuinely tested - and the verdict is the answer it was
    # tested for. Without it the incident records a list of explanations and no
    # sign of which one the walk was on.
    some_candidate = a_determined_hypothesis(a_random_id())

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(), about=some_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      complete_action=complete_action,
                                      record_action=record_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_candidate_was_tested_and_settled(some_candidate,
                                                    str(Verdict.REFUTED),
                                                    record_outcome))


@pytest.mark.unit
def test_the_moment_an_action_was_taken_travels_with_the_walk(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # A later round is told when each attempt was made, beside the flag
    # provider's record of the same change. Dated by the moment the walk moved
    # on from it - after the verification wait - the two disagreed
    # by the length of that wait, and the round read two changes where there
    # was one.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_walk_carries_the_moment_the_action_was_announced(published))


@pytest.mark.unit
@pytest.mark.parametrize("verdict", [Verdict.PLATFORM_UNREACHABLE, Verdict.NOT_ATTEMPTED,
                                     Verdict.ESCALATED, Verdict.STOPPED],
                         ids=lambda verdict: verdict.value)
def test_an_attempt_that_ended_before_its_write_announces_no_action(
    verdict: Verdict,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Announced ahead of the write, a rollback the platform never answered was
    # told as "Rolled back" on every page and in every write-up. Its verdict is
    # what says it was reached for and not done - and with nothing changed,
    # there is no moment of change for a later round to be told about.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, verdict, judged=False,
                                                  performed=False)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_a_rollback_action()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(all_of(
            _no_action_was_announced(published),
            _the_walk_carries_no_moment_of_change(),
            _the_verdict_names_the_action_not_done(an_action_taking_incident, complete_action)
        ))


@pytest.mark.unit
def test_the_verdict_on_a_change_made_says_it_was_made(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The same line, for the action that was performed: the verdict names it,
    # and says it was done.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            _the_verdict_names_the_action_done(an_action_taking_incident, complete_action)
        )


@pytest.mark.unit
@pytest.mark.parametrize("judged", [True, False], ids=["read", "never-read"])
def test_the_verdict_says_whether_the_action_was_judged(
    judged: bool,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # An escalation is a wait nobody could read and a refutation whose undo
    # failed alike; only the second judged anything, and the line has to say
    # which it was.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, Verdict.ESCALATED, judged=judged)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            _the_verdict_says_it_was_judged(judged, complete_action)
        )


@pytest.mark.unit
def test_the_plan_is_made_before_the_claim_and_written_on_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The claim carries what the write will compare the estate with - the change
    # and when the state it was worked out from was read - and it carries it
    # from the moment it is written, before anything in the estate moves. A plan
    # made after the claim leaves a claim a resumed walk has nothing to compare
    # with, for exactly the stretch it is likeliest to be resumed in.
    happened: list[str] = []
    some_plan = Planned(descriptor=_a_scale_out_of_three(), since=SOME_MOMENT_THE_PLAN_WAS_READ)

    Scenario() \
        .given(
            calling(lambda: _noting_when_it_is_claimed(record_action, happened)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            planning := _planning_answering(some_plan, happened),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=ScaleOut(application=SOME_APPLICATION)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=planning,
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _happened_in_order(happened, ["planned", "claimed"]),
            _the_claim_carries(some_plan, record_action)
        ))


@pytest.mark.unit
def test_the_action_is_taken_on_the_plan_its_claim_carries(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The same plan, and not one worked out again: the write compares the estate
    # with what the claim recorded, so a second plan would be compared against a
    # state nothing wrote down.
    some_plan = Planned(descriptor=_a_scale_out_of_three(), since=SOME_MOMENT_THE_PLAN_WAS_READ)

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=ScaleOut(application=SOME_APPLICATION)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(some_plan),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            _the_action_was_taken_on(some_plan, take)
        )


@pytest.mark.unit
def test_an_action_with_nothing_to_plan_is_claimed_and_taken_with_no_plan(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # A restart leaves nothing for a write to compare, so its claim carries no
    # plan and no moment one was read at - rather than a plan of nothing.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=RestartService(service=SOME_APPLICATION)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(None),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_claim_carries(None, record_action),
            _the_action_was_taken_on(None, take)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("verdict", [Verdict.NOT_ATTEMPTED, Verdict.PLATFORM_UNREACHABLE,
                                     Verdict.ESCALATED],
                         ids=lambda verdict: verdict.value)
def test_a_plan_refused_is_recorded_as_the_attempt_and_the_action_is_not_taken(
    verdict: Verdict,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The refusals the write used to raise are raised at the plan now, and the
    # record of the attempt is what it was: a claim, completed with the refusal
    # as its verdict and nothing performed - so the cap on attempts per subject,
    # the write-up and the memory of what was tried all read the same row they
    # read before. The claim carries no plan, since none was made.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=ScaleOut(application=SOME_APPLICATION)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(
                                          _a_plan_refused_as(verdict)
                                      ),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_claim_carries(None, record_action),
            _the_action_row_records_the_outcome(verdict, complete_action),
            _the_action_row_records_whether_it_was_performed(False, complete_action),
            _the_verdict_names_the_action_not_done(an_action_taking_incident, complete_action),
            _the_verdict_reported_is(verdict),
            _no_action_was_announced(published),
            _the_walk_carries_no_moment_of_change()
        ))


@pytest.mark.unit
def test_a_plan_refused_as_spent_passes_the_candidate_over_untested_saying_why(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # As a spent write did: the tier's own sentence on the candidate's row and
    # on the verdict's line, and no verdict on the explanation.
    some_candidate = a_determined_hypothesis(a_random_id())

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=ScaleOut(application=SOME_APPLICATION), about=some_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(
                                          _a_plan_refused_as(Verdict.NOT_ATTEMPTED)
                                      ),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_candidate_was_left_untested_because(some_candidate, SOME_REFUSAL_AT_THE_PLAN,
                                                     record_outcome),
            _the_verdict_s_line_says_why_it_was_not_performed(SOME_REFUSAL_AT_THE_PLAN,
                                                              complete_action)
        ))


@pytest.mark.unit
def test_a_plan_whose_platform_was_not_there_narrows_the_walk(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # A platform that could not be asked for a plan has taken every action
    # through it away, as one that could not be asked for the write had.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_a_rollback_action()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(
                                          _a_plan_refused_as(Verdict.PLATFORM_UNREACHABLE)
                                      ),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(all_of(
            _the_platforms_recorded_as_unreachable([DEPLOYMENT_PLATFORM]),
            _the_platform_was_published_as_unavailable(
                DEPLOYMENT_PLATFORM, the_actions_through(DEPLOYMENT_PLATFORM), published
            )
        ))


@pytest.mark.unit
@pytest.mark.parametrize("this_walks_own_planning", [
    pytest.param(lambda: Planned(
        descriptor=FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True),
        since=SOME_MOMENT_THE_CLAIM_WAS_WRITTEN + timedelta(minutes=5)
    ), id="a-later-plan"),
    pytest.param(lambda: _a_plan_refused_as(Verdict.NOT_ATTEMPTED), id="a-refused-plan")
])
def test_a_resumed_walk_acting_again_acts_on_the_plan_the_earlier_claim_carries(
    this_walks_own_planning: Callable[[], Planned[Any] | Outcome],
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The claim is the earlier attempt's, and so is its plan: the write compares
    # the estate with what the claim recorded. This walk's own plan was made
    # from an estate read later - acted on, it would be compared against a state
    # no row wrote down, and refused, it would stop an attempt the claim's own
    # plan still holds.
    the_plan_the_claim_carries = Planned(
        descriptor=FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True),
        since=SOME_MOMENT_THE_PLAN_WAS_READ
    )

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=the_plan_the_claim_carries)),
            calling(lambda: _nothing_of_it_landed(resuming)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(
                                          this_walks_own_planning()
                                      ),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            _the_action_was_taken_on(the_plan_the_claim_carries, take)
        )


@pytest.mark.unit
def test_a_plan_refused_after_a_person_ended_the_incident_is_recorded_as_the_stop(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Taking an action asks whether anybody still wants it before anything
    # else, and a refused plan never reaches that question - so the walk asks
    # it in its place. A person who ended the incident gets the attempt read
    # as the stop it was, rather than as a refusal nobody was waiting on.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _nobody_wants_it_any_more(still_wanted)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=ScaleOut(application=SOME_APPLICATION)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(
                                          _a_plan_refused_as(Verdict.NOT_ATTEMPTED)
                                      ),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_action_row_records_the_outcome(Verdict.STOPPED, complete_action),
            _the_action_row_records_whether_it_was_performed(False, complete_action),
            _the_verdict_reported_is(Verdict.STOPPED)
        ))


@pytest.mark.unit
def test_a_resumed_walk_reports_the_earlier_outcome_whatever_its_own_plan_found(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The plan is made before the claim is asked for, so a walk resumed after the
    # attempt finished has planned too - and finds, as often as not, that there
    # is nothing left to do, because the earlier attempt did it. The claim is the
    # earlier attempt's and so is its row: completed with this walk's refusal, it
    # would overwrite the verdict that attempt measured.
    the_outcome_the_first_attempt_recorded = Verdict.CONFIRMED

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, the_outcome_the_first_attempt_recorded)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=ScaleOut(application=SOME_APPLICATION)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(
                                          _a_plan_refused_as(Verdict.NOT_ATTEMPTED)
                                      ),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _nothing_was_completed(complete_action),
            _the_verdict_reported_is(the_outcome_the_first_attempt_recorded)
        ))


@pytest.mark.unit
def test_a_walk_resumed_after_the_action_was_taken_does_not_take_it_again(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # A worker died inside this node and another took the run up. The claim is
    # already in the database, so this walk is refused it - and refusing it is
    # the whole guard: acting again would set a flag that is already set and,
    # worse, write a second attempt into an incident that made one.
    the_outcome_the_first_attempt_recorded = Verdict.CONFIRMED

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, the_outcome_the_first_attempt_recorded)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_not_taken(take),
                     _nothing_was_completed(complete_action),
                     _the_verdict_reported_is(the_outcome_the_first_attempt_recorded)))


@pytest.mark.unit
def test_a_resumed_claim_carries_no_reason_left_from_an_earlier_round(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The walk keeps every field a node leaves unset. A resumed claim records
    # the verdict and not the reason, so a reason left by an earlier round's
    # refuted action would be handed to the next round as this action's - a
    # wrong reason, given to the Investigator as evidence.
    some_earlier_reason = "the rule that fired was still firing"

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, Verdict.REFUTED)),
            an_incident_past_a_refuted_round := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            ).model_copy(update={"action_because": some_earlier_reason})
        ) \
        .when(lambda: mitigation_node(an_incident_past_a_refuted_round,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(_the_walk_is_told_no_reason())


@pytest.mark.unit
def test_a_resumed_walk_says_it_caught_up_rather_than_acting(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # An incident whose story runs from a taken action straight to a conclusion
    # reads as one that lost a step - or as one that acted twice. This is the
    # only place that knows a second walk picked the incident up and read the
    # answer off the row, so it is the only place that can say so.
    the_outcome_the_first_attempt_recorded = Verdict.REFUTED
    some_candidate = _a_candidate_blaming(SOME_FLAG_THE_CANDIDATE_BLAMES)
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, the_outcome_the_first_attempt_recorded)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(), about=some_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_resumption_published_was(
            some_candidate, the_outcome_the_first_attempt_recorded, published))


@pytest.mark.unit
def test_a_walk_that_claimed_the_action_takes_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The other half, so the guard cannot pass by never acting at all: a walk
    # that got the claim is the one attempt, and it does the work.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_taken(take),
                     _no_earlier_outcome_was_looked_up(already_taken)))


@pytest.mark.unit
@pytest.mark.parametrize("verdict", [Verdict.CONFIRMED, Verdict.REFUTED])
def test_the_action_is_taken_while_acting_for_the_row_this_walk_claimed(
    verdict: Verdict,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # Every write the action makes is marked with the row its claim wrote, so
    # what it changed names the row that says what was done to it. A refuted
    # change is put back inside the same taking, and its putting back is
    # marked as the same action's.
    happened: list[str] = []

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, verdict)),
            calling(lambda: _noting_when_it_is_taken(take, happened)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      acting_for=_Acting(happened),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(
            _happened_in_order(happened, [
                f"acting for {THE_ACTION_THIS_WALK_CLAIMED}",
                "taken",
                f"no longer acting for {THE_ACTION_THIS_WALK_CLAIMED}"
            ])
        )


@pytest.mark.unit
def test_a_resumed_walk_acting_again_acts_for_the_row_the_earlier_attempt_claimed(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    resuming: ports.Resuming,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The row is the earlier attempt's, and this walk takes the action that row
    # was claimed for - so its writes are marked with that row, the one that
    # will say what came of them.
    happened: list[str] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=DONT_CARE_PLAN)),
            calling(lambda: _nothing_of_it_landed(resuming)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            calling(lambda: _noting_when_it_is_taken(take, happened)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=_a_candidate_blaming(SOME_FLAG_THE_CANDIDATE_BLAMES)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      acting_for=_Acting(happened),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(
            _happened_in_order(happened, [
                f"acting for {THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED}",
                "taken",
                f"no longer acting for {THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED}"
            ])
        )


@pytest.mark.unit
def test_a_claim_whose_verdict_this_version_cannot_read_escalates(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # A verdict was reached and this version cannot say which. The row comes
    # from a writer that is gone - a rename, an older deploy - and every
    # answer available here is wrong: reporting it hands a spelling to a walk
    # whose whole downstream reads verdicts, and acting again changes a
    # subject somebody already settled. So it stops, the way it stops for a
    # provider that will not answer.
    #
    # Not by asking whether the change landed, either. That question belongs
    # to a claim carrying nothing, and this one carries an outcome.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action,
                already_taken,
                UnreadVerdict("dissolved")
            )),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=_a_candidate_blaming(SOME_FLAG_THE_CANDIDATE_BLAMES)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_not_taken(take),
                     _the_incident_was_escalated(),
                     _nothing_was_read_of_the_estate(resuming),
                     _the_claim_was_not_advanced(advance_action)))


@pytest.mark.unit
def test_a_claim_nobody_could_account_for_escalates_without_asking_again(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # An earlier resume asked and nobody could say. Asking again could only
    # come back with a "no" - and a "no" here would have this walk act a
    # second time on a flag somebody may already have set.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.UNKNOWN)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=_a_candidate_blaming(SOME_FLAG_THE_CANDIDATE_BLAMES)
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_outcome=record_outcome,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_action_was_not_taken(take),
                     _the_incident_was_escalated(),
                     _the_walk_says(A_CHANGE_NOBODY_CAN_ACCOUNT_FOR),
                     _nothing_was_read_of_the_estate(resuming),
                     _the_claim_was_not_advanced(advance_action),
                     _nothing_was_completed(complete_action)))


@pytest.mark.unit
def test_the_change_is_put_on_the_claim_the_moment_the_agent_says_it_was_made(
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # Before the wait, with what the tier said would put it back, on the row
    # this walk claimed - so a worker that dies while the service is watched
    # leaves a change a withdrawal can undo and a write-up can call tried.
    some_way_back = FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True)

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            take := _an_agent_that_tells_of_the_change(some_way_back, Verdict.CONFIRMED),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            _the_claim_was_advanced_to(ActionProgress.PERFORMED, an_action_taking_incident,
                                       advance_action, undo_descriptor=some_way_back)
        )


@pytest.mark.unit
def test_a_change_that_could_not_be_put_on_the_claim_does_not_stop_the_attempt(
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock,
    caplog: pytest.LogCaptureFixture
) -> None:
    # The change is made by now, and the wait is what judges it. Abandoning
    # the attempt over an early copy of the record would leave the world
    # changed and unmeasured - and the completion writes the same facts again.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.WARNING)),
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_claim_cannot_be_written(advance_action)),
            take := _an_agent_that_tells_of_the_change(
                FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True), Verdict.CONFIRMED
            ),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_verdict_reported_is(Verdict.CONFIRMED),
            _the_action_row_records_the_outcome(Verdict.CONFIRMED, complete_action),
            one_record_was_logged(caplog, "orchestrator.walk.mitigating", logging.WARNING,
                                  "the change could not be recorded as made before the wait")
        ))


@pytest.mark.unit
def test_a_change_that_could_not_be_put_on_the_claim_of_a_lost_run_stops_the_attempt(
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The one write before the wait that is not an early copy of anything: it
    # says the run is another claim's now. Waiting on the change from here
    # would be a walk nobody holds measuring production for minutes, and the
    # completion after it would be refused for the same reason.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_claim_is_refused_for_a_lost_run(advance_action)),
            take := _an_agent_that_tells_of_the_change(
                FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True), Verdict.CONFIRMED
            ),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(attempting(lambda: mitigation_node(an_action_taking_incident,
                                                 take=take,
                                                 plan_action=_a_plan_nobody_checks(),
                                                 resuming=_resuming_nobody_checks(),
                                                 advance_action=advance_action,
                                                 owe_a_put_back=_an_owing_nobody_checks(),
                                                 record_action=record_action,
                                                 complete_action=complete_action,
                                                 record_outcome=record_outcome,
                                                 already_taken=already_taken,
                                                 acting_for=acting_for,
                                                 still_wanted=still_wanted))) \
        .then(all_of(
            an_error_was_raised(RunLost),
            _no_action_row_was_completed(complete_action)
        ))


# A cache entry a discard names, which nothing in a case reads.
DONT_CARE_CACHE_KEY = "kuki:1"


@pytest.mark.unit
@pytest.mark.parametrize(("some_action", "its_plan"), [
    # Lambdas, so the builders they call can be defined further down.
    pytest.param(RestartService(service=SOME_APPLICATION), lambda dont_care_action: None,
                 id="restart"),
    pytest.param(DiscardCacheEntries(service=SOME_APPLICATION, keys=(DONT_CARE_CACHE_KEY,)),
                 lambda dont_care_action: None, id="discard"),
    pytest.param(RollBackDeployment(application=SOME_APPLICATION),
                 lambda action: _a_plan_of(action), id="rollback-on-its-plan")
])
def test_an_action_whose_answer_was_lost_after_it_was_sent_is_kept_as_nobody_can_say_and_escalates(
    some_action: Action,
    its_plan: Callable[[Action], Planned[Any] | None],
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # Asked for and never answered: a restart or a discard the transport would
    # not ask again, or a rollback asked again that got no answer either. The
    # change may have been made, or not. The claim keeps that nobody can say -
    # the same answer a resumed walk gives a claim it cannot account for, so the
    # walk resumed after this one reads it and asks nothing again - with what
    # may be out there: the plan, for a rollback, whose way back it is; nothing,
    # for a restart or a discard, which plan none. The incident goes to a
    # person. No verdict is written: there is no outcome to write, and a
    # completed row would say the attempt ended in one. Nothing is announced,
    # since nothing is known to have been done.
    published: list[IncidentEvent] = []
    the_plan = its_plan(some_action)

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            take := _an_agent_whose_answer_was_lost(),
            an_action_taking_incident := _a_mitigating_incident(proposing=some_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(the_plan),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(all_of(
            _the_claim_was_advanced_to(
                ActionProgress.UNKNOWN, an_action_taking_incident, advance_action,
                undo_descriptor=the_plan.descriptor if the_plan is not None else None
            ),
            _the_incident_was_escalated(),
            _the_walk_says(A_CHANGE_LOST_AFTER_IT_WAS_ASKED_FOR),
            _no_verdict_was_written(complete_action, record_outcome),
            _no_action_was_announced(published)
        ))


@pytest.mark.unit
def test_a_resumed_claim_taken_again_whose_answer_was_lost_keeps_its_plan_and_escalates(
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A claim nothing of which landed, taken again on its plan as the live walk
    # takes it - and the rollback asked again got no answer either. As the
    # live walk's: the claim keeps that nobody can say, with the plan whose way
    # back it is, and the incident goes to a person with nothing completed.
    a_rollback = RollBackDeployment(application=SOME_APPLICATION)
    the_plan = _a_plan_of(a_rollback)
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=the_plan)),
            take := _an_agent_whose_answer_was_lost(),
            an_action_taking_incident := _a_resumed_incident(proposing=a_rollback)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_claim_was_advanced_to(ActionProgress.UNKNOWN, an_action_taking_incident,
                                       advance_action, undo_descriptor=the_plan.descriptor),
            _the_incident_was_escalated(),
            _the_walk_says(A_CHANGE_LOST_AFTER_IT_WAS_ASKED_FOR),
            _no_verdict_was_written(complete_action, record_outcome),
            _no_action_was_announced(published)
        ))


@pytest.mark.unit
def test_an_action_that_stopped_the_symptom_goes_on_to_look_for_a_fix() -> None:
    # The path that did not exist before. A mitigation that worked used to end
    # the incident at the postmortem, which meant the fault it exposed was
    # never fixed - a flag left holding back a bug nobody had written down.
    Scenario() \
        .given(a_mitigated_incident := _an_incident_in(IncidentStatus.MITIGATED)) \
        .when(lambda: route_after_mitigation(a_mitigated_incident)) \
        .then(the_route_is(FIXING_ROUTE))


@pytest.mark.unit
def test_a_refuted_action_is_handed_to_the_walk() -> None:
    # A refuted action stays in `mitigating` - the same phase of the same
    # incident, with another explanation about to be tried. It asks the walk
    # whether there is one, and Code-Fix is what happens when there is not.
    Scenario() \
        .given(a_mitigating_incident := _an_incident_in(IncidentStatus.MITIGATING)) \
        .when(lambda: route_after_mitigation(a_mitigating_incident)) \
        .then(the_route_is(NEXT_CANDIDATE_ROUTE))


@pytest.mark.unit
def test_an_action_that_could_not_be_answered_for_reaches_a_human() -> None:
    Scenario() \
        .given(an_escalated_incident := _an_incident_in(IncidentStatus.ESCALATED)) \
        .when(lambda: route_after_mitigation(an_escalated_incident)) \
        .then(the_route_is(ESCALATED_ROUTE))


@pytest.mark.unit
def test_the_graph_says_what_action_it_took_and_for_which_candidate(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The one moment production state changes. An account that omitted it
    # would describe an investigation rather than an intervention.
    published: list[IncidentEvent] = []
    some_candidate = a_determined_hypothesis(a_random_id())
    the_action = _an_action_with_an_undo_descriptor()

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=the_action, about=some_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_exactly_one_action_was_announced(some_candidate, the_action, published))


@pytest.mark.unit
def test_the_action_announced_says_the_number_of_the_candidate_it_was_for(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The number every telling says the candidate by. The move to mitigating
    # names no candidate, so this line is where a reader learns which cause the
    # action answered - and a reader told nothing takes it for the leader's.
    published: list[IncidentEvent] = []
    a_second_rounds_candidate = a_determined_hypothesis(a_random_id()).model_copy(
        update={"number": 3})

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(),
                about=a_second_rounds_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(all_of(
            _the_action_announced_was_for_candidate(3, published),
            _the_verdict_was_for_candidate(3, complete_action)
        ))


@pytest.mark.unit
def test_an_attempt_that_ended_before_its_write_says_the_candidate_it_was_for(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Announced by nothing else: the verdict's line is the one saying what was
    # reached for, so it is the one saying for which candidate.
    a_second_rounds_candidate = a_determined_hypothesis(a_random_id()).model_copy(
        update={"number": 3})

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_action_came_back(take, Verdict.ESCALATED, judged=False,
                                                  performed=False)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_a_rollback_action(), about=a_second_rounds_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            _the_verdict_was_for_candidate(3, complete_action)
        )


@pytest.mark.unit
def test_the_graph_says_which_way_it_moved_the_flag(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # "A flag was changed" is the half of the sentence nobody can act on.
    # Whether the service is now running with the feature on or off is the
    # whole point of the change.
    published: list[IncidentEvent] = []
    the_action = _an_action_with_an_undo_descriptor()

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(proposing=the_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_announced_action_moved_the_flag(the_action.enabled, published))


@pytest.mark.unit
def test_the_graph_says_which_card_it_held_the_deployment_to(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # "The deployment was held to a card" is the half a reader cannot check.
    # Which card is the half they hold against the placement recorded at the
    # onset, and the action is the only thing that knows it.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            a_pinning_incident := _a_mitigating_incident(
                proposing=PinToAccelerator(
                    application="kuki-service", accelerator=SOME_ACCELERATOR
                )
            )
        ) \
        .when(lambda: mitigation_node(a_pinning_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_announced_action_held_it_to(SOME_ACCELERATOR, published))


@pytest.mark.unit
def test_the_graph_says_what_verdict_came_back(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The verdict is what the action was for, and it arrives after it - two
    # lines in the narration, because they are two moments. It travels with the
    # verdict's own write rather than separately, so the two cannot disagree.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.REFUTED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_verdict_was_narrated(str(Verdict.REFUTED), complete_action))


@pytest.mark.unit
def test_a_node_nobody_is_listening_to_does_the_same_thing(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The account is never part of the work, at this level as at every other.
    # One clock for both runs, because when the action was taken is part of it.
    def run(publisher: Publisher) -> StateDelta:
        return mitigation_node(
            _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor()),
            take=take,
            plan_action=_a_plan_nobody_checks(),
            resuming=_resuming_nobody_checks(),
            advance_action=_an_advance_nobody_checks(),
            owe_a_put_back=_an_owing_nobody_checks(),
            record_action=record_action,
            complete_action=complete_action,
            record_outcome=record_outcome,
            already_taken=already_taken,
            acting_for=acting_for,
            still_wanted=still_wanted,
            publisher=publisher,
            now=lambda: DONT_CARE_MOMENT_IT_WAS_TAKEN
        )

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
        ) \
        .when(
            lambda: (
                run(_a_listener()), 
                run(nobody)
            )
        ) \
        .then(_both_runs_did_the_same_work())


@pytest.mark.unit
def test_an_action_aimed_at_a_dependency_is_announced_as_one(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Argus restarted something it was never paged about, and the account has
    # to carry the reason it was allowed to. The walk is the only party that
    # holds both halves - the service that alerted and the service the action
    # is addressed to - so it is the only one that can say it.
    a_dependency_of_the_alerting_service = "kuki-pricing"
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_acting_elsewhere := _a_mitigating_incident(
                proposing=RestartService(service=a_dependency_of_the_alerting_service)
            )
        ) \
        .when(lambda: mitigation_node(an_incident_acting_elsewhere,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_action_was_announced_as_a_dependency_of("kuki-service", published))


@pytest.mark.unit
def test_an_action_on_the_service_that_alerted_is_announced_as_nobodys_dependency(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The ordinary incident, and the one that has to stay silent. Argus has
    # been restarting the service it was paged about since before there was a
    # register, and nothing about that needs explaining.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_acting_on_the_alerting_service := _a_mitigating_incident(
                proposing=RestartService(service="kuki-service")
            )
        ) \
        .when(lambda: mitigation_node(an_incident_acting_on_the_alerting_service,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_action_was_announced_as_a_dependency_of(None, published))


@pytest.mark.unit
def test_a_flag_reverted_is_announced_as_nobodys_dependency(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # A flag is not an address. Its subject is the flag's own name, which is
    # never the service that alerted - so anything deciding this by comparing
    # the two announces every revert Argus makes as acting on a dependency,
    # and the clause that was meant to mark the unusual incident marks the
    # commonest one instead.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_reverting_a_flag := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_incident_reverting_a_flag,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(_the_action_was_announced_as_a_dependency_of(None, published))


@pytest.mark.unit
def test_the_minute_the_alert_dated_the_incident_to_reaches_the_agent(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Mitigation judges an incident whose minutes were never published by whether
    # readings come back rather than by whether a level does, and the minute it
    # asks that about is the one the alert dated the incident to. The agent cannot
    # derive it - nothing it is handed says when the incident began - so a walk
    # that keeps the minute to itself leaves the judgement keyed on `None` and the
    # blind case silently judged on levels it does not have.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_its_alert_dated := _a_mitigating_incident_dated_at(
                SOME_ONSET_THE_ALERT_STATED
            )
        ) \
        .when(lambda: mitigation_node(an_incident_its_alert_dated,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_onset_handed_over_is(SOME_ONSET_THE_ALERT_STATED, take))


@pytest.mark.unit
def test_an_incident_no_alert_dated_hands_over_no_minute(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Every incident whose onset was measured rather than stated, which is almost
    # all of them. `None` is what keeps the new judgement from reaching them: a
    # measured onset came from minutes that therefore exist, so the question the
    # minute selects does not arise.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_nothing_dated := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_incident_nothing_dated,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_onset_handed_over_is(None, take))


def _a_mitigating_incident_dated_at(onset: datetime) -> IncidentState:
    """A mitigating incident whose alert states when the incident began.

    The alert is the only thing that ever states one, and it states one only where
    it knows something no series carries - so this is the shape of an incident
    found by a reconciliation or by an absence rather than by a rule watching a
    graph.
    """
    state = _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor())

    return state.model_copy(
        update={"alert": state.alert.model_copy(update={"stated_onset": onset})}
    )


def _the_onset_handed_over_is(expected: datetime | None,
                              take: MagicMock) -> Assertion[object]:
    """What minute the agent was asked to judge the incident from.

    Read off the call rather than from anything the node returns, because handing
    it over is the whole of what this node does with it - the judgement itself
    belongs to the agent, and a test that asserted the verdict would be asserting
    the agent's behaviour through a mock of the agent.
    """
    def assertion(_: object) -> bool:
        handed_over = take.call_args.kwargs.get("onset")

        if handed_over != expected:
            raise AssertionError(
                f"Expected the agent to be handed onset [{expected}], and it was "
                f"handed [{handed_over}] - so the minute the incident was dated to "
                f"never reaches the wait that has to judge it."
            )

        return True

    return assertion


@pytest.mark.unit
def test_the_minute_the_investigation_dated_the_incident_from_reaches_the_agent(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Mitigation looks for the service's recovery after the incident began, or a
    # service that flapped before it is credited with a recovery from an incident
    # that had not yet begun. Where it began is the investigation's to say, and
    # nothing else the agent is handed says it.
    the_incident_began = "2026-09-04T21:48:00Z"

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_the_investigation_dated := _a_mitigating_incident_begun_at(
                the_incident_began
            )
        ) \
        .when(lambda: mitigation_node(an_incident_the_investigation_dated,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_beginning_handed_over_is(the_incident_began, take))


def _a_mitigating_incident_begun_at(minute: str) -> IncidentState:
    """A mitigating incident whose investigation dated it from `minute`."""
    state = _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor())

    return state.model_copy(update={"onset": EstablishedOnset(
        minute=minute, how_known=HowTheMinuteIsKnown.MEASURED
    )})


def _the_beginning_handed_over_is(expected: str | None,
                                  take: MagicMock) -> Assertion[object]:
    """Which minute the agent was told the incident began in, or none."""
    def assertion(_: object) -> bool:
        handed_over = take.call_args.kwargs.get("incident_began")

        if handed_over != expected:
            raise AssertionError(
                f"Expected the agent to be handed incident_began [{expected}], and "
                f"it was handed [{handed_over}] - so a recovery can be dated before "
                f"the incident it ends began."
            )

        return True

    return assertion


@pytest.mark.unit
def test_the_rule_a_series_alert_names_is_handed_to_the_agent(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The rule that paged is what the action is judged by, where the alert is
    # about a series: it defines what is acceptable for the service. The agent
    # cannot find it - nothing else it is handed says which rule fired.
    some_rule = "some-rule"

    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_paged_by_a_rule := _a_mitigating_incident_paged_by(
                some_rule, AlarmClaim.A_SERIES_CONDITION
            )
        ) \
        .when(lambda: mitigation_node(an_incident_paged_by_a_rule,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_rule_handed_over_is(some_rule, take))


@pytest.mark.unit
def test_a_finding_hands_the_agent_no_rule_to_wait_on(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # A check that runs weekly resolves when it next runs, so waiting on its rule
    # would hold the incident open for days. A finding keeps the confirmation it
    # has: the store's receipt, or readings returning.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_a_check_found := _a_mitigating_incident_paged_by(
                "io-shop-cached-spend-totals-are-stale", AlarmClaim.ITS_OWN_FINDING
            )
        ) \
        .when(lambda: mitigation_node(an_incident_a_check_found,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_rule_handed_over_is(None, take))


def _a_mitigating_incident_paged_by(rule: str, claim: AlarmClaim) -> IncidentState:
    """A mitigating incident whose alert names the rule that fired."""
    state = _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor())

    return state.model_copy(
        update={"alert": state.alert.model_copy(update={"rule": rule, "claim": claim})}
    )


def _the_rule_handed_over_is(expected: str | None,
                             take: MagicMock) -> Assertion[object]:
    """Which rule the agent was asked to judge the action by, or none."""
    def assertion(_: object) -> bool:
        handed_over = take.call_args.kwargs.get("rule")

        if handed_over != expected:
            raise AssertionError(
                f"Expected the agent to be handed rule [{expected}], and it was "
                f"handed [{handed_over}]."
            )

        return True

    return assertion


def _an_incident_in(status: IncidentStatus) -> IncidentState:
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    return an_incident_state(some_alert, status)


def _a_mitigating_incident(proposing: Action | None = None,
                           about: Hypothesis | None = None,
                           listing: list[ServiceDependency] | None = None) -> IncidentState:
    """An incident whose action the gate let through.

    So the register is the one the gate admitted it against: where the action
    is aimed somewhere other than the service that alerted, the register lists
    that service as the organisation's own - unless a case hands a register of
    its own in `listing`, which is how it says the policy should refuse.
    """
    state = _an_incident_in(IncidentStatus.MITIGATING)

    return state.model_copy(
        update={
            "hypothesis": about or a_determined_hypothesis(state.incident_id),
            "proposed_action": proposing,
            "dependencies": (listing if listing is not None
                             else _a_register_vouching_for(proposing, state.alert.service))
        }
    )


def _a_register_vouching_for(action: Action | None,
                             alerting_service: str) -> list[ServiceDependency]:
    """The register the gate admitted `action` against: empty where it is aimed
    at the service that alerted or at no service, and otherwise listing the
    service it is aimed at as the organisation's own."""
    addressed_to = the_service_addressed_by(action) if action is not None else None

    if addressed_to is None or addressed_to == alerting_service:
        return []

    return [_a_dependency_of_ours(addressed_to)]


def _a_dependency_of_ours(name: str) -> ServiceDependency:
    return ServiceDependency(
        name=name,
        purpose="something the alerting service calls while it serves a request",
        host=f"{name}.example",
        owner="some-team",
        ownership=Ownership.INTERNAL
    )


def _a_candidate_blaming(flag: str) -> Hypothesis:
    """The subject matters in the resumed cases: it is the flag the provider's
    log is asked about, so a candidate blaming nothing in particular would make
    the question unanswerable for a reason the test never meant to introduce."""
    return a_determined_hypothesis(a_random_id()).model_copy(update={"subject": flag})


def _an_action_with_an_undo_descriptor() -> RevertFeatureFlag:
    return RevertFeatureFlag(
        flag=DONT_CARE_FLAG,
        enabled=False,
        undo_descriptor=FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True)
    )


def _the_action_came_back(take: MagicMock,
                          verdict: Verdict,
                          undo_descriptor: UndoDescriptor | None = None,
                          judged: bool = True,
                          because: str | None = None,
                          performed: bool = True,
                          left_behind_known: bool = True,
                          not_performed_because: str | None = None,
                          undone: Undone | None = None,
                          undone_detail: str | None = None) -> None:
    """The agent answers with `verdict` - telling of the change as it makes it,
    as the real one does, wherever the action was performed."""
    outcome = Outcome(verdict=verdict,
                      detail="dont care",
                      undo_descriptor=undo_descriptor,
                      judged=judged,
                      because=because,
                      performed=performed,
                      left_behind_known=left_behind_known,
                      not_performed_because=not_performed_because,
                      undone=undone,
                      undone_detail=undone_detail)

    def taking(dont_care_admitted: Admitted[Action], /, **keywords: object) -> Outcome:
        change_made = cast(ChangeMade, keywords["change_made"])
        if performed:
            change_made(undo_descriptor)

        return outcome

    take.side_effect = taking


def _noting_when_it_is_taken(take: MagicMock, happened: list[str]) -> None:
    """`take` answering as the case set it, and noting into `happened` when it
    was asked - so a case can say what was in force around it."""
    answering = take.side_effect

    def taking(admitted: Admitted[Action], /, **keywords: object) -> Outcome:
        happened.append("taken")

        return cast(Outcome, answering(admitted, **keywords))

    take.side_effect = taking


def _happened_in_order(happened: list[str], expected: list[str]) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if happened != expected:
            raise AssertionError(f"Expected {expected} in that order, got {happened}.")

        return True

    return assertion


def _nobody_wants_it_any_more(still_wanted: MagicMock) -> None:
    """A person ended the incident: no next step is wanted."""
    still_wanted.return_value = False


# ---------------------------------------------------------------------------
# A claim refused because another change of Argus's to the subject is open
# ---------------------------------------------------------------------------

# Another incident whose change to the same thing is in progress or may still
# be in place, and how a line names it: the first eight characters of its id.
ANOTHER_INCIDENT_HOLDING_IT = "7b3d5f1e-0000-4000-8000-0000000000b2"
ANOTHER_INCIDENT_SAID_AS = ANOTHER_INCIDENT_HOLDING_IT[:8]
NO_HOLDER_FOUND = None

# Why the claim was refused, in the refusal's own sentence, and the clause that
# follows it by whose the other change is - none, where no holder was found.
WHY_THE_SUBJECT_WAS_OPEN = why_it_was_refused(Refusal.SUBJECT_ALREADY_OPEN)
HELD_BY_ANOTHER_INCIDENT = f" - incident {ANOTHER_INCIDENT_SAID_AS}'s"
HELD_BY_THIS_INCIDENT = " - this incident's own, from earlier"
HELD_BY_NOBODY_FOUND = ""

# Every holder a refused claim can name - another incident, the incident the
# claim was for, or nobody found - given the incident, with the clause each
# is said with.
EVERY_HOLDER_OF_AN_OPEN_SUBJECT = [
    pytest.param(lambda dont_care_state: ANOTHER_INCIDENT_HOLDING_IT, HELD_BY_ANOTHER_INCIDENT,
                 id="another-incident"),
    pytest.param(lambda state: state.incident_id, HELD_BY_THIS_INCIDENT, id="this-incident"),
    pytest.param(lambda dont_care_state: NO_HOLDER_FOUND, HELD_BY_NOBODY_FOUND,
                 id="none-found")
]


@pytest.mark.unit
@pytest.mark.parametrize(("holder", "clause"), EVERY_HOLDER_OF_AN_OPEN_SUBJECT)
def test_a_claim_refused_for_an_open_subject_escalates_saying_whose_the_change_is(
    holder: Callable[[IncidentState], str | None],
    clause: str,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The database refused the claim: another change of Argus's to the same
    # thing is in progress or may still be in place, and acting beside it is
    # what this guards against. Nothing is taken and no action row is written;
    # the candidate is recorded untested, the refusal is published naming the
    # holder, and the walk escalates - in one sentence, said the same way by
    # the candidate's row, the reason and the line.
    published: list[IncidentEvent] = []
    some_candidate = a_determined_hypothesis(a_random_id())
    an_action_taking_incident = _a_mitigating_incident(
        proposing=_an_action_with_an_undo_descriptor(),
        about=some_candidate
    )
    open_in = holder(an_action_taking_incident)
    said = f"{WHY_THE_SUBJECT_WAS_OPEN}{clause}"

    Scenario() \
        .given(
            calling(lambda: _the_subject_is_open_in(record_action, open_in)),
            an_action_taking_incident
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _nothing_was_completed(complete_action),
            _the_candidate_was_left_untested_because(some_candidate, said, record_outcome),
            _the_subject_s_refusal_was_published(published, some_candidate, open_in),
            _the_verdict_reported_is(Verdict.ESCALATED),
            _the_reason_reported_is(said)
        ))


@pytest.mark.unit
def test_a_resumed_walk_whose_claim_is_refused_for_an_open_subject_escalates_the_same_way(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A walk resumed after its worker died claims as any walk does, and the
    # claim's answer decides: refused for an open subject, nothing of an
    # earlier attempt is read - there is no claim of this walk's to resume -
    # and it escalates as the live walk does.
    published: list[IncidentEvent] = []
    some_candidate = a_determined_hypothesis(a_random_id())
    said = f"{WHY_THE_SUBJECT_WAS_OPEN}{HELD_BY_ANOTHER_INCIDENT}"

    Scenario() \
        .given(
            calling(lambda: _the_subject_is_open_in(record_action, ANOTHER_INCIDENT_HOLDING_IT)),
            an_action_taking_incident := _a_resumed_incident().model_copy(
                update={"hypothesis": some_candidate}
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _nothing_was_completed(complete_action),
            _no_earlier_attempt_was_read(already_taken),
            _nothing_was_read_of_the_estate(resuming),
            _the_candidate_was_left_untested_because(some_candidate, said, record_outcome),
            _the_subject_s_refusal_was_published(published, some_candidate,
                                                 ANOTHER_INCIDENT_HOLDING_IT),
            _the_verdict_reported_is(Verdict.ESCALATED),
            _the_reason_reported_is(said)
        ))


# Somewhere the register does not list, so the autonomy policy refuses an action
# aimed at it - and the sentence that refusal is said in.
SOME_SERVICE_NOBODY_LISTED = "kuki-billing"
WHY_IT_WAS_OUT_OF_REACH = why_it_was_refused(Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH)
# An action aimed there that has a plan, for the resumed cases: a claim's change
# is asked after on its plan, and one with none is never asked after at all.
A_ROLLBACK_NOBODY_LISTED = RollBackDeployment(application=SOME_SERVICE_NOBODY_LISTED)


@pytest.mark.unit
def test_the_action_is_taken_as_the_autonomy_policy_admitted_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # What the agent is handed is the policy's admission of the action, not the
    # action: the write accepts nothing else, so a node that handed over the
    # bare proposal could not be type-checked, and one that handed over an
    # admission of something else would have taken a different action.
    Scenario() \
        .given(
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=(the_proposal := _an_action_with_an_undo_descriptor())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_it_was_taken_as_the_admission_of(the_proposal, take))


@pytest.mark.unit
def test_a_resumed_walk_takes_the_claimed_action_as_the_autonomy_policy_admits_it_again(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # An admission is never kept in the walk's state - a checkpoint is data, and
    # a proof that could be read back from one could be written into one. So a
    # walk resumed after its worker died, finding the claim's change not made,
    # takes the action as the policy admits it now, asked of the same action,
    # alert and register the gate asked.
    the_plan_the_claim_carries = _a_plan_of(_an_action_with_an_undo_descriptor())

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=the_plan_the_claim_carries)),
            calling(lambda: _nothing_of_it_landed(resuming)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_resumed_incident(
                proposing=(the_proposal := _an_action_with_an_undo_descriptor())
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=_Acting(),
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(_it_was_taken_as_the_admission_of(the_proposal, take))


@pytest.mark.unit
def test_an_action_the_autonomy_policy_refuses_when_it_comes_to_be_taken_is_never_taken(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The gate asked the same policy and was told yes, so an action reaching
    # here that the policy refuses came some way the gate did not stand on - an
    # edge into the node past it, or a declared set narrowed under a resumed
    # walk. With no earlier attempt holding a claim, nothing is planned, claimed
    # or taken; the candidate is kept as untested and the refusal published as
    # the gate's are; and the incident goes to a person rather than to the next
    # candidate, since whatever let this through is not a judgement on this
    # candidate alone.
    published: list[IncidentEvent] = []
    plan_action = _a_plan_nobody_checks()
    some_candidate = a_determined_hypothesis(a_random_id())

    Scenario() \
        .given(
            calling(lambda: _no_earlier_attempt_holds_a_claim(already_taken)),
            # Answering as an agent would, so a node that took it anyway says
            # so in the assertions rather than in a crash on a stand-in's reply.
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_aimed_outside_the_estate := _a_mitigating_incident(
                proposing=RestartService(service=SOME_SERVICE_NOBODY_LISTED),
                about=some_candidate,
                listing=[]
            )
        ) \
        .when(lambda: mitigation_node(an_incident_aimed_outside_the_estate,
                                      take=take,
                                      plan_action=plan_action,
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append)) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _nothing_was_planned_or_claimed(plan_action, record_action),
            _the_candidate_was_left_untested_because(some_candidate, WHY_IT_WAS_OUT_OF_REACH,
                                                     record_outcome),
            _the_refusal_published_was(Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH, some_candidate,
                                       published),
            _the_verdict_reported_is(Verdict.ESCALATED),
            _the_reason_reported_is(WHY_IT_WAS_OUT_OF_REACH)
        ))


@pytest.mark.unit
def test_a_resumed_walk_the_autonomy_policy_now_refuses_does_not_take_the_claimed_action_again(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Asked again on a resume and refused - the declared set or the register
    # narrowed while the walk was down. The claim is read and the estate asked
    # whether its change was made, as any resumed walk asks; found not made,
    # taking it now would be a new write nothing admitted. So it is not taken.
    # The claim is completed as not performed, saying why, rather than left
    # open to close its subject to every incident after this one, the
    # candidate is kept as untested with that reason, and the incident goes to
    # a person.
    some_candidate = a_determined_hypothesis(a_random_id())
    its_plan = _a_plan_of(A_ROLLBACK_NOBODY_LISTED)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=its_plan)),
            calling(lambda: _nothing_of_it_landed(resuming)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_incident_aimed_outside_the_estate := _a_resumed_incident(
                proposing=A_ROLLBACK_NOBODY_LISTED, about=some_candidate, listing=[])
        ) \
        .when(lambda: mitigation_node(an_incident_aimed_outside_the_estate,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_asked_whether_made_on(A_ROLLBACK_NOBODY_LISTED, its_plan, resuming),
            _the_action_was_not_taken(take),
            _the_action_row_records_whether_it_was_performed(False, complete_action),
            _the_verdict_s_line_says_why_it_was_not_performed(WHY_IT_WAS_OUT_OF_REACH,
                                                              complete_action),
            _the_candidate_was_left_untested_because(some_candidate, WHY_IT_WAS_OUT_OF_REACH,
                                                     record_outcome),
            _the_verdict_reported_is(Verdict.ESCALATED),
            _the_reason_reported_is(WHY_IT_WAS_OUT_OF_REACH)
        ))


@pytest.mark.unit
def test_a_claimed_change_found_made_is_still_watched_when_the_autonomy_policy_now_refuses_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The policy refuses a new write, and watching a change the earlier worker
    # already made is not one. Left unwatched, a change Argus made would stand
    # with nobody judging whether it helped, and nobody putting it back if it
    # did not - the refusal would have made the incident worse, not safer.
    its_plan = _a_plan_of(A_ROLLBACK_NOBODY_LISTED)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=its_plan)),
            calling(lambda: _it_was_found_made(resuming, Made(
                descriptor=its_plan.descriptor,
                made_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE))),
            calling(lambda: _the_watch_came_back(resuming, _an_outcome(Verdict.CONFIRMED))),
            an_incident_aimed_outside_the_estate := _a_resumed_incident(
                proposing=A_ROLLBACK_NOBODY_LISTED, listing=[])
        ) \
        .when(lambda: mitigation_node(an_incident_aimed_outside_the_estate,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_change_made_earlier_was_watched(A_ROLLBACK_NOBODY_LISTED, resuming),
            _the_action_was_not_taken(take),
            _the_action_row_records_the_outcome(Verdict.CONFIRMED, complete_action),
            _the_verdict_reported_is(Verdict.CONFIRMED)
        ))


@pytest.mark.unit
def test_a_change_told_as_made_is_still_watched_when_the_autonomy_policy_now_refuses_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The worker died in the wait: the change is out there, and watching it is
    # no new write. Refused or not, it is watched and recorded as any change
    # told as made is.
    its_plan = _a_plan_of(A_ROLLBACK_NOBODY_LISTED)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=its_plan,
                progress=ActionProgress.PERFORMED, undo_descriptor=its_plan.descriptor,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: _it_was_found(resuming, ChangeFound(still_argus_s=True))),
            calling(lambda: _the_watch_came_back(resuming, _an_outcome(Verdict.REFUTED))),
            an_incident_aimed_outside_the_estate := _a_resumed_incident(
                proposing=A_ROLLBACK_NOBODY_LISTED, listing=[])
        ) \
        .when(lambda: mitigation_node(an_incident_aimed_outside_the_estate,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_change_made_earlier_was_watched(A_ROLLBACK_NOBODY_LISTED, resuming),
            _the_action_was_not_taken(take),
            _the_action_row_records_the_outcome(Verdict.REFUTED, complete_action),
            _the_verdict_reported_is(Verdict.REFUTED)
        ))


@pytest.mark.unit
def test_a_change_owed_back_is_still_put_back_when_the_autonomy_policy_now_refuses_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The watch refuted the change and the worker died before putting it back.
    # Putting back what Argus itself made is the one write the refusal must not
    # stop: refusing it would leave a refuted change standing on a service the
    # policy now says Argus may not touch.
    its_plan = _a_plan_of(A_ROLLBACK_NOBODY_LISTED)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PUTTING_BACK, undo_descriptor=its_plan.descriptor,
                performed_at=SOME_MOMENT_IT_WAS_MADE, put_back_because=SOME_FINDING)),
            an_incident_aimed_outside_the_estate := _a_resumed_incident(
                proposing=A_ROLLBACK_NOBODY_LISTED, listing=[])
        ) \
        .when(lambda: mitigation_node(an_incident_aimed_outside_the_estate,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_change_made_earlier_was_put_back(A_ROLLBACK_NOBODY_LISTED, resuming),
            _it_was_not_watched(resuming),
            _the_action_was_not_taken(take)
        ))


def _no_earlier_attempt_holds_a_claim(already_taken: MagicMock) -> None:
    already_taken.return_value = None


def _the_change_made_earlier_was_watched(action: Action,
                                         resuming: ports.Resuming) -> Assertion[StateDelta]:
    """Watched once, as `action` - in whatever words its kind says it in, which
    the cases about the words assert on their own."""
    def assertion(dont_care_result: StateDelta) -> bool:
        watched = [call.args[0] for call in _mocked(resuming.watch).call_args_list]

        if watched != [action]:
            raise AssertionError(f"Expected [{action}] watched once, got {watched}.")

        return True

    return assertion


def _the_change_made_earlier_was_put_back(action: Action,
                                          resuming: ports.Resuming) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        settled = [call.args[0] for call in _mocked(resuming.settle).call_args_list]

        if settled != [action.action_type]:
            raise AssertionError(
                f"Expected a [{action.action_type}] put back once, got {settled}."
            )

        return True

    return assertion


def _it_was_taken_as_the_admission_of(action: Action, take: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if not take.called:
            raise AssertionError(f"Expected [{action}] to be taken, nothing was.")

        handed = take.call_args.args[0]

        if not isinstance(handed, Admitted) or handed.action != action:
            raise AssertionError(
                f"Expected the agent to be handed the admission of [{action}], it was "
                f"handed a [{type(handed).__name__}]: [{handed}]."
            )

        return True

    return assertion


def _nothing_was_planned_or_claimed(plan_action: MagicMock,
                                    record_action: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        asked = {name: called.call_args_list
                 for name, called in (("planned", plan_action), ("claimed", record_action))
                 if called.called}

        if asked:
            raise AssertionError(f"Expected nothing planned or claimed, got {asked}.")

        return True

    return assertion


def _the_refusal_published_was(refusal: Refusal,
                               candidate: Hypothesis,
                               published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """One refusal published, about `candidate` - by its id and the number a
    reader knows it by - saying `refusal`."""
    def assertion(dont_care_result: StateDelta) -> bool:
        refusals = [(event.hypothesis_id, event.candidate_number, event.refusal)
                    for event in published if isinstance(event, ActionRefused)]
        wanted = [(candidate.id, candidate.number, refusal)]

        if refusals != wanted:
            raise AssertionError(f"Expected the refusals published {wanted}, got {refusals}.")

        return True

    return assertion


def _the_subject_is_open_in(record_action: MagicMock, open_in: str | None) -> None:
    """The claim refused: another change of Argus's to the subject is open, in
    `open_in` - `None` where none was found."""
    record_action.return_value = SubjectOpen(open_in=open_in)


def _the_subject_s_refusal_was_published(published: list[IncidentEvent],
                                         candidate: Hypothesis,
                                         open_in: str | None) -> Assertion[StateDelta]:
    """One refusal published for an open subject, about `candidate` - by its id
    and the number a reader knows it by - naming `open_in`."""
    def assertion(dont_care_result: StateDelta) -> bool:
        refusals = [(event.hypothesis_id, event.candidate_number, event.refusal, event.open_in)
                    for event in published if isinstance(event, ActionRefused)]
        wanted = [(candidate.id, candidate.number, Refusal.SUBJECT_ALREADY_OPEN, open_in)]

        if refusals != wanted:
            raise AssertionError(f"Expected the refusals published {wanted}, got {refusals}.")

        return True

    return assertion


def _no_earlier_attempt_was_read(already_taken: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if already_taken.called:
            raise AssertionError(
                f"Expected no earlier attempt read, got {already_taken.call_args_list}."
            )

        return True

    return assertion


def _this_walk_holds_the_claim(record_action: MagicMock) -> None:
    record_action.return_value = Claimed(action_id=THE_ACTION_THIS_WALK_CLAIMED)


def _noting_when_it_is_claimed(record_action: MagicMock, happened: list[str]) -> None:
    """This walk wins the claim, noting into `happened` when it was asked."""
    def claiming(*dont_care_args: object, **dont_care_keywords: object) -> Claimed:
        happened.append("claimed")

        return Claimed(action_id=THE_ACTION_THIS_WALK_CLAIMED)

    record_action.side_effect = claiming


def _a_plan_nobody_checks() -> MagicMock:
    """A plan for whatever action is asked, in a case about something else."""
    return _planning_answering(DONT_CARE_PLAN)


def _planning_answering(answer: Planned[Any] | Outcome | None,
                        happened: list[str] | None = None) -> MagicMock:
    """The write tier answering every action's plan with `answer` - a plan, an
    outcome for a plan it refused, or nothing for an action with no plan -
    noting into `happened`, where a case gives one, when it was asked."""
    def planning(dont_care_action: Action, /) -> Planned[Any] | Outcome | None:
        if happened is not None:
            happened.append("planned")

        return answer

    plan_action = cast(MagicMock, create_autospec(ports.PlanAction, instance=True))
    plan_action.side_effect = planning

    return plan_action


def _a_plan_refused_as(verdict: Verdict) -> Outcome:
    """What planning answers for a plan the write tier refused: the outcome the
    same refusal from the write was recorded as - nothing performed, nothing
    judged, nothing left behind."""
    return Outcome(verdict=verdict,
                   detail=f"did not scale [{SOME_APPLICATION}] out - {SOME_REFUSAL_AT_THE_PLAN}",
                   not_performed_because=SOME_REFUSAL_AT_THE_PLAN,
                   judged=False,
                   performed=False,
                   left_behind_known=True)


def _a_scale_out_of_three() -> ReplicaUndo:
    return ReplicaUndo(application=SOME_APPLICATION, was_replicas=3, replicas_asked_for=6,
                       was_syncing_itself=True)


def _the_claim_carries(planned: Planned[Any] | None,
                       record_action: MagicMock) -> Assertion[StateDelta]:
    """The claim was written carrying this plan, with the moment its state was
    read - or none, for an action with nothing to plan or a plan refused."""
    def assertion(dont_care_result: StateDelta) -> bool:
        carried = record_action.call_args.kwargs.get("planned")

        if carried != planned:
            raise AssertionError(
                f"Expected the claim to carry the plan [{planned}], it carried "
                f"[{carried}]."
            )

        return True

    return assertion


def _the_action_was_taken_on(plan: Planned[Any] | None,
                             take: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if not take.called:
            raise AssertionError(f"Expected the action taken on [{plan}], it was not taken.")

        # Said outright, `None` included: an action with no plan is handed none,
        # rather than left to a default nobody chose.
        if "plan" not in take.call_args.kwargs:
            raise AssertionError(
                f"Expected the action taken on the plan [{plan}], it was handed no plan "
                f"at all: {take.call_args}."
            )

        handed = take.call_args.kwargs["plan"]
        if handed != plan:
            raise AssertionError(
                f"Expected the action taken on the plan [{plan}], it was taken on "
                f"[{handed}]."
            )

        return True

    return assertion


def _an_earlier_attempt_holds_the_claim(
        record_action: MagicMock,
        already_taken: MagicMock,
        nothing_recorded: Verdict | UnreadVerdict | None,
        written_at: datetime = SOME_MOMENT_THE_CLAIM_WAS_WRITTEN,
        progress: ActionProgress = ActionProgress.CLAIMED,
        planned: Planned[Any] | None = None,
        undo_descriptor: UndoDescriptor | None = None,
        performed_at: datetime | None = None,
        put_back_because: str | None = None) -> None:
    """The claim was written by a worker that is gone.

    `nothing_recorded` is what it left against it - an outcome, or `None` where
    it stopped between taking the action and saying what happened. The moment
    comes back on the same value because it is the same row: the branch with no
    outcome to read is the one that asks the provider what happened after it.
    `progress` is how far the row says it got - a claim and nothing more,
    unless a case says otherwise - and `planned` the plan it was written with,
    none unless a case gives one. `undo_descriptor`, `performed_at` and
    `put_back_because` are what the row says of a change it was told was made
    and, where it got that far, owed back.
    """
    record_action.return_value = AlreadyClaimed()
    already_taken.return_value = ports.ClaimedAction(
        outcome=nothing_recorded, claimed_at=written_at, progress=progress,
        action_id=THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED, planned=planned,
        undo_descriptor=undo_descriptor, performed_at=performed_at,
        put_back_because=put_back_because)


def _the_walk_is_told_no_reason() -> Assertion[StateDelta]:
    """Told outright, rather than left unset: a field a node leaves unset keeps
    whatever an earlier node put there."""
    def assertion(updates: StateDelta) -> bool:
        told = updates.as_updates()

        if "action_because" not in told or told["action_because"] is not None:
            raise AssertionError(
                f"Expected the node to tell the walk there is no reason, it told it "
                f"[{told.get('action_because', 'nothing at all')}]."
            )

        return True

    return assertion


def _the_reason_reported_is(expected: str) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if updates.action_because != expected:
            raise AssertionError(
                f"Expected the node to report the reason [{expected}], "
                f"it reported [{updates.action_because}]."
            )

        return True

    return assertion


def _the_verdict_reported_is(expected: Verdict) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        reported = updates.action_outcome
        if reported != expected:
            raise AssertionError(
                f"Expected the verdict [{expected}], the node reported [{reported}]."
            )

        return True

    return assertion


def _the_walk_carries_the_moment_the_action_was_announced(
        published: list[IncidentEvent]) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        announced = [event.at for event in published if isinstance(event, ActionTaken)]

        if announced != [updates.acted_at]:
            raise AssertionError(
                f"Expected the walk to carry the moment its one action was announced, "
                f"{announced}, got [{updates.acted_at}].")

        return True

    return assertion


def _no_action_was_announced(published: list[IncidentEvent]) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        announced = [event for event in published if isinstance(event, ActionTaken)]
        if announced:
            raise AssertionError(f"Expected no action announced for an attempt that ended "
                                 f"before its write, got {announced}.")

        return True

    return assertion


def _the_walk_carries_no_moment_of_change() -> Assertion[StateDelta]:
    """Told outright, rather than left unset: a field a node leaves unset keeps
    whatever an earlier round put there, and a later round would be told this
    attempt was made at the moment the last one was."""
    def assertion(updates: StateDelta) -> bool:
        told = updates.as_updates()
        if "acted_at" not in told or told["acted_at"] is not None:
            raise AssertionError(f"Expected the walk told no change was made, it was told "
                                 f"[{told.get('acted_at', 'nothing at all')}].")

        return True

    return assertion


def _the_verdict_names_the_action_not_done(state: IncidentState,
                                           complete_action: MagicMock
                                           ) -> Assertion[StateDelta]:
    return _the_verdict_names(state, complete_action, performed=False)


def _the_verdict_names_the_action_done(state: IncidentState,
                                       complete_action: MagicMock) -> Assertion[StateDelta]:
    return _the_verdict_names(state, complete_action, performed=True)


def _the_verdict_names(state: IncidentState,
                       complete_action: MagicMock,
                       performed: bool) -> Assertion[StateDelta]:
    """The verdict's line names the action it was reached about, and whether it
    was done - for an attempt that ended before its write, the only line that
    says what was reached for."""
    def assertion(dont_care_result: StateDelta) -> bool:
        assert state.proposed_action is not None
        narrating = _the_completion(complete_action)["narrating"]
        said = (narrating.action_type, narrating.subject, narrating.performed)
        wanted = (state.proposed_action.action_type,
                  the_subject_of(state.proposed_action), performed)
        if said != wanted:
            raise AssertionError(f"Expected the verdict to name {wanted}, it named {said}.")

        return True

    return assertion


def _the_verdict_says_it_was_judged(expected: bool,
                                      complete_action: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        said = _the_completion(complete_action)["narrating"].judged
        if said is not expected:
            raise AssertionError(f"Expected the verdict to say judged is {expected}, "
                                 f"it said {said}.")

        return True

    return assertion


def _the_walk_carries(expected: datetime) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        if updates.acted_at != expected:
            raise AssertionError(
                f"Expected the walk to carry the moment the action was taken, "
                f"[{expected}], got [{updates.acted_at}].")

        return True

    return assertion


def _the_incident_was_escalated() -> Assertion[StateDelta]:
    """Nothing was measured and nothing can be: the node reports the verdict
    that says so - escalated - with the sentence it says as the reason, which
    `status_after` derives the status from."""
    def assertion(updates: StateDelta) -> bool:
        told = updates.as_updates()
        said = updates.narration.said() if updates.narration is not None else None

        if told.get("action_outcome") is not Verdict.ESCALATED:
            raise AssertionError(
                f"Expected the node to report the verdict [{Verdict.ESCALATED}], it "
                f"reported [{told.get('action_outcome', 'nothing at all')}]."
            )

        if told.get("action_because") != said:
            raise AssertionError(
                f"Expected the node to report the reason it says, [{said}], it reported "
                f"[{told.get('action_because', 'nothing at all')}]."
            )

        return True

    return assertion


def _an_advance_nobody_checks() -> MagicMock:
    """Somewhere for the claim to be moved on, in a case about something else."""
    return cast(MagicMock, create_autospec(ports.AdvanceAction, instance=True))


def _the_claim_cannot_be_written(advance_action: MagicMock) -> None:
    advance_action.side_effect = RuntimeError("the database went away")


def _the_claim_is_refused_for_a_lost_run(advance_action: MagicMock) -> None:
    advance_action.side_effect = RunLost(A_NEWER_CLAIM_HOLDS_THE_RUN)


def _an_agent_whose_answer_was_lost() -> MagicMock:
    """An agent whose write the tier was asked for and never answered, and that
    the transport could not ask again for an answer."""
    take = cast(MagicMock, create_autospec(ports.TakeAction, instance=True))
    take.side_effect = LostAfterSending(DONT_CARE_WHAT_THE_TRANSPORT_SAID)

    return take


def _no_verdict_was_written(complete_action: MagicMock,
                            record_outcome: MagicMock) -> Assertion[StateDelta]:
    """Neither the claim's verdict nor the candidate's: nothing was judged, and
    nothing is known to have been done."""
    def assertion(dont_care_result: StateDelta) -> bool:
        written = {"the claim's verdict": complete_action.call_args_list,
                   "the candidate's outcome": record_outcome.call_args_list}
        written = {what: calls for what, calls in written.items() if calls}

        if written:
            raise AssertionError(f"Expected no verdict written, and it was: {written}")

        return True

    return assertion


def _no_action_row_was_completed(complete_action: MagicMock) -> Assertion[Exception | None]:
    def assertion(dont_care_error: Exception | None) -> bool:
        if complete_action.called:
            raise AssertionError(
                f"Expected no action row completed for a lost run, one was completed with "
                f"{complete_action.call_args}."
            )

        return True

    return assertion


def _an_agent_that_tells_of_the_change(undo_descriptor: UndoDescriptor,
                                       verdict: Verdict) -> ports.TakeAction:
    """An agent that makes the change, says so with what would put it back,
    and then reaches `verdict` - as the real one does, in that order."""
    def take(dont_care_action: Action, /, *, change_made: ChangeMade = lambda _: None,
             **dont_care_keywords: object) -> Outcome:
        change_made(undo_descriptor)

        return Outcome(verdict=verdict, detail="dont care", undo_descriptor=undo_descriptor,
                       left_behind_known=True)

    return cast(ports.TakeAction, take)


def _the_walk_says(expected: str) -> Assertion[StateDelta]:
    """What a person reading the incident is told about the attempt."""
    def assertion(updates: StateDelta) -> bool:
        said = updates.narration.detail if updates.narration is not None else None
        if said != expected:
            raise AssertionError(f"Expected the walk to say [{expected}], it said [{said}].")

        return True

    return assertion


def _the_claim_was_advanced_to(expected: ActionProgress,
                               state: IncidentState,
                               advance_action: MagicMock,
                               undo_descriptor: UndoDescriptor | None = None,
                               performed_at: datetime | None = None
                               ) -> Assertion[StateDelta]:
    """The claim on this incident's candidate moved on once, to `expected`,
    carrying `undo_descriptor` - and made at `performed_at`, where a case is
    about the moment; a case that is not compares everything else."""
    def assertion(dont_care_result: StateDelta) -> bool:
        assert state.hypothesis is not None
        made = [(call.args,
                 {name: value for name, value in call.kwargs.items()
                  if performed_at is not None or name != "performed_at"})
                for call in advance_action.call_args_list]
        wanted_keywords: dict[str, object] = {"hypothesis_id": state.hypothesis.id,
                                              "to": expected,
                                              "undo_descriptor": undo_descriptor}
        if performed_at is not None:
            wanted_keywords["performed_at"] = performed_at
        wanted = [((state.incident_id,), wanted_keywords)]
        if made != wanted:
            raise AssertionError(f"Expected the claim moved on once, to [{expected}] "
                                 f"carrying [{undo_descriptor}], got {made}.")

        return True

    return assertion


def _the_claim_was_not_advanced(advance_action: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if advance_action.called:
            raise AssertionError(f"Expected the claim left as it was, it was moved on: "
                                 f"{advance_action.call_args_list}.")

        return True

    return assertion


def _the_action_row_records_whether_it_was_performed(expected: bool,
                                                     complete_action: MagicMock
                                                     ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        recorded = _the_completion(complete_action)["performed"]
        if recorded is not expected:
            raise AssertionError(
                f"Expected the action row to record performed as {expected}, it "
                f"recorded {recorded}."
            )

        return True

    return assertion


def _the_action_row_records_whether_what_it_left_is_known(expected: bool,
                                                         complete_action: MagicMock
                                                         ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        recorded = _the_completion(complete_action)["left_behind_known"]
        if recorded is not expected:
            raise AssertionError(
                f"Expected the action row to record what the attempt left behind as "
                f"{'known' if expected else 'not known'}, it recorded "
                f"left_behind_known={recorded}."
            )

        return True

    return assertion


def _the_action_row_records_the_way_back(expected: UndoDescriptor | None,
                                         complete_action: MagicMock
                                         ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        recorded = _the_completion(complete_action)["undo_descriptor"]
        if recorded != expected:
            raise AssertionError(
                f"Expected the action row to record {expected}, it recorded "
                f"{recorded}."
            )

        return True

    return assertion


def _the_action_row_records_the_outcome(expected: str,
                                        complete_action: MagicMock
                                        ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        recorded = _the_completion(complete_action)["outcome"]
        if recorded != expected:
            raise AssertionError(
                f"Expected the action row to record [{expected}], it recorded "
                f"[{recorded}]."
            )

        return True

    return assertion


def _the_candidate_was_left_untested_because(candidate: Hypothesis,
                                             reason: str,
                                             record_outcome: MagicMock
                                             ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        recorded = [(call.args[0], call.kwargs) for call in record_outcome.call_args_list]
        expected = [(candidate.id, {"tested": False, "result": reason})]

        if recorded != expected:
            raise AssertionError(
                f"Expected the candidate recorded once as untested because [{reason}], "
                f"it was recorded as {recorded}."
            )

        return True

    return assertion


def _the_verdict_s_line_says_why_it_was_not_performed(reason: str,
                                                      complete_action: MagicMock
                                                      ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        said = _the_completion(complete_action)["narrating"].not_performed_because

        if said != reason:
            raise AssertionError(
                f"Expected the verdict's line to say it was not performed because "
                f"[{reason}], it said [{said}]."
            )

        return True

    return assertion


def _putting_it_back_was_kept_as(expected: Undone,
                                 said: str,
                                 complete_action: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        kept = _the_completion(complete_action)
        narrating = kept["narrating"]
        found = (kept["undone"], narrating.undone, narrating.undone_detail)

        if found != (expected, expected, said):
            raise AssertionError(
                f"Expected the row and the line to keep the undo as [{expected}] "
                f"saying [{said}], got row [{found[0]}] and line [{found[1]}] "
                f"saying [{found[2]}]."
            )

        return True

    return assertion


def _the_candidate_learned_nothing(record_outcome: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if record_outcome.call_count != 0:
            raise AssertionError(
                f"Expected the candidate to be left untouched, it was recorded "
                f"as {record_outcome.call_args_list}."
            )

        return True

    return assertion


def _the_candidate_was_tested_and_settled(candidate: Hypothesis,
                                          verdict: str,
                                          record_outcome: MagicMock
                                          ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        recorded_about = record_outcome.call_args.args[0]
        if recorded_about != candidate.id:
            raise AssertionError(
                f"Expected the outcome to be about [{candidate.id}], it was "
                f"about [{recorded_about}]."
            )

        recorded = record_outcome.call_args.kwargs
        if recorded["tested"] is not True:
            raise AssertionError(
                "Expected the candidate to be recorded as having been tested."
            )

        if recorded["result"] != verdict:
            raise AssertionError(
                f"Expected the candidate to record [{verdict}], it recorded "
                f"[{recorded['result']}]."
            )

        return True

    return assertion


def _the_action_was_taken(take: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if not take.called:
            raise AssertionError("Expected the action to be taken, it was not.")

        return True

    return assertion


def _the_action_was_not_taken(take: MagicMock) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if take.called:
            raise AssertionError(
                f"Expected the action not to be taken, it was taken with "
                f"{take.call_args}."
            )

        return True

    return assertion


def _the_completion(complete_action: MagicMock) -> dict[str, Any]:
    """What the action row was completed with - a failed expectation, rather than
    an `AttributeError` that stops every assertion after it, where it never
    was."""
    if complete_action.call_args is None:
        raise AssertionError("Expected the action row to be completed, it never was.")

    return dict(complete_action.call_args.kwargs)


def _nothing_was_completed(complete_action: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if complete_action.called:
            raise AssertionError(
                f"Expected no action row to be completed, one was completed with "
                f"{complete_action.call_args}."
            )

        return True

    return assertion


def _no_earlier_outcome_was_looked_up(already_taken: MagicMock
                                      ) -> Assertion[StateDelta]:
    """A walk holding the claim has no earlier attempt to ask about, and asking
    anyway would mean the guard was reading state it had already ruled out."""
    def assertion(dont_care_result: StateDelta) -> bool:
        if already_taken.called:
            raise AssertionError(
                "Expected no earlier outcome to be looked up, one was."
            )

        return True

    return assertion


def _the_subject_recorded_is(service: str,
                             record_action: MagicMock,
                             published: list[IncidentEvent]
                             ) -> Assertion[StateDelta]:
    """The row and the announcement both name what the action acted on.

    Both, because they are read by different people and drift apart quietly:
    the row is what the attempt cap counts and what the write-up quotes, and
    the event is what a reader watching the incident sees happen.
    """
    def assertion(dont_care_result: StateDelta) -> bool:
        claimed = record_action.call_args.kwargs["subject"]
        if claimed != service:
            raise AssertionError(
                f"Expected the claim to record [{service}], got [{claimed}]."
            )

        announced = [event for event in published if isinstance(event, ActionTaken)]
        if [event.subject for event in announced] != [service]:
            raise AssertionError(
                f"Expected one action announced against [{service}], got "
                f"{[event.subject for event in announced]}."
            )

        return True

    return assertion


def _the_claim_is_dated_before_the_announcement(record_action: MagicMock,
                                                published: list[IncidentEvent]
                                                ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        claimed = record_action.call_args.kwargs["at"]
        announced = [event.at for event in published if isinstance(event, ActionTaken)]

        if claimed != SOME_MOMENT_THE_CLAIM_WAS_WRITTEN or len(announced) != 1 \
                or not announced[0] > claimed:
            raise AssertionError(
                f"Expected the claim dated [{SOME_MOMENT_THE_CLAIM_WAS_WRITTEN}] by the "
                f"walk's clock and the one action announced after it, got the claim at "
                f"[{claimed}] and announcements at {announced}."
            )

        return True

    return assertion


def _a_listener() -> Publisher:
    """A subscriber that does nothing with what it hears. What matters is that
    somebody is listening, not what they make of it."""
    published: list[IncidentEvent] = []

    return published.append


def _exactly_one_action_was_announced(candidate: Hypothesis,
                                      action: Action,
                                      published: list[IncidentEvent]
                                      ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        taken = [event for event in published if isinstance(event, ActionTaken)]
        if len(taken) != 1:
            raise AssertionError(f"Expected one action announced, got {len(taken)}.")

        announced = taken[0]
        if (announced.hypothesis_id, announced.action_type) != (candidate.id,
                                                                action.action_type):
            raise AssertionError(
                f"Expected [{action.action_type}] for candidate [{candidate.id}], "
                f"got [{announced.action_type}] for [{announced.hypothesis_id}]."
            )

        return True

    return assertion


def _the_action_announced_was_for_candidate(number: int,
                                            published: list[IncidentEvent]
                                            ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        said = [event.candidate_number for event in published
                if isinstance(event, ActionTaken)]
        if said != [number]:
            raise AssertionError(
                f"Expected the action announced for candidate {number}, and it was "
                f"announced for {said}."
            )

        return True

    return assertion


def _the_verdict_was_for_candidate(number: int,
                                   complete_action: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        said = _the_completion(complete_action)["narrating"].candidate_number
        if said != number:
            raise AssertionError(
                f"Expected the verdict's line to be for candidate {number}, and it was "
                f"for {said}."
            )

        return True

    return assertion


def _the_announced_action_moved_the_flag(expected: bool,
                                         published: list[IncidentEvent]
                                         ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        moved_to = [event.enabled for event in published
                    if isinstance(event, ActionTaken)]
        if moved_to != [expected]:
            raise AssertionError(
                f"Expected the flag to be announced as [{expected}], got {moved_to}."
            )

        return True

    return assertion


def _the_announced_action_held_it_to(expected: str,
                                     published: list[IncidentEvent]
                                     ) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        held_to = [event.accelerator for event in published
                   if isinstance(event, ActionTaken)]
        if held_to != [expected]:
            raise AssertionError(
                f"Expected one action announced as holding the deployment to "
                f"[{expected}], got {held_to}."
            )

        return True

    return assertion


def _the_verdict_was_narrated(expected: str,
                              complete_action: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        narrating = _the_completion(complete_action)["narrating"]
        if not isinstance(narrating, VerdictReached):
            raise AssertionError(
                f"Expected the verdict to be narrated as one, it was narrated as "
                f"[{type(narrating).__name__}]."
            )

        if narrating.outcome != expected:
            raise AssertionError(
                f"Expected the narration to report [{expected}], it reported "
                f"[{narrating.outcome}]."
            )

        return True

    return assertion


def _both_runs_did_the_same_work() -> Assertion[tuple[StateDelta, StateDelta]]:
    def assertion(runs: tuple[StateDelta, StateDelta]) -> bool:
        listened_to, unheard = runs
        if listened_to != unheard:
            raise AssertionError(
                f"Expected the same work with nobody listening, got {unheard} "
                f"instead of {listened_to}."
            )

        return True

    return assertion


def _the_resumption_published_was(candidate: Hypothesis,
                                  outcome: Verdict,
                                  published: list[IncidentEvent]) -> Assertion[StateDelta]:
    """The gap in the account, filled by the walk that found it.

    The verdict itself was published by the walk that reached it, in the same
    transaction that recorded it - so this is not the verdict being announced
    twice. It is the only account of a walk having stopped and another having
    picked the incident up, which is otherwise a story that jumps from a taken
    action to a conclusion with nothing in between.
    """
    def assertion(dont_care_updates: StateDelta) -> bool:
        resumptions = [event for event in published
                       if isinstance(event, MitigationResumed)]

        if not resumptions:
            raise AssertionError(
                f"Expected the resumption to be published, got "
                f"{[event.kind for event in published]}."
            )

        said = resumptions[0]
        if (said.hypothesis_id, said.outcome) != (candidate.id, outcome):
            raise AssertionError(
                f"Expected [{candidate.id}] read back as [{outcome}], got "
                f"[{said.hypothesis_id}] as [{said.outcome}]."
            )

        return True

    return assertion


def _the_action_was_announced_as_a_dependency_of(expected: str | None,
                                                 published: list[IncidentEvent]
                                                 ) -> Assertion[StateDelta]:
    """Whose dependency the thing acted on was, as the announcement carries it.

    `None` is the ordinary incident and is asserted as firmly as a name: a
    clause said of every restart distinguishes nothing, and the line a
    responder reads under pressure would carry a sentence explaining the
    unremarkable.
    """
    def assertion(dont_care_result: StateDelta) -> bool:
        announced = [event.a_dependency_of for event in published
                     if isinstance(event, ActionTaken)]

        if announced != [expected]:
            raise AssertionError(
                f"Expected one action announced as a dependency of [{expected}], "
                f"got {announced}."
            )

        return True

    return assertion


def _a_rollback_action() -> RollBackDeployment:
    """An action on the deployment platform, for the cases about which platform.

    A rollback rather than the flag revert every other case here uses, because
    that is the whole subject: the platform recorded has to be the one this
    action acts through, and a suite that only ever attempted flag reverts would
    pass with the platform hardcoded.
    """
    return RollBackDeployment(application="dont-care-application")


def _the_platforms_recorded_as_unreachable(
    expected: list[str]
) -> Assertion[StateDelta]:
    def assertion(updates: StateDelta) -> bool:
        recorded = updates.unreachable_platforms

        if recorded != expected:
            raise AssertionError(
                f"Expected the walk to carry {expected} as unreachable, it "
                f"carries {recorded}."
            )

        return True

    return assertion


def _nothing_was_recorded_as_unreachable() -> Assertion[StateDelta]:
    """The node said nothing about any platform, rather than said it was empty.

    `model_fields_set` is the distinction, and it is the one that matters here for
    the reason the field's own comment gives: a node that did not mention a field
    must not overwrite what another node decided. An outcome that wrote an empty
    list would clear a platform an earlier attempt had already found unreachable,
    and the walk would go back to trying candidates it had passed over.
    """
    def assertion(updates: StateDelta) -> bool:
        if "unreachable_platforms" in updates.model_fields_set:
            raise AssertionError(
                f"Expected the node to say nothing about unreachable platforms, "
                f"it set {updates.unreachable_platforms}."
            )

        return True

    return assertion


def _the_platform_published_as_unavailable(
    published: list[IncidentEvent]
) -> PlatformUnavailable | None:
    """The one event about a platform, if exactly one was published.

    `None` where none was, and an assertion failure where more than one was:
    "at least one" is not the claim - the fact is about the platform, and
    repeating it per candidate teaches a reader to skim the sentence that
    explains the outcome.
    """
    about_a_platform = [
        event for event in published
        if isinstance(event, PlatformUnavailable)
    ]

    if len(about_a_platform) > 1:
        raise AssertionError(
            f"Expected one event about the platform, {len(about_a_platform)} "
            f"were published."
        )

    return about_a_platform[0] if about_a_platform else None


def _the_platform_was_published_as_unavailable(
    platform: str, took_away: Sequence[str], published: list[IncidentEvent]
) -> Assertion[StateDelta]:
    def assertion(dont_care_updates: StateDelta) -> bool:
        said = _the_platform_published_as_unavailable(published)

        if said is None:
            raise AssertionError(
                f"Expected [{platform}] published as unavailable, and nothing "
                f"about any platform was published."
            )

        if (said.platform, list(said.actions_unavailable)) != (
            platform, list(took_away)
        ):
            raise AssertionError(
                f"Expected [{platform}] published as having taken away "
                f"{list(took_away)}, and what was published was "
                f"[{said.platform}] taking away {list(said.actions_unavailable)}."
            )

        return True

    return assertion


def _no_platform_was_published_as_unavailable(
    published: list[IncidentEvent]
) -> Assertion[StateDelta]:
    def assertion(dont_care_updates: StateDelta) -> bool:
        said = _the_platform_published_as_unavailable(published)

        if said is not None:
            raise AssertionError(
                f"Expected nothing published about a platform, and {said} was."
            )

        return True

    return assertion


@pytest.mark.unit
def test_the_change_made_is_put_on_the_claim_with_the_walk_s_clock_before_it_is_announced(
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The row says when the change was made, on the clock the walk dates its
    # minutes by - read for the row, just before it is written; the
    # announcement keeps the reading it has always taken, after the row, so
    # the account a replay compares is dated as it was.
    some_way_back = FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True)
    readings = iter([SOME_MOMENT_THE_CLAIM_WAS_WRITTEN, SOME_MOMENT_IT_WAS_MADE,
                     SOME_MOMENT_IT_WAS_ANNOUNCED])

    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            take := _an_agent_that_tells_of_the_change(some_way_back, Verdict.CONFIRMED),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=lambda: next(readings))) \
        .then(all_of(
            _the_claim_was_advanced_to(ActionProgress.PERFORMED, an_action_taking_incident,
                                       advance_action, undo_descriptor=some_way_back,
                                       performed_at=SOME_MOMENT_IT_WAS_MADE),
            _the_walk_carries(SOME_MOMENT_IT_WAS_ANNOUNCED)
        ))


@pytest.mark.unit
def test_a_change_owed_back_is_put_on_the_claim_with_what_the_watch_found(
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    owe_a_put_back: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # Before the put-back, on the row this walk claimed: a worker that dies
    # putting it back leaves a claim saying the change is owed back and why.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            take := _an_agent_that_owes_a_put_back(FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True),
                                                   SOME_FINDING),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=owe_a_put_back,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(
            _the_put_back_was_owed_on_the_claim(an_action_taking_incident, owe_a_put_back,
                                                SOME_FINDING)
        )


@pytest.mark.unit
def test_a_put_back_that_could_not_be_put_on_the_claim_as_owed_does_not_stop_the_attempt(
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    owe_a_put_back: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock,
    caplog: pytest.LogCaptureFixture
) -> None:
    # The change made being recorded early is the reasoning here too: the
    # put-back is what the refutation is owed, and the completion writes the
    # verdict whatever the early copy did. Abandoning the attempt over it
    # would leave a refuted change standing.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.WARNING)),
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_put_back_cannot_be_owed(owe_a_put_back)),
            take := _an_agent_that_owes_a_put_back(FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True),
                                                   SOME_FINDING),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=owe_a_put_back,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_verdict_reported_is(Verdict.REFUTED),
            _the_action_row_records_the_outcome(Verdict.REFUTED, complete_action),
            one_record_was_logged(caplog, "orchestrator.walk.mitigating", logging.WARNING,
                                  "the put-back could not be recorded as owed before it was "
                                  "attempted")
        ))


@pytest.mark.unit
def test_a_put_back_that_could_not_be_put_on_the_claim_of_a_lost_run_stops_the_attempt(
    record_action: MagicMock,
    complete_action: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    owe_a_put_back: MagicMock,
    record_outcome: MagicMock,
    still_wanted: MagicMock
) -> None:
    # The run is another claim's now: the put-back is that walk's to make or
    # not, and a completion from here would be refused for the same reason.
    Scenario() \
        .given(
            calling(lambda: _this_walk_holds_the_claim(record_action)),
            calling(lambda: _the_put_back_is_refused_for_a_lost_run(owe_a_put_back)),
            take := _an_agent_that_owes_a_put_back(FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True),
                                                   SOME_FINDING),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(attempting(lambda: mitigation_node(an_action_taking_incident,
                                                 take=take,
                                                 plan_action=_a_plan_nobody_checks(),
                                                 resuming=_resuming_nobody_checks(),
                                                 advance_action=_an_advance_nobody_checks(),
                                                 owe_a_put_back=owe_a_put_back,
                                                 record_action=record_action,
                                                 complete_action=complete_action,
                                                 record_outcome=record_outcome,
                                                 already_taken=already_taken,
                                                 acting_for=acting_for,
                                                 still_wanted=still_wanted))) \
        .then(all_of(
            an_error_was_raised(RunLost),
            _no_action_row_was_completed(complete_action)
        ))


def _an_owing_nobody_checks() -> MagicMock:
    """Somewhere for a put-back to be owed, in a case about something else."""
    return cast(MagicMock, create_autospec(ports.OweAPutBack, instance=True))


def _the_put_back_cannot_be_owed(owe_a_put_back: MagicMock) -> None:
    owe_a_put_back.side_effect = RuntimeError("the database went away")


def _the_put_back_is_refused_for_a_lost_run(owe_a_put_back: MagicMock) -> None:
    owe_a_put_back.side_effect = RunLost(A_NEWER_CLAIM_HOLDS_THE_RUN)


def _an_agent_that_owes_a_put_back(undo_descriptor: UndoDescriptor,
                                   because: str) -> ports.TakeAction:
    """An agent that makes the change, says so, finds against it, says it is
    owed back with what it found, and puts it back - as the real one does, in
    that order."""
    def take(dont_care_action: Action, /, *,
             change_made: ChangeMade = lambda _: None,
             put_back_owed: PutBackOwed = lambda _: None,
             **dont_care_keywords: object) -> Outcome:
        change_made(undo_descriptor)
        put_back_owed(because)

        return Outcome(verdict=Verdict.REFUTED, detail="dont care", because=because,
                       undo_descriptor=undo_descriptor, undone=Undone.RESTORED,
                       left_behind_known=True)

    return cast(ports.TakeAction, take)


def _the_put_back_was_owed_on_the_claim(state: IncidentState,
                                        owe_a_put_back: MagicMock,
                                        because: str) -> Assertion[StateDelta]:
    """The claim on this incident's candidate was told once that its change is
    owed back, because of `because`."""
    def assertion(dont_care_result: StateDelta) -> bool:
        assert state.hypothesis is not None
        made = [(call.args, call.kwargs) for call in owe_a_put_back.call_args_list]
        wanted = [((state.incident_id,), {"hypothesis_id": state.hypothesis.id,
                                           "because": because})]
        if made != wanted:
            raise AssertionError(f"Expected the claim told once its change is owed back "
                                 f"because [{because}], got {made}.")

        return True

    return assertion


# ---------------------------------------------------------------------------
# A resumed walk: what it reads, and what it carries on with
# ---------------------------------------------------------------------------

# How far back the metrics are kept (`metrics_window_minutes`), for a resumed
# walk asking whether they still reach back to when the incident began. The
# configured default, though only its relation to the onsets below matters.
THE_METRICS_KEPT = timedelta(minutes=360)
# The resumed walk's clock, in the cases about where the incident began.
SOME_NOW = datetime(2026, 9, 5, 3, 0, tzinfo=UTC)
# An incident that began well inside what the metrics keep.
SOME_RECENT_ONSET = SOME_NOW - THE_METRICS_KEPT / 2
# The way back an earlier attempt's row kept for its change: the one the flag
# revert below (`_an_action_with_an_undo_descriptor`) makes.
THE_WAY_BACK_THE_ROW_KEPT = FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True)
# The plan that row was claimed with, which the estate is read from.
THE_PLAN_THE_ROW_KEPT = Planned(descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                                since=SOME_MOMENT_THE_PLAN_WAS_READ)
# The words that flag revert's kind says its change in - it turns the flag OFF.
WHAT_THE_REVERT_SAID = f"set flag [{DONT_CARE_FLAG}] OFF"
# When an earlier attempt's change was made, as the estate dates it.
SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE = SOME_MOMENT_THE_CLAIM_WAS_WRITTEN + timedelta(
    seconds=3)
# What a write-tier read found, in its words.
SOME_FINDING_ON_THE_ESTATE = "flag [dont-care-flag] was changed by [kuki] since Argus set it"

# How a resumed walk hands an incident over, in the words a person reads.
THE_METRICS_NO_LONGER_REACH_BACK = (
    "the metrics kept no longer reach back to when the incident began, so whether "
    "the change helped cannot be judged"
)
CHANGED_SINCE_IT_WAS_MADE = (
    "an earlier attempt carried out this action, and it has been changed since"
)
NOBODY_CAN_SAY_IT_STILL_STANDS = (
    "an earlier attempt carried out this action, and nothing can say whether it "
    "still stands as it was left"
)


def _resuming_nobody_checks() -> ports.Resuming:
    """What a resumed walk reads and carries on with, in a case about something
    else: nothing of a claim landed, a change told as made is still Argus's,
    nothing is on file, and the watch and the put-back answer as they would."""
    whether_made = cast(MagicMock, create_autospec(ports.WhetherItWasMade, instance=True))
    whether_made.return_value = NotMade(left_behind=None)
    still_argus_s = cast(MagicMock, create_autospec(ports.StillArgusS, instance=True))
    still_argus_s.return_value = ChangeFound(still_argus_s=True)
    watch = cast(MagicMock, create_autospec(ports.WatchWhatWasPerformed, instance=True))
    watch.return_value = _an_outcome(Verdict.CONFIRMED)
    settle = cast(MagicMock, create_autospec(ports.SettleTheRefutation, instance=True))
    settle.return_value = _an_outcome(Verdict.REFUTED)
    announced = cast(MagicMock, create_autospec(ports.ActionAnnounced, instance=True))
    announced.return_value = False
    plan_the_claim = cast(MagicMock, create_autospec(ports.PlanTheClaim, instance=True))

    return ports.Resuming(whether_it_was_made=whether_made, still_argus_s=still_argus_s,
                          watch=watch, settle=settle, announced=announced,
                          plan_the_claim=plan_the_claim, metrics_window=THE_METRICS_KEPT)


def _an_outcome(verdict: Verdict,
                undo_descriptor: UndoDescriptor | None = THE_WAY_BACK_THE_ROW_KEPT,
                undone: Undone | None = None) -> Outcome:
    return Outcome(verdict=verdict, detail="dont care", undo_descriptor=undo_descriptor,
                   left_behind_known=True, undone=undone)


def _mocked(port: object) -> MagicMock:
    return cast(MagicMock, port)


def _nothing_of_it_landed(resuming: ports.Resuming,
                          left_behind: UndoDescriptor | None = None) -> None:
    """The claim's change not made - carrying `left_behind`, what of the claim's
    is out there all the same, where a case names it."""
    _mocked(resuming.whether_it_was_made).return_value = NotMade(left_behind=left_behind)


def _it_was_found_made(resuming: ports.Resuming, made: Made[Any]) -> None:
    _mocked(resuming.whether_it_was_made).return_value = made


def _the_read_answered(resuming: ports.Resuming, answer: Outcome | NobodyCanSay) -> None:
    _mocked(resuming.whether_it_was_made).return_value = answer


def _it_was_found(resuming: ports.Resuming, found: ChangeFound) -> None:
    _mocked(resuming.still_argus_s).return_value = found


def _an_announcement_is_on_file(resuming: ports.Resuming) -> None:
    _mocked(resuming.announced).return_value = True


def _the_watch_came_back(resuming: ports.Resuming, outcome: Outcome) -> None:
    _mocked(resuming.watch).return_value = outcome


def _the_put_back_came_back(resuming: ports.Resuming, outcome: Outcome) -> None:
    _mocked(resuming.settle).return_value = outcome


def _noting_each_step_of(resuming: ports.Resuming, happened: list[str]) -> None:
    """Each read and step of the resumption noting into `happened` when it was
    asked, answering as the case set it."""
    for name, said in (("whether_it_was_made", "read whether made"),
                       ("still_argus_s", "checked"),
                       ("watch", "watched"),
                       ("settle", "put back")):
        port = _mocked(getattr(resuming, name))
        answer = port.return_value

        def answering(*dont_care_args: object, _said: str = said, _answer: object = answer,
                      **dont_care_keywords: object) -> object:
            happened.append(_said)

            return _answer

        port.side_effect = answering


def _a_minute(instant: datetime) -> str:
    """`instant` as the investigation states a minute."""
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


def _a_resumed_incident(began: datetime = SOME_RECENT_ONSET,
                        proposing: Action | None = None,
                        about: Hypothesis | None = None,
                        listing: list[ServiceDependency] | None = None) -> IncidentState:
    """A mitigating incident the investigation dated from `began` - about
    `about` and with the register `listing` where a case gives them, as
    `_a_mitigating_incident` takes them."""
    state = _a_mitigating_incident(proposing=proposing or _an_action_with_an_undo_descriptor(),
                                   about=about, listing=listing)

    return state.model_copy(update={"onset": EstablishedOnset(
        minute=_a_minute(began), how_known=HowTheMinuteIsKnown.MEASURED
    )})


def _a_resumed_incident_paged_by(rule: str) -> IncidentState:
    """A resumed incident whose alert, about a series, names the rule that fired."""
    state = _a_resumed_incident()

    return state.model_copy(update={"alert": state.alert.model_copy(
        update={"rule": rule, "claim": AlarmClaim.A_SERIES_CONDITION})})


def _the_clock_at(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


def _a_plan_of(action: Action) -> Planned[Any]:
    """A plan of the change `action` makes, read before its claim."""
    match action:
        case RevertFeatureFlag():
            descriptor: UndoDescriptor = FlagUndo(flag=action.flag,
                                                  was_enabled=not action.enabled)
        case RollBackDeployment():
            descriptor = DeploymentRollbackUndo(
                application=action.application, was_on_history_id=7, was_on_revision="b2",
                rolled_back_to_revision="a1", rolled_back_to_history_id=6,
                was_syncing_itself=True)
        case ScaleOut():
            descriptor = ReplicaUndo(application=action.application, was_replicas=3,
                                     replicas_asked_for=6, was_syncing_itself=True)
        case PinAutoscaler():
            descriptor = AutoscalerUndo(application=action.application, was_min_replicas=2,
                                        min_replicas_asked_for=8, was_syncing_itself=True)
        case PinToAccelerator():
            descriptor = AcceleratorPinUndo(application=action.application,
                                            was_pinned_to=None, pinned_to=action.accelerator,
                                            was_syncing_itself=True)
        case _:
            raise AssertionError(f"Expected an action that plans, got [{action}].")

    return Planned(descriptor=descriptor, since=SOME_MOMENT_THE_PLAN_WAS_READ)


def _it_was_asked_whether_made_on(action: Action,
                                  plan: Planned[Any],
                                  resuming: ports.Resuming) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        asked = [call.args for call in _mocked(resuming.whether_it_was_made).call_args_list]

        if asked != [(action, plan)]:
            raise AssertionError(
                f"Expected the estate asked once whether [{action}] was made on the plan "
                f"[{plan}], got {asked}."
            )

        return True

    return assertion


def _the_change_was_watched_as(action: Action,
                               performed: Performed,
                               resuming: ports.Resuming) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        watched = [call.args for call in _mocked(resuming.watch).call_args_list]

        if watched != [(action, performed)]:
            raise AssertionError(
                f"Expected [{action}] watched once as [{performed}], got {watched}."
            )

        return True

    return assertion


def _it_was_not_watched(resuming: ports.Resuming) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if _mocked(resuming.watch).called:
            raise AssertionError(
                f"Expected nothing watched, got {_mocked(resuming.watch).call_args_list}."
            )

        return True

    return assertion


def _it_was_put_back_as(action: Action,
                        performed: Performed,
                        because: str,
                        resuming: ports.Resuming) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        settled = [call.args for call in _mocked(resuming.settle).call_args_list]
        wanted = [(action.action_type, performed, because)]

        if settled != wanted:
            raise AssertionError(f"Expected the refutation settled as {wanted}, got {settled}.")

        return True

    return assertion


def _it_was_checked_whether_still_argus_s(plan: Planned[Any] | None,
                                          descriptor: UndoDescriptor,
                                          resuming: ports.Resuming) -> Assertion[StateDelta]:
    """Asked of the change the row says was made, and of the plan it was made
    from - the estate's own records are read from the plan's moment, as the
    write read them."""
    def assertion(dont_care_result: StateDelta) -> bool:
        asked = [call.args for call in _mocked(resuming.still_argus_s).call_args_list]

        if asked != [(plan, descriptor)]:
            raise AssertionError(
                f"Expected the estate asked once whether [{descriptor}], made from the "
                f"plan [{plan}], is still Argus's, got {asked}."
            )

        return True

    return assertion


def _nothing_was_read_of_the_estate(resuming: ports.Resuming) -> Assertion[object]:
    """Neither asked whether the change was made or still stands, nor watched,
    nor put back: the row already says all a resumed walk can do with it."""
    def assertion(dont_care_result: object) -> bool:
        asked = {name: _mocked(getattr(resuming, name)).call_args_list
                 for name in ("whether_it_was_made", "still_argus_s", "watch", "settle")
                 if _mocked(getattr(resuming, name)).called}

        if asked:
            raise AssertionError(f"Expected nothing read of the estate or done, got {asked}.")

        return True

    return assertion


def _it_was_asked_whether_announced_for(state: IncidentState,
                                        resuming: ports.Resuming) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        assert state.hypothesis is not None
        asked = [(call.args, call.kwargs)
                 for call in _mocked(resuming.announced).call_args_list]
        flattened = [tuple(args) + tuple(keywords.values()) for args, keywords in asked]
        wanted = (state.incident_id, state.hypothesis.id)

        if flattened != [wanted]:
            raise AssertionError(
                f"Expected the account asked once whether {wanted} was announced, "
                f"got {flattened}."
            )

        return True

    return assertion


def _the_actions_announced_were_at(expected: list[datetime],
                                   published: list[IncidentEvent]) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        announced = [event.at for event in published if isinstance(event, ActionTaken)]

        if announced != expected:
            raise AssertionError(f"Expected actions announced at {expected}, got {announced}.")

        return True

    return assertion


def _the_put_back_was_never_owed(owe_a_put_back: MagicMock) -> Assertion[StateDelta]:
    def assertion(dont_care_result: StateDelta) -> bool:
        if owe_a_put_back.called:
            raise AssertionError(
                f"Expected no put-back owed, got {owe_a_put_back.call_args_list}."
            )

        return True

    return assertion


# ---------------------------------------------------------------------------
# A resumed walk: an outcome on file
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("progress", [ActionProgress.PERFORMED, ActionProgress.PUTTING_BACK],
                         ids=["made", "owed-back"])
def test_a_resumed_outcome_of_a_change_made_carries_when_it_was_made(
    progress: ActionProgress,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # The round that remembers the attempt is told when the change was made,
    # which the row keeps once a change is - not when it was claimed, which is
    # before the write, and before the agent was even called in. A row the
    # walk completed owing its put-back is a change made all the same.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, Verdict.REFUTED, progress=progress,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_walk_carries(SOME_MOMENT_IT_WAS_MADE))


@pytest.mark.unit
def test_a_resumed_outcome_of_a_change_made_at_no_recorded_moment_carries_when_it_was_claimed(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # Made, and the row cannot say when - a rollback found made while its
    # operation was still pending has no moment to give. The claim is the
    # nearest the row has: written just before the change.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, Verdict.REFUTED,
                written_at=SOME_MOMENT_THE_CLAIM_WAS_WRITTEN,
                progress=ActionProgress.PERFORMED,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT, performed_at=None)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_walk_carries(SOME_MOMENT_THE_CLAIM_WAS_WRITTEN))


@pytest.mark.unit
def test_a_resumed_outcome_of_a_change_never_made_carries_no_moment_of_change(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    still_wanted: MagicMock
) -> None:
    # As the live walk tells it: an action never performed is no attempt a
    # later round may be told was made at some moment.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, Verdict.NOT_ATTEMPTED,
                progress=ActionProgress.NOT_PERFORMED)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=_resuming_nobody_checks(),
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(_the_walk_carries_no_moment_of_change())


@pytest.mark.unit
def test_a_refutation_completed_owing_its_put_back_is_reported_as_the_outcome_on_file(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A person ended the incident between the refutation and the put-back, and
    # the walk recorded the refutation with nothing put back. That is an
    # outcome on file like any other: reported, and not put back here - the
    # withdrawal's unwinding is what puts it back.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, Verdict.REFUTED,
                progress=ActionProgress.PUTTING_BACK,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT, put_back_because=SOME_FINDING)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_verdict_reported_is(Verdict.REFUTED),
                     _the_action_was_not_taken(take),
                     _nothing_was_read_of_the_estate(resuming),
                     _nothing_was_completed(complete_action)))


# ---------------------------------------------------------------------------
# A resumed walk: a change owed back
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_change_owed_back_is_put_back_in_the_words_it_was_made_with(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The watch refuted the change and the worker died before putting it back.
    # It is put back - not watched again, not made again - for what the watch
    # found, and said in the words the walk that made it used.
    an_action = _an_action_with_an_undo_descriptor()

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PUTTING_BACK,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE, put_back_because=SOME_FINDING)),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_put_back_as(an_action,
                                Performed(said=WHAT_THE_REVERT_SAID,
                                          undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT),
                                SOME_FINDING, resuming),
            _it_was_not_watched(resuming),
            _the_action_was_not_taken(take)
        ))


@pytest.mark.unit
def test_a_change_owed_back_is_recorded_as_the_live_walk_records_its_put_back(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The row is completed with what the put-back did, the candidate is tested
    # and settled, and the verdict reported - the same three things the walk
    # that died would have done.
    some_candidate = _a_candidate_blaming(SOME_FLAG_THE_CANDIDATE_BLAMES)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PUTTING_BACK,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT, put_back_because=SOME_FINDING)),
            calling(lambda: _the_put_back_came_back(
                resuming, _an_outcome(Verdict.REFUTED, undone=Undone.RESTORED))),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor(), about=some_candidate
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(
            _the_action_row_records_the_outcome(Verdict.REFUTED, complete_action),
            _the_action_row_records_the_way_back(THE_WAY_BACK_THE_ROW_KEPT, complete_action),
            _the_candidate_was_tested_and_settled(some_candidate, Verdict.REFUTED,
                                                  record_outcome),
            _the_verdict_reported_is(Verdict.REFUTED)
        ))


@pytest.mark.unit
def test_a_change_owed_back_is_put_back_acting_for_the_row_that_owes_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The put-back is a write, marked with the action it puts back.
    happened: list[str] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PUTTING_BACK,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT, put_back_because=SOME_FINDING)),
            calling(lambda: _noting_each_step_of(resuming, happened)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=_Acting(happened),
                                      still_wanted=still_wanted)) \
        .then(_happened_in_order(happened, [
            f"acting for {THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED}",
            "put back",
            f"no longer acting for {THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED}"
        ]))


@pytest.mark.unit
def test_a_change_owed_back_asks_whether_its_own_incident_is_still_wanted(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The put-back is a change to the world, and the walk asks before every
    # one - of this incident, bound before the question is handed over.
    def asking_the_put_back_s_question(dont_care_result: StateDelta) -> bool:
        handed = _mocked(resuming.settle).call_args.kwargs["still_wanted"]
        handed()

        if still_wanted.call_args.args != (an_action_taking_incident.incident_id,):
            raise AssertionError(
                f"Expected the put-back's question asked of incident "
                f"[{an_action_taking_incident.incident_id}], got {still_wanted.call_args}."
            )

        return True

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PUTTING_BACK,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT, put_back_because=SOME_FINDING)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(asking_the_put_back_s_question)


@pytest.mark.unit
def test_a_change_owed_back_carries_when_it_was_made_and_is_neither_owed_again_nor_moved_on(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    owe_a_put_back: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The row already says the change is owed back and why; the walk carries
    # the moment it was made on to the round that remembers it.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PUTTING_BACK,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE, put_back_because=SOME_FINDING)),
            an_action_taking_incident := _a_mitigating_incident(
                proposing=_an_action_with_an_undo_descriptor()
            )
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=owe_a_put_back,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted)) \
        .then(all_of(_the_walk_carries(SOME_MOMENT_IT_WAS_MADE),
                     _the_put_back_was_never_owed(owe_a_put_back),
                     _the_claim_was_not_advanced(advance_action)))


# ---------------------------------------------------------------------------
# A resumed walk: a claim and nothing more
# ---------------------------------------------------------------------------

SOME_UNDOABLE_ACTIONS = [
    pytest.param(RevertFeatureFlag(flag=DONT_CARE_FLAG, enabled=False,
                                   undo_descriptor=FlagUndo(flag=DONT_CARE_FLAG,
                                                            was_enabled=True)),
                 id="flag-revert"),
    pytest.param(RollBackDeployment(application=SOME_APPLICATION), id="rollback"),
    pytest.param(ScaleOut(application=SOME_APPLICATION), id="scale-out"),
    pytest.param(PinAutoscaler(application=SOME_APPLICATION), id="autoscaler-pin"),
    pytest.param(PinToAccelerator(application=SOME_APPLICATION, accelerator=SOME_ACCELERATOR),
                 id="card-pin")
]


@pytest.mark.unit
@pytest.mark.parametrize("some_action", SOME_UNDOABLE_ACTIONS)
def test_a_claimed_change_is_asked_after_on_its_own_plan_before_it_is_taken(
    some_action: Action,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Every kind that plans has a record of whether its change was made - a
    # mark, an entry in a history - so a claim with nothing after it is asked
    # first, on the plan it was written with, and taken on that plan where
    # nothing of it landed. Nothing else is asked before the read.
    happened: list[str] = []
    the_plan_the_claim_carries = _a_plan_of(some_action)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=the_plan_the_claim_carries)),
            calling(lambda: _nothing_of_it_landed(resuming)),
            calling(lambda: _noting_each_step_of(resuming, happened)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            calling(lambda: _noting_when_it_is_taken(take, happened)),
            an_action_taking_incident := _a_resumed_incident(proposing=some_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=_Acting(happened),
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_asked_whether_made_on(some_action, the_plan_the_claim_carries, resuming),
            _the_action_was_taken_on(the_plan_the_claim_carries, take),
            _happened_in_order(happened, [
                f"acting for {THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED}",
                "read whether made",
                "taken",
                f"no longer acting for {THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED}"
            ])
        ))


@pytest.mark.unit
def test_a_claim_written_with_no_plan_is_asked_after_and_taken_on_this_walk_s_plan(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A claim whose plan the tier refused was written with none, and its worker
    # died before recording the refusal. Nothing was written for it, so this
    # walk's own plan is the one there is - asked after and taken on.
    an_action = _an_action_with_an_undo_descriptor()
    this_walk_s_plan = _a_plan_of(an_action)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=None)),
            calling(lambda: _nothing_of_it_landed(resuming)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(this_walk_s_plan),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_asked_whether_made_on(an_action, this_walk_s_plan, resuming),
            _the_action_was_taken_on(this_walk_s_plan, take)
        ))


@pytest.mark.unit
def test_a_claimed_change_found_made_is_moved_on_to_made_when_the_estate_says_it_was(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The dead worker's change landed. Recorded as made with what the estate
    # says puts it back, at the moment the estate says it was made - the only
    # record of when it happened - and not made a second time.
    an_action = _an_action_with_an_undo_descriptor()
    what_the_estate_found = FlagUndo(flag=DONT_CARE_FLAG, was_enabled=True,
                                     written_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _it_was_found_made(resuming, Made(
                descriptor=what_the_estate_found,
                made_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE))),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_claim_was_advanced_to(ActionProgress.PERFORMED, an_action_taking_incident,
                                       advance_action, undo_descriptor=what_the_estate_found,
                                       performed_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE)
        ))


@pytest.mark.unit
def test_a_claimed_change_found_made_is_watched_in_the_words_it_was_made_with(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Then carried on as a change told as made: watched, judged, and recorded
    # as the live walk records it.
    an_action = _an_action_with_an_undo_descriptor()

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _it_was_found_made(resuming, Made(
                descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                made_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE))),
            calling(lambda: _the_watch_came_back(resuming, _an_outcome(Verdict.CONFIRMED))),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_change_was_watched_as(an_action,
                                       Performed(said=WHAT_THE_REVERT_SAID,
                                                 undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT),
                                       resuming),
            _the_action_row_records_the_outcome(Verdict.CONFIRMED, complete_action),
            _the_verdict_reported_is(Verdict.CONFIRMED)
        ))


@pytest.mark.unit
def test_a_claimed_change_found_made_and_announced_nowhere_is_announced_when_it_was_made(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The dead worker died before it announced the change. The account gets
    # the line, dated when the change was made rather than when this walk found
    # it, and the round that remembers the attempt is told the same moment.
    an_action = _an_action_with_an_undo_descriptor()
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _it_was_found_made(resuming, Made(
                descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                made_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE))),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_asked_whether_announced_for(an_action_taking_incident, resuming),
            _the_actions_announced_were_at([SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE],
                                           published),
            _the_walk_carries(SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE)
        ))


@pytest.mark.unit
def test_a_claimed_change_found_made_and_already_announced_is_not_announced_again(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The dead worker announced the change whether or not its advance landed,
    # so a claim with nothing after it can still have its line on file. Two
    # lines would read as Argus acting twice.
    an_action = _an_action_with_an_undo_descriptor()
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _it_was_found_made(resuming, Made(
                descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                made_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE))),
            calling(lambda: _an_announcement_is_on_file(resuming)),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_actions_announced_were_at([], published),
            _the_walk_carries(SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE)
        ))


@pytest.mark.unit
def test_a_rollback_found_made_while_its_operation_is_pending_is_dated_by_its_claim(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Asked and not yet run, the platform's operation has no start to date it
    # by. The row is told it was made at no moment - never this walk's clock,
    # which would put it minutes after it happened - and the walk is told the
    # claim's, the nearest the row has.
    a_rollback = RollBackDeployment(application=SOME_APPLICATION)
    the_plan = _a_plan_of(a_rollback)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                written_at=SOME_MOMENT_THE_CLAIM_WAS_WRITTEN, planned=the_plan)),
            calling(lambda: _it_was_found_made(resuming, Made(descriptor=the_plan.descriptor,
                                                              made_at=None))),
            an_action_taking_incident := _a_resumed_incident(proposing=a_rollback)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_claim_was_advanced_to(ActionProgress.PERFORMED, an_action_taking_incident,
                                       advance_action, undo_descriptor=the_plan.descriptor),
            _the_claim_was_told_no_moment_it_was_made(advance_action),
            _the_walk_carries(SOME_MOMENT_THE_CLAIM_WAS_WRITTEN)
        ))


def _the_claim_was_told_no_moment_it_was_made(advance_action: MagicMock
                                              ) -> Assertion[StateDelta]:
    """Told outright, rather than left to a default: no moment, and never the
    walk's own clock."""
    def assertion(dont_care_result: StateDelta) -> bool:
        told = [call.kwargs.get("performed_at", "nothing at all")
                for call in advance_action.call_args_list]

        if told != [None]:
            raise AssertionError(
                f"Expected the claim told once that it was made at no moment, got {told}."
            )

        return True

    return assertion


@pytest.mark.unit
def test_a_claimed_change_found_changed_since_is_recorded_as_the_live_write_s_refusal_is(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The read answers as the write would have: somebody changed it since the
    # plan, and this claim's change had landed first. What the live walk's
    # changed-since path made of that is the attempt, recorded on the claim
    # with what it left behind - and nothing taken, nothing watched.
    an_action = _an_action_with_an_undo_descriptor()
    the_changed_since_outcome = Outcome(
        verdict=Verdict.ESCALATED, detail="dont care", left_behind_known=True,
        undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT, performed=True, judged=False)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _the_read_answered(resuming, the_changed_since_outcome)),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_row_records_the_outcome(Verdict.ESCALATED, complete_action),
            _the_action_row_records_the_way_back(THE_WAY_BACK_THE_ROW_KEPT, complete_action),
            _the_action_row_records_whether_it_was_performed(True, complete_action),
            _the_verdict_reported_is(Verdict.ESCALATED),
            _the_action_was_not_taken(take),
            _it_was_not_watched(resuming)
        ))


def _the_read_tells_of_the_change(dont_care_action: Action,
                                  dont_care_plan: Planned[Any], /, *,
                                  change_made: ChangeMade) -> Outcome:
    """The changed-since path's read: this claim's change had landed before
    somebody overtook it, told through the walk's own hook."""
    change_made(THE_WAY_BACK_THE_ROW_KEPT)

    return _an_outcome(Verdict.ESCALATED)


@pytest.mark.unit
@pytest.mark.parametrize(("on_file", "announced_at"), [
    pytest.param(False, [SOME_MOMENT_THE_CLAIM_WAS_WRITTEN], id="announced-nowhere"),
    pytest.param(True, [], id="already-announced")
])
def test_a_claimed_change_the_read_tells_of_is_put_on_the_claim_as_the_live_walk_puts_it(
    on_file: bool,
    announced_at: list[datetime],
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The changed-since path tells of a change that landed through the walk's
    # own hook, so the claim is moved on to made with what puts it back - at no
    # moment: the refusal says nothing of when, and this walk's clock is no
    # stand-in. Dated by its claim, the nearest the row has, and announced at it
    # only where no line for the claim is on file.
    an_action = _an_action_with_an_undo_descriptor()
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                written_at=SOME_MOMENT_THE_CLAIM_WAS_WRITTEN, planned=_a_plan_of(an_action))),
            calling(lambda: setattr(_mocked(resuming.whether_it_was_made), "side_effect",
                                    _the_read_tells_of_the_change)),
            calling(lambda: setattr(_mocked(resuming.announced), "return_value", on_file)),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_claim_was_advanced_to(ActionProgress.PERFORMED, an_action_taking_incident,
                                       advance_action,
                                       undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT),
            _the_claim_was_told_no_moment_it_was_made(advance_action),
            _the_actions_announced_were_at(announced_at, published),
            _the_walk_carries(SOME_MOMENT_THE_CLAIM_WAS_WRITTEN)
        ))


@pytest.mark.unit
def test_a_claimed_change_nobody_can_say_was_made_is_handed_over_as_unknown(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The estate could not be read, or could not say whose a change was. Not a
    # "no": acting on it would be acting on a guess about whether production
    # was already changed. Kept on the claim, which is final, and nothing is
    # completed - there is no attempt this walk can account for.
    an_action = _an_action_with_an_undo_descriptor()

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _the_read_answered(
                resuming, NobodyCanSay(because=SOME_FINDING_ON_THE_ESTATE))),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_incident_was_escalated(),
            _the_walk_says(A_CHANGE_NOBODY_CAN_ACCOUNT_FOR),
            _the_claim_was_advanced_to(ActionProgress.UNKNOWN, an_action_taking_incident,
                                       advance_action),
            _nothing_was_completed(complete_action)
        ))


@pytest.mark.unit
def test_a_claimed_change_nobody_can_say_was_made_keeps_what_the_refusal_said_it_left(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The platform in a sync of its own: nobody can say whether the change was
    # made, and the refusal says this claim's suspension stands. Kept on the
    # claim as it goes to unknown, so whatever puts the incident's changes back
    # reaches the suspension.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=ITS_PLAN)),
            calling(lambda: _the_read_answered(resuming, NobodyCanSay(
                because=SOME_FINDING_ON_THE_ESTATE, left_behind=ITS_PLAN.descriptor))),
            an_action_taking_incident := _a_resumed_incident(
                proposing=A_CHANGE_THAT_SUSPENDS_FIRST)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_incident_was_escalated(),
            _the_claim_was_advanced_to(ActionProgress.UNKNOWN, an_action_taking_incident,
                                       advance_action, undo_descriptor=ITS_PLAN.descriptor)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "some_action",
    [
        pytest.param(RestartService(service="kuki-service"), id="restart"),
        pytest.param(DiscardCacheEntries(service="kuki-service", keys=("kuki:1",)),
                     id="discard")
    ]
)
def test_a_claimed_restart_or_discard_is_not_redone_and_is_handed_over_as_unknown(
    some_action: Action,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Neither leaves a record of whether it ran - no mark, no history - and
    # neither may be done twice on a guess. Nothing is read, nothing is acted
    # for, and nobody can say is kept on the claim.
    happened: list[str] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=None)),
            an_action_taking_incident := _a_resumed_incident(proposing=some_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(None),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=_Acting(happened),
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_incident_was_escalated(),
            _the_walk_says(A_CHANGE_NOBODY_CAN_ACCOUNT_FOR),
            _nothing_was_read_of_the_estate(resuming),
            _the_claim_was_advanced_to(ActionProgress.UNKNOWN, an_action_taking_incident,
                                       advance_action),
            _happened_in_order(happened, [])
        ))


@pytest.mark.unit
def test_a_claimed_change_nothing_of_which_landed_is_not_taken_once_the_metrics_cannot_judge_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Taken now, the change would be watched against metrics that no longer
    # reach back to when the incident began - so whether it helped could not
    # be judged, and a change nobody can judge is not made.
    an_action = _an_action_with_an_undo_descriptor()
    an_onset_past_what_is_kept = SOME_NOW - THE_METRICS_KEPT - timedelta(minutes=1)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _nothing_of_it_landed(resuming)),
            an_action_taking_incident := _a_resumed_incident(
                began=an_onset_past_what_is_kept, proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_incident_was_escalated(),
            _the_walk_says(THE_METRICS_NO_LONGER_REACH_BACK)
        ))


# A change whose kind suspends the platform's own sync before it writes - so a
# claim of it can leave the suspension out there with the change itself never
# made - and the plan its claim was written with.
A_CHANGE_THAT_SUSPENDS_FIRST = ScaleOut(application=SOME_APPLICATION)
ITS_PLAN = _a_plan_of(A_CHANGE_THAT_SUSPENDS_FIRST)

# Every way taking a claimed change found not made ends before its change is
# made, as the agent answers: nobody wants it any more, the tier refused it,
# or it was handed over - each with nothing of its own to say it left.
EVERY_WAY_TAKING_IT_ENDS_UNMADE = [
    pytest.param(Verdict.STOPPED, False, id="nobody-wants-it-any-more"),
    pytest.param(Verdict.NOT_ATTEMPTED, True, id="refused"),
    pytest.param(Verdict.ESCALATED, True, id="escalated")
]


@pytest.mark.unit
def test_a_claim_s_suspension_left_out_there_is_recorded_when_the_metrics_cannot_judge_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The change was not made, and the suspension before it was: the walk
    # stops before it writes, and the row records the suspension as left
    # behind - the one record of it a withdrawal can put back from.
    an_onset_past_what_is_kept = SOME_NOW - THE_METRICS_KEPT - timedelta(minutes=1)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=ITS_PLAN)),
            calling(lambda: _nothing_of_it_landed(resuming, left_behind=ITS_PLAN.descriptor)),
            an_action_taking_incident := _a_resumed_incident(
                began=an_onset_past_what_is_kept, proposing=A_CHANGE_THAT_SUSPENDS_FIRST)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_action_row_records_the_way_back(ITS_PLAN.descriptor, complete_action),
            _the_action_row_records_whether_what_it_left_is_known(True, complete_action)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("verdict", "wanted"), EVERY_WAY_TAKING_IT_ENDS_UNMADE)
def test_a_claim_s_suspension_left_out_there_is_recorded_when_taking_it_ends_unmade(
    verdict: Verdict,
    wanted: bool,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Not made, and taken on the claim's plan as a live walk takes it - which
    # ends before the change, saying nothing of its own left behind. What the
    # read carried still stands out there, and the row records it.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=ITS_PLAN)),
            calling(lambda: _nothing_of_it_landed(resuming, left_behind=ITS_PLAN.descriptor)),
            calling(lambda: setattr(still_wanted, "return_value", wanted)),
            calling(lambda: _the_action_came_back(take, verdict, undo_descriptor=None,
                                                  judged=False, performed=False)),
            an_action_taking_incident := _a_resumed_incident(
                proposing=A_CHANGE_THAT_SUSPENDS_FIRST)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_row_records_the_way_back(ITS_PLAN.descriptor, complete_action),
            _the_action_row_records_whether_what_it_left_is_known(True, complete_action)
        ))


# The same kind of change aimed somewhere the register does not list, so the
# autonomy policy refuses to take it again - and the plan its claim was written
# with.
A_CHANGE_THAT_SUSPENDS_FIRST_NOBODY_LISTED = ScaleOut(application=SOME_SERVICE_NOBODY_LISTED)
ITS_CLAIM_S_PLAN = _a_plan_of(A_CHANGE_THAT_SUSPENDS_FIRST_NOBODY_LISTED)


@pytest.mark.unit
def test_a_claim_s_suspension_left_out_there_is_recorded_when_taking_it_again_is_refused(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Not made, and the autonomy policy now refuses to take it: the walk stops
    # before it writes, as it stops when the metrics cannot judge the change.
    # What the read carried still stands out there all the same, and the row
    # records it - the one record of it a withdrawal can put back from.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=ITS_CLAIM_S_PLAN)),
            calling(lambda: _nothing_of_it_landed(resuming,
                                                  left_behind=ITS_CLAIM_S_PLAN.descriptor)),
            an_incident_aimed_outside_the_estate := _a_resumed_incident(
                proposing=A_CHANGE_THAT_SUSPENDS_FIRST_NOBODY_LISTED, listing=[])
        ) \
        .when(lambda: mitigation_node(an_incident_aimed_outside_the_estate,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_action_row_records_the_way_back(ITS_CLAIM_S_PLAN.descriptor, complete_action),
            _the_action_row_records_whether_what_it_left_is_known(True, complete_action)
        ))


@pytest.mark.unit
def test_a_claim_nothing_of_which_landed_records_nothing_left_when_nobody_wants_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The same exit with nothing of the claim's out there: the row records
    # nothing left behind, and knows it - the plan is no change of anybody's.
    nothing_left = None

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=ITS_PLAN)),
            calling(lambda: _nothing_of_it_landed(resuming, left_behind=nothing_left)),
            calling(lambda: _nobody_wants_it_any_more(still_wanted)),
            calling(lambda: _the_action_came_back(take, Verdict.STOPPED, undo_descriptor=None,
                                                  judged=False, performed=False)),
            an_action_taking_incident := _a_resumed_incident(
                proposing=A_CHANGE_THAT_SUSPENDS_FIRST)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_row_records_the_way_back(nothing_left, complete_action),
            _the_action_row_records_whether_what_it_left_is_known(True, complete_action)
        ))


@pytest.mark.unit
def test_a_claimed_change_found_made_is_never_recorded_untaken_when_nobody_wants_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The estate is read before anybody is asked whether the change is still
    # wanted: the dead worker's change landed, so it is recorded as made -
    # whatever a person decided since - and never as an action not taken.
    an_action = _an_action_with_an_undo_descriptor()
    happened: list[str] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _it_was_found_made(resuming, Made(
                descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                made_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE))),
            calling(lambda: _noting_each_step_of(resuming, happened)),
            calling(lambda: _nobody_wants_it_noting(still_wanted, happened)),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_estate_was_read_before_anybody_was_asked(happened),
            _the_claim_was_advanced_to(ActionProgress.PERFORMED, an_action_taking_incident,
                                       advance_action, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                                       performed_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE),
            _never_recorded_untaken(complete_action)
        ))


# What a case notes when the walk asks whether anybody still wants the change.
ASKED_WHETHER_WANTED = "asked whether wanted"


def _nobody_wants_it_noting(still_wanted: MagicMock, happened: list[str]) -> None:
    """A person ended the incident, and each asking notes into `happened`."""
    def answering(*dont_care_args: object, **dont_care_keywords: object) -> bool:
        happened.append(ASKED_WHETHER_WANTED)

        return False

    still_wanted.side_effect = answering


def _the_estate_was_read_before_anybody_was_asked(happened: list[str]) -> Assertion[StateDelta]:
    """Whether the change was made is read first; any asking whether it is still
    wanted comes after it."""
    def assertion(dont_care_result: StateDelta) -> bool:
        read = "read whether made"

        if read not in happened or (
                ASKED_WHETHER_WANTED in happened
                and happened.index(ASKED_WHETHER_WANTED) < happened.index(read)):
            raise AssertionError(
                f"Expected the estate read whether made before anybody was asked whether "
                f"the change is wanted, got {happened}."
            )

        return True

    return assertion


def _never_recorded_untaken(complete_action: MagicMock) -> Assertion[StateDelta]:
    """No completion of the row says the change was not performed."""
    def assertion(dont_care_result: StateDelta) -> bool:
        untaken = [call.kwargs for call in complete_action.call_args_list
                   if call.kwargs.get("performed") is False]

        if untaken:
            raise AssertionError(
                f"Expected a change found made never recorded as not performed, got {untaken}."
            )

        return True

    return assertion


@pytest.mark.unit
def test_a_claimed_change_found_made_is_not_watched_once_the_metrics_cannot_judge_it(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Recorded as made - it was - and handed over rather than watched.
    an_action = _an_action_with_an_undo_descriptor()
    an_onset_past_what_is_kept = SOME_NOW - THE_METRICS_KEPT - timedelta(minutes=1)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=_a_plan_of(an_action))),
            calling(lambda: _it_was_found_made(resuming, Made(
                descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                made_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE))),
            an_action_taking_incident := _a_resumed_incident(
                began=an_onset_past_what_is_kept, proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_not_watched(resuming),
            _the_incident_was_escalated(),
            _the_walk_says(THE_METRICS_NO_LONGER_REACH_BACK),
            _the_claim_was_advanced_to(ActionProgress.PERFORMED, an_action_taking_incident,
                                       advance_action, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                                       performed_at=SOME_MOMENT_THE_ESTATE_SAYS_IT_WAS_MADE)
        ))


# ---------------------------------------------------------------------------
# A resumed walk: a change told as made
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_change_told_as_made_and_still_argus_s_is_watched_and_recorded(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The worker died in the wait. The change is still as it left it, so it is
    # watched afresh - in the words it was made with - and what the watch
    # finds is recorded as the live walk records it. Not made again.
    an_action = _an_action_with_an_undo_descriptor()

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                planned=THE_PLAN_THE_ROW_KEPT, progress=ActionProgress.PERFORMED,
                undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT, performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: _it_was_found(resuming, ChangeFound(still_argus_s=True))),
            calling(lambda: _the_watch_came_back(resuming, _an_outcome(Verdict.REFUTED))),
            an_action_taking_incident := _a_resumed_incident(proposing=an_action)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_checked_whether_still_argus_s(THE_PLAN_THE_ROW_KEPT,
                                                  THE_WAY_BACK_THE_ROW_KEPT, resuming),
            _the_change_was_watched_as(an_action,
                                       Performed(said=WHAT_THE_REVERT_SAID,
                                                 undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT),
                                       resuming),
            _the_action_was_not_taken(take),
            _the_action_row_records_the_outcome(Verdict.REFUTED, complete_action),
            _the_verdict_reported_is(Verdict.REFUTED),
            _the_walk_carries(SOME_MOMENT_IT_WAS_MADE)
        ))


@pytest.mark.unit
def test_a_change_told_as_made_is_checked_and_watched_acting_for_its_own_row(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Whose mark the estate carries is asked of this claim's, and a refutation
    # the watch puts back is a write marked as that action's.
    happened: list[str] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: _noting_each_step_of(resuming, happened)),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=_Acting(happened),
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(_happened_in_order(happened, [
            f"acting for {THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED}",
            "checked",
            "watched",
            f"no longer acting for {THE_ACTION_AN_EARLIER_ATTEMPT_CLAIMED}"
        ]))


@pytest.mark.unit
def test_a_change_told_as_made_is_watched_for_its_own_incident_and_owes_its_put_back_there(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    owe_a_put_back: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The watch is handed what the live walk hands it - the incident, the
    # moments it began, the rule that paged - and a refutation it reaches is
    # put on this claim as owed back before it is put back.
    some_rule = "some-rule"

    def the_watch_was_handed_its_incident(dont_care_result: StateDelta) -> bool:
        assert an_incident.hypothesis is not None
        handed = _mocked(resuming.watch).call_args.kwargs
        handed["put_back_owed"](SOME_FINDING)
        wanted = {"incident_id": an_incident.incident_id,
                  "onset": an_incident.alert.stated_onset,
                  "incident_began": _a_minute(SOME_RECENT_ONSET),
                  "rule": some_rule}
        got = {name: handed.get(name) for name in wanted}
        owed = [(call.args, call.kwargs) for call in owe_a_put_back.call_args_list]
        flattened = [tuple(args) + tuple(keywords.values()) for args, keywords in owed]

        if got != wanted or flattened != [(an_incident.incident_id, an_incident.hypothesis.id,
                                           SOME_FINDING)]:
            raise AssertionError(
                f"Expected the watch handed {wanted} and its put-back owed on this claim, "
                f"got {got} and owed {flattened}."
            )

        return True

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            an_incident := _a_resumed_incident_paged_by(some_rule)
        ) \
        .when(lambda: mitigation_node(an_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=owe_a_put_back,
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(the_watch_was_handed_its_incident)


@pytest.mark.unit
def test_a_change_told_as_made_that_somebody_changed_since_is_handed_over_saying_what(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # What the service does now is no longer Argus's change alone to answer
    # for, so it is not watched. The row keeps the way back it already holds,
    # so a withdrawal can still put back whatever of it is Argus's.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: _it_was_found(resuming, ChangeFound(
                still_argus_s=False, found=SOME_FINDING_ON_THE_ESTATE))),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_not_watched(resuming),
            _the_action_was_not_taken(take),
            _the_incident_was_escalated(),
            _the_walk_says(f"{CHANGED_SINCE_IT_WAS_MADE}: {SOME_FINDING_ON_THE_ESTATE}"),
            _the_claim_was_not_advanced(advance_action),
            _nothing_was_completed(complete_action)
        ))


@pytest.mark.unit
def test_a_change_told_as_made_that_nobody_can_say_still_stands_is_handed_over(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A reading of a service whose state nobody can describe would judge a
    # change nobody can say is there.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: _it_was_found(resuming, ChangeFound(
                still_argus_s=None, found=SOME_FINDING_ON_THE_ESTATE))),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_not_watched(resuming),
            _the_incident_was_escalated(),
            _the_walk_says(f"{NOBODY_CAN_SAY_IT_STILL_STANDS}: {SOME_FINDING_ON_THE_ESTATE}"),
            _the_claim_was_not_advanced(advance_action),
            _nothing_was_completed(complete_action)
        ))


@pytest.mark.unit
def test_a_change_told_as_made_whose_read_failed_unexpectedly_is_handed_over_as_unsayable(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A read that raised anything at all, of any kind, found nothing: nobody
    # can say whether the change still stands, in the failure's own words -
    # not a walk that stops with the incident in nobody's hands.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: setattr(_mocked(resuming.still_argus_s), "side_effect",
                                    RuntimeError(SOME_FINDING_ON_THE_ESTATE))),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=advance_action,
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_not_watched(resuming),
            _the_incident_was_escalated(),
            _the_walk_says(f"{NOBODY_CAN_SAY_IT_STILL_STANDS}: {SOME_FINDING_ON_THE_ESTATE}"),
            _the_claim_was_not_advanced(advance_action),
            _nothing_was_completed(complete_action)
        ))


@pytest.mark.unit
def test_a_change_told_as_made_whose_read_found_the_run_lost_stops_the_walk(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    advance_action: MagicMock,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The incident is another claim's walk now: raised, with nothing recorded
    # and nothing said by this one.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: setattr(_mocked(resuming.still_argus_s), "side_effect",
                                    RunLost(A_NEWER_CLAIM_HOLDS_THE_RUN))),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(attempting(lambda: mitigation_node(an_action_taking_incident,
                                                 take=take,
                                                 plan_action=_a_plan_nobody_checks(),
                                                 resuming=resuming,
                                                 advance_action=advance_action,
                                                 owe_a_put_back=_an_owing_nobody_checks(),
                                                 record_action=record_action,
                                                 complete_action=complete_action,
                                                 record_outcome=record_outcome,
                                                 already_taken=already_taken,
                                                 acting_for=acting_for,
                                                 still_wanted=still_wanted,
                                                 now=_the_clock_at(SOME_NOW)))) \
        .then(all_of(
            an_error_was_raised(RunLost),
            _no_action_row_was_completed(complete_action)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("change_found", "words"), [
    pytest.param(False, CHANGED_SINCE_IT_WAS_MADE, id="changed-since"),
    pytest.param(None, NOBODY_CAN_SAY_IT_STILL_STANDS, id="nobody-can-say")
])
def test_a_change_told_as_made_and_found_not_argus_s_is_announced_before_it_is_handed_over(
    change_found: bool | None,
    words: str,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Whatever the estate says now, the change was made: where the dead worker
    # died before announcing it, the line is on file, dated when it was made,
    # before the incident goes to a person.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: _it_was_found(resuming, ChangeFound(
                still_argus_s=change_found, found=SOME_FINDING_ON_THE_ESTATE))),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_actions_announced_were_at([SOME_MOMENT_IT_WAS_MADE], published),
            _the_incident_was_escalated(),
            _the_walk_says(f"{words}: {SOME_FINDING_ON_THE_ESTATE}")
        ))


@pytest.mark.unit
def test_a_change_told_as_made_with_no_plan_is_asked_after_on_its_way_back_alone(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Every kind but a flag asks of the change alone: a row that kept no plan
    # is asked after all the same, and watched where it still stands - not
    # handed over for a plan its read never needed.
    no_plan = None

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=no_plan,
                progress=ActionProgress.PERFORMED, undo_descriptor=ITS_PLAN.descriptor,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            an_action_taking_incident := _a_resumed_incident(
                proposing=A_CHANGE_THAT_SUSPENDS_FIRST)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_checked_whether_still_argus_s(no_plan, ITS_PLAN.descriptor, resuming),
            _the_verdict_reported_is(Verdict.CONFIRMED)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("progress", "undo_descriptor", "put_back_because"), [
    pytest.param(ActionProgress.PERFORMED, None, None, id="made-with-no-way-back"),
    pytest.param(ActionProgress.PUTTING_BACK, None, SOME_FINDING,
                 id="owed-back-with-no-way-back"),
    pytest.param(ActionProgress.PUTTING_BACK, THE_WAY_BACK_THE_ROW_KEPT, None,
                 id="owed-back-with-no-reason")
])
def test_a_row_said_made_that_keeps_nothing_to_go_on_is_handed_over_as_never_recorded(
    progress: ActionProgress,
    undo_descriptor: UndoDescriptor | None,
    put_back_because: str | None,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A change made with nothing that puts it back, or owed back with no reason
    # the watch gave: nothing to ask after it with, nothing to put it back for.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, progress=progress,
                undo_descriptor=undo_descriptor, performed_at=SOME_MOMENT_IT_WAS_MADE,
                put_back_because=put_back_because)),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_incident_was_escalated(),
            _the_walk_says(A_CHANGE_MADE_AND_NEVER_RECORDED),
            _nothing_was_read_of_the_estate(resuming),
            _nothing_was_completed(complete_action)
        ))


@pytest.mark.unit
def test_a_row_not_performed_with_no_outcome_is_handed_over_as_unaccountable(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A row no walk writes: not performed, and nothing recorded against it.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.NOT_PERFORMED)),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _the_incident_was_escalated(),
            _the_walk_says(A_CHANGE_NOBODY_CAN_ACCOUNT_FOR),
            _nothing_was_read_of_the_estate(resuming),
            _nothing_was_completed(complete_action)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("wanted", "recorded"), [
    pytest.param(True, Verdict.NOT_ATTEMPTED, id="still-wanted"),
    pytest.param(False, Verdict.STOPPED, id="nobody-wants-it-any-more")
])
def test_a_claim_with_no_plan_whose_fresh_plan_is_refused_records_the_refusal(
    wanted: bool,
    recorded: Verdict,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The dead worker's plan was refused and so is this walk's: nothing was
    # written, so nothing is asked of the estate, and the refusal is the
    # attempt - or the stop, where a person ended the incident since.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=None)),
            calling(lambda: setattr(still_wanted, "return_value", wanted)),
            an_action_taking_incident := _a_resumed_incident(
                proposing=A_CHANGE_THAT_SUSPENDS_FIRST)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(
                                          _a_plan_refused_as(Verdict.NOT_ATTEMPTED)),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_action_was_not_taken(take),
            _nothing_was_read_of_the_estate(resuming),
            _the_action_row_records_the_outcome(recorded, complete_action),
            _the_action_row_records_whether_it_was_performed(False, complete_action)
        ))


@pytest.mark.unit
def test_a_claim_with_no_plan_has_this_walk_s_plan_written_onto_it_before_the_write(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The plan lives on the claim, and the write compares with it: a walk
    # resumed after this one dies asks after the change on the plan it was
    # taken on, so the plan is on the claim before anything is asked or written.
    happened: list[str] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=None)),
            calling(lambda: _noting_each_step_of(resuming, happened)),
            calling(lambda: _noting_the_plan_put_on_the_claim(resuming, happened)),
            calling(lambda: _the_action_came_back(take, Verdict.CONFIRMED)),
            calling(lambda: _noting_when_it_is_taken(take, happened)),
            an_action_taking_incident := _a_resumed_incident(
                proposing=A_CHANGE_THAT_SUSPENDS_FIRST)
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_planning_answering(ITS_PLAN),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _the_claim_was_planned_as(an_action_taking_incident, ITS_PLAN, resuming),
            _happened_in_order(happened, [PLANNED_THE_CLAIM, "read whether made", "taken"])
        ))


@pytest.mark.unit
def test_a_claim_with_no_plan_whose_plan_cannot_be_written_onto_it_is_not_taken(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # A write made with the plan nowhere on the claim would leave a walk
    # resumed after this one to plan again, and read a change that landed as
    # never attempted. So the run fails here: nothing is asked of the estate,
    # and nothing written - its escalation is all it costs.
    dont_care_failure = "the database went away"

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None, planned=None)),
            calling(lambda: setattr(_mocked(resuming.plan_the_claim), "side_effect",
                                    RuntimeError(dont_care_failure))),
            an_action_taking_incident := _a_resumed_incident(
                proposing=A_CHANGE_THAT_SUSPENDS_FIRST)
        ) \
        .when(attempting(lambda: mitigation_node(an_action_taking_incident,
                                                 take=take,
                                                 plan_action=_planning_answering(ITS_PLAN),
                                                 resuming=resuming,
                                                 advance_action=_an_advance_nobody_checks(),
                                                 owe_a_put_back=_an_owing_nobody_checks(),
                                                 record_action=record_action,
                                                 complete_action=complete_action,
                                                 record_outcome=record_outcome,
                                                 already_taken=already_taken,
                                                 acting_for=acting_for,
                                                 still_wanted=still_wanted,
                                                 now=_the_clock_at(SOME_NOW)))) \
        .then(all_of(
            an_error_was_raised(RuntimeError),
            _the_action_was_not_taken(take),
            _nothing_was_read_of_the_estate(resuming)
        ))


# What a case notes when the walk writes its plan onto a claim.
PLANNED_THE_CLAIM = "planned the claim"


def _noting_the_plan_put_on_the_claim(resuming: ports.Resuming, happened: list[str]) -> None:
    def planning(*dont_care_args: object, **dont_care_keywords: object) -> None:
        happened.append(PLANNED_THE_CLAIM)

    _mocked(resuming.plan_the_claim).side_effect = planning


def _the_claim_was_planned_as(state: IncidentState,
                              planned: Planned[Any],
                              resuming: ports.Resuming) -> Assertion[StateDelta]:
    """The claim on this incident's candidate was given `planned`, once."""
    def assertion(dont_care_result: StateDelta) -> bool:
        assert state.hypothesis is not None
        given = [(call.args, call.kwargs)
                 for call in _mocked(resuming.plan_the_claim).call_args_list]
        flattened = [tuple(args) + tuple(keywords.values()) for args, keywords in given]
        wanted = (state.incident_id, state.hypothesis.id, planned)

        if flattened != [wanted]:
            raise AssertionError(
                f"Expected the claim given the plan {wanted} once, got {flattened}."
            )

        return True

    return assertion


def _an_incident_dated_only_by(source: str, instant: datetime) -> IncidentState:
    """A resumed incident whose beginning only `source` states: the
    investigation's minute, the minute the alert stated, or the alert's own
    time."""
    state = _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor())

    match source:
        case "investigation":
            return state.model_copy(update={"onset": EstablishedOnset(
                minute=_a_minute(instant), how_known=HowTheMinuteIsKnown.MEASURED)})
        case "stated-onset":
            return state.model_copy(update={"onset": None, "alert": state.alert.model_copy(
                update={"stated_onset": instant, "started_at": None})})
        case "alert":
            return state.model_copy(update={"onset": None, "alert": state.alert.model_copy(
                update={"stated_onset": None, "started_at": instant})})

    raise AssertionError(f"Expected a source of an incident's beginning, got [{source}].")


def _an_incident_nothing_dates() -> IncidentState:
    """A resumed incident with no minute measured, none stated, and no time on
    its alert."""
    state = _a_mitigating_incident(proposing=_an_action_with_an_undo_descriptor())

    return state.model_copy(update={"onset": None, "alert": state.alert.model_copy(
        update={"stated_onset": None, "started_at": None})})


@pytest.mark.unit
@pytest.mark.parametrize("source", ["investigation", "stated-onset", "alert"])
def test_a_change_told_as_made_is_not_watched_once_the_metrics_cannot_reach_back(
    source: str,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The watch compares the service with how it was before the incident, and
    # the metrics are kept only so far back. Where the incident began is the
    # investigation's minute, else the one the alert stated, else when the alert
    # fired - the same instant whichever states it.
    an_onset_past_what_is_kept = SOME_NOW - THE_METRICS_KEPT - timedelta(minutes=1)

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            an_incident_long_begun := _an_incident_dated_only_by(source,
                                                                  an_onset_past_what_is_kept)
        ) \
        .when(lambda: mitigation_node(an_incident_long_begun,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_not_watched(resuming),
            _the_incident_was_escalated(),
            _the_walk_says(THE_METRICS_NO_LONGER_REACH_BACK)
        ))


@pytest.mark.unit
def test_a_change_told_as_made_is_watched_while_the_metrics_reach_back_to_the_very_minute(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Within means within: the oldest minute the metrics keep is still kept.
    an_onset_at_the_edge = SOME_NOW - THE_METRICS_KEPT

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            an_incident_begun_at_the_edge := _a_resumed_incident(began=an_onset_at_the_edge)
        ) \
        .when(lambda: mitigation_node(an_incident_begun_at_the_edge,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(_the_change_was_watched_as(
            _an_action_with_an_undo_descriptor(),
            Performed(said=WHAT_THE_REVERT_SAID, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT),
            resuming))


@pytest.mark.unit
@pytest.mark.parametrize("on_file", [False, True], ids=["none-on-file", "one-on-file"])
def test_a_change_told_as_made_is_announced_only_where_no_announcement_is_on_file(
    on_file: bool,
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # The dead worker told the claim the change was made, then announced it -
    # and may have died in between. Where it did, the line is announced now,
    # dated when the change was made.
    published: list[IncidentEvent] = []

    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            calling(lambda: _an_announcement_is_on_file(resuming) if on_file else None),
            an_action_taking_incident := _a_resumed_incident()
        ) \
        .when(lambda: mitigation_node(an_action_taking_incident,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      publisher=published.append,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(all_of(
            _it_was_asked_whether_announced_for(an_action_taking_incident, resuming),
            _the_actions_announced_were_at([] if on_file else [SOME_MOMENT_IT_WAS_MADE],
                                           published)
        ))


@pytest.mark.unit
def test_a_change_told_as_made_of_an_incident_nothing_dates_is_watched(
    take: MagicMock,
    record_action: MagicMock,
    complete_action: MagicMock,
    record_outcome: MagicMock,
    already_taken: MagicMock,
    acting_for: ports.ActingFor,
    resuming: ports.Resuming,
    still_wanted: MagicMock
) -> None:
    # Nothing states when it began - no minute measured, none stated, no time on
    # the alert - so no window can be said to have passed it: watched, as the
    # live walk watches such an incident.
    Scenario() \
        .given(
            calling(lambda: _an_earlier_attempt_holds_the_claim(
                record_action, already_taken, nothing_recorded=None,
                progress=ActionProgress.PERFORMED, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT,
                performed_at=SOME_MOMENT_IT_WAS_MADE)),
            an_incident_nothing_dates := _an_incident_nothing_dates()
        ) \
        .when(lambda: mitigation_node(an_incident_nothing_dates,
                                      take=take,
                                      plan_action=_a_plan_nobody_checks(),
                                      resuming=resuming,
                                      advance_action=_an_advance_nobody_checks(),
                                      owe_a_put_back=_an_owing_nobody_checks(),
                                      record_action=record_action,
                                      complete_action=complete_action,
                                      record_outcome=record_outcome,
                                      already_taken=already_taken,
                                      acting_for=acting_for,
                                      still_wanted=still_wanted,
                                      now=_the_clock_at(SOME_NOW))) \
        .then(_the_change_was_watched_as(
            _an_action_with_an_undo_descriptor(),
            Performed(said=WHAT_THE_REVERT_SAID, undo_descriptor=THE_WAY_BACK_THE_ROW_KEPT),
            resuming))
