"""The Investigator: what caused this incident, and what it read to say so.

The package's front door is `investigate`, which runs one investigation as a
conversation with the model. `Findings`, which is what it hands back, and
`Reading`, which is what it read to get there, are named here as well - but
both are kernel contracts, because the walk that calls this names them too.
"""

from __future__ import annotations

from argus_core.models import Findings, Reading

from agent_investigator.investigation import investigate

__all__ = ["Findings", "Reading", "investigate"]
