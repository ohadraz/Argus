from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from argus_core import ReadMcpEndpoint, WriteMcpEndpoint, get_settings
from argus_core.models import ChangeEvent, ChangeKind, FlagChange, MetricBucket
from read_mcp_client import get_change_events, get_log_lines, get_metrics_summary
from write_mcp_client import get_recent_flag_changes

MetricsFetcher = Callable[[str | None], list[MetricBucket]]
LogFetcher = Callable[[str, str], list[str]]
ChangeFetcher = Callable[[str, str, str], list[ChangeEvent]]

# The two systems that record a change, as this module reaches them. Named
# types rather than bare `Callable`s in the signature below, so that the seams
# read as what they are - a deploy history and a flag history - where two
# three-argument callables would be told apart only by position.
#
# `Protocol` rather than a `Callable` alias because a test stands each of these
# in with `create_autospec`, which needs something introspectable. Specing
# against the client functions instead would be specing against the wrong
# shape: those take the address they dial, and a history is asked about a
# service and a window.


class DeployHistory(Protocol):
    def __call__(self,
                 *,
                 service: str,
                 window_start: str,
                 window_end: str) -> list[ChangeEvent]: ...


class FlagHistory(Protocol):
    def __call__(self, since: str, /) -> list[FlagChange]: ...


def _deploys_between(service: str,
                     window_start: str,
                     window_end: str) -> list[ChangeEvent]:
    """The read tier's change channel, at the address this deployment holds.

    Named here because the client takes the address it dials, and these are
    the defaults a caller gets when it names no source. Read from the
    environment for now; it moves to the composition root with the rest of
    `Collaborators` (V7b / M4).
    """
    return get_change_events(
        service=service,
        window_start=window_start,
        window_end=window_end,
        endpoint=ReadMcpEndpoint.of(get_settings())
    )


def _flag_changes_since(since: str) -> list[FlagChange]:
    """The write tier's flag history, asked from one moment onwards."""
    return get_recent_flag_changes(
        since, endpoint=WriteMcpEndpoint.of(get_settings())
    )


def fetch_metrics(alert_time: str | None) -> list[MetricBucket]:
    """Phase one of spec §16's two-phase retrieval: the per-minute buckets the
    onset is located in.

    A named function rather than `get_metrics_summary` passed directly,
    because the loop needs exactly one of that tool's four calling shapes -
    anchored on the alert - and a seam is only useful if a test can spec
    against the shape the caller actually uses.
    """
    return get_metrics_summary(
        alert_time=alert_time, endpoint=ReadMcpEndpoint.of(get_settings())
    )


def fetch_logs(window_start: str, window_end: str) -> list[str]:
    """Phase two: the log lines for one explicit window, both bounds ISO-8601.

    Always an explicit window, never an alert anchor - by the time the loop
    reads logs it has an onset, and the whole point of two-phase retrieval is
    to spend the expensive phase around that onset rather than around the
    moment somebody's alerting rule happened to fire.
    """
    return get_log_lines(
        window_start=window_start,
        window_end=window_end,
        endpoint=ReadMcpEndpoint.of(get_settings())
    )


def fetch_change_events(service: str,
                        window_start: str,
                        window_end: str,
                        get_change_events: DeployHistory = _deploys_between,
                        get_recent_flag_changes: FlagHistory = _flag_changes_since
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
