"""Whether Argus can recognise its own change in the provider's log.

The first question a resumed walk asks of a claim on a flag - was the change
made, on the plan the claim carries - and the one thing no unit test can answer:
it turns on whether the actor Argus is configured with is the name the provider
actually records against its writes. Those two are set in different
repositories, and a drift between them switches the recognition off silently -
the failure this exists to catch.

One client for the whole test, as a worker holds one for its whole life. The
plans, the write and the questions about them all go over that session, which is
also how the walk makes them. And one run, held as a worker holds the run it
walks: the write tier changes nothing for a call that names no run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any, Final

import pytest
from argus_testkit import Assertion, Scenario, all_of
from core import Fence, Holding, WriteMcpEndpoint, connect_from_env, get_settings, utc_now
from core.models import Alert, FlagUndo, Made, NotMade, Planned
from incident_record.repository import incidents, runs
from mcp_transport import ChangedSince
from write_mcp_client import WriteTier, write_mcp

from tests.e2e.framework.flags import THE_DEMO_FLAG, THE_FALLBACK_FLAG
from tests.e2e.framework.worker import the_worker_is_paused, the_worker_resumes

# Outlasts the test, so the run is still the claim's when the flag is set.
A_GENEROUS_LEASE: Final = timedelta(minutes=5)


@pytest.fixture
def claimed_run() -> Iterator[runs.Run]:
    """A run this test holds for the length of one test.

    Claimed with the stack's worker paused, which would otherwise take the run
    the moment it is queued and walk it. Finished once the test is done, so the
    suite's teardown has no held run to wait out the lease of.
    """
    the_worker_is_paused()()

    try:
        with connect_from_env() as conn:
            incident_id = incidents.create(
                conn, Alert(service="io-shop", alert_name="HighErrorRate"), at=utc_now()
            )
            runs.enqueue(conn, incident_id)
            claimed = runs.claim(conn, "dont-care-worker", A_GENEROUS_LEASE)
    finally:
        the_worker_resumes()

    assert claimed is not None

    yield claimed

    with connect_from_env() as conn:
        runs.finish(conn, claimed)


@pytest.fixture
def write_tier(claimed_run: runs.Run) -> Iterator[WriteTier]:
    """One session to `argus-write-mcp`, holding `claimed_run`, for the length
    of one test."""
    holding = Holding()

    with (
        write_mcp(WriteMcpEndpoint.of(get_settings()), holding=holding) as tier,
        holding.of(Fence(run_id=claimed_run.id, epoch=claimed_run.epoch))
    ):
        yield tier


@pytest.mark.e2e
def test_argus_recognises_the_change_it_made_and_no_other(
    write_tier: WriteTier
) -> None:
    # The demo flag boots off and the fallback boots on: each is planned into
    # the other state, so neither plan is refused as already done. The fallback
    # is planned first, so the window its read covers starts before Argus's
    # change to the demo flag - and only the demo flag is then set.
    Scenario() \
        .given(
            the_fallback_s_plan := write_tier.plan_flag(THE_FALLBACK_FLAG, False),
            the_demo_flag_s_plan := _planned_and_set_by_argus(THE_DEMO_FLAG, True, write_tier)
        ) \
        .when(
            _answered_or_refused(
                lambda: write_tier.whether_flag_was_made(the_demo_flag_s_plan)
            )
        ) \
        .then(all_of(
            _it_was_found_made(),
            _a_plan_argus_did_not_act_on_finds_nothing_landed(the_fallback_s_plan, write_tier)
        ))


def _answered_or_refused(step: Callable[[], object]) -> Callable[[], object]:
    """`attempting`'s catch, keeping the answer where there was one: which
    answer came back - or which refusal - is what says what drifted."""
    def answer() -> object:
        try:
            return step()
        except Exception as refused:
            return refused

    return answer


def _planned_and_set_by_argus(flag: str,
                              enabled: bool,
                              tier: WriteTier) -> Planned[FlagUndo]:
    """A change made through Argus's own write path from its plan, so the
    provider attributes it exactly as it would during an incident - and the
    plan, as the claim carries it."""
    planned = tier.plan_flag(flag, enabled)
    tier.set_feature_flag(planned, enabled)

    return planned


def _it_was_found_made() -> Assertion[Any]:
    """Made - and where not, what each other answer says drifted."""
    def assertion(answered: Any) -> bool:
        if isinstance(answered, Made):
            return True

        if isinstance(answered, ChangedSince):
            cause = ("the actor the write tier is configured with is not the one the "
                     "provider records Argus's writes under, so Argus's own change read as "
                     "somebody else's")
        elif isinstance(answered, Exception):
            cause = ("the write tier has no actor configured, or could not read the "
                     "provider's log")
        elif isinstance(answered, NotMade):
            cause = "Argus's change is missing from the provider's log"
        else:
            cause = "the read answered with something it never answers"

        raise AssertionError(
            f"Expected the provider's log to show the flag Argus changed as made, got "
            f"[{answered!r}]: {cause}."
        )

    return assertion


def _a_plan_argus_did_not_act_on_finds_nothing_landed(planned: Planned[FlagUndo],
                                                     tier: WriteTier) -> Assertion[Any]:
    def assertion(dont_care_answered: Any) -> bool:
        answered = tier.whether_flag_was_made(planned)

        # A flag has no suspension before its change, so nothing of the
        # claim's is out there to carry.
        if not isinstance(answered, NotMade) or answered.left_behind is not None:
            raise AssertionError(
                f"Expected nothing landed for [{planned.descriptor.flag}], which Argus "
                f"planned and did not touch, and nothing left behind, got [{answered!r}]."
            )

        return True

    return assertion
