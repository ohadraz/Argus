"""The Investigator: what caused this incident, and what it read to say so.

The package's front door is `investigate`, which runs one investigation as a
conversation with the model, and `Findings`, which is what it hands back.
`Reading` travels with them: it is what the investigation retrieved, and what
a later round is told about the one before it.
"""

from __future__ import annotations

from argus_core.models.reading import Reading

from agent_investigator.investigation import Findings, investigate

__all__ = ["Findings", "Reading", "investigate"]
