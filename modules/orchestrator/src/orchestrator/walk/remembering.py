"""Filing what this incident tried, for whichever incident comes after it.

Before the postmortem rather than after it, and a step of its own either way.
A postmortem is a document a person opens; this is a row nobody reads until an
incident like this one happens again, and the two are written from different
sources for different readers - joining them would make an unwritten document
into a missing memory.

Nothing downstream reads what this node produces, and nothing in this incident
is worse off if it fails: the incident is over. Which is exactly why a failure
here is swallowed and said out loud rather than raised - the postmortem after it
still has to be written, and a store that is down must not be the reason an
incident ends without its write-up.
"""

from __future__ import annotations

from argus_core.events import IncidentRemembered, Publisher, RememberingFailed, nobody, publish
from incident_memory.composing import a_memory_of
from incident_memory.describing import what_it_looked_like

from orchestrator.walk.deltas import StateDelta
from orchestrator.walk.ports import ActionsTaken, RememberIncident
from orchestrator.walk.state import IncidentState


def remembering_node(state: IncidentState,
                     actions_taken: ActionsTaken,
                     remember: RememberIncident,
                     publisher: Publisher = nobody) -> StateDelta:
    """Writes what was tried on this incident into long-term memory (spec §11.2).

    What is filed is the subjects Argus changed and what each change turned out
    to be worth. Nothing is filed where no attempt reached a verdict on a
    subject it named: the record's whole content is what attempts were worth, and
    an incident that produced none would be findable by a later search with
    nothing to tell it when found.

    Both collaborators are injected for the usual reason - what a record says
    belongs to `incident_memory`, where the rows are and where the record goes
    belong to a deployment - so this node's own logic can be tested without a
    database or a vector store.
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
        # Deliberately every exception. What can go wrong here is a store that
        # is down, a collection that will not take a payload, or a model that
        # will not load - and the walk's answer to all three is identical,
        # because none of them is a fact about the incident. Naming a narrower
        # family would be this node claiming to know which failures a store it
        # cannot see is capable of.
        publish(
            RememberingFailed(incident_id=state.incident_id, refusal=str(refused)),
            publisher
        )

        return StateDelta()

    publish(
        IncidentRemembered(
            incident_id=state.incident_id,
            subjects=[attempt.subject for attempt in record.tried]
        ),
        publisher
    )

    return StateDelta()
