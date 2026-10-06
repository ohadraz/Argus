"""Every party of the stack reads one clock, whatever rate it runs at.

`e2e_replay` runs the stack faster than real time, so that the minutes a case
waits for cost a fraction of themselves. That is only safe if every party agrees
what time it is: Argus's processes work it out from the epoch and speed they were
handed, and the parties that cannot run Argus's code - its Postgres, the flag
provider, the provider's Postgres and the Target Service - are put there by
libfaketime. A party left on the wall's clock would be minutes adrift within a
minute of the stack coming up, and the symptom would be a verdict gone wrong
somewhere else entirely.

So this asserts the agreement itself, the rate, and the one consequence two
databases can show between them: a change the flag provider stamped during an
incident lands inside the incident Argus's own database stamped. It holds on the
real clock as well, which is what the paid `e2e` runs on.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Final

import httpx2
import psycopg
import pytest
from argus_core import get_settings, the_clock_named_by, utc_now
from argus_core.models import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_FALLBACK_DISABLED,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import FLAG_PROVIDER_DATABASE_URL, THE_FALLBACK_FLAG
from tests.e2e.framework.world import a_scenario_was_seeded

# How fast this stack's clock runs, read the way every process of it reads it.
THE_SPEED: Final = the_clock_named_by(os.environ).speed

# How far a database's clock may read from this process's, in simulated seconds.
# A reading takes up to a fifth of a real second to come back, and the clock
# writer refreshes the containers' offset every tenth of one - each worth `speed`
# times itself here. A party on the wall's clock is minutes outside this.
A_DATABASE_MAY_DIFFER_BY: Final = timedelta(seconds=1 + 0.3 * THE_SPEED)

# The same for a party read through its HTTP `Date` header, which is truncated to
# the second and refreshed about once a real second by Node and uvicorn alike - so
# it trails the clock by up to `speed` simulated seconds without being wrong.
A_DATE_HEADER_MAY_DIFFER_BY: Final = A_DATABASE_MAY_DIFFER_BY + timedelta(
    seconds=1 + THE_SPEED
)

# How far the measured rate may stray from the configured one. Two readings a real
# second apart, each taking some milliseconds to come back, so not exact.
THE_RATE_MAY_STRAY_BY: Final = 0.2

# The provider's records of a flag being switched, which is what Argus's revert is.
A_FLAG_SWITCHED: Final = ("feature-environment-enabled", "feature-environment-disabled")


@pytest.mark.e2e
def test_every_party_of_the_stack_reads_the_clock_argus_reads() -> None:
    Scenario() \
        .given(
            the_parties := {
                "Argus's Postgres": (
                    lambda: _a_database_clock(DATABASE_URL), A_DATABASE_MAY_DIFFER_BY
                ),
                "the flag provider's Postgres": (
                    lambda: _a_database_clock(FLAG_PROVIDER_DATABASE_URL),
                    A_DATABASE_MAY_DIFFER_BY
                ),
                "the flag provider": (
                    lambda: _a_date_header(f"{get_settings().unleash_base_url}/health"),
                    A_DATE_HEADER_MAY_DIFFER_BY
                ),
                "the Target Service": (
                    lambda: _a_date_header(f"{TARGET_SERVICE_BASE_URL}/health"),
                    A_DATE_HEADER_MAY_DIFFER_BY
                )
            }
        ) \
        .when(
            lambda: _how_far_each_reads_from_argus(the_parties)
        ) \
        .then(
            all_of(*(
                _reads_within(party, allowed)
                for party, (_, allowed) in the_parties.items()
            ))
        )


@pytest.mark.e2e
def test_the_stacks_clock_runs_at_the_speed_it_was_given() -> None:
    # Read off Argus's Postgres, which is faked through libfaketime: agreement at
    # one instant could be a fixed offset that happened to match, and this is what
    # says the offset grows at the rate it should.
    some_real_seconds = 1.0

    Scenario() \
        .given(
            some_real_seconds
        ) \
        .when(
            lambda: _the_rate_argus_postgres_runs_at_over(some_real_seconds)
        ) \
        .then(
            _the_rate_is(THE_SPEED)
        )


@pytest.mark.e2e
def test_a_flag_argus_switched_is_dated_inside_the_incident_argus_recorded() -> None:
    # Two databases, each faked on its own: the provider's stamps the flag Argus
    # switched back on, Argus's stamps the incident and the action. On one clock
    # the first lies between the action and the incident's end; on two, it lies
    # wherever the gap between them puts it.
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("fallback-disabled")),
            calling(the_model_answers_from(RECORDED_FALLBACK_DISABLED))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _argus_switched_the_flag_inside_the_incident(THE_FALLBACK_FLAG)
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


def _a_database_clock(url: str) -> datetime:
    with psycopg.connect(url) as conn:
        row = conn.execute("SELECT clock_timestamp()").fetchone()

    if row is None:
        raise AssertionError(f"The database at [{url}] answered no time at all.")

    instant: datetime = row[0]

    return instant


def _a_date_header(url: str) -> datetime:
    response = httpx2.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    return parsedate_to_datetime(response.headers["date"])


def _how_far_each_reads_from_argus(
    parties: dict[str, tuple[Callable[[], datetime], timedelta]]
) -> dict[str, timedelta]:
    """Each party's reading less this process's, taken just before it."""
    offsets = {}

    for party, (read, _) in parties.items():
        argus_reads = utc_now()
        offsets[party] = read() - argus_reads

    return offsets


def _the_rate_argus_postgres_runs_at_over(real_seconds: float) -> float:
    real_before = time.monotonic()
    first = _a_database_clock(DATABASE_URL)
    time.sleep(real_seconds)
    second = _a_database_clock(DATABASE_URL)

    return (second - first).total_seconds() / (time.monotonic() - real_before)


def _the_incident_and_its_first_action(incident_id: str) -> tuple[datetime, datetime, datetime]:
    """When Argus's database says the incident began, ended, and was first acted on.

    Raises while the incident has not ended, which `eventually` reads as not yet.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT i.created_at, i.ended_at, min(a.taken_at) "
            "FROM incident i JOIN action a ON a.incident_id = i.id "
            "WHERE i.id = %s GROUP BY i.id",
            (incident_id,)
        ).fetchone()

    if row is None or row[1] is None:
        raise AssertionError(
            f"Incident [{incident_id}] has not ended with an action taken yet: {row}."
        )

    return row[0], row[1], row[2]


