from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from argus_core.anomaly import has_recovered_since
from argus_core.config import get_settings
from argus_core.events import (
    AwaitingRecovery,
    Publisher,
    RecoveryChecked,
    nobody,
    publish,
)
from argus_core.models.hypothesis import Hypothesis
from argus_core.timestamps import to_iso_minute

from agent_mitigation.actions import (
    REVERT_FEATURE_FLAG,
    Action,
    Outcome,
    UndoAttempt,
    Undone,
    Verdict,
    propose_action,
)
from agent_mitigation.tools import (
    Clock,
    EnabledFlags,
    FlagChangeFetcher,
    FlagSetter,
    MetricsFetcher,
    Sleeper,
    StillWanted,
    fetch_recent_flag_changes,
    fetch_recent_metrics,
    set_flag,
    utc_now,
)

# Aliased so the parameter it defaults can carry the name a caller writes -
# `enabled_flags=` reads as what is being supplied, and the tool keeps the name
# it has everywhere else.
from agent_mitigation.tools import enabled_flags as read_enabled_flags

__all__ = [
    "REVERT_FEATURE_FLAG",
    "Action",
    "Outcome",
    "UndoAttempt",
    "Undone",
    "Verdict",
    "mitigate",
    "propose_action",
    "take_action",
    "undo_change",
]

ActionTaker = Callable[[Action], Outcome]

# How often the service is re-read while waiting for it to answer an action.
# Metrics are aggregated per minute, so a tighter interval only re-reads the
# same four numbers; a looser one spends the verification budget waiting.
_SECONDS_BETWEEN_METRIC_READS = 10.0


def _nobody_stopped_this_walk() -> bool:
    """The default answer to "is this still wanted", for a caller with no walk.

    True rather than a caller being made to supply one: an `Action` is not
    incident-scoped and neither is `take_action`, so a caller with nothing to be
    withdrawn from is the ordinary case. The Orchestrator, which does have a
    walk, passes one that reads the incident.
    """
    return True


def take_action(action: Action,
                set_state: FlagSetter = set_flag,
                fetch_metrics: MetricsFetcher = fetch_recent_metrics,
                now: Clock = utc_now,
                sleep: Sleeper = time.sleep,
                still_wanted: StillWanted = _nobody_stopped_this_walk,
                enabled_flags: EnabledFlags = read_enabled_flags,
                incident_id: str | None = None,
                publisher: Publisher = nobody) -> Outcome:
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

    `incident_id` is optional because an `Action` is not incident-scoped and
    neither is this call - a caller with no incident to attribute the wait to
    narrates nothing, which is better than an event hung on an incident that
    was invented to hold it.
    """
    try:
        undo_descriptor = set_state(action.flag, action.enabled)
    except Exception as error:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=f"could not set flag [{action.flag}]: {error}",
        )

    settled = _what_watching_the_service_settled(
        fetch_metrics, now, sleep, still_wanted, incident_id, publisher
    )

    if settled is Verdict.CONFIRMED:
        return Outcome(
            verdict=Verdict.CONFIRMED,
            detail=(
                f"set flag [{action.flag}] {_state_name(action.enabled)} "
                f"and the service returned to baseline"
            ),
            undo_descriptor=undo_descriptor,
        )

    # Left where it is, carrying what would put it back. Undoing it here would
    # be a second opinion about a decision the withdrawal makes once, for every
    # action the incident took and only where the flag still holds what Argus
    # wrote.
    if settled is Verdict.WITHDRAWN:
        return Outcome(
            verdict=Verdict.WITHDRAWN,
            detail=(
                f"set flag [{action.flag}] {_state_name(action.enabled)}, and the "
                f"incident was withdrawn before the service could answer for it"
            ),
            undo_descriptor=undo_descriptor,
        )

    return _undone(action, undo_descriptor, set_state, enabled_flags)


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


def _what_watching_the_service_settled(fetch_metrics: MetricsFetcher,
                                       now: Clock,
                                       sleep: Sleeper,
                                       still_wanted: StillWanted,
                                       incident_id: str | None = None,
                                       publisher: Publisher = nobody) -> Verdict:
    """What the service did after the action, within the time allowed.

    `REFUTED` on expiry rather than an error, because that is a real answer
    about the world: the action was taken and did not visibly help in the time
    it was given. Calling it an error would route an incident to a human over
    what is ordinary evidence against a hypothesis.

    `WITHDRAWN` where somebody stopped the walk while this was waiting. The loop
    already wakes every ten seconds to re-read the metrics, so asking here costs
    nothing and ends the wait within one interval of the withdrawal rather than
    at the end of a window nobody is waiting for.

    Each look is published. This is the one stretch of an incident where Argus
    is doing something and has nothing to show for it yet, and a page that went
    quiet here would read as a page that had stopped.
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

    def say(event: AwaitingRecovery | RecoveryChecked) -> None:
        """Narrates the wait, where there is an incident to narrate it for."""
        if incident_id is not None:
            publish(event, publisher)

    if incident_id is not None:
        say(AwaitingRecovery(
            incident_id=incident_id,
            from_minute=first_whole_minute,
            seconds_allowed=settings.mitigation_verification_timeout_seconds,
        ))

    while True:
        recovered = has_recovered_since(fetch_metrics(), first_whole_minute)
        if incident_id is not None:
            say(RecoveryChecked(
                incident_id=incident_id,
                minute=first_whole_minute,
                recovered=recovered,
            ))

        # Asked before the recovery is acted on, and it outranks it: an incident
        # somebody took back is over whichever way this minute reads, and
        # claiming a confirmation on the pass the walk was stopped would credit
        # Argus with an ending it did not reach.
        if not still_wanted():
            return Verdict.WITHDRAWN

        if recovered:
            return Verdict.CONFIRMED

        if now() >= deadline:
            return Verdict.REFUTED

        sleep(_SECONDS_BETWEEN_METRIC_READS)


