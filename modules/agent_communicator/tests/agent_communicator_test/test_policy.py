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

from __future__ import annotations

from decimal import Decimal

import pytest
from agent_communicator.policy import Register, how_it_is_said
from argus_core import new_id
from argus_core.events import (
    ActionRecommended,
    ActionRefused,
    ActionTaken,
    AgentInvoked,
    AlarmDisproven,
    AlertAcknowledged,
    AwaitingRecovery,
    CandidateSelected,
    CandidatesReordered,
    ChangesRetrieved,
    ChangeUndone,
    ChannelsUnread,
    CommunicationFailed,
    FixAttempted,
    FlagChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    IncidentRemembered,
    LogsRetrieved,
    MessageUnderstood,
    MetricsRetrieved,
    MitigationResumed,
    OfferExpired,
    OnsetDetected,
    PersonWrote,
    PostmortemWritten,
    RecoveryChecked,
    RememberingFailed,
    ResolutionOffered,
    RetrievalRequested,
    StatusChanged,
    VerdictReached,
    WithdrawalOffered,
)
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    ActionIdentity,
    Actor,
    Alert,
    FailureMode,
    FixOutcome,
    IncidentStatus,
    Meaning,
    OpenedPullRequest,
    Refusal,
    RetrievalChannel,
    Undone,
    Verdict,
    a_chat_message,
)
from argus_testkit import Assertion, Scenario

AN_INCIDENT = new_id()

SOME_MESSAGE = a_chat_message("some-chat", "some-channel", "some-message")


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
                                    IncidentStatus.DISPROVEN,
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
def test_the_grounds_for_a_disproof_are_followed_rather_than_announced() -> None:
    # Which signals were judged and over how long is the case for the ending
    # rather than the ending, and a case belongs where the incident is followed.
    # The channel hears what happened; the thread is where somebody can check
    # whether the window was wide enough to have held the condition at all.
    #
    # Not unsaid, though, which is where the policy's wildcard would leave it. A
    # thread that went from an alert to a terminal status with nothing in between
    # reads as an incident Argus could not work out - the opposite finding.
    the_disproof = AlarmDisproven(
        incident_id=AN_INCIDENT,
        condition="error rate above 5% for 5m",
        signals_judged=("error_rate", "p95_ms"),
        earliest_minute="2026-10-03T09:00Z",
        latest_minute="2026-10-03T09:29Z",
        minutes_judged=30
    )

    Scenario() \
        .given(the_disproof) \
        .when(lambda: how_it_is_said(the_disproof)) \
        .then(_it_is_said(Register.FOLLOWED))


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
def test_an_order_memory_changed_is_not_said_either() -> None:
    # Which order Argus tries its candidates in is a fact about how Argus
    # works. What the people following the incident hear is which candidate is
    # being tested now, and that line is said where it is decided.
    Scenario() \
        .given(
            what_memory_did := CandidatesReordered(
                incident_id=AN_INCIDENT,
                action_type=REVERT_FEATURE_FLAG,
                subject="new-checkout-flow",
                on_the_strength_of="3f2b1a09-0000-4000-8000-00000000000a"
            )
        ) \
        .when(lambda: how_it_is_said(what_memory_did)) \
        .then(_it_is_said(Register.UNSAID))


@pytest.mark.unit
def test_what_was_filed_for_the_next_incident_is_not_said_in_this_one() -> None:
    # A fact about how Argus is built rather than about the incident: what was
    # written into long-term memory changes nothing for the people following
    # this one, and is read on the page by whoever wonders later.
    Scenario() \
        .given(
            what_was_filed := IncidentRemembered(
                incident_id=AN_INCIDENT,
                tried=[ActionIdentity(action_type=REVERT_FEATURE_FLAG,
                                      subject="new-checkout-flow")]
            )
        ) \
        .when(lambda: how_it_is_said(what_was_filed)) \
        .then(_it_is_said(Register.UNSAID))


@pytest.mark.unit
def test_a_memory_that_could_not_be_written_is_not_said_either() -> None:
    # A store that is down costs the next incident an advantage and costs this
    # one nothing, and a war room is about this one. It is on the page, where
    # whoever maintains Argus reads it.
    Scenario() \
        .given(
            what_was_not_filed := RememberingFailed(
                incident_id=AN_INCIDENT,
                refusal="connection refused"
            )
        ) \
        .when(lambda: how_it_is_said(what_was_not_filed)) \
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
def test_what_code_fix_concluded_is_said_in_the_incident_s_own_conversation() -> None:
    # The step that ends with somebody else's turn, so it has to reach them.
    # Followed rather than announced: it belongs to the incident being worked,
    # and the ending that does interrupt already carries where things stand.
    # Said whichever way it went - "I read the code and there is nothing to
    # change" and "the repository refused" are both things the people watching
    # this incident are waiting to hear.
    a_proposal = FixAttempted(
        incident_id=new_id(),
        outcome=FixOutcome.PROPOSED,
        pull_request=OpenedPullRequest(
            number=7, url="https://example.invalid/pull/7", branch="argus/fix-abc"
        ),
        detail="dont care what it said"
    )

    Scenario() \
        .given(a_proposal) \
        .when(lambda: how_it_is_said(a_proposal)) \
        .then(_it_is_said(Register.FOLLOWED))


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


