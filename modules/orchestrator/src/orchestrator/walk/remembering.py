"""Filing what this incident tried, for whichever incident comes after it.

Before the postmortem rather than after it, and a step of its own either way.
A postmortem is a document a person opens; this is a row nobody reads until an
incident like this one happens again, and the two are written from different
sources for different readers - joining them would make an unwritten document
into a missing memory.

Filed rather than kept: what is written here is a row the fence can refuse, and
the store a later walk searches is filled from the rows by a process of its own.
A walk whose run was taken back writes nothing over the record of the walk that
holds it now.

Nothing downstream reads what this node produces, and nothing in this incident
is worse off if it fails: the incident is over. Which is exactly why a failure
here is swallowed and said out loud rather than raised - the postmortem after it
still has to be written, and a filing that failed must not be the reason an
incident ends without its write-up. All but a lost run, which is not this
incident's failure to say.
"""

from __future__ import annotations

import logging

from argus_core import was_lost
from argus_core.events import IncidentRemembered, Publisher, RememberingFailed, nobody, publish
from incident_memory.composing import a_memory_of
from incident_memory.describing import what_it_looked_like

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.ports import ActionsTaken, RememberIncident
from orchestrator.walk.state import IncidentState

logger = logging.getLogger(__name__)


def remembering_node(state: IncidentState,
                     actions_taken: ActionsTaken,
                     remember: RememberIncident,
                     publisher: Publisher = nobody) -> StateDelta:
    """Files what was tried on this incident for long-term memory (spec §11.2).

    What is filed is the actions Argus took and what each one turned out to be
    worth - the kind and the subject together, because a later walk matches
    what it would do against what was done, and half a key matches sometimes.
    Nothing is filed where no attempt reached a verdict on a subject it named:
    the record's whole content is what attempts were worth, and an incident
    that produced none would be findable by a later search with nothing to tell
    it when found.

    Said once the record is filed, which is the moment it is on its way: the
    deliverer carries every filed record to the store, and nothing this walk
    does afterwards changes whether it gets there.

    Both collaborators are injected for the usual reason - what a record says
    belongs to `incident_memory`, where the rows are belongs to a deployment -
    so this node's own logic can be tested without a database.
    """
    record = a_memory_of(
        state.incident_id,
        state.alert,
        actions_taken(state.incident_id),
        what_it_looked_like(state.alert, state.hypothesis)
    )

    if record is None:
        return StateDelta()

    try:
        remember(record)
    except Exception as refused:
        # Deliberately every exception. What can go wrong here is a database
        # that is down or a row it will not take, and the walk's answer to both
        # is identical, because neither is a fact about the incident. Naming a
        # narrower family would be this node claiming to know which failures a
        # filing it cannot see is capable of.
        #
        # Except a lost run, which is no failure of the filing: the fence
        # refused the row because a newer claim walks this incident, and a line
        # saying its memory could not be filed would be said on that walk's
        # timeline, for it.
        if was_lost(refused):
            raise

        logger.warning("incident could not be remembered", exc_info=True)
        publish(
            RememberingFailed(incident_id=state.incident_id, refusal=str(refused)),
            publisher
        )

        return StateDelta()

    publish(
        IncidentRemembered(
            incident_id=state.incident_id,
            tried=[attempt.identity for attempt in record.tried]
        ),
        publisher
    )
    logger.info("incident remembered", extra={"attempts": len(record.tried)})

    return StateDelta()
