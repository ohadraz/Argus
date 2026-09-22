"""That what the budget charged and what the incident is shown to have spent
are the same number.

Two paths compute it and no compiler connects them: `Budget.record` sums four
counts in Python between turns, and `get_tokens_spent` sums the same four in
SQL over the replay log afterwards. Each says in its docstring that it agrees
with the other, which is exactly the kind of agreement that holds until one
side is edited by somebody who never read the other - and the disagreement it
would leave is the defect this arithmetic was changed to remove, returned by a
different door.

So this runs a real investigation and compares the two figures over the same
run. Only two things are stood in for, and neither is on the path under test:
the model answers from a committed recording and retrieval answers from
memory, because what is being checked is the arithmetic either side of the run
rather than what the model made of it.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import psycopg
import pytest
from agent_investigator import investigate
from agent_investigator.budget import InvestigationSettings, a_budget_for
from anthropic_double.server import DEFAULT_BASE_URL
from argus_core import connect_from_env, get_settings
from argus_core.budget import Budget
from argus_core.models import Alert
from argus_incidents.publishing import calls_into
from argus_incidents.repository import incidents, replay
from argus_testkit import Assertion, Scenario, all_of, calling

from tests.framework.investigating import (
    logs_that_say_little,
    metrics_that_show_an_onset,
    no_changes,
    the_configured_thresholds,
)
from tests.framework.recordings import RECORDED_TOOL_USE_TURN, the_double_is_answering

DATABASE_URL = get_settings().database_url



@pytest.fixture
def double() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=DEFAULT_BASE_URL, timeout=30.0) as control:
        control.post("/double-control/reset").raise_for_status()
        control.post(
            "/double-control/seed",
            json={"recording": RECORDED_TOOL_USE_TURN, "repeat": None},
        ).raise_for_status()
        yield control
        control.post("/double-control/reset").raise_for_status()


@pytest.mark.integration
def test_the_budget_charged_what_the_incident_is_shown_to_have_spent(
    double: httpx.Client,
) -> None:
    # The same run, counted twice, by two modules that share no code. Asserted
    # as equality rather than as a ratio: a bound that stopped an
    # investigation at one figure while a human was shown another would be two
    # answers to what the incident cost, and either could be the wrong one.
    with psycopg.connect(DATABASE_URL) as conn:
        incident_id = incidents.create(conn, _an_alert())
        conn.commit()  # the recorder writes on a connection of its own
        the_budget = a_budget_for(InvestigationSettings.of(get_settings()))

        Scenario() \
            .given(
                calling(lambda: the_double_is_answering(double))
            ) \
            .when(
                lambda: investigate(
                    alert=_an_alert(),
                    incident_id=incident_id,
                    fetch_metrics=metrics_that_show_an_onset,
                    fetch_logs=logs_that_say_little,
                    fetch_change_events=no_changes,
                    settings=InvestigationSettings.of(get_settings()),
                    thresholds=the_configured_thresholds(),
                    budget=the_budget,
                    recorder=calls_into(connect_from_env)
                )
            ) \
            .then(
                all_of(
                    _something_was_actually_spent(the_budget),
                    _the_two_totals_agree(conn, incident_id, the_budget)
                )
            )


def _an_alert() -> Alert:
    return Alert(service="io-shop", alert_name="HighErrorRate")


def _something_was_actually_spent(budget: Budget) -> Assertion[object]:
    """That there is a number to agree about.

    Without this the test passes on a run that never reached a model - two
    zeroes are equal, and an investigation that escalated at retrieval would
    report perfect agreement between two paths neither of which ran.
    """
    def assertion(_result: object) -> bool:
        if budget.tokens_spent() <= 0:
            raise AssertionError(
                "Expected the investigation to have spent tokens, and it spent none - "
                "so the two totals agree about nothing."
            )

        return True

    return assertion


def _the_two_totals_agree(conn: psycopg.Connection,
                          incident_id: str,
                          budget: Budget) -> Assertion[object]:
    """The figure the loop enforced against the figure a human is shown.

    Both are named in the failure, because which of them is wrong is the whole
    question: a message saying only that they differ leaves the next reader to
    run the investigation again to find out in which direction.
    """
    def assertion(_result: object) -> bool:
        charged = budget.tokens_spent()
        reported = replay.get_tokens_spent(conn, incident_id)

        if charged != reported:
            raise AssertionError(
                f"Expected the budget's total and the replay log's to agree, but the "
                f"budget charged [{charged}] and the log reports [{reported}]."
            )

        return True

    return assertion
