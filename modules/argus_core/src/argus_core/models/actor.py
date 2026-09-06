from __future__ import annotations

from enum import StrEnum


class Actor(StrEnum):
    """Who did the thing a row records - the Orchestrator, one of the five
    sub-agents spec §7 names, or whoever stopped them.

    Every node in the graph belongs to exactly one of these, fixed when the
    graph is assembled. A row's actor comes from that registration rather than
    from the node itself, which is one fewer thing a node can be wrong about.

    `human` is the one that belongs to no node, and exists because a withdrawal
    does: an incident taken back from Argus is the single row Argus writes
    about something it did not decide, and attributing it to the Orchestrator
    would have the timeline say Argus chose to stop itself.
    """

    ORCHESTRATOR = "orchestrator"
    HUMAN = "human"
    INVESTIGATOR = "investigator"
    MITIGATION = "mitigation"
    CODEFIX = "codefix"
    COMMUNICATOR = "communicator"
    POSTMORTEM = "postmortem"
