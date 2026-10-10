"""The relay over the real log, which is the thing that actually runs.

`relaying` decides what gets said and in what order and knows about no database
at all, and the log and the place it reads through are `argus_incidents`' and
tested there. What is left to ask here is the two together: that everything
published is said once, and that a second look with nothing new says
nothing.

A component test rather than an integration one: what talks to postgres is
`argus_incidents`' repositories, which have integration tests of their own.
This is one module through its own front door with the infrastructure it cannot
fake behind it.
"""

from __future__ import annotations

import psycopg
import pytest
from agent_communicator.relaying import CHAT_RELAY, relay_once
from argus_core import connect_from_env
from argus_core.events import IncidentEvent
from argus_core.models import Alert
from argus_incidents.following import events_since, place_for
from argus_incidents.repository import events, incidents
from argus_testkit import Scenario, all_of, calling

from agent_communicator_test.framework.assertions import it_said, the_lines_said_were
from agent_communicator_test.framework.builders import (
    a_destination_that_takes_everything,
    three_steps_of,
)


@pytest.mark.component
def test_a_relay_over_the_real_log_says_what_was_published_and_then_stops(
        a_clean_database: None) -> None:
    # The two seams and the flow together: everything published is said
    # once, and a second look with nothing new to say says nothing.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        a_destination = a_destination_that_takes_everything()

        Scenario() \
            .given(
                calling(lambda: _publish(conn, *three_steps_of(incident_id))),
                calling(lambda: relay_once(events_since(connect_from_env),
                                           place_for(connect_from_env, CHAT_RELAY),
                                           a_destination))
            ) \
            .when(lambda: relay_once(events_since(connect_from_env),
                                     place_for(connect_from_env, CHAT_RELAY),
                                     a_destination)) \
            .then(all_of(
                it_said(0),
                the_lines_said_were(a_destination, ["onset-detected",
                                                    "action-taken",
                                                    "status-changed"])
            ))


def _publish(conn: psycopg.Connection, *published: IncidentEvent) -> None:
    """Publishes events and lets them land, as every real publisher does."""
    for event in published:
        events.record(conn, event)

    conn.commit()
