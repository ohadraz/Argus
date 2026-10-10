"""How a register becomes a message: the channel, or a reply in the thread.

The policy says how loudly a line is said and this is the only module that
knows what loudly means in Slack - a message in the channel reaches everyone,
a reply reaches whoever is following that thread. Nothing above here has an
opinion about threads, and nothing below here has one about what is worth
interrupting a person with.

The double stands where Slack does, so what runs here is the client the demo
builds and the arguments the SDK encodes. What is asserted is what a person
would see: where the message landed, what it said, and which conversation it
joined.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import httpx2
import psycopg
import pytest
from agent_communicator.policy import Register
from agent_communicator.relaying import Destination, Outcome
from agent_communicator.saying import a_chat_destination, a_destination_per_register
from argus_core import connect_from_env, utc_now
from argus_core.events import (
    ActionTaken,
    CommunicationFailed,
    IncidentEvent,
    OfferExpired,
    OnsetDetected,
    PostmortemWritten,
    ResolutionOffered,
    StatusChanged,
)
from argus_core.models import (
    CHAT_OFFER,
    CHAT_THREAD,
    Alert,
    IncidentStatus,
    Report,
    ReportChannel,
    a_chat_message,
    a_chat_offer,
    the_place_of,
)
from argus_incidents.repository import events, incidents, references
from argus_narration import a_narration_line
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    calling,
    one_record_was_logged,
)
from chat_platform.slack import ChatSettings, Slack
from chat_platform.slack_deliveries import ACTION_ID, RESOLVE_ACTION, VALUE
from chat_platform.slack_posting import ACTIONS_BLOCK, BLOCK_TYPE, BUTTON_ELEMENT, ELEMENTS
from slack_sdk import WebClient

from agent_communicator_test.framework.slack import messages_posted_to

A_WAR_ROOM = "C-war-room"

# Where write-ups are kept, which a team may well configure to be the war room
# itself. Separate here because two channels is the case that can go wrong.
AN_ARCHIVE = "C-postmortems"

# Where Argus answers, as somebody outside it would reach it. A test's own
# address rather than the configured one: a link is right or wrong regardless
# of where this run happens to be serving.
ARGUS_AT = "http://argus.example"

# The message a person wrote in the war room's thread, as Slack named it - what
# an offer is about, and what its button has to carry back.
SOME_PERSONS_MESSAGE = "1788999999.000001"


@pytest.mark.component
def test_an_announced_line_is_posted_to_the_channel(
        slack: str, a_clean_database: None) -> None:
    # Addressed to everyone, including whoever is not following this incident.
    # A reply would reach only the people who already know.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack)
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_incident_ending(incident_id)),
                                  Register.ANNOUNCED)) \
            .then(all_of(
                _it_landed(),
                _slack_holds_one_message(slack),
                _that_message_went_to(slack, A_WAR_ROOM),
                _that_message_was_not_a_reply(slack)
            ))


@pytest.mark.component
def test_the_first_message_becomes_the_conversation_the_incident_is_told_in(
        slack: str, a_clean_database: None) -> None:
    # An incident's thread is whatever Slack called its first message. Not
    # remembering it would leave every later line to start a conversation of
    # its own, which is a channel of loose sentences about several incidents.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        say = _a_destination_pointed_at(slack)

        Scenario() \
            .given(
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_onset_of(incident_id)),
                                        Register.ANNOUNCED))
            ) \
            .when(lambda: _the_thread_in(conn, incident_id, A_WAR_ROOM)) \
            .then(_it_is_the_thread_slack_opened(slack))


@pytest.mark.component
def test_a_followed_line_is_a_reply_in_the_incident_s_own_thread(
        slack: str, a_clean_database: None) -> None:
    # The body of an incident, kept out of everybody's way: following it is a
    # choice made once, rather than an interruption taken per line.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        say = _a_destination_pointed_at(slack)

        Scenario() \
            .given(
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_onset_of(incident_id)),
                                        Register.ANNOUNCED))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_action_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(all_of(
                _it_landed(),
                _the_last_message_replied_to_the_first(slack)
            ))


@pytest.mark.component
def test_a_followed_line_with_no_thread_yet_goes_to_the_channel(
        slack: str, a_clean_database: None) -> None:
    # The opening message failed, or this relay arrived mid-incident. A line in
    # the wrong shape is worth more than silence about an incident being
    # worked, so it goes to the channel - and becomes the thread the rest of
    # the incident joins.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack)
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_action_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(all_of(
                _it_landed(),
                _that_message_was_not_a_reply(slack),
                _the_incident_now_has_a_thread(conn, incident_id)
            ))


@pytest.mark.component
def test_a_line_names_who_did_it_and_marks_the_word_the_dashboard_marks(
        slack: str, a_clean_database: None) -> None:
    # The same account the page shows, in Slack's own emphasis. `who` is on the
    # line because "what did Argus do" is really "which of its agents did
    # what", and the marked word is the flag, the status, the verdict - the one
    # thing somebody scanning a channel needs to find without reading.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack)
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_action_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(all_of(
                _that_message_names(slack, "Mitigation Agent"),
                _that_message_marks(slack, "monthly-spend-feature")
            ))


@pytest.mark.component
def test_an_offer_is_a_reply_whose_button_answers_the_person_s_own_message(
        slack: str, a_clean_database: None) -> None:
    # The one line a person answers with a press. The button names the message
    # it is about, because a press is matched to its offer by that message -
    # and only whoever wrote it may confirm. In the thread, beside the message
    # it answers, rather than in the channel where nobody wrote anything.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        say = _a_destination_pointed_at(slack)

        Scenario() \
            .given(
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_onset_of(incident_id)),
                                        Register.ANNOUNCED))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_offer_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(all_of(
                _it_landed(),
                _the_last_message_replied_to_the_first(slack),
                _the_last_message_carries_one_button(slack,
                                                     action_id=RESOLVE_ACTION,
                                                     value=SOME_PERSONS_MESSAGE)
            ))


@pytest.mark.component
def test_an_offer_is_remembered_so_that_it_can_be_retired(
        slack: str, a_clean_database: None) -> None:
    # A button outlives the question it asked: the incident may end by another
    # channel while it is still on screen. Whatever Slack called the offer is
    # kept against the incident, so that whoever ends it can find the button
    # again and take it away.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack)
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_offer_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(_the_offers_remembered_are_the_ones_slack_holds(conn, incident_id, slack))


@pytest.mark.component
def test_a_line_that_offers_nothing_is_not_remembered_as_an_offer(
        slack: str, a_clean_database: None) -> None:
    # Only a message with a button has a button to retire. Every other line
    # remembered as an offer would be one more message rewritten when the
    # incident ends - the account of it, overwritten by its ending.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack)
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_action_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(_no_offer_is_remembered(conn, incident_id))


@pytest.mark.component
def test_an_offer_slack_refused_leaves_no_offer_to_retire(
        slack: str, a_clean_database: None) -> None:
    # Refused for good, so there is no message to come back to. Remembering one
    # would send the ending looking for a button nobody was ever shown.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack),
                calling(lambda: _slack_will_refuse(slack))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_offer_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(all_of(
                _it_will_never_land(),
                _no_offer_is_remembered(conn, incident_id)
            ))


@pytest.mark.component
def test_an_incident_past_resolving_takes_the_button_off_its_offer(
        slack: str, a_clean_database: None) -> None:
    # A button outlives the question it asked. Once the incident is resolved -
    # by this press, by PagerDuty, from the page - the offer says who ended it
    # and through what, and carries nothing left to press: a button that does
    # nothing when pressed reads as Argus not listening.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        say = _a_destination_pointed_at(slack)

        Scenario() \
            .given(
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_onset_of(incident_id)),
                                        Register.ANNOUNCED)),
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_offer_on(incident_id)),
                                        Register.FOLLOWED))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_resolved_by(incident_id, "some person",
                                                                ReportChannel.PAGERDUTY)),
                                  Register.ANNOUNCED)) \
            .then(all_of(
                _it_landed(),
                _the_offer_now_says(slack, "some person", "PagerDuty")
            ))


@pytest.mark.component
def test_a_move_that_still_takes_a_resolution_leaves_the_offer_standing(
        slack: str, a_clean_database: None) -> None:
    # Mitigated is as far as Argus goes and not as far as the incident goes:
    # the person who said it is fixed may still be the one who resolves it.
    # Taking their button away here would leave them the page and nothing else.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        say = _a_destination_pointed_at(slack)

        Scenario() \
            .given(
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_onset_of(incident_id)),
                                        Register.ANNOUNCED)),
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_offer_on(incident_id)),
                                        Register.FOLLOWED))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_a_move_of(incident_id,
                                                              to=IncidentStatus.MITIGATED)),
                                  Register.ANNOUNCED)) \
            .then(_the_offer_still_asks(slack))


@pytest.mark.component
def test_an_offer_not_confirmed_in_time_loses_its_button(
        slack: str, a_clean_database: None) -> None:
    # Argus stopped waiting and carried on, so the question is no longer being
    # asked. A button left on it would resolve an incident on an answer nobody
    # was waiting for any more - the person who still means it writes again.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        say = _a_destination_pointed_at(slack)

        Scenario() \
            .given(
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_onset_of(incident_id)),
                                        Register.ANNOUNCED)),
                calling(lambda: say(incident_id,
                                        a_narration_line(_the_offer_on(incident_id)),
                                        Register.FOLLOWED))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_offer_expiring_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(all_of(
                _it_landed(),
                _the_offer_now_says(slack, "not confirmed in time")
            ))


@pytest.mark.component
def test_an_offer_slack_would_not_take_the_button_off_is_written_down(
        slack: str, a_clean_database: None) -> None:
    # Somebody deleted the offer, or the workspace lost it. The incident is
    # resolved all the same - this is a line that could not be changed, not a
    # decision that failed - and the timeline says so, as it does for a line
    # that could not be said.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack),
                calling(lambda: _an_offer_slack_no_longer_holds(conn, incident_id))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_resolved_by(incident_id, "some person",
                                                                ReportChannel.SLACK)),
                                  Register.ANNOUNCED)) \
            .then(all_of(
                _it_landed(),
                _that_failure_says(conn, incident_id,
                                   refusal="message_not_found",
                                   channel=A_WAR_ROOM,
                                   about="status-changed")
            ))


@pytest.mark.component
def test_a_message_refused_for_good_is_reported_as_never_landing(
        slack: str, a_clean_database: None) -> None:
    # A channel that is not there is not there on the next pass either. The
    # relay reads this as "pass over it" - answering that it landed would count
    # a line nobody saw, and answering "not now" would stop the account here
    # for as long as the workspace stays the way it is.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack),
                calling(lambda: _slack_will_refuse(slack))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_onset_of(incident_id)),
                                  Register.ANNOUNCED)) \
            .then(all_of(
                _it_will_never_land(),
                _slack_holds_nothing(slack),
                _the_incident_has_no_thread(conn, incident_id)
            ))


@pytest.mark.component
def test_a_line_refused_for_good_is_written_down_on_the_incident(
        slack: str, a_clean_database: None) -> None:
    # The gap in the account, explained where the account is. Slack is where a
    # human was going to read this and the one place it cannot now be said, so
    # the timeline is what has to carry that Argus tried and was refused - and
    # which refusal it was, because a renamed channel and a revoked token need
    # different people to fix them.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack),
                calling(lambda: _slack_will_refuse(slack))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_onset_of(incident_id)),
                                  Register.ANNOUNCED)) \
            .then(
                _that_failure_says(conn, incident_id,
                                   refusal="channel_not_found",
                                   channel=A_WAR_ROOM,
                                   about="onset-detected")
            )


@pytest.mark.component
def test_a_filed_line_goes_to_the_archive_and_everything_else_to_the_war_room(
        slack: str, a_clean_database: None) -> None:
    # Two channels, one destination. Which one a line lands in is decided by
    # its register and nothing else - so a team that keeps its write-ups
    # somewhere of their own gets them there, and the conversation about the
    # incident is not interrupted by the record of it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := a_destination_per_register(
                    _a_destination_pointed_at(slack),
                    _a_destination_pointed_at(slack, channel=AN_ARCHIVE)
                )
            ) \
            .when(lambda: [
                say(incident_id,
                        a_narration_line(_the_incident_ending(incident_id)),
                        Register.ANNOUNCED),
                say(incident_id,
                        a_narration_line(_the_write_up_of(incident_id)),
                        Register.FILED)
            ]) \
            .then(all_of(
                _the_messages_in(slack, A_WAR_ROOM, count=1),
                _the_messages_in(slack, AN_ARCHIVE, count=1),
                _the_only_message_in(slack, AN_ARCHIVE, mentions="Wrote the postmortem")
            ))


@pytest.mark.component
def test_a_write_up_filed_elsewhere_is_pointed_at_from_the_war_room(
        slack: str, a_clean_database: None) -> None:
    # A conversation that ends without mentioning the write-up leaves whoever
    # followed the incident to guess that one exists. Told where to look rather
    # than told what it says - the postmortem is long, it is already somewhere,
    # and both messages carry the link to the page that holds all of it.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        its_page = f"{ARGUS_AT}/incidents/{incident_id}/postmortem"

        Scenario() \
            .given(
                say := a_destination_per_register(
                    _a_destination_pointed_at(slack),
                    _a_destination_pointed_at(slack, channel=AN_ARCHIVE),
                    argus_at=ARGUS_AT,
                    filed_in=AN_ARCHIVE
                )
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_write_up_of(incident_id)),
                                  Register.FILED)) \
            .then(all_of(
                _the_only_message_in(slack, AN_ARCHIVE, mentions="Wrote the postmortem"),
                _the_only_message_in(slack, AN_ARCHIVE, mentions=its_page),
                _the_only_message_in(slack, A_WAR_ROOM, mentions=AN_ARCHIVE),
                _the_only_message_in(slack, A_WAR_ROOM, mentions=its_page)
            ))


@pytest.mark.component
def test_a_line_refused_for_good_is_logged_as_an_error(
        slack: str, a_clean_database: None, caplog: pytest.LogCaptureFixture) -> None:
    # A line of the incident's account that nobody will ever read in Slack, and
    # a channel or a token somebody has to go and fix before the next one.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack),
                calling(lambda: _slack_will_refuse(slack))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_the_onset_of(incident_id)),
                                  Register.ANNOUNCED)) \
            .then(
                one_record_was_logged(caplog, "agent_communicator.saying",
                                      logging.ERROR, "line will never be said",
                                      values={"channel": A_WAR_ROOM,
                                              "refusal": "channel_not_found"})
            )


@pytest.mark.component
def test_an_offer_that_keeps_its_button_is_logged_as_a_warning(
        slack: str, a_clean_database: None, caplog: pytest.LogCaptureFixture) -> None:
    # A warning rather than an error: the incident is over and a press on what
    # is left changes nothing. What somebody may want to know is which channel
    # and why, since a message that still asks is a small lie in that channel.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                say := _a_destination_pointed_at(slack),
                calling(lambda: _an_offer_slack_no_longer_holds(conn, incident_id))
            ) \
            .when(lambda: say(incident_id,
                                  a_narration_line(_resolved_by(incident_id, "some person",
                                                                ReportChannel.SLACK)),
                                  Register.ANNOUNCED)) \
            .then(
                one_record_was_logged(caplog, "agent_communicator.saying",
                                      logging.WARNING, "offer keeps its button",
                                      values={"channel": A_WAR_ROOM,
                                              "refusal": "message_not_found"})
            )


def _a_destination_pointed_at(base_url: str, channel: str = A_WAR_ROOM) -> Destination:
    return a_chat_destination(connect_from_env, channel=channel, chat=_slack_at(base_url))


def _the_onset_of(incident_id: str) -> IncidentEvent:
    return OnsetDetected(incident_id=incident_id, onset="2026-08-30T10:03:00Z")


def _the_action_on(incident_id: str) -> IncidentEvent:
    return ActionTaken(
        incident_id=incident_id,
        hypothesis_id=None,
        action_type="revert-feature-flag",
        subject="monthly-spend-feature",
        enabled=False
    )


def _the_offer_on(incident_id: str) -> IncidentEvent:
    return ResolutionOffered(
        incident_id=incident_id,
        message=a_chat_message(ReportChannel.SLACK, A_WAR_ROOM, SOME_PERSONS_MESSAGE),
        person_id="some-person-id",
        person_name="some person",
        said="rolled the flag back by hand, we're fine"
    )


def _resolved_by(incident_id: str, by: str, through: ReportChannel) -> IncidentEvent:
    return StatusChanged(incident_id=incident_id,
                         to_status=IncidentStatus.RESOLVED,
                         reported=Report(by=by, channel=through))


def _a_move_of(incident_id: str, to: IncidentStatus) -> IncidentEvent:
    return StatusChanged(incident_id=incident_id, to_status=to)


def _the_offer_expiring_on(incident_id: str) -> IncidentEvent:
    return OfferExpired(
        incident_id=incident_id,
        message=a_chat_message(ReportChannel.SLACK, A_WAR_ROOM, SOME_PERSONS_MESSAGE)
    )


def _an_offer_slack_no_longer_holds(conn: psycopg.Connection, incident_id: str) -> None:
    """An offer the incident remembers, for a message Slack never posted."""
    references.add(conn, incident_id,
                   [a_chat_offer(ReportChannel.SLACK, A_WAR_ROOM, "1788999999.999999")])
    conn.commit()


def _the_incident_ending(incident_id: str) -> IncidentEvent:
    return StatusChanged(incident_id=incident_id, to_status=IncidentStatus.RESOLVED)


def _the_write_up_of(incident_id: str) -> IncidentEvent:
    return PostmortemWritten(
        incident_id=incident_id,
        root_cause="monthly-spend-feature divided by a month with no purchases",
        executive_summary="Account pages failed for a third of shoppers.",
        customer_loss_estimate=Decimal("1240.50"),
        estimate_currency="USD",
        engineer_minutes=34
    )


def _slack_will_refuse(base_url: str) -> None:
    """Queues the refusal the next post is met with."""
    httpx2.post(f"{base_url}/double-control/seed",
               json={"error": "channel_not_found"}).raise_for_status()


def _it_landed() -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if outcome is not Outcome.SAID:
            raise AssertionError(
                f"Expected the line to have landed, it reported [{outcome}]."
            )

        return True

    return assertion


def _it_will_never_land() -> Assertion[Outcome]:
    """A refusal about the message itself, which the next pass would meet too.

    The relay reads this as "pass over it": the line is lost and said so on the
    timeline, and holding the place for it would lose every line behind it too.
    """
    def assertion(outcome: Outcome) -> bool:
        if outcome is not Outcome.NEVER:
            raise AssertionError(
                f"Expected the line never to land, it reported [{outcome}]."
            )

        return True

    return assertion


def _slack_holds_one_message(base_url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = messages_posted_to(base_url)
        if len(held) != 1:
            raise AssertionError(f"Expected one message in Slack, got {len(held)}: {held}")

        return True

    return assertion


def _slack_holds_nothing(base_url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = messages_posted_to(base_url)
        if held:
            raise AssertionError(f"Expected nothing said, Slack holds {held}")

        return True

    return assertion


def _that_message_went_to(base_url: str, channel: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        addressed = [message["channel"] for message in messages_posted_to(base_url)]
        if addressed != [channel]:
            raise AssertionError(f"Expected it addressed to [{channel}], got {addressed}")

        return True

    return assertion


def _that_message_was_not_a_reply(base_url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = messages_posted_to(base_url)
        replied_to = [message["thread_ts"] for message in held]
        if any(replied_to):
            raise AssertionError(
                f"Expected a message to the channel itself, it replied to {replied_to}"
            )

        return True

    return assertion


def _the_last_message_replied_to_the_first(base_url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = messages_posted_to(base_url)
        if len(held) != 2:
            raise AssertionError(f"Expected two messages in Slack, got {len(held)}: {held}")

        if held[-1]["thread_ts"] != held[0]["ts"]:
            raise AssertionError(
                f"Expected a reply in thread [{held[0]['ts']}], it replied to "
                f"[{held[-1]['thread_ts']}]."
            )

        if held[-1]["channel"] != held[0]["channel"]:
            raise AssertionError(
                f"Expected the reply in [{held[0]['channel']}], it went to "
                f"[{held[-1]['channel']}]."
            )

        return True

    return assertion


def _the_last_message_carries_one_button(base_url: str,
                                         action_id: str,
                                         value: str) -> Assertion[Any]:
    """One button, in an actions block, naming the action and the message it
    answers.

    Read out of the blocks the way Slack lays them out, rather than by looking
    for the action anywhere in the message: a button outside an actions block
    is one Slack refuses to draw, and a test finding it anyway would pass on a
    message nobody could press.
    """
    def assertion(_: Any) -> bool:
        blocks = messages_posted_to(base_url)[-1]["blocks"]
        buttons = [element
                   for block in blocks if block[BLOCK_TYPE] == ACTIONS_BLOCK
                   for element in block[ELEMENTS] if element[BLOCK_TYPE] == BUTTON_ELEMENT]
        if len(buttons) != 1:
            raise AssertionError(f"Expected one button, got {len(buttons)} in {blocks}.")

        pressed_as = (buttons[0].get(ACTION_ID), buttons[0].get(VALUE))
        if pressed_as != (action_id, value):
            raise AssertionError(
                f"Expected a button for [{action_id}] on [{value}], got "
                f"[{pressed_as[0]}] on [{pressed_as[1]}]."
            )

        return True

    return assertion


def _that_message_names(base_url: str, who: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        said = messages_posted_to(base_url)[-1]["text"]
        if who not in said:
            raise AssertionError(f"Expected [{who}] named in [{said}].")

        return True

    return assertion


def _that_message_marks(base_url: str, word: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        said = messages_posted_to(base_url)[-1]["text"]
        if f"*{word}*" not in said:
            raise AssertionError(f"Expected [*{word}*] marked in [{said}].")

        return True

    return assertion


def _it_is_the_thread_slack_opened(base_url: str) -> Assertion[str | None]:
    def assertion(remembered: str | None) -> bool:
        held = messages_posted_to(base_url)
        if not held:
            raise AssertionError("Expected a message in Slack to compare the thread against.")

        if remembered != held[0]["ts"]:
            raise AssertionError(
                f"Expected the incident to be in thread [{held[0]['ts']}], "
                f"it is in [{remembered}]."
            )

        return True

    return assertion


def _the_incident_now_has_a_thread(conn: psycopg.Connection,
                                   incident_id: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if _the_thread_in(conn, incident_id, A_WAR_ROOM) is None:
            raise AssertionError(
                "Expected the message that went to the channel to become the "
                "incident's thread, it was not remembered."
            )

        return True

    return assertion


def _the_incident_has_no_thread(conn: psycopg.Connection,
                                incident_id: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        remembered = _the_thread_in(conn, incident_id, A_WAR_ROOM)
        if remembered is not None:
            raise AssertionError(
                f"Expected no thread for a message nobody received, got [{remembered}]."
            )

        return True

    return assertion


def _the_offers_remembered_are_the_ones_slack_holds(conn: psycopg.Connection,
                                                    incident_id: str,
                                                    base_url: str) -> Assertion[Any]:
    """Every offer the incident remembers, against every message Slack holds.

    Compared whole rather than counted, because the claim is that the offer can
    be found again: a reference to the wrong message is one the ending would
    rewrite, and that message is somebody else's line.
    """
    def assertion(_: Any) -> bool:
        remembered = references.get_values_for(conn, incident_id, CHAT_OFFER)
        held = [a_chat_offer(ReportChannel.SLACK, message["channel"], message["ts"]).value
                for message in messages_posted_to(base_url)]
        if remembered != held:
            raise AssertionError(
                f"Expected the offers {held} remembered, got {remembered}."
            )

        return True

    return assertion


def _no_offer_is_remembered(conn: psycopg.Connection, incident_id: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        remembered = references.get_values_for(conn, incident_id, CHAT_OFFER)
        if remembered:
            raise AssertionError(f"Expected no offer remembered, got {remembered}.")

        return True

    return assertion


def _the_offer_now_says(base_url: str, *words: str) -> Assertion[Any]:
    """The offer - the second message, after the one that opened the thread -
    rewritten to name how the incident ended, with nothing left to press."""
    def assertion(_: Any) -> bool:
        offer = messages_posted_to(base_url)[1]
        if not offer["updated"] or offer["blocks"]:
            raise AssertionError(
                f"Expected the offer rewritten with no blocks, it reads {offer}."
            )

        missing = [word for word in words if word not in offer["text"]]
        if missing:
            raise AssertionError(f"Expected {missing} in [{offer['text']}].")

        return True

    return assertion


def _the_offer_still_asks(base_url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        offer = messages_posted_to(base_url)[1]
        if offer["updated"] or not offer["blocks"]:
            raise AssertionError(
                f"Expected the offer as it was posted, button and all, it reads {offer}."
            )

        return True

    return assertion


def _the_thread_in(conn: psycopg.Connection, incident_id: str, channel: str) -> str | None:
    """The thread the incident is told in in this channel, as Slack named its
    first message, or `None`."""
    for value in references.get_values_for(conn, incident_id, CHAT_THREAD):
        in_channel, message = the_place_of(value)

        if in_channel == channel:
            return message

    return None


def _the_failures_on(conn: psycopg.Connection,
                     incident_id: str) -> list[CommunicationFailed]:
    """Every line this incident's timeline says could not be said."""
    return [written for written in events.get_by_incident(conn, incident_id)
            if isinstance(written, CommunicationFailed)]


