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
# Where an incident goes once Code-Fix has had its turn, however that turn went.
# Named for the destination rather than for an outcome, because by then the
# outcome is the status's to carry and every one of them gets written up - the
# incident nothing could be done for most of all.
POSTMORTEM_ROUTE: Final = "postmortem"
WITHDRAWN_ROUTE: Final = "withdrawn"
