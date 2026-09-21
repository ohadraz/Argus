from __future__ import annotations

import time
from collections.abc import Callable

from argus_core import SettingsSlice
from argus_core.budget import Bound, Budget
from argus_core.models import Effort


class InvestigationSettings(SettingsSlice):
    """What one investigation may spend, and how wide it may look.

    Declared here rather than beside the windows because this is the lower of
    the two modules that read it - `tools.windows` imports from here, never the
    other way about.

    The three bounds fail differently and none implies the others; the
    reasoning is on `Budget` below, which enforces them. The window fields are
    the defaults a channel reaches for when the model names none, and the
    change lookback is deliberately unrelated to the log ones: how far back a
    *cause* may lie is the operator's judgement, where a log window is what the
    read tier can afford to serve.
    """

    investigation_max_tool_calls: int
    investigation_max_tokens: int
    investigation_max_seconds: float
    # Which model answers this agent and how hard it is asked to think. Here
    # beside the bounds rather than anywhere else for the same reason they
    # are: both are what a deployment decides about one investigation, and
    # both are read once when the loop starts rather than per turn.
    #
    # The loop does not read these. It hands them to whatever builds its
    # conversation, exactly as it hands the bounds to `Budget.from_settings`,
    # and goes on holding a seam that knows of no model and no effort.
    investigation_model: str
    investigation_effort: Effort
    log_initial_lookback_minutes: int
    log_initial_lookahead_minutes: int
    log_max_window_minutes: int
    change_lookback_minutes: int


def a_budget_for(settings: InvestigationSettings,
                 now: Callable[[], float] = time.monotonic) -> Budget:
    """The budget one investigation gets, as this deployment configures it.

    Here rather than on `Budget` itself, which moved to the kernel when
    Code-Fix came to need the same three bounds. What the two agents share is
    the arithmetic; what they do not share is what their numbers are called,
    and a kernel that knew `investigation_max_tool_calls` would be a kernel
    that knew one of its callers by name.

    Read once, here, rather than per check: how far an investigation may reach
    is a property of the deployment, and a budget that re-read its settings
    could change bound mid-incident.
    """
    return Budget(
        max_tool_calls=settings.investigation_max_tool_calls,
        max_tokens=settings.investigation_max_tokens,
        max_seconds=settings.investigation_max_seconds,
        now=now
    )


# Re-exported rather than re-declared. The bounds moved to the kernel when
# Code-Fix needed the same three, and this is still where the investigator's
# own numbers live - so a reader who comes looking for what bounds an
# investigation finds both halves in one place, and every caller that already
# named them here goes on working.
__all__ = ["Bound", "Budget", "InvestigationSettings", "a_budget_for"]
