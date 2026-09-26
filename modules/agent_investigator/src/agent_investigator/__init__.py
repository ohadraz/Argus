"""The Investigator: what caused this incident, and what it read to say so.

The package's front door is `investigate`, which runs one investigation as a
conversation with the model. `Findings`, which is what it hands back, and
`Reading`, which is what it read to get there, are named here as well - but
both are kernel contracts, because the walk that calls this names them too.

None of the retrieval channels is defaulted, so the functions that build them are
doors as well. Each takes the connection a process holds to a tier and hands
back the channel asked over it, which is what a composition root needs and all
it needs: where a server is reached is a fact about a deployment, and nothing
under this door has any business reading it.

`BRIEF` and `investigator_tools` are doors for one reason and one caller: what
the eval measures is a *prompt*, so the prompt has to be part of what names the
population a sample belongs to. Held privately, the two changed without the
pool's identity changing, and a re-measure averaged a new prompt's samples with
an old prompt's under one digest - which is a rate for a configuration that never
ran. Nothing may read these to reproduce what the loop sends; `investigate` is
still the only way to run one.
"""

from __future__ import annotations

from argus_core.models import Findings, Reading

from agent_investigator.investigation import BRIEF, investigate
from agent_investigator.retrieval import (
    changes_over,
    dependencies_over,
    deployment_diffs_over,
    logs_over,
    metrics_over,
)
from agent_investigator.tools import investigator_tools

__all__ = [
    "BRIEF",
    "Findings",
    "Reading",
    "changes_over",
    "dependencies_over",
    "deployment_diffs_over",
    "investigate",
    "investigator_tools",
    "logs_over",
    "metrics_over"
]
