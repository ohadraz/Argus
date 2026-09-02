"""Every tool the Investigator is offered, assembled in one place.

The tier boundary is this list. The Investigator is read-only because of what
it possesses, not because a prompt asks it to behave, so a write tool
appearing here is the one failure in this package that matters most - and the
reason the offered set is asserted in a test rather than assumed.
"""

from __future__ import annotations

from argus_core.models.tool_definition import ToolDefinition

from agent_investigator.tools.answer import answer_tool
from agent_investigator.tools.changes import changes_tool
from agent_investigator.tools.logs import logs_tool
from agent_investigator.tools.metrics import metrics_tool


def investigator_tools() -> list[ToolDefinition]:
    """Every tool the Investigator is offered, and nothing else.

    Three retrievals and one way to finish. Each retrieval takes its own
    optional window, because which minutes are worth reading is the model's
    decision to make once it has seen something - and leaving a window out is
    also a decision, answered by each channel's own default rather than by the
    model guessing at an anchor it was already told.
    """
    return [metrics_tool(), logs_tool(), changes_tool(), answer_tool()]