@pytest.mark.unit
def test_a_resumed_walk_does_not_re_announce_a_verdict_the_thread_already_has() -> None:
    # The verdict was written and published by the walk that reached it, in one
    # transaction, so a follower has already heard this answer. What a resumed
    # walk adds is that Argus restarted and caught up - a fact about how Argus
    # is built rather than about the incident, which is the same reason
    # `agent-invoked` says nothing. The page still shows it; a channel does not
    # interrupt with a conclusion it already delivered.
    some_resumption = MitigationResumed(
        incident_id=AN_INCIDENT,
        hypothesis_id=new_id(),
        outcome=Verdict.REFUTED
    )

    Scenario() \
        .given(some_resumption) \
        .when(lambda: how_it_is_said(some_resumption)) \
        .then(_it_is_said(Register.UNSAID))


@pytest.mark.unit
def test_an_offer_to_resolve_is_said_where_the_person_wrote() -> None:
    # The one line in an incident that waits on a particular person, and it is
    # the button they press. Unsaid, the policy's default, would be an offer
    # nobody was shown - an incident a person said was over, sitting open
    # because Argus asked the question only to its own page.
    #
    # Followed rather than announced: it answers somebody who wrote in the
    # incident's own conversation, and the channel hears the ending their press
    # brings about, as it hears every other ending.
    some_offer = ResolutionOffered(
        incident_id=AN_INCIDENT,
        message=SOME_MESSAGE,
        person_id="some-person-id",
        person_name="some person",
        said="rolled the flag back by hand, we're fine"
    )

    Scenario() \
        .given(some_offer) \
        .when(lambda: how_it_is_said(some_offer)) \
        .then(_it_is_said(Register.FOLLOWED))


@pytest.mark.unit
def test_an_offer_to_withdraw_is_said_where_the_person_wrote() -> None:
    # For the resolution offer's reason: a person asked Argus to stand down,
    # and an offer only Argus's own page showed would leave Argus working on
    # over their head.
    some_offer = WithdrawalOffered(
        incident_id=AN_INCIDENT,
        message=SOME_MESSAGE,
        person_id="some-person-id",
        person_name="some person",
        said="stop, I've got this"
    )

    Scenario() \
        .given(some_offer) \
        .when(lambda: how_it_is_said(some_offer)) \
        .then(_it_is_said(Register.FOLLOWED))


@pytest.mark.unit
def test_an_offer_not_confirmed_in_time_is_said_where_it_was_made() -> None:
    # Said, because saying it is what takes the button away: a line the relay
    # never handles is an offer left asking a question Argus stopped waiting
    # for. Followed, where the offer was made, because it answers the person
    # who was asked - nobody else was waiting on it.
    some_expiry = OfferExpired(incident_id=AN_INCIDENT, message=SOME_MESSAGE)

    Scenario() \
        .given(some_expiry) \
        .when(lambda: how_it_is_said(some_expiry)) \
        .then(_it_is_said(Register.FOLLOWED))


@pytest.mark.unit
def test_what_a_person_wrote_and_what_it_was_read_as_are_not_said_back() -> None:
    # A person's own message is already in the conversation, and saying it
    # back to them is an echo. What Argus took it to mean is a fact about how
    # Argus reads rather than about the incident: when the reading leads
    # anywhere, the offer it leads to is the line that is said. Both are on
    # the page, which is where the timeline shows Argus heard.
    Scenario() \
        .given(
            what_was_heard := _what_a_person_wrote_and_how_it_was_read()
        ) \
        .when(lambda: [(event.kind, how_it_is_said(event))
                       for event in what_was_heard]) \
        .then(_they_are_all(Register.UNSAID))


def _what_a_person_wrote_and_how_it_was_read() -> list[IncidentEvent]:
    """A person's message, and Argus's reading of it as the one meaning that
    leads to an offer - the reading most tempting to say out loud."""
    return [
        PersonWrote(incident_id=AN_INCIDENT,
                    message=SOME_MESSAGE,
                    person_id="some-person-id",
                    text="rolled the flag back by hand, we're fine"),
        MessageUnderstood(incident_id=AN_INCIDENT,
                          message=SOME_MESSAGE,
                          meaning=Meaning.RESOLVE)
    ]


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

    `action-refused` is the one a reader would most want to have been told: it
    is the autonomy boundary holding, and a system that changed nothing because
    it would not risk the change has said the most important thing it can say.

    `action-recommended` is the other half of it, and the only line in an
    incident that asks a reader to do something. A refusal heard without it
    tells somebody Argus stopped and not what stopping left them holding - and
    for this incident the shop is still writing wrong totals while they read it.
    """
    return [
        OnsetDetected(incident_id=AN_INCIDENT, onset="2026-08-30T10:03:00Z"),
        HypothesisFormed(
            incident_id=AN_INCIDENT,
            hypothesis_id=new_id(),
            rank=1,
            summary="the monthly-spend flag was turned on",
            failure_mode=FailureMode.FEATURE_FLAG_TOGGLE,
            confidence=0.8,
            subject="monthly-spend-feature",
            evidence=[]
        ),
        CandidateSelected(
            incident_id=AN_INCIDENT,
            hypothesis_id=new_id(),
            summary="the monthly-spend flag was turned on",
            confidence=0.8
        ),
        ActionRefused(
            incident_id=AN_INCIDENT,
            hypothesis_id=new_id(),
            refusal=Refusal.NOT_A_GENERIC_MITIGATION
        ),
        ActionRecommended(
            incident_id=AN_INCIDENT,
            hypothesis_id=new_id(),
            action_type=REVERT_FEATURE_FLAG,
            subject="monthly-spend-feature"
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
                       outcome=Verdict.CONFIRMED),
        ChangeUndone(
            incident_id=AN_INCIDENT,
            subject="monthly-spend-feature",
            outcome=Undone.RESTORED,
            detail="put back the way Argus found it"
        )
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
