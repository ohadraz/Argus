"""How an incident reaches a human (spec §7.5).

Nothing in the walk calls anything here. Argus publishes what it does as it
does it, and `relaying` follows that log and says what is new somewhere a
person is - so an incident is reported because it happened, not because
whoever handled it remembered to say so.

Underneath that: `policy` decides which lines a human hears and how loudly,
`delivering` turns that into a Slack message or a reply in the incident's
thread, `slack` is the one module that knows Slack exists, and `following`
plugs the relay into the event log. `watching` is the process that runs it.
"""

from agent_communicator.delivering import a_slack_delivery
from agent_communicator.following import events_since, place_for
from agent_communicator.policy import Register, how_it_is_said
from agent_communicator.relaying import SLACK_RELAY, Backlog, Delivery, Place, relay_once
from agent_communicator.slack import a_slack_client, post_message
from agent_communicator.watching import watch_forever

__all__ = [
    "SLACK_RELAY",
    "Backlog",
    "Delivery",
    "Place",
    "Register",
    "a_slack_client",
    "a_slack_delivery",
    "events_since",
    "how_it_is_said",
    "place_for",
    "post_message",
    "relay_once",
    "watch_forever"
]
