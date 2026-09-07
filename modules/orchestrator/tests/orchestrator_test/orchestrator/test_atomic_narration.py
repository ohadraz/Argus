from __future__ import annotations

import pytest
from argus_core.db import connect
from argus_core.events import IncidentEvent, Publisher, StatusChanged, VerdictReached
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.graph import Records
from orchestrator.publishing import events_into_connection
from orchestrator.repository import actions, events, hypotheses, incidents, timeline

from ..framework.builders import a_determined_hypothesis

"""That a decision and the account of it are one write.

The incident tables record what Argus concluded; the event stream is what a
human reads the incident from. Written separately they can disagree: a crash
between the two leaves a mitigation nobody can see, or a line about a decision
that was never recorded.

So they share a transaction. What that must not cost is the promise in §4
principle 8 - publishing cannot fail the work it describes - which is why the
narration is written inside a savepoint of its own: it commits with the
transition, and it fails alone.
"""

DONT_CARE_ACTOR = Actor.MITIGATION
DONT_CARE_ACTION = "kukibuki"
SOME_STATUS = IncidentStatus.MITIGATING


@pytest.mark.component
def test_a_transition_survives_a_narration_that_could_not_be_written(
    a_clean_database: None
) -> None:
    # The half that must not regress. An account that could take a mitigation
    # down with it would make the story load-bearing, and the story is never
    # load-bearing: the flag is already off in production by the time this row
    # is written, and losing it loses the only record of how to put it back.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

    records = Records(connect, publisher_for=lambda dont_care_conn: _nobody_can_write)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: records.transition(
                incident_id,
                SOME_STATUS,
                actor=DONT_CARE_ACTOR,
                action=DONT_CARE_ACTION,
                narrating=_a_status_change_for(incident_id, SOME_STATUS)
            )
        ) \
        .then(all_of(
            _the_incident_is(incident_id, SOME_STATUS),
            _the_timeline_records_a_transition_to(incident_id, SOME_STATUS),
            _nothing_was_narrated(incident_id)
        ))


@pytest.mark.component
def test_a_transition_is_not_durable_before_the_line_that_narrates_it(
    a_clean_database: None
) -> None:
    # The other half, and the whole reason the event table lives in this
    # database: one transaction, so there is no moment at which a reader sees a
    # decision that nothing yet accounts for. Asserted from a second connection
    # asked *while* the narration is being written - the only vantage point
    # from which two writes and one write look different.
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)

    seen_mid_write: list[IncidentStatus] = []

    records = Records(
        connect,
        publisher_for=lambda conn: _a_publisher_that_looks_from_outside(
            seen_mid_write, events_into_connection(conn)
        )
    )

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: records.transition(
                incident_id,
                SOME_STATUS,
                actor=DONT_CARE_ACTOR,
                action=DONT_CARE_ACTION,
                narrating=_a_status_change_for(incident_id, SOME_STATUS)
            )
        ) \
        .then(all_of(
            _nothing_outside_saw(seen_mid_write, SOME_STATUS),
            _the_incident_is(incident_id, SOME_STATUS),
            _the_narration_records(incident_id, SOME_STATUS)
        ))


@pytest.mark.component
def test_a_verdict_is_not_durable_before_the_line_that_narrates_it(
    a_clean_database: None
) -> None:
    # The same rule where the fact is what the action settled rather than where
    # the incident stands. An outcome recorded and not yet narrated is a verdict
    # a reader would find with nothing beside it saying what reached it.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")
    some_outcome = "confirmed"
    dont_care_undo_descriptor = {"tool": "set_feature_flag", "was_enabled": True}

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        candidate = a_determined_hypothesis(incident_id)
        hypotheses.record(conn, candidate)
        actions.claim(
            conn,
            incident_id,
            hypothesis_id=candidate.id,
            action_type=DONT_CARE_ACTION
        )

    seen_mid_write: list[str | None] = []

    records = Records(
        connect,
        publisher_for=lambda conn: _a_publisher_that_looks_at_the_action(
            seen_mid_write, incident_id, candidate.id, events_into_connection(conn)
        )
    )

    Scenario() \
        .given(
            candidate.id
        ) \
        .when(
            lambda: records.complete_action(
                incident_id,
                hypothesis_id=candidate.id,
                outcome=some_outcome,
                undo_descriptor=dont_care_undo_descriptor,
                narrating=VerdictReached(
                    incident_id=incident_id,
                    hypothesis_id=candidate.id,
                    outcome=some_outcome
                )
            )
        ) \
        .then(all_of(
            _nothing_outside_saw_the_outcome(seen_mid_write, some_outcome),
            _the_action_records_the_outcome(incident_id, candidate.id, some_outcome),
            _the_narration_reports_the_verdict(incident_id, some_outcome)
        ))


