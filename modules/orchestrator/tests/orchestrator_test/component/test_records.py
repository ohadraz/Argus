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

from __future__ import annotations

from typing import Final

import pytest
from argus_core import connect_from_env
from argus_core.events import (
    IncidentEvent,
    LeadWeighed,
    Publisher,
    StatusChanged,
    VerdictReached,
)
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    Actor,
    Alert,
    FlagUndo,
    IncidentStatus,
    Meaning,
    Standing,
    ThreadMessage,
    Verdict,
    Weighing,
)
from argus_incidents.publishing import events_into_connection
from argus_incidents.repository import (
    conversation,
    events,
    hypotheses,
    incidents,
    taken_actions,
)
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from orchestrator.records import Records

from orchestrator_test.framework.builders import a_determined_hypothesis, a_lead

DONT_CARE_ACTOR = Actor.MITIGATION
DONT_CARE_ACTION: Final = REVERT_FEATURE_FLAG
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

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    records = Records(connect_from_env, publisher_for=lambda dont_care_conn: _nobody_can_write)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: records.transition(
                incident_id,
                SOME_STATUS,
                narrating=_a_status_change_for(incident_id, SOME_STATUS)
            )
        ) \
        .then(all_of(
            _the_incident_is(incident_id, SOME_STATUS),
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

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    seen_mid_write: list[IncidentStatus] = []

    records = Records(
        connect_from_env,
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
                narrating=_a_status_change_for(incident_id, SOME_STATUS)
            )
        ) \
        .then(all_of(
            _nothing_outside_saw(seen_mid_write, SOME_STATUS),
            _the_incident_is(incident_id, SOME_STATUS),
            _the_narration_records(incident_id, SOME_STATUS)
        ))


@pytest.mark.component
def test_a_withdrawn_incident_is_neither_moved_nor_said_to_have_moved(
    a_clean_database: None
) -> None:
    # The step that finished after a person withdrew the incident. Its status is
    # not written, and neither is the line about it: a stream saying the
    # incident went on to be mitigated would be the account disagreeing with
    # the row it accounts for.
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        incidents.withdraw(conn, incident_id)

    records = Records(connect_from_env, publisher_for=events_into_connection)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: records.transition(
                incident_id,
                SOME_STATUS,
                narrating=_a_status_change_for(incident_id, SOME_STATUS)
            )
        ) \
        .then(all_of(
            _the_transition_reported(False),
            _the_incident_is(incident_id, IncidentStatus.WITHDRAWN),
            _the_stream_never_said(incident_id, SOME_STATUS)
        ))


