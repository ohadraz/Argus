from __future__ import annotations

from decimal import Decimal

import pytest
from agent_communicator.policy import Register, how_it_is_said
from argus_core.events import (
    ActionTaken,
    AgentInvoked,
    AlertAcknowledged,
    AwaitingRecovery,
    ChangesRetrieved,
    ChannelsUnread,
    CommunicationFailed,
    FlagChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    PostmortemWritten,
    RecoveryChecked,
    RetrievalChannel,
    RetrievalRequested,
    StatusChanged,
    VerdictReached,
)
from argus_core.ids import new_id
from argus_core.models.action import Verdict
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario

"""Which of the things Argus publishes a human actually hears, and how loudly.

Everything is published and everything is on the dashboard; a channel is not a
dashboard. What earns an interruption is what Argus found, what it changed, what
it concluded and where the incident now stands - not the reading it did to get
there, which is evidence a reader goes looking for rather than news.

Register, not a flag: the opening of an incident and its ending are addressed to
everyone, and everything in between is addressed to whoever is following it.
Said in words a destination can translate - Slack into a channel message and a
thread reply, email into a send and a digest - rather than in Slack's own.

The policy lives here and not where events are published. A component that knew
which of its own lines were worth interrupting somebody with would be a
component making an editorial decision in the middle of doing its job.
"""

AN_INCIDENT = new_id()


@pytest.mark.unit
def test_what_argus_read_is_not_said_at_all() -> None:
    # The retrievals are the bulk of an incident's account and the least of its
    # news: forty log lines read is a fact about the investigation's method,
    # and a channel that reported it would bury the four lines that matter.
    Scenario() \
        .given(
            everything_it_read := _everything_argus_read()
        ) \
        .when(lambda: [(event.kind, how_it_is_said(event))
                       for event in everything_it_read]) \
        .then(_they_are_all(Register.UNSAID))


@pytest.mark.unit
def test_what_argus_found_and_did_is_said_in_the_incident_s_own_conversation() -> None:
    # The body of the story. Heard by whoever chose to follow this incident,
    # and not by everyone else: the point of a conversation per incident is
    # that following one is a choice made once rather than an interruption
    # taken repeatedly.
    Scenario() \
        .given(
            what_it_found_and_did := _what_argus_found_and_did()
        ) \
        .when(lambda: [(event.kind, how_it_is_said(event))
                       for event in what_it_found_and_did]) \
        .then(_they_are_all(Register.FOLLOWED))


@pytest.mark.unit
def test_an_incident_opening_is_announced() -> None:
    # The one line nobody can have chosen to follow yet, because it is what
    # there is to follow. Announced, or the incident is invisible.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    Scenario() \
        .given(
            the_alert_arriving := AlertAcknowledged(incident_id=AN_INCIDENT,
                                                    alert=some_alert)
        ) \
        .when(lambda: how_it_is_said(the_alert_arriving)) \
        .then(_it_is_said(Register.ANNOUNCED))


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.RESOLVED,
                                    IncidentStatus.ESCALATED,
                                    IncidentStatus.WITHDRAWN])
def test_an_incident_ending_is_announced(ending: IncidentStatus) -> None:
    # How it ended is addressed to everyone who did not follow it - including
    # the one ending that needs somebody to act: an escalation heard only by
    # whoever was already watching is an escalation to nobody.
    Scenario() \
        .given(
            the_incident_ending := StatusChanged(incident_id=AN_INCIDENT,
                                                 to_status=ending)
        ) \
        .when(lambda: how_it_is_said(the_incident_ending)) \
        .then(_it_is_said(Register.ANNOUNCED))


@pytest.mark.unit
def test_a_failure_to_say_something_is_itself_not_said() -> None:
    # Written because a destination refused a line, and sent nowhere itself.
    # Telling Slack that Slack could not be told is either impossible or noise,
    # and a relay that tried would make a new failure out of every failure.
    # The page is where this one is read.
    Scenario() \
        .given(
            the_line_that_was_lost := CommunicationFailed(
                incident_id=AN_INCIDENT,
                channel="#war-room",
                refusal="channel_not_found",
                about_kind="verdict-reached"
            )
        ) \
        .when(lambda: how_it_is_said(the_line_that_was_lost)) \
        .then(_it_is_said(Register.UNSAID))