def _the_flag_switches_argus_made(flag: str) -> list[datetime]:
    with psycopg.connect(FLAG_PROVIDER_DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT created_at FROM events "
            "WHERE feature_name = %s AND created_by = %s AND type = ANY(%s) "
            "ORDER BY id",
            (flag, get_settings().unleash_actor, list(A_FLAG_SWITCHED))
        ).fetchall()

    return [row[0] for row in rows]


def _reads_within(party: str, allowed: timedelta) -> Assertion[dict[str, timedelta]]:
    def assertion(offsets: dict[str, timedelta]) -> bool:
        offset = offsets[party]

        if abs(offset) > allowed:
            raise AssertionError(
                f"Expected {party} to read within [{allowed.total_seconds():.1f}s] of "
                f"Argus's clock, running at [{THE_SPEED:g}] times real time, and it "
                f"read [{offset.total_seconds():+.1f}s] from it."
            )

        return True

    return assertion


def _the_rate_is(expected: float) -> Assertion[float]:
    def assertion(rate: float) -> bool:
        if abs(rate - expected) > THE_RATE_MAY_STRAY_BY * expected:
            raise AssertionError(
                f"Expected Argus's Postgres to run at [{expected:g}] times real time, "
                f"and it ran at [{rate:.2f}]."
            )

        return True

    return assertion


def _argus_switched_the_flag_inside_the_incident(flag: str) -> Assertion[httpx2.Response]:
    def assertion(response: httpx2.Response) -> bool:
        created_at, ended_at, first_action_at = _the_incident_and_its_first_action(
            incident_id_from(response)
        )
        switches = _the_flag_switches_argus_made(flag)
        outside = [
            at for at in switches
            if not (first_action_at - A_DATABASE_MAY_DIFFER_BY
                    <= at
                    <= ended_at + A_DATABASE_MAY_DIFFER_BY)
        ]

        if not switches or outside:
            raise AssertionError(
                f"Expected the flag provider to date Argus's switches of [{flag}] "
                f"between the first action [{first_action_at}] and the end "
                f"[{ended_at}] of the incident created [{created_at}], and it dated "
                f"them {switches}."
            )

        return True

    return assertion
