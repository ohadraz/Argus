"""The process that watches the event log and keeps the chat up to date.

It does one thing in a loop: look at the log, say what is new, move on. Nothing
calls it and it calls nothing in the walk - the two share a table and no code,
which is what lets an incident be reported by a process that was restarted
halfway through it.

A process of its own rather than a thread inside the worker: a worker walking
an incident is busy for minutes at a time, and a relay sharing that process
would go quiet exactly while an incident was most worth hearing about.
"""

from __future__ import annotations

import time

from incident_record import Backlog, Place

from communication.relaying import Destination, relay_once


def watch_forever(backlog: Backlog,
                  place: Place,
                  say: Destination,
                  pause: float) -> None:
    """Says what is new for as long as the process lives.

    Looks again immediately after saying anything and waits only when it found
    nothing: the pause is the delay between something happening and a person
    hearing about it, and paying it between two lines that were already waiting
    would add it to every one of them.

    Nothing here catches anything. A pass that fails on the database fails the
    process, and the place it kept is what makes that harmless - a relay
    restarted carries on from the last line anybody saw, saying at worst one
    line twice.
    """
    while True:
        if not relay_once(backlog, place, say):
            time.sleep(pause)
