"""Whether Argus can recognise its own change in the provider's log.

The one question a resumed walk asks the provider, and the one thing no unit
test can answer: it turns on whether the actor Argus is configured with is the
name the provider actually records against its writes. Those two are set in
different repositories, and a drift between them switches the recognition off
silently - the failure this exists to catch.

One client for the whole test, as a worker holds one for its whole life. The
write and the two questions about it all go over that session, which is also how
the walk makes them. And one run, held as a worker holds the run it walks: the
write tier changes nothing for a call that names no run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any, Final

import pytest
from agent_mitigation import flag_changes_over
from agent_mitigation.tools import MitigationSettings, argus_changed_flag_since, set_flag
from argus_core import Fence, Holding, WriteMcpEndpoint, connect_from_env, get_settings, utc_now
from argus_core.mcp_transport import McpClient
from argus_core.models import Alert
from argus_incidents.repository import incidents, runs
from argus_testkit import Assertion, Scenario, all_of, calling
from write_mcp_client import write_mcp

from tests.e2e.framework.flags import THE_DEMO_FLAG, THE_FALLBACK_FLAG
from tests.e2e.framework.worker import the_worker_is_paused, the_worker_resumes

# Before anything this test does, so a change it makes cannot be missed for
# having been made a moment too early.
A_MOMENT_AGO = timedelta(seconds=30)

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
def write_tier(claimed_run: runs.Run) -> Iterator[McpClient]:
    """One session to `argus-write-mcp`, holding `claimed_run`, for the length
    of one test."""
    holding = Holding()

    with (
        write_mcp(WriteMcpEndpoint.of(get_settings()), holding=holding) as client,
        holding.of(Fence(run_id=claimed_run.id, epoch=claimed_run.epoch))
    ):
        yield client


@pytest.mark.e2e
def test_argus_recognises_the_change_it_made_and_no_other(
    write_tier: McpClient
) -> None:
    since = utc_now() - A_MOMENT_AGO

    Scenario() \
        .given(
            calling(_argus_changed(THE_DEMO_FLAG, write_tier))
        ) \
        .when(
            lambda: _did_argus_change(THE_DEMO_FLAG, since, write_tier)
        ) \
        .then(all_of(
            _the_answer_is(True),
            _a_flag_argus_did_not_touch_answers(
                THE_FALLBACK_FLAG, since, False, write_tier
            )
        ))


def _argus_changed(flag: str, client: McpClient) -> Callable[[], bool]:
    """A change made through Argus's own write path, so the provider attributes
    it exactly as it would during an incident."""
    def step() -> bool:
        set_flag(flag, enabled=True, client=client)

        return True

    return step


def _did_argus_change(flag: str, since: datetime, client: McpClient) -> bool | None:
    """The question a resumed walk asks, over the session it already holds."""
    return argus_changed_flag_since(
        flag,
        since,
        MitigationSettings.of(get_settings()),
        flag_changes_over(client)
    )


def _the_answer_is(expected: bool) -> Assertion[Any]:
    def assertion(answered: Any) -> bool:
        if answered is not expected:
            raise AssertionError(
                f"Expected the provider's log to answer [{expected}] for a flag "
                f"Argus changed, got [{answered!r}]. `None` means the actor "
                f"Argus is configured with is not the one the provider records."
            )

        return True

    return assertion


def _a_flag_argus_did_not_touch_answers(flag: str,
                                        since: datetime,
                                        expected: bool,
                                        client: McpClient) -> Assertion[Any]:
    def assertion(_answered: Any) -> bool:
        answered = _did_argus_change(flag, since, client)

        if answered is not expected:
            raise AssertionError(
                f"Expected [{expected}] for [{flag}], which Argus did not touch, "
                f"got [{answered!r}]."
            )

        return True

    return assertion
