"""The walk: the nodes an incident passes through, and the graph wiring them.

One module per node, each holding the node, its own helpers, and the router
that reads the state it produced. What every node asks of the world is in
`ports`; where those asks are answered is `graph`, which is the only module
here that names more than one node.
"""

from orchestrator.walk.choosing import (
    next_candidate_node,
    route_after_next_candidate,
)
from orchestrator.walk.closing import postmortem_node
from orchestrator.walk.fixing import codefix_node, route_after_codefix
from orchestrator.walk.gating import route_after_gate, tier_gate_node
from orchestrator.walk.graph import build_graph, recursion_limit
from orchestrator.walk.investigating import investigator_node, route_after_investigation
from orchestrator.walk.mitigating import mitigation_node, route_after_mitigation
from orchestrator.walk.narrating import Narration, with_status
from orchestrator.walk.proposing import mitigation_proposal_node
from orchestrator.walk.withdrawing import stopping_when_withdrawn

__all__ = [
    "Narration",
    "build_graph",
    "codefix_node",
    "investigator_node",
    "mitigation_node",
    "mitigation_proposal_node",
    "next_candidate_node",
    "postmortem_node",
    "recursion_limit",
    "route_after_codefix",
    "route_after_gate",
    "route_after_investigation",
    "route_after_mitigation",
    "route_after_next_candidate",
    "stopping_when_withdrawn",
    "tier_gate_node",
    "with_status"
]
