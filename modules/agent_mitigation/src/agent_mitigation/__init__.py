from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from argus_core.anomaly import has_recovered_since
from argus_core.config import get_settings
from argus_core.models.hypothesis import Hypothesis
from argus_core.timestamps import to_iso_minute

from agent_mitigation.actions import (
    REVERT_FEATURE_FLAG,
    Action,
    Outcome,
    Verdict,
    propose_action,
)
from agent_mitigation.tools import (
    Clock,
    FlagChangeFetcher,
    FlagSetter,
    MetricsFetcher,
    Sleeper,
    fetch_recent_flag_changes,
    fetch_recent_metrics,
    set_flag,
    utc_now,
)

__all__ = [
    "REVERT_FEATURE_FLAG",
    "Action",
    "Outcome",
    "Verdict",
    "mitigate",
    "propose_action",
    "take_action",
]

ActionTaker = Callable[[Action], Outcome]

# How often the service is re-read while waiting for it to answer an action.
# Metrics are aggregated per minute, so a tighter interval only re-reads the
# same four numbers; a looser one spends the verification budget waiting.
_SECONDS_BETWEEN_METRIC_READS = 10.0


def take_action(action: Action,
                set_state: FlagSetter = set_flag,
                fetch_metrics: MetricsFetcher = fetch_recent_metrics,
                now: Clock = utc_now,
                sleep: Sleeper = time.sleep) -> Outcome:
    """Performs `action` and answers with what the service then did (spec §7.3).

    Three things happen in order, and the order is the point. The flag is set,
    which is the only moment production state changes. The service is re-read
    until a minute that began *after* that moment can be judged - the newest
    bucket covers the minute in progress, aggregated over seconds that are
    mostly pre-action, so a verdict read off it describes the incident rather
    than the mitigation. And a refuted action is put back.

    The verdict rests on the same departure rule that located the onset, so
    Mitigation and the Investigator cannot disagree about whether a given
    minute was healthy - two agents that could would be two incidents.

    An action that could not be taken at all is `ESCALATED`, not `REFUTED`:
    nothing was changed, so there is nothing to judge and nothing to undo, and
    a verdict here would describe an experiment that never ran.
    """
    try:
        undo_descriptor = set_state(action.flag, action.enabled)
    except Exception as error:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=f"could not set flag [{action.flag}]: {error}",
        )

    if _the_service_recovered(fetch_metrics, now, sleep):
        return Outcome(
            verdict=Verdict.CONFIRMED,
            detail=(
                f"set flag [{action.flag}] {_state_name(action.enabled)} "
                f"and the service returned to baseline"
            ),
            undo_descriptor=undo_descriptor,
        )

    return _undone(action, undo_descriptor, set_state)


def mitigate(hypothesis: Hypothesis,
             fetch_flag_changes: FlagChangeFetcher = fetch_recent_flag_changes,
             take: ActionTaker = take_action) -> Outcome:
    """Answers `hypothesis` with a reversible action and a verdict (spec §7.3).

    Takes the whole `Hypothesis` rather than its summary text because
    `cause_type` is what selects the action - deterministically, in code. A
    summary is prose written for a human, and deriving a production write from
    it would mean parsing or a second model call.

    This composes the two halves for callers that have no gate to run between
    them. The Orchestrator does have one (§13), and calls `propose_action` and
    `take_action` either side of it instead.
    """
    action = propose_action(hypothesis, fetch_flag_changes())

    if action is None:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=f"no reversible action answers a cause of [{hypothesis.cause_type}]",
        )

    return take(action)


def _the_service_recovered(fetch_metrics: MetricsFetcher,
                           now: Clock,
                           sleep: Sleeper) -> bool:
    """Whether the service returns to baseline within the time allowed.

    False on expiry rather than an error, because that is a real answer about
    the world: the action was taken and did not visibly help in the time it was
    given. Calling it an error would route an incident to a human over what is
    ordinary evidence against a hypothesis.
    """
    settings = get_settings()
    started_at = now()
    deadline = started_at + timedelta(
        seconds=settings.mitigation_verification_timeout_seconds
    )
    # The first minute that began after the action. The minute the action fell
    # inside is aggregated over seconds either side of it and can only blur the
    # two states together.
    first_whole_minute = to_iso_minute(started_at + timedelta(minutes=1))

    while True:
        if has_recovered_since(fetch_metrics(), first_whole_minute):
            return True

        if now() >= deadline:
            return False

        sleep(_SECONDS_BETWEEN_METRIC_READS)


def _undone(action: Action,
            undo_descriptor: dict[str, Any],
            set_state: FlagSetter) -> Outcome:
    """Puts a refuted action back, and says so.

    A refuted action was taken on a hypothesis the evidence has not borne out,
    so leaving its change in place would mean production state was altered for
    a cause that was not the cause, with nobody told. The restore reads the
    state from the descriptor the write tier returned rather than assuming the
    inverse of what was set - the descriptor is the record of what actually
    changed.

    A restore that itself fails escalates carrying both facts. An environment
    left in a state Argus cannot account for is precisely what a human needs
    paging for, and the page has to say both what was changed and that putting
    it back did not work.
    """
    was_enabled = bool(undo_descriptor["was_enabled"])
    taken = f"set flag [{action.flag}] {_state_name(action.enabled)}"

    try:
        set_state(action.flag, was_enabled)
    except Exception as error:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=(
                f"{taken}, the service did not recover, and it could not be put "
                f"back {_state_name(was_enabled)}: {error}"
            ),
            undo_descriptor=dict(undo_descriptor),
        )

    return Outcome(
        verdict=Verdict.REFUTED,
        detail=(
            f"{taken}, the service did not recover, so it was put back "
            f"{_state_name(was_enabled)}"
        ),
        undo_descriptor=dict(undo_descriptor),
    )


def _state_name(enabled: bool) -> str:
    return "on" if enabled else "off"
