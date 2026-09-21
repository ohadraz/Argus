"""How this deployment is configured, as a test says it.

Stated here rather than read from the environment. Every window, bound and
threshold below is a number a test can reason about, and one taken from
whatever `.env` happens to hold would make an assertion about a window agree
with itself whatever either said.

Generous where a bound is not the point, for the reason `a_budget` is: a
ceiling that binds in a test which never mentioned it ends the investigation
for a reason the failure does not name.
"""

from __future__ import annotations

from agent_investigator.budget import InvestigationSettings
from argus_core.anomaly import AnomalyThresholds
from argus_core.models import Effort

A_LOOKBACK_IN_MINUTES = 30
A_LOOKAHEAD_IN_MINUTES = 10
A_LOG_CEILING_IN_MINUTES = 180
A_CHANGE_LOOKBACK_IN_MINUTES = 1440

ROOM_TO_SPARE_IN_TOOL_CALLS = 99
ROOM_TO_SPARE_IN_TOKENS = 1_000_000
ROOM_TO_SPARE_IN_SECONDS = 3600.0

# Where the algorithm draws its lines. The same numbers the environment carries
# by default, stated here so that an assertion about an onset is arithmetic on
# values the test can see.
SOME_DEVIATIONS_FROM_BASELINE = 3.0
SOME_PERSISTENCE_IN_MINUTES = 2
SOME_RECOVERY_FRACTION = 0.8

# Which model a test's deployment names, and how hard it asks it to think.
# Deliberately not the production defaults: a test asserting that the
# configured model is the one asked for would pass against a loop that ignored
# the setting entirely, if the setting happened to say what the code would
# have said anyway.
SOME_MODEL = "claude-sonnet-5"
SOME_EFFORT: Effort = "medium"


def some_investigation_settings(
    tool_calls: int = ROOM_TO_SPARE_IN_TOOL_CALLS,
    tokens: int = ROOM_TO_SPARE_IN_TOKENS,
    seconds: float = ROOM_TO_SPARE_IN_SECONDS,
    model: str = SOME_MODEL,
    effort: Effort = SOME_EFFORT,
    lookback_minutes: int = A_LOOKBACK_IN_MINUTES,
    lookahead_minutes: int = A_LOOKAHEAD_IN_MINUTES,
    log_ceiling_minutes: int = A_LOG_CEILING_IN_MINUTES,
    change_lookback_minutes: int = A_CHANGE_LOOKBACK_IN_MINUTES
) -> InvestigationSettings:
    """What one investigation may spend, and how wide it may look.

    Not `some_windows` - `model.py` already has one of those, and it is a list
    of window arguments a scripted model asks with. Two different things, and
    one suite imports both.
    """
    return InvestigationSettings(
        investigation_max_tool_calls=tool_calls,
        investigation_max_tokens=tokens,
        investigation_max_seconds=seconds,
        investigation_model=model,
        investigation_effort=effort,
        log_initial_lookback_minutes=lookback_minutes,
        log_initial_lookahead_minutes=lookahead_minutes,
        log_max_window_minutes=log_ceiling_minutes,
        change_lookback_minutes=change_lookback_minutes
    )


def some_thresholds(
    deviations: float = SOME_DEVIATIONS_FROM_BASELINE,
    persistence_minutes: int = SOME_PERSISTENCE_IN_MINUTES,
    recovery_fraction: float = SOME_RECOVERY_FRACTION
) -> AnomalyThresholds:
    """What counts as an incident starting, and what counts as recovery."""
    return AnomalyThresholds(
        deviations_from_baseline=deviations,
        persistence_minutes=persistence_minutes,
        recovery_fraction_of_the_rise=recovery_fraction
    )
