"""Every tool the Investigator is offered, assembled in one place.

The tier boundary is this list. The Investigator is read-only because of what
it possesses, not because a prompt asks it to behave, so a write tool
appearing here is the one failure in this package that matters most - and the
reason the offered set is asserted in a test rather than assumed.
"""

from __future__ import annotations

from argus_core.models import ToolDefinition

from agent_investigator.tools.answer import answer_tool
from agent_investigator.tools.changes import changes_tool
from agent_investigator.tools.dependencies import dependencies_tool
from agent_investigator.tools.deployments import deployment_diff_tool
from agent_investigator.tools.logs import logs_tool
from agent_investigator.tools.metrics import metrics_tool


def investigator_tools() -> list[ToolDefinition]:
    """Every tool the Investigator is offered, and nothing else.

    Five retrievals and one way to finish, in three shapes. Three take their own
    optional window, because which minutes are worth reading is the model's
    decision to make once it has seen something - and leaving a window out is also
    a decision, answered by each channel's own default rather than by the model
    guessing at an anchor it was already told.

    The register takes nothing at all, and the asymmetry is the point rather than
    an oversight: what a service calls is a fact about how it is built, so there
    is no window to name and no default to fall back on.

    The deployment channel is the third shape - no window, but a subject. What a
    deployment changed has nothing to date either, and there is more than one
    deployment, so the one being asked about is named. It is the only channel whose
    argument comes out of another channel's answer.
    """
    return [
        metrics_tool(),
        logs_tool(),
        changes_tool(),
        dependencies_tool(),
        deployment_diff_tool(),
        answer_tool()
    ]
