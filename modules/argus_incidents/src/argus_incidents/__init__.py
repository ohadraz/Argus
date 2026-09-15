"""The incident record: the tables, and what is done to an incident that is
not the walk.

Three operations behind one public name. `intake` takes an alert and makes an
incident of it, `withdrawal` stops one and answers whether anybody still wants
it walked, and `publishing` is the one subscriber the event stream has - where
an event is written on the connection its decision is written on.

`repository` is deliberately not flattened into this namespace. Its modules are
named for the tables they own and are meant to be read that way -
`incidents.get`, `runs.claim`, `events.record` - and a flat door would have to
rename half of them to keep `record` from meaning four things. A caller reaches
one as `from argus_incidents.repository import incidents`, which is how the
layering contract already spells what this module may be reached by.

That leaves the reads coarser than they should be: a caller still asks for rows
by table rather than for the incident's story, and the repository is public to
everything that can name this package. Narrowing it is a design change - a
reads API returning domain values, with the tables behind it - and not one a
refactor gets to make on the way past.
"""

from __future__ import annotations

from argus_incidents.intake import start_incident
from argus_incidents.publishing import (
    PublisherFor,
    acknowledge_alert,
    calls_into,
    events_into,
    events_into_connection,
    publish_beside,
)
from argus_incidents.withdrawal import IsStillWanted, wanted_via, withdraw_incident

__all__ = [
    "IsStillWanted",
    "PublisherFor",
    "acknowledge_alert",
    "calls_into",
    "events_into",
    "events_into_connection",
    "publish_beside",
    "start_incident",
    "wanted_via",
    "withdraw_incident"
]