def undo_change(undo_descriptor: dict[str, Any],
                set_state: FlagSetter = set_flag,
                enabled_flags: EnabledFlags = read_enabled_flags) -> UndoAttempt:
    """Puts one recorded change back, where it is still Argus's to put back.

    The capability, on its own: one change, one answer. Which changes to undo,
    in what order, and where the answers are written down belong to whoever
    holds the records - a refuted action asks for its own, and a withdrawn
    incident asks for every change it made. Sequencing them here would put a
    coordinator inside an agent, and a database behind it.

    Conditional, and that is the whole of why this is not a bare `set_state`.
    Somebody who has changed the flag since Argus set it changed it
    deliberately, and a restore that overwrote them would replace a decision
    with a state nobody chose - while claiming to be tidying up after itself.

    The state the descriptor records is what gets written, rather than the
    inverse of what the flag reads now: the descriptor is the record of what
    actually changed, and re-deriving it from a live reading would restore
    whatever happens to be true at the moment of the read.

    Nothing raises. An unwind runs over every change an incident made, and one
    flag nobody can read must not stop the others being put back.
    """
    flag = str(undo_descriptor["flag"])
    was_enabled = bool(undo_descriptor["was_enabled"])
    # What Argus wrote, which is the only thing the flag can still be holding
    # for this change to be Argus's to undo. Derived rather than stored: the
    # descriptor records the state that existed before, and a write that set it
    # to anything but the opposite of that would not have been this change.
    argus_set_it_to = not was_enabled

    try:
        holds_what_argus_wrote = (flag in enabled_flags()) == argus_set_it_to
    except Exception as error:
        return UndoAttempt(
            flag=flag,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"whether flag [{flag}] still holds what Argus set could not be "
                f"established, so it was not written: {error}"
            ),
        )

    if not holds_what_argus_wrote:
        return UndoAttempt(
            flag=flag,
            outcome=Undone.LEFT_AS_FOUND,
            detail=(
                f"flag [{flag}] was left as found: it has been changed from "
                f"outside since Argus set it"
            ),
        )

    try:
        set_state(flag, was_enabled)
    except Exception as error:
        return UndoAttempt(
            flag=flag,
            outcome=Undone.NOT_ESTABLISHED,
            detail=(
                f"flag [{flag}] could not be put back "
                f"{_state_name(was_enabled)}: {error}"
            ),
        )

    return UndoAttempt(
        flag=flag,
        outcome=Undone.RESTORED,
        detail=f"flag [{flag}] was put back {_state_name(was_enabled)}",
    )


def _undone(action: Action,
            undo_descriptor: dict[str, Any],
            set_state: FlagSetter,
            read_flags: EnabledFlags) -> Outcome:
    """Puts a refuted action back, and says so as a verdict.

    A refuted action was taken on a hypothesis the evidence has not borne out,
    so leaving its change in place would mean production state was altered for
    a cause that was not the cause, with nobody told.

    The undo itself is `undo_change`; what this adds is what a *verdict* is
    made of. A change left as found is still a refutation - the service did not
    recover, which is what the verdict is about - while a change nobody could
    account for escalates, because an environment Argus cannot describe is
    precisely what a human needs paging for.
    """
    was_enabled = bool(undo_descriptor["was_enabled"])
    taken = f"set flag [{action.flag}] {_state_name(action.enabled)}"
    attempt = undo_change(undo_descriptor, set_state, read_flags)

    if attempt.outcome is Undone.NOT_ESTABLISHED:
        return Outcome(
            verdict=Verdict.ESCALATED,
            detail=f"{taken}, the service did not recover, and {attempt.detail}",
            undo_descriptor=dict(undo_descriptor),
        )

    if attempt.outcome is Undone.LEFT_AS_FOUND:
        return Outcome(
            verdict=Verdict.REFUTED,
            detail=f"{taken}, the service did not recover, and {attempt.detail}",
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
