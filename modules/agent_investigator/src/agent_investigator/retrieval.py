from __future__ import annotations

from collections.abc import Callable

from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.flag_change import FlagChange
from argus_core.models.metrics import MetricBucket
from read_mcp_client import get_change_events, get_log_lines, get_metrics_summary
from write_mcp_client import get_recent_flag_changes

MetricsFetcher = Callable[[str | None], list[MetricBucket]]
LogFetcher = Callable[[str, str], list[str]]
ChangeFetcher = Callable[[str, str, str], list[ChangeEvent]]

# The two systems that record a change, as this module reaches them. Named
# aliases rather than bare `Callable`s in the signature below, so that the
# seams read as what they are - a deploy history and a flag history - where
# two three-argument callables would be told apart only by position.
DeployHistory = Callable[..., list[ChangeEvent]]
FlagHistory = Callable[[str], list[FlagChange]]


def fetch_metrics(alert_time: str | None) -> list[MetricBucket]:
    """Phase one of spec §16's two-phase retrieval: the per-minute buckets the
    onset is located in.

    A named function rather than `get_metrics_summary` passed directly,
    because the loop needs exactly one of that tool's four calling shapes -
    anchored on the alert - and a seam is only useful if a test can spec
    against the shape the caller actually uses.
    """
    return get_metrics_summary(alert_time=alert_time)


def fetch_logs(window_start: str, window_end: str) -> list[str]:
    """Phase two: the log lines for one explicit window, both bounds ISO-8601.

    Always an explicit window, never an alert anchor - by the time the loop
    reads logs it has an onset, and the whole point of two-phase retrieval is
    to spend the expensive phase around that onset rather than around the
    moment somebody's alerting rule happened to fire.
    """
    return get_log_lines(window_start=window_start, window_end=window_end)


def fetch_change_events(service: str,
                        window_start: str,
                        window_end: str,
                        get_change_events: DeployHistory = get_change_events,
                        get_recent_flag_changes: FlagHistory = get_recent_flag_changes
                        ) -> list[ChangeEvent]:
    """The third channel: what changed on the service over one explicit window.

    A separate seam from the log fetcher because it answers a different
    question on a different timescale - *what changed* rather than what the
    service said - over a window far wider than any the widening schedule
    reaches. There are only ever a handful of changes to read where there
    would be millions of log lines.

    Two sources, because two systems record a change to what a service does.
    A deploy has a commit and a pipeline behind it; a feature flag flipped has
    neither, and until it was read here the Investigator could only find one by
    noticing that a log line happened to mention it - a cause found by luck.

    They arrive from different tiers, and that is not an accident to tidy away:
    the flag provider serves its audit log to admin credentials only, and the
    read process holds none by design. Reading history is strictly less than
    the write tier can already do, and the tier split's claim is that the
    *read* process cannot mutate - which is untouched.

    Merged here rather than by either server, so neither has to learn that the
    other exists. What comes back is one history in time order, because that is
    what it is: the things that happened to this service, whoever recorded them.

    Raises rather than reporting nothing when either source cannot be reached.
    "Nothing changed" is a conclusion something acts on, so a source that was
    never read must not arrive looking like one that was read and found empty.
    """
    deploys = get_change_events(
        service=service, window_start=window_start, window_end=window_end
    )
    # The provider is asked what happened *since* a moment - it has no notion of
    # a far end - so the window's close is applied here. Without it a flag
    # flipped after the incident began would be offered as something that might
    # have caused it.
    toggles = [
        _as_a_change(toggle)
        for toggle in get_recent_flag_changes(window_start)
        if toggle.occurred_at <= window_end
    ]

    return sorted([*deploys, *toggles], key=lambda change: change.occurred_at)


def _as_a_change(toggle: FlagChange) -> ChangeEvent:
    """One flag toggle, as the change channel's own shape.

    The direction is spelled out rather than left to the reader of a boolean:
    both are real - a feature is put back by switching it off, a withdrawn
    fallback by switching it on - and "the flag changed" leaves the model
    unable to say which state is now in effect.

    The flag's own name becomes the `reference`, verbatim. It is what
    identifies the change to everything downstream, and something acts on that
    name afterwards; a name Argus invented identifies nothing.

    The actor is carried across because it is load-bearing rather than
    decorative: Argus writes under a credential of its own, and this is what
    tells its own revert from a human's - which is what stops it offering its
    own action as a cause of the incident it was acting on.
    """
    return ChangeEvent(
        kind=ChangeKind.FLAG_TOGGLE,
        occurred_at=toggle.occurred_at,
        reference=toggle.flag,
        summary=f"feature flag {toggle.flag} was switched "
                f"{'on' if toggle.enabled else 'off'}",
        actor=toggle.actor
    )
