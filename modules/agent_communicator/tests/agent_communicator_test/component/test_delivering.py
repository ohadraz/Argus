from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import psycopg
import pytest
from agent_communicator.delivering import a_destination_per_register, a_slack_delivery
from agent_communicator.policy import Register
from agent_communicator.relaying import Delivery, Outcome
from agent_communicator.repository import threads
from agent_communicator.slack import a_slack_client
from argus_core.db import connect
from argus_core.events import (
    ActionTaken,
    CommunicationFailed,
    IncidentEvent,
    OnsetDetected,
    PostmortemWritten,
    StatusChanged,
)
from argus_core.models.alert import Alert
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import events, incidents
from argus_narration import a_narration_line
from argus_testkit import Assertion, Scenario, all_of, calling

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

A_WAR_ROOM = "C-war-room"

# Where write-ups are kept, which a team may well configure to be the war room
# itself. Separate here because two channels is the case that can go wrong.
AN_ARCHIVE = "C-postmortems"

# Where Argus answers, as somebody outside it would reach it. A test's own
# address rather than the configured one: a link is right or wrong regardless
# of where this run happens to be serving.
ARGUS_AT = "http://argus.example"


@pytest.mark.component
def test_an_announced_line_is_posted_to_the_channel(
        slack: str, a_clean_database: None) -> None:
    # Addressed to everyone, including whoever is not following this incident.
    # A reply would reach only the people who already know.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                deliver := _a_delivery_pointed_at(slack)
            ) \
            .when(lambda: deliver(incident_id,
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

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        deliver = _a_delivery_pointed_at(slack)

        Scenario() \
            .given(
                calling(lambda: deliver(incident_id,
                                        a_narration_line(_the_onset_of(incident_id)),
                                        Register.ANNOUNCED))
            ) \
            .when(lambda: threads.get(conn, incident_id, A_WAR_ROOM)) \
            .then(_it_is_the_thread_slack_opened(slack))


@pytest.mark.component
def test_a_followed_line_is_a_reply_in_the_incident_s_own_thread(
        slack: str, a_clean_database: None) -> None:
    # The body of an incident, kept out of everybody's way: following it is a
    # choice made once, rather than an interruption taken per line.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        deliver = _a_delivery_pointed_at(slack)

        Scenario() \
            .given(
                calling(lambda: deliver(incident_id,
                                        a_narration_line(_the_onset_of(incident_id)),
                                        Register.ANNOUNCED))
            ) \
            .when(lambda: deliver(incident_id,
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

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                deliver := _a_delivery_pointed_at(slack)
            ) \
            .when(lambda: deliver(incident_id,
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

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                deliver := _a_delivery_pointed_at(slack)
            ) \
            .when(lambda: deliver(incident_id,
                                  a_narration_line(_the_action_on(incident_id)),
                                  Register.FOLLOWED)) \
            .then(all_of(
                _that_message_names(slack, "Mitigation Agent"),
                _that_message_marks(slack, "monthly-spend-feature")
            ))


@pytest.mark.component
def test_a_message_refused_for_good_is_reported_as_never_landing(
        slack: str, a_clean_database: None) -> None:
    # A channel that is not there is not there on the next pass either. The
    # relay reads this as "pass over it" - answering that it landed would count
    # a line nobody saw, and answering "not now" would stop the account here
    # for as long as the workspace stays the way it is.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate")

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                deliver := _a_delivery_pointed_at(slack),
                calling(lambda: _slack_will_refuse(slack))
            ) \
            .when(lambda: deliver(incident_id,
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

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                deliver := _a_delivery_pointed_at(slack),
                calling(lambda: _slack_will_refuse(slack))
            ) \
            .when(lambda: deliver(incident_id,
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

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()

        Scenario() \
            .given(
                deliver := a_destination_per_register(
                    _a_delivery_pointed_at(slack),
                    _a_delivery_pointed_at(slack, channel=AN_ARCHIVE)
                )
            ) \
            .when(lambda: [
                deliver(incident_id,
                        a_narration_line(_the_incident_ending(incident_id)),
                        Register.ANNOUNCED),
                deliver(incident_id,
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

    with connect() as conn:
        incident_id = incidents.create(conn, some_alert)
        conn.commit()
        its_page = f"{ARGUS_AT}/incidents/{incident_id}/postmortem"

        Scenario() \
            .given(
                deliver := a_destination_per_register(
                    _a_delivery_pointed_at(slack),
                    _a_delivery_pointed_at(slack, channel=AN_ARCHIVE),
                    argus_at=ARGUS_AT,
                    filed_in=AN_ARCHIVE
                )
            ) \
            .when(lambda: deliver(incident_id,
                                  a_narration_line(_the_write_up_of(incident_id)),
                                  Register.FILED)) \
            .then(all_of(
                _the_only_message_in(slack, AN_ARCHIVE, mentions="Wrote the postmortem"),
                _the_only_message_in(slack, AN_ARCHIVE, mentions=its_page),
                _the_only_message_in(slack, A_WAR_ROOM, mentions=AN_ARCHIVE),
                _the_only_message_in(slack, A_WAR_ROOM, mentions=its_page)
            ))


def _a_delivery_pointed_at(base_url: str, channel: str = A_WAR_ROOM) -> Delivery:
    return a_slack_delivery(connect,
                            channel=channel,
                            slack=a_slack_client(base_url=base_url))


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
    httpx.post(f"{base_url}/double-control/seed",
               json={"error": "channel_not_found"}).raise_for_status()


def _posted(base_url: str) -> list[dict[str, Any]]:
    """Every message the double accepted, read back through its control seam."""
    answered: dict[str, Any] = httpx.get(f"{base_url}/double-control/posted").json()
    held: list[dict[str, Any]] = answered["posted"]

    return held


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
        held = _posted(base_url)
        if len(held) != 1:
            raise AssertionError(f"Expected one message in Slack, got {len(held)}: {held}")

        return True

    return assertion


def _slack_holds_nothing(base_url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = _posted(base_url)
        if held:
            raise AssertionError(f"Expected nothing delivered, Slack holds {held}")

        return True

    return assertion


def _that_message_went_to(base_url: str, channel: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        addressed = [message["channel"] for message in _posted(base_url)]
        if addressed != [channel]:
            raise AssertionError(f"Expected it addressed to [{channel}], got {addressed}")

        return True

    return assertion


def _that_message_was_not_a_reply(base_url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = _posted(base_url)
        replied_to = [message["thread_ts"] for message in held]
        if any(replied_to):
            raise AssertionError(
                f"Expected a message to the channel itself, it replied to {replied_to}"
            )

        return True

    return assertion


def _the_last_message_replied_to_the_first(base_url: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = _posted(base_url)
        if len(held) != 2:
            raise AssertionError(f"Expected two messages in Slack, got {len(held)}: {held}")

        if held[-1]["thread_ts"] != held[0]["ts"]:
            raise AssertionError(
                f"Expected a reply in thread [{held[0]['ts']}], it replied to "
                f"[{held[-1]['thread_ts']}]"
            )

        if held[-1]["channel"] != held[0]["channel"]:
            raise AssertionError(
                f"Expected the reply in [{held[0]['channel']}], it went to "
                f"[{held[-1]['channel']}]"
            )

        return True

    return assertion


def _that_message_names(base_url: str, who: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        said = _posted(base_url)[-1]["text"]
        if who not in said:
            raise AssertionError(f"Expected [{who}] named in [{said}]")

        return True

    return assertion


def _that_message_marks(base_url: str, word: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        said = _posted(base_url)[-1]["text"]
        if f"*{word}*" not in said:
            raise AssertionError(f"Expected [*{word}*] marked in [{said}]")

        return True

    return assertion


def _it_is_the_thread_slack_opened(base_url: str) -> Assertion[str | None]:
    def assertion(remembered: str | None) -> bool:
        held = _posted(base_url)
        if not held:
            raise AssertionError("Expected a message in Slack to compare the thread against")

        if remembered != held[0]["ts"]:
            raise AssertionError(
                f"Expected the incident to be in thread [{held[0]['ts']}], "
                f"it is in [{remembered}]"
            )

        return True

    return assertion


def _the_incident_now_has_a_thread(conn: psycopg.Connection,
                                   incident_id: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        if threads.get(conn, incident_id, A_WAR_ROOM) is None:
            raise AssertionError(
                "Expected the message that went to the channel to become the "
                "incident's thread, it was not remembered"
            )

        return True

    return assertion


def _the_incident_has_no_thread(conn: psycopg.Connection,
                                incident_id: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        remembered = threads.get(conn, incident_id, A_WAR_ROOM)
        if remembered is not None:
            raise AssertionError(
                f"Expected no thread for a message nobody received, got [{remembered}]"
            )

        return True

    return assertion


def _the_failures_on(conn: psycopg.Connection,
                     incident_id: str) -> list[CommunicationFailed]:
    """Every line this incident's timeline says could not be delivered."""
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
        held = [message for message in _posted(base_url) if message["channel"] == channel]
        if len(held) != count:
            raise AssertionError(
                f"Expected {count} message(s) in [{channel}], got {len(held)}: {held}"
            )

        return True

    return assertion


def _the_only_message_in(base_url: str, channel: str, mentions: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        held = [message for message in _posted(base_url) if message["channel"] == channel]
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