@pytest.mark.component
def test_a_verdict_survives_a_narration_that_could_not_be_written(
    a_clean_database: None
) -> None:
    # The savepoint, from the side that costs something. The flag has already
    # been put back or left as it was by the time this row is written, and the
    # verdict is what says which - losing it to a sentence nobody could write
    # would make the account load-bearing (spec §4 principle 8).
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_outcome = "refuted"
    dont_care_undo_descriptor = {"tool": "set_feature_flag", "was_enabled": True}

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        candidate = a_determined_hypothesis(incident_id)
        hypotheses.record(conn, candidate)
        actions.claim(
            conn,
            incident_id,
            hypothesis_id=candidate.id,
            action_type=DONT_CARE_ACTION
        )

    records = Records(connect, publisher_for=lambda dont_care_conn: _nobody_can_write)

    Scenario() \
        .given(
            candidate.id
        ) \
        .when(
            lambda: records.complete_action(
                incident_id,
                hypothesis_id=candidate.id,
                outcome=some_outcome,
                undo_descriptor=dont_care_undo_descriptor,
                narrating=VerdictReached(
                    incident_id=incident_id,
                    hypothesis_id=candidate.id,
                    outcome=some_outcome
                )
            )
        ) \
        .then(all_of(
            _the_action_records_the_outcome(incident_id, candidate.id, some_outcome),
            _nothing_was_narrated(incident_id)
        ))


def _nobody_can_write(dont_care_event: IncidentEvent) -> None:
    """A subscriber having the worst day it can have."""
    raise RuntimeError("the event store refused the write")


def _a_status_change_for(incident_id: str,
                         status: IncidentStatus) -> StatusChanged:
    dont_care_detail = "shuki tuki"
    return StatusChanged(
        incident_id=incident_id,
        to_status=status,
        detail=dont_care_detail
    )


def _the_incident_is(incident_id: str, status: IncidentStatus) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect() as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected the incident to be [{status}], got [{incident.status}]."
            )

        return True

    return assertion


def _the_timeline_records_a_transition_to(incident_id: str,
                                          status: IncidentStatus) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect() as conn:
            recorded = [event.to_status
                        for event in timeline.get_timeline_events(conn, incident_id)]

        if status not in recorded:
            raise AssertionError(
                f"Expected the timeline to record a transition to [{status}], "
                f"got {recorded}."
            )

        return True

    return assertion


def _nothing_was_narrated(incident_id: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect() as conn:
            narrated = events.get_by_incident(conn, incident_id)

        if narrated:
            raise AssertionError(
                f"Expected a refused narration to leave no event behind, got "
                f"{[type(event).__name__ for event in narrated]}."
            )

        return True

    return assertion


def _the_narration_records(incident_id: str,
                           status: IncidentStatus) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect() as conn:
            narrated = events.get_by_incident(conn, incident_id)

        told = [event.to_status
                for event in narrated
                if isinstance(event, StatusChanged)]

        if status not in told:
            raise AssertionError(
                f"Expected the stream to say the incident reached [{status}], got "
                f"{told}."
            )

        return True

    return assertion


def _nothing_outside_saw(seen: list[IncidentStatus],
                         status: IncidentStatus) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        if not seen:
            raise AssertionError(
                "Expected the narration to have been written at all - nothing "
                "looked from outside, so nothing was asserted."
            )

        if status in seen:
            raise AssertionError(
                f"Expected a reader outside the transaction to see no [{status}] "
                f"while it was still being written, got {seen}."
            )

        return True

    return assertion


def _a_publisher_that_looks_from_outside(seen: list[IncidentStatus],
                                         then_publishing: Publisher) -> Publisher:
    """Reads the incident from a second connection while the first is still
    holding the transition open, then lets the real subscriber write."""
    def publisher(event: IncidentEvent) -> None:
        with connect() as another_connection:
            looking = incidents.get(another_connection, event.incident_id)

            if looking is None:
                raise AssertionError(
                    f"No incident found with id [{event.incident_id}] to look at."
                )

            seen.append(looking.status)

        then_publishing(event)

    return publisher


def _a_publisher_that_looks_at_the_action(seen: list[str | None],
                                          incident_id: str,
                                          hypothesis_id: str,
                                          then_publishing: Publisher) -> Publisher:
    """Reads the action back from a second connection while the first still
    holds the outcome open, then lets the real subscriber write."""
    def publisher(event: IncidentEvent) -> None:
        with connect() as another_connection:
            taken = actions.get_action_for_hypothesis(
                another_connection, incident_id, hypothesis_id
            )

            if taken is None:
                raise AssertionError(
                    f"No action found for candidate [{hypothesis_id}] to look at."
                )

            seen.append(taken.outcome)

        then_publishing(event)

    return publisher


def _nothing_outside_saw_the_outcome(seen: list[str | None],
                                     outcome: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        if not seen:
            raise AssertionError(
                "Expected the narration to have been written at all - nothing "
                "looked from outside, so nothing was asserted."
            )

        if outcome in seen:
            raise AssertionError(
                f"Expected a reader outside the transaction to see no [{outcome}] "
                f"while it was still being written, got {seen}."
            )

        return True

    return assertion


def _the_action_records_the_outcome(incident_id: str,
                                    hypothesis_id: str,
                                    outcome: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect() as conn:
            taken = actions.get_action_for_hypothesis(conn, incident_id, hypothesis_id)

        if taken is None:
            raise AssertionError(f"No action found for candidate [{hypothesis_id}].")

        if taken.outcome != outcome:
            raise AssertionError(
                f"Expected the action to record [{outcome}], got [{taken.outcome}]."
            )

        return True

    return assertion


def _the_narration_reports_the_verdict(incident_id: str,
                                       outcome: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect() as conn:
            narrated = events.get_by_incident(conn, incident_id)

        reached = [event.outcome
                   for event in narrated
                   if isinstance(event, VerdictReached)]

        if outcome not in reached:
            raise AssertionError(
                f"Expected the stream to report the verdict [{outcome}], got "
                f"{reached}."
            )

        return True

    return assertion
