"""What one attempt at a fix is aimed and bounded by.

The settings a deployment decides about a fix, and the arithmetic that holds the
loop to them. Declared here rather than beside the loop because everything else
in this agent reads them - the tools it is offered and the message it opens with
both turn on `code_search` - and the loop is the one module that may depend on all
of them.
"""

from __future__ import annotations

from argus_core import SettingsSlice
from argus_core.budget import Budget
from argus_core.models import CodeSearch, Effort


class FixSettings(SettingsSlice):
    """What the fix loop is aimed and bounded by.

    `github_base_branch` is what a fix is cut from and proposed onto - the
    branch that is actually deployed, since a fix against anything else patches
    a repository nobody is running.
    """

    github_base_branch: str
    # Three bounds rather than one, for the reason the investigation has
    # three: they fail differently and none implies the others. This
    # agent is the case a call count alone cannot see - it reads whole
    # files and writes whole files, so a run can be frugal in calls and
    # ruinous in tokens. Measured, one that reads the three largest files
    # in the Target Service carries 47,950 tokens of source for every
    # remaining turn.
    #
    # Calls rather than turns, because a model may ask for several files
    # at once and a bound counting turns would let it read several times
    # what it was allowed while still looking healthy.
    codefix_max_tool_calls: int
    codefix_max_tokens: int
    codefix_max_seconds: float
    # Which model writes the fix and how hard it is asked to think. Here
    # with the bound rather than anywhere else because both are what a
    # deployment decides about one attempt at a fix, and both are read once
    # when the loop starts. This is the agent the choice matters most for:
    # its answers are whole files, which is the workload where the higher
    # efforts earn their cost and the cheaper models most obviously do not.
    codefix_model: str
    codefix_effort: Effort
    # Whole files, so far more room than any other agent needs, and past
    # the line where the answer has to be streamed to arrive at all.
    codefix_max_output_tokens: int
    # Which ways of finding code this deployment has, and so which the model
    # is offered. Both in production, where the model chooses per question;
    # one alone where the benchmark is comparing them, or where nothing builds
    # an index and a tool that could only ever answer nothing would teach the
    # model that the cause is not in the code.
    code_search: CodeSearch


def a_budget_for(settings: FixSettings) -> Budget:
    """What one attempt at a fix may spend, as this deployment configures it.

    Beside the settings it reads rather than on `Budget`, which is the
    kernel's and knows none of its callers by name. The investigator has one
    of these too, over fields of its own - what the two share is the
    arithmetic, not what their numbers are called.
    """
    return Budget(
        max_tool_calls=settings.codefix_max_tool_calls,
        max_tokens=settings.codefix_max_tokens,
        max_seconds=settings.codefix_max_seconds
    )
