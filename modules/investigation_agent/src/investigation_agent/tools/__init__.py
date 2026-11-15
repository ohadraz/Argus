"""What the Investigator may ask for, and what happens when it asks.

Two halves of one boundary. `investigator_tools` is the offer - every tool the
model is ever given, all of them reads - and `Dispatcher` is what turns a call
into a retrieval and its answer back into something the model can read. The
Investigator is read-only because that list is the whole of what it possesses,
not because a prompt asks it to behave.

One module per channel, each holding both halves of that channel: the tool as
it is offered and the code that serves it. They are the pair that has to agree
- a schema offering an argument nothing reads, or a dispatcher reading one
nothing offers, is the bug this layout is arranged to make visible - and
splitting definitions from handlers would have put each half of that agreement
in a different file.
"""

from __future__ import annotations

from investigation_agent.tools.answer import ANSWER_TOOL, HYPOTHESES_ARG
from investigation_agent.tools.changes import CHANGES_TOOL
from investigation_agent.tools.dependencies import DEPENDENCIES_TOOL
from investigation_agent.tools.deployments import DEPLOYMENT_DIFF_TOOL
from investigation_agent.tools.dispatch import Dispatcher
from investigation_agent.tools.logs import LOGS_TOOL
from investigation_agent.tools.metrics import METRICS_TOOL
from investigation_agent.tools.offer import (
    READ_TIER_HELD,
    ReadTierTools,
    investigator_tools,
    read_tier_tools_over,
)
from investigation_agent.tools.rollouts import ROLLOUT_TOOL

__all__ = [
    "ANSWER_TOOL",
    "CHANGES_TOOL",
    "DEPENDENCIES_TOOL",
    "DEPLOYMENT_DIFF_TOOL",
    "HYPOTHESES_ARG",
    "LOGS_TOOL",
    "METRICS_TOOL",
    "READ_TIER_HELD",
    "ROLLOUT_TOOL",
    "Dispatcher",
    "ReadTierTools",
    "investigator_tools",
    "read_tier_tools_over"
]
