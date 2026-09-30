"""The incident no series reports, end to end.

Every other case here is an incident a window shows. This one is the window
stopping. A revision lands on Io's shop that renames the port its metrics are
served on, and nothing else about it changes: the shop goes on trading exactly
as it was, every page renders the right numbers, nothing throws and nothing
waits, and from the minute that revision arrived `/metrics` carries no row at
all. The commit reads as housekeeping, which is the honest shape of this
failure - nobody ships a change meaning to go blind.

Nothing crossed a threshold, because for those minutes there is no series to
cross one. What pages somebody is the rule every monitoring stack has and none
of these scenarios has needed: a series that was reporting has stopped, held
long enough that it cannot be a scrape that went missing. The alert states when
the last sample arrived, and that is the only thing dating the incident.

Four things this case pins that no other one can.

**That a window which stops is not a window that is well.** The minutes after
the revision landed are absent, not calm, and the two arrive identically to
anything reading only the rows that exist. A walk that read the truncated window
as a healthy service would close the incident having looked at nothing.

**That the onset comes from the alert rather than from the series.** Every other
case measures its onset from a departure. There is no departure here, so the
stated minute is all there is - and it is what makes the action confirmable at
all, since the readings do not cover the incident's own minutes.

**That a cause after the onset is still the cause.** The onset is the last row,
because a stopped series offers nothing else to date it from, so the change that
stopped the rows is necessarily later than the last one written. Every other
case in this directory rewards the opposite rule - the change at the onset is
the suspect - and this is the one where following it discards the only candidate
there is.

**That recovery is the readings coming back.** There is no level to return to.
What answers the rollback is rows existing again from the minute the revision
went back, and `_the_rows_stopped_and_came_back` asserts both halves: a window
with no hole in it never staged the incident, and a hole that is still open is a
mitigation that did not work. The minutes it was blind for stay missing, which
is the honest outcome - they were never published and nothing keeps them.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run proves
the path exists - an absence read as an absence, the strategy reaching for the
deployment, and the wait judged on readings rather than on levels. Under `nox -s
e2e` a real model reads a real truncated window and decides for itself whether a
shop that stopped reporting is a shop that is well.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from argus_core.models import FailureMode, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_MONITORING_BLIND_SPOT,
    THE_SERVICE_NAME,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_took_a_rollback_of,
    the_model_answers_from,
    the_shop_raises_its_own_alert,
)
from tests.e2e.framework.world import a_scenario_was_seeded, the_shops_window
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

# The scenario, named as the Target Service registers it.
A_SHOP_THAT_STOPPED_REPORTING = "monitoring-blind-spot"

# How far apart two consecutive published minutes may be before the window has a
# hole in it. A minute plus a little: the rows are per-minute, so anything under
# two minutes is the ordinary spacing and anything at or over it is a gap.
THE_ROWS_ARE_A_MINUTE_APART = timedelta(minutes=2)

# How long a stretch of missing rows has to be to be the incident rather than a
# scrape that went astray. The fixture's own alert rule uses two minutes; this
# asks for more, so a window that merely lost a sample cannot pass the assertion
# that the scenario was staged.
A_HOLE_WORTH_PAGING_FOR = timedelta(minutes=3)

# A minute nobody would be paged for. The shop idles near one percent and this
# scenario never touches the rate - the revision moved where the readings are
# served, not what the shop did.
A_CALM_ERROR_RATE = 0.05

# How far the median may drift across the published minutes. Loose, because the
# figure wobbles minute to minute; far tighter than any incident would move it.
THE_MEDIAN_HOLDS_WITHIN = 1.5


@pytest.mark.e2e
def test_a_shop_that_stopped_reporting_is_made_visible_again() -> None:
    # The alert is raised by the shop rather than built here, and that is
    # load-bearing rather than tidy. Every other case in this directory
    # assembles its own payload, because every other alert is a rule firing on
    # a series whose departure the walk measures again for itself. There is no
    # departure here - the rows stop - so `find_onset` returns nothing and the
    # only thing dating this incident is the minute the alert states. A payload
    # assembled here would carry no onset, the walk would have nothing to anchor
    # on, and it would give up before it ever read the window.
    #
    # The rollback is the same call two other cases here end with, and that is
    # the point: the platform answers a broken value, a broken revision and a
    # revision that broke the watching identically. What keeps this case honest
    # is the cause assertion above it - the strategy proposes a rollback for any
    # blind spot whatever the model understood, so a walk that named the wrong
    # mode would still see the rows come back.
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(A_SHOP_THAT_STOPPED_REPORTING)),
            calling(the_model_answers_from(RECORDED_MONITORING_BLIND_SPOT))
        ) \
        .when(
            the_shop_raises_its_own_alert()
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(
                        the_cause_was_identified_as(
                            FailureMode.MONITORING_BLIND_SPOT
                        ),
                        some_confidence_was_given()
                    ),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    argus_took_a_rollback_of(THE_SERVICE_NAME),
                    _the_rows_stopped_and_came_back(),
                    _the_shop_was_well_throughout()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


def _the_rows_stopped_and_came_back() -> Assertion[httpx.Response]:
    """The incident and its end, both read off the one channel that stopped.

    Both halves are required. A window with no hole in it never staged this
    scenario at all, and would pass any assertion written only about the rows
    that exist - which is the mistake the whole mode is about. A hole still open
    at the end is a revision nobody sent back.

    The hole is found by spacing rather than by counting, because the window
    slides: what minute it starts at is a function of when the run happened, and
    a count would pin the fixture's span instead of the incident's shape.

    The minutes inside the hole are never expected back. They were not published
    and nothing keeps them, so what the rollback restores is the sight of the
    shop and not the record of it.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        published = sorted(
            datetime.fromisoformat(minute["bucket_id"].replace("Z", "+00:00"))
            for minute in the_shops_window()
        )

        if len(published) < 2:
            raise AssertionError(
                f"Expected a window with minutes on both sides of the blind "
                f"stretch, and it carries {len(published)} row(s) - so there is "
                f"nothing here to have stopped or resumed."
            )

        gaps = [
            (earlier, later)
            for earlier, later in zip(published, published[1:], strict=False)
            if later - earlier >= THE_ROWS_ARE_A_MINUTE_APART
        ]

        if not gaps:
            raise AssertionError(
                f"Expected the shop to have gone uncollected for a stretch, "
                f"and every one of the {len(published)} rows is a minute after "
                f"the one before it - so this window is of a shop that never "
                f"went quiet, and the scenario staged nothing."
            )

        widest = max(later - earlier for earlier, later in gaps)

        if widest < A_HOLE_WORTH_PAGING_FOR:
            raise AssertionError(
                f"Expected a stretch long enough to be an instrumentation gap "
                f"rather than a scrape that went astray, and the widest is "
                f"[{widest}] - which is a missed sample, not this incident."
            )

        _, resumed_at = max(gaps, key=lambda gap: gap[1] - gap[0])

        if resumed_at >= published[-1]:
            raise AssertionError(
                f"Expected the rows to come back and keep coming, and the "
                f"newest minute in the window [{published[-1]}] is the first "
                f"one after the gap [{resumed_at}] - so the shop published once "
                f"more and stopped, which is not a deployment that went back."
            )

        return True

    return assertion


