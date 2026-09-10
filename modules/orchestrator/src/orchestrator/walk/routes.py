"""The graph's edge keys - the vocabulary a router answers in.

Not statuses, though several are spelled like one: a router says which edge to
take, and `next_candidate` and `fixing` are edges no incident is ever *in*.
Named here rather than written twice because each one is stated in two places
that must agree - the router that returns it, and the mapping in `build_graph`
that resolves it to a node. A typo in either is a `KeyError` at walk time, in
whichever run first reaches that edge.
"""

from __future__ import annotations

from typing import Final

ESCALATED_ROUTE: Final = "escalated"
FIXING_ROUTE: Final = "fixing"
INVESTIGATING_ROUTE: Final = "investigating"
MITIGATING_ROUTE: Final = "mitigating"
NEXT_CANDIDATE_ROUTE: Final = "next_candidate"
RESOLVED_ROUTE: Final = "resolved"
WITHDRAWN_ROUTE: Final = "withdrawn"