def _that_failure_says(conn: psycopg.Connection,
                       incident_id: str,
                       refusal: str,
                       channel: str,
                       about: str) -> Assertion[Any]:
    """The gap explained: which line was lost, where it was going, and why.

    All three together, because each alone leaves the reader guessing. Without
    the channel nobody knows which destination went quiet, without the refusal
    nobody knows whether to fix the token or the channel, and without the line
    it was about the timeline says only that something went unsaid.
    """
    def assertion(_: Any) -> bool:
        written = _the_failures_on(conn, incident_id)
        if not written:
            raise AssertionError("Expected a failure on the timeline, there is none.")

        said = written[0]
        if (said.refusal, said.channel, said.about_kind) != (refusal, channel, about):
            raise AssertionError(
                f"Expected [{refusal}] in [{channel}] about [{about}], got "
                f"[{said.refusal}] in [{said.channel}] about [{said.about_kind}]."
            )

        return True

    return assertion


def _the_messages_in(base_url: str, channel: str, count: int) -> Assertion[Any]:
    """How many messages one channel is holding, and only that channel.

    Counted per channel rather than in total, because the claim is about where
    lines went: two messages in the right place and two in the wrong one add
    up to the same total as four correct ones.
    """
    def assertion(_: Any) -> bool:
        held = [
            message for message in messages_posted_to(base_url)
            if message["channel"] == channel
        ]
        if len(held) != count:
            raise AssertionError(
                f"Expected {count} message(s) in [{channel}], got {len(held)}: {held}"
            )

        return True

    return assertion


def _the_only_message_in(base_url: str, channel: str, mentions: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = [
            message for message in messages_posted_to(base_url)
            if message["channel"] == channel
        ]
        if len(held) != 1:
            raise AssertionError(
                f"Expected one message in [{channel}] to read, got {len(held)}."
            )

        if mentions not in held[0]["text"]:
            raise AssertionError(
                f"Expected it to mention [{mentions}], it said [{held[0]['text']}]."
            )

        return True

    return assertion


def _slack_at(base_url: str) -> Slack:
    """The chat platform's adapter, aimed at `base_url` as the relay's process
    would aim it.

    A token because a workspace without one builds no platform, and an empty
    signing secret because nothing here reads a delivery.
    """
    return Slack(
        ChatSettings(slack_bot_token="xoxb-dont-care",
                     slack_base_url=base_url,
                     slack_signing_secret=""),
        client_of=WebClient,
        clock=utc_now
    )