@pytest.mark.unit
def test_a_postmortem_is_filed_rather_than_announced() -> None:
    # Where postmortems are kept, which is not where an incident is worked.
    # A register rather than a channel name: Slack reads this as the postmortem
    # channel, email as an attachment, and the policy has an opinion about
    # neither - only that this is the one line that belongs with the archive
    # rather than in the conversation about the incident.
    Scenario() \
        .given(
            the_write_up := PostmortemWritten(
                incident_id=AN_INCIDENT,
                root_cause="monthly-spend-feature divided by a month with no purchases",
                executive_summary="Account pages failed for a third of shoppers.",
                customer_loss_estimate=Decimal("1240.50"),
                estimate_currency="USD",
                engineer_minutes=34
            )
        ) \
        .when(lambda: how_it_is_said(the_write_up)) \
        .then(_it_is_said(Register.FILED))


@pytest.mark.unit
@pytest.mark.parametrize("move", [IncidentStatus.INVESTIGATING,
                                  IncidentStatus.MITIGATING,
                                  IncidentStatus.FIXING])
def test_a_move_that_is_not_an_ending_stays_in_the_conversation(
        move: IncidentStatus) -> None:
    # A walk moves between these several times and none of them is news to
    # somebody who is not following the incident. `fixing` reads like an ending
    # and is not one, which is exactly why the question asked here is whether
    # the status is terminal rather than what it is called.
    Scenario() \
        .given(
            the_incident_moving := StatusChanged(incident_id=AN_INCIDENT,
                                                 to_status=move)
        ) \
        .when(lambda: how_it_is_said(the_incident_moving)) \
        .then(_it_is_said(Register.FOLLOWED))


def _everything_argus_read() -> list[IncidentEvent]:
    """Every event that reports a look rather than a finding.

    `agent-invoked` is here too. Which of Argus's agents is working is a fact
    about how Argus is built rather than about the incident, and the line that
    follows it says what that agent did.
    """
    return [
        AgentInvoked(incident_id=AN_INCIDENT, agent=Actor.INVESTIGATOR),
        RetrievalRequested(
            incident_id=AN_INCIDENT,
            channel=RetrievalChannel.LOGS,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z"
        ),
        MetricsRetrieved(
            incident_id=AN_INCIDENT,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z",
            buckets=[]
        ),
        LogsRetrieved(
            incident_id=AN_INCIDENT,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z",
            lines=[]
        ),
        ChangesRetrieved(
            incident_id=AN_INCIDENT,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z",
            changes=[]
        ),
        FlagChangesRetrieved(incident_id=AN_INCIDENT, changes=[]),
        ChannelsUnread(incident_id=AN_INCIDENT, channels=[]),
        RecoveryChecked(incident_id=AN_INCIDENT,
                        minute="2026-08-30T10:15:00Z",
                        recovered=False)
    ]


def _what_argus_found_and_did() -> list[IncidentEvent]:
    """Every event that reports a finding, a change, or a conclusion.

    `awaiting-recovery` is here rather than among the looks: it is the longest
    silence in an incident, and a conversation that went quiet for six minutes
    without saying it was waiting reads as one that stopped.
    """
    return [
        OnsetDetected(incident_id=AN_INCIDENT, onset="2026-08-30T10:03:00Z"),
        HypothesisFormed(
            incident_id=AN_INCIDENT,
            hypothesis_id=new_id(),
            rank=1,
            summary="the monthly-spend flag was turned on",
            cause_type=CauseType.FEATURE_FLAG_TOGGLE,
            confidence=0.8,
            subject="monthly-spend-feature",
            evidence=[]
        ),
        ActionTaken(
            incident_id=AN_INCIDENT,
            hypothesis_id=None,
            action_type="revert-feature-flag",
            subject="monthly-spend-feature",
            enabled=False
        ),
        AwaitingRecovery(
            incident_id=AN_INCIDENT,
            from_minute="2026-08-30T10:14:00Z",
            seconds_allowed=360
        ),
        VerdictReached(incident_id=AN_INCIDENT,
                       hypothesis_id=None,
                       outcome=Verdict.CONFIRMED)
    ]


def _it_is_said(expected: Register) -> Assertion[Register]:
    def assertion(register: Register) -> bool:
        if register != expected:
            raise AssertionError(f"Expected [{expected}], got [{register}].")

        return True

    return assertion


def _they_are_all(expected: Register) -> Assertion[list[tuple[str, Register]]]:
    def assertion(said: list[tuple[str, Register]]) -> bool:
        wrong = {kind: register for kind, register in said if register != expected}
        if wrong:
            raise AssertionError(
                f"Expected every one of them to be [{expected}], "
                f"{len(wrong)} of {len(said)} were not: {wrong}."
            )

        return True

    return assertion
