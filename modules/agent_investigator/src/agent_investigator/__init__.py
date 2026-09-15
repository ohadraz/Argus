"""The Investigator: what caused this incident, and what it read to say so.

The package's front door is `investigate`, which runs one investigation as a
conversation with the model. `Findings`, which is what it hands back, and
`Reading`, which is what it read to get there, are named here as well - but
both are kernel contracts, because the walk that calls this names them too.

The three retrieval channels are not defaulted, so the three that build them are
doors as well. Each takes the connection a process holds to a tier and hands
back the channel asked over it, which is what a composition root needs and all
it needs: where a server is reached is a fact about a deployment, and nothing
under this door has any business reading it.
"""

from __future__ import annotations

from argus_core.models import Findings, Reading

from agent_investigator.investigation import investigate
from agent_investigator.retrieval import changes_over, logs_over, metrics_over

__all__ = [
    "Findings",
    "Reading",
    "changes_over",
    "investigate",
    "logs_over",
    "metrics_over"
]
