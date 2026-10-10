"""How an incident reaches a human (spec §7.5).

Nothing in the walk calls anything here. Argus publishes what it does as it
does it, and `relaying` follows that log and says what is new somewhere a
person is - so an incident is reported because it happened, not because
whoever handled it remembered to say so.

Underneath that: `policy` decides which lines a human hears and how loudly, and
`saying` turns that into a message in the channel or a reply in the incident's
thread, through the chat platform's port - which is where the platform itself,
Slack today, is known. The log is followed through
`argus_incidents.following`, which every reader of it shares. `watching` is the
process that runs it.
"""

from agent_communicator.policy import Register, how_it_is_said
from agent_communicator.relaying import Destination, relay_once
from agent_communicator.saying import a_chat_destination

__all__ = [
    "Destination",
    "Register",
    "a_chat_destination",
    "how_it_is_said",
    "relay_once"
]