def _the_shop_was_well_throughout() -> Assertion[httpx.Response]:
    """That nothing was ever wrong with the service itself.

    The corroboration this mode rests on, asserted from the rows that do exist.
    If the published minutes carried failures or slow pages, this would be an
    ordinary incident that also happened to lose some telemetry, and the one
    thing the scenario must not look like is a shop that is down.

    It is also what separates this case from the bad deployment two files away,
    where a revision landed and the shop got worse. Here a revision landed and
    the shop did not change at all - and that unchanged shop is the mode rather
    than evidence the revision was innocent.

    Read across the whole window rather than at its end, because a rate that
    moved and came back would mean the fixture was staging a fault it is not
    supposed to have.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = the_shops_window()
        worst_rate = max(minute["error_rate"] for minute in window)
        calmest_median = min(minute["p50_ms"] for minute in window)
        worst_median = max(minute["p50_ms"] for minute in window)

        if worst_rate > A_CALM_ERROR_RATE:
            raise AssertionError(
                f"Expected every request the shop served to succeed while it "
                f"was not reporting, and the worst published minute failed "
                f"[{worst_rate:.1%}] - so the logs and the metrics disagree "
                f"about a shop this scenario says is well."
            )

        if worst_median > calmest_median * THE_MEDIAN_HOLDS_WITHIN:
            raise AssertionError(
                f"Expected the pages to render as quickly as they always do, "
                f"and the median went from [{calmest_median}]ms to "
                f"[{worst_median}]ms - which is a latency incident, and this "
                f"scenario stages none."
            )

        return True

    return assertion