@pytest.mark.component
def test_a_verdict_is_not_durable_before_the_line_that_narrates_it(
    a_clean_database: None
) -> None:
    # The same rule where the fact is what the action settled rather than where
    # the incident stands. An outcome recorded and not yet narrated is a verdict
    # a reader would find with nothing beside it saying what reached it.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")
    some_outcome = Verdict.CONFIRMED
    dont_care_undo_descriptor = FlagUndo(flag="monthly-spend-feature", was_enabled=True)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        candidate = a_determined_hypothesis(incident_id)
        hypotheses.record(conn, candidate)
        taken_actions.claim(
            conn,
            incident_id,
            hypothesis_id=candidate.id,
            action_type=DONT_CARE_ACTION,
            subject="dont-care-flag"
        )

    seen_mid_write: list[str | None] = []

    records = Records(
        connect_from_env,
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
    some_outcome = Verdict.REFUTED
    dont_care_undo_descriptor = FlagUndo(flag="monthly-spend-feature", was_enabled=True)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        candidate = a_determined_hypothesis(incident_id)
        hypotheses.record(conn, candidate)
        taken_actions.claim(
            conn,
            incident_id,
            hypothesis_id=candidate.id,
            action_type=DONT_CARE_ACTION,
            subject="dont-care-flag"
        )

    records = Records(connect_from_env, publisher_for=lambda dont_care_conn: _nobody_can_write)

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


@pytest.mark.component
def test_a_weighing_is_kept_on_the_lead_and_said(
    a_clean_database: None
) -> None:
    # Kept on the row, because the row is what a later round, Code-Fix and the
    # postmortem read a lead's standing from; and said, because the person who
    # wrote it is owed an answer in the thread they wrote in.
    some_alert = Alert(service="kuki-service", alert_name="HighErrorRate")
    some_weighing = Weighing(standing=Standing.SUPPORTED, reason="the flag history agrees")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    a_lead_written = _a_lead_written_in(incident_id, "the kuki flag was flipped at noon")
    records = Records(connect_from_env, publisher_for=events_into_connection)

    Scenario() \
        .given(
            a_weighed_lead := a_lead_written.model_copy(update={"weighing": some_weighing})
        ) \
        .when(
            lambda: records.weighing(a_weighed_lead)
        ) \
        .then(all_of(
            _the_lead_stands(a_lead_written, some_weighing),
            _the_narration_reports_the_weighing(incident_id, some_weighing)
        ))


@pytest.mark.component
def test_a_weighing_survives_a_narration_that_could_not_be_written(
    a_clean_database: None
) -> None:
    # The work, from the side the sentence must never cost. A standing lost to
    # an event nobody could write would be a lead the next round shows as never
    # weighed, and Code-Fix reads as unweighed (spec §4 principle 8).
    some_alert = Alert(service="buki-service", alert_name="HighErrorRate")
    some_weighing = Weighing(standing=Standing.REFUTED, reason="the database answered throughout")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    a_lead_written = _a_lead_written_in(incident_id, "it is the database again")
    records = Records(connect_from_env, publisher_for=lambda dont_care_conn: _nobody_can_write)

    Scenario() \
        .given(
            a_weighed_lead := a_lead_written.model_copy(update={"weighing": some_weighing})
        ) \
        .when(
            lambda: records.weighing(a_weighed_lead)
        ) \
        .then(all_of(
            _the_lead_stands(a_lead_written, some_weighing),
            _nothing_was_narrated(incident_id)
        ))


@pytest.mark.component
def test_a_lead_nobody_weighed_is_refused_rather_than_said_to_be_weighed(
    a_clean_database: None
) -> None:
    # A lead with no standing has nothing to keep, and an event saying it was
    # weighed would tell its writer something nobody concluded.
    some_alert = Alert(service="muki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)

    a_lead_written = _a_lead_written_in(incident_id, "the kuki flag was flipped at noon")
    records = Records(connect_from_env, publisher_for=events_into_connection)

    Scenario() \
        .given(
            a_lead_written
        ) \
        .when(
            attempting(lambda: records.weighing(a_lead_written))
        ) \
        .then(all_of(
            an_error_was_raised(ValueError),
            _nothing_was_narrated(incident_id)
        ))


@pytest.mark.component
def test_the_leads_read_are_what_people_told_this_incident(
    a_clean_database: None
) -> None:
    # Another incident's thread is somebody else's conversation, and a lead
    # from it would have the model weighing what was said about a different
    # fault.
    some_alert = Alert(service="tuki-service", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        another_incident_id = incidents.create(conn, some_alert)

    a_lead_here = _a_lead_written_in(incident_id, "the kuki flag was flipped at noon",
                                     ts="1760000100.000200")
    _a_lead_written_in(another_incident_id, "it is the database again",
                       ts="1760000200.000300")
    records = Records(connect_from_env, publisher_for=events_into_connection)

    Scenario() \
        .given(
            incident_id
        ) \
        .when(
            lambda: records.leads(incident_id)
        ) \
        .then(
            _the_leads_are([a_lead_here])
        )


def _a_lead_written_in(incident_id: str,
                       words: str,
                       ts: str = "1760000100.000200") -> ThreadMessage:
    """A message a person wrote in the incident's thread, on the record and
    understood as information."""
    lead = a_lead(words, ts=ts).model_copy(update={"incident_id": incident_id})

    with connect_from_env() as conn:
        conversation.write(conn, lead)
        conversation.understood(conn, lead.message, Meaning.INFORMATION)

    return lead


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
        with connect_from_env() as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status != status:
            raise AssertionError(
                f"Expected the incident to be [{status}], got [{incident.status}]."
            )

        return True

    return assertion


def _nothing_was_narrated(incident_id: str) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect_from_env() as conn:
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
        with connect_from_env() as conn:
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
        with connect_from_env() as another_connection:
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
        with connect_from_env() as another_connection:
            taken = taken_actions.get_action_for_hypothesis(
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
        with connect_from_env() as conn:
            taken = taken_actions.get_action_for_hypothesis(conn, incident_id, hypothesis_id)

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
        with connect_from_env() as conn:
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


def _the_transition_reported(expected: bool) -> Assertion[bool]:
    def assertion(moved: bool) -> bool:
        if moved != expected:
            raise AssertionError(
                f"Expected the transition to report that it "
                f"{"took effect" if expected else "changed nothing"}, "
                f"got [{moved!r}]."
            )

        return True

    return assertion


def _the_stream_never_said(incident_id: str,
                           status: IncidentStatus) -> Assertion[bool]:
    def assertion(_result: bool) -> bool:
        with connect_from_env() as conn:
            narrated = events.get_by_incident(conn, incident_id)

        told = [event.to_status
                for event in narrated
                if isinstance(event, StatusChanged)]

        if status in told:
            raise AssertionError(
                f"Expected the stream to say nothing about a move to [{status}] "
                f"that was never made, got {told}."
            )

        return True

    return assertion


def _the_lead_stands(lead: ThreadMessage, weighing: Weighing) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect_from_env() as conn:
            kept = conversation.get(conn, lead.message)

        if kept is None:
            raise AssertionError(f"No message found named [{lead.message}].")

        if kept.weighing != weighing:
            raise AssertionError(
                f"Expected the lead to stand as {weighing}, and the record holds "
                f"{kept.weighing}."
            )

        return True

    return assertion


def _the_narration_reports_the_weighing(incident_id: str,
                                        weighing: Weighing) -> Assertion[None]:
    def assertion(_result: None) -> bool:
        with connect_from_env() as conn:
            narrated = events.get_by_incident(conn, incident_id)

        said = [Weighing(standing=event.standing, reason=event.reason)
                for event in narrated
                if isinstance(event, LeadWeighed)]

        if said != [weighing]:
            raise AssertionError(
                f"Expected the stream to say the lead was weighed once, as "
                f"{weighing}, and it said {said}."
            )

        return True

    return assertion


def _the_leads_are(expected: list[ThreadMessage]) -> Assertion[list[ThreadMessage]]:
    def assertion(leads: list[ThreadMessage]) -> bool:
        if [lead.message for lead in leads] != [lead.message for lead in expected]:
            raise AssertionError(
                f"Expected the leads {[lead.message for lead in expected]}, and "
                f"the record answered {[lead.message for lead in leads]}."
            )

        return True

    return assertion
