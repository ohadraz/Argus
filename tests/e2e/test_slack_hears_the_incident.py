from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import pytest
from argus_core.config import get_settings
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_FLAG_TOGGLE,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_returns_status,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with

"""What a person in Slack sees while Argus works, over a whole real incident.

Nothing in the walk posts anything. The relay follows the event log and says
what is new, so this is the one test that can fail for the reason that matters
most: an incident handled perfectly that nobody outside the dashboard ever
heard about.

Four things are asserted, and they are the registers the delivery policy has.
The incident opens with a message in the channel, because nobody can have
chosen to follow it yet. What Argus then found and did arrives as replies, out
of everyone else's way. How it ended goes back to the channel, addressed to the
people who never opened it.

The write-up it leaves behind is filed where postmortems are kept - here the
war room, no archive being configured - carrying a link to the page that holds
all of it.

And one thing is asserted by its absence: what Argus read. The retrievals are
the bulk of an incident's account and the least of its news, and a channel that
carried them would bury the four lines that matter.
"""

# What the account says while Argus is reading rather than concluding. Not one
# of these belongs in a channel, and the policy that decides so is only really
# tested where the sentences are real.
WHAT_READING_SOUNDS_LIKE = ("Asked for", "Read back", "Read the flag provider")


@pytest.mark.e2e
def test_slack_hears_an_incident_open_work_and_end() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_a_feature_flag_was_toggled_on()),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE)),
            said_before := _what_slack_already_holds()
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(all_of(
            argus_returns_status(HttpStatus.ACCEPTED),
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.RESOLVED),
                    _slack_was_told_the_alert_arrived(said_before, some_alert_name),
                    _slack_was_told_how_it_ended(said_before, IncidentStatus.RESOLVED),
                    _what_argus_did_arrived_as_replies(said_before),
                    _slack_was_not_told_what_argus_read(said_before),
                    _slack_was_given_the_postmortem(said_before)
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        ))


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    """The scenario that breaks the shop and is resolved by putting it back.

    Its own copy rather than another test module's: that one is private to its
    file, and a test reaching into another test module's `_name` is the same
    violation anywhere else in this repo.
    """
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "feature-flag-toggle"},
            timeout=10.0
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario


def _slack() -> str:
    """Where Slack is, as the relay was told it - the double, in this stack."""
    return get_settings().slack_base_url


def _posted() -> list[dict[str, Any]]:
    """Every message Slack holds, read back through the double's control seam."""
    answered: dict[str, Any] = httpx.get(f"{_slack()}/double-control/posted").json()
    held: list[dict[str, Any]] = answered["posted"]

    return held


def _what_slack_already_holds() -> int:
    """How much had been said before this test fired anything.

    Counted rather than reset, because the double serves the whole suite and a
    test that emptied it would be deleting what another test was about to
    assert on. Everything below reads only what arrived after this point.
    """
    return len(_posted())


def _said_since(already: int) -> list[dict[str, Any]]:
    return _posted()[already:]


def _slack_was_told_the_alert_arrived(already: int,
                                      alert_name: str) -> Assertion[httpx.Response]:
    """The opening line, in the channel itself.

    In the channel because nobody can have chosen to follow this incident yet -
    it is what there is to follow. A reply would reach only people who already
    knew.
    """
    def assertion(_: httpx.Response) -> bool:
        opening = [message for message in _said_since(already)
                   if alert_name in message["text"] and message["thread_ts"] is None]
        if not opening:
            raise AssertionError(
                f"expected a channel message naming [{alert_name}], got "
                f"{[message['text'] for message in _said_since(already)]}"
            )

        return True

    return assertion


def _slack_was_told_how_it_ended(already: int,
                                 ending: IncidentStatus) -> Assertion[httpx.Response]:
    """The closing line, back in the channel, naming the status it ended in."""
    def assertion(_: httpx.Response) -> bool:
        said = str(ending).upper()
        announced = [message for message in _said_since(already)
                     if said in message["text"] and message["thread_ts"] is None]
        if not announced:
            raise AssertionError(
                f"expected a channel message naming [{said}], got "
                f"{[message['text'] for message in _said_since(already)]}"
            )

        return True

    return assertion


def _what_argus_did_arrived_as_replies(already: int) -> Assertion[httpx.Response]:
    """The body of the incident, inside a conversation rather than beside it.

    Replies rather than channel messages, and all of them in the same one: an
    incident scattered across a channel is indistinguishable from several
    incidents, which is the state two concurrent failures would leave a reader
    in.
    """
    def assertion(_: httpx.Response) -> bool:
        replies = [message for message in _said_since(already)
                   if message["thread_ts"] is not None]
        if not replies:
            raise AssertionError(
                "expected what Argus found and did to arrive as thread replies, "
                f"every message went to the channel: "
                f"{[message['text'] for message in _said_since(already)]}"
            )

        threads = {message["thread_ts"] for message in replies}
        if len(threads) != 1:
            raise AssertionError(
                f"expected one conversation for this incident, its lines went "
                f"into {len(threads)}: {threads}"
            )

        return True

    return assertion


def _slack_was_not_told_what_argus_read(already: int) -> Assertion[httpx.Response]:
    """The retrievals, absent - which is the delivery policy, end to end."""
    def assertion(_: httpx.Response) -> bool:
        reading = [message["text"] for message in _said_since(already)
                   if message["text"].startswith(WHAT_READING_SOUNDS_LIKE)
                   or any(sounds in message["text"] for sounds in WHAT_READING_SOUNDS_LIKE)]
        if reading:
            raise AssertionError(
                f"expected nothing about what Argus read to reach Slack, got {reading}"
            )

        return True

    return assertion


def _slack_was_given_the_postmortem(already: int) -> Assertion[httpx.Response]:
    """The write-up itself, in the channel, linking to the page that holds it.

    In the channel rather than the thread, and in this stack the war room
    rather than an archive: no postmortem channel is configured, so the
    write-up lands where everything else did - which is the arrangement most
    teams will run, and the one where a separate channel cannot hide a bug.

    The link is asserted as a link rather than by its address. Where Argus
    answers is a deployment fact the suite has no opinion about; that a reader
    is given somewhere to go for the rest of it is the claim.
    """
    def assertion(_: httpx.Response) -> bool:
        write_ups = [message for message in _said_since(already)
                     if "Wrote the postmortem" in message["text"]
                     and message["thread_ts"] is None]
        if not write_ups:
            raise AssertionError(
                f"expected the postmortem in the channel, got "
                f"{[message['text'] for message in _said_since(already)]}"
            )

        if "/postmortem|" not in write_ups[0]["text"]:
            raise AssertionError(
                f"expected it to link to the page holding the whole write-up, "
                f"it said [{write_ups[0]['text']}]"
            )

        return True

    return assertion
