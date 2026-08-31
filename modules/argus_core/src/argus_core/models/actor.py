from __future__ import annotations

from enum import StrEnum


class Actor(StrEnum):
    """Who did the thing a row records - the Orchestrator, or one of the five
    sub-agents spec §7 names.

    Every node in the graph belongs to exactly one of these, fixed when the
    graph is assembled. A row's actor comes from that registration rather than
    from the node itself, which is one fewer thing a node can be wrong about.
    """

    ORCHESTRATOR = "orchestrator"
    INVESTIGATOR = "investigator"
    MITIGATION = "mitigation"
    CODEFIX = "codefix"
    COMMUNICATOR = "communicator"
    POSTMORTEM = "postmortem"
