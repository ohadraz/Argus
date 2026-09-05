from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from argus_core.attribution import change_by_actor_to, changes_not_made_by
from argus_core.config import get_settings
from argus_core.models.flag_change import FlagChange
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import to_iso
from read_mcp_client import get_metrics_summary
from write_mcp_client import get_recent_flag_changes, set_feature_flag

FlagChangeFetcher = Callable[[], list[FlagChange]]
# The same tool asked for a window that starts where the caller says, rather
# than where configuration says. Only the resumed walk needs that: it is asking
# about one particular moment - when an action was claimed - and the configured
# lookback is about something else entirely.
class FlagChangesSince(Protocol):
    def __call__(self, since: str) -> list[FlagChange]: ...
MetricsFetcher = Callable[[], list[MetricBucket]]
FlagSetter = Callable[[str, bool], dict[str, Any]]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


def fetch_recent_flag_changes() -> list[FlagChange]:
    """The flag toggles recorded over the configured lookback, oldest first -
    excluding the ones Argus itself made.

    A named function rather than `get_recent_flag_changes` passed directly,
    because the agent needs exactly one of that tool's calling shapes - a
    window ending now - and a seam is only useful if a test can spec against
    the shape the caller actually uses. Deciding the window here also keeps
    `propose_action` free of both configuration and I/O.

    Argus's own changes are dropped here rather than by the caller, because
    every caller wants the same thing: what somebody *else* did. Once Argus can
    act more than once on an incident, its own revert lands in this window, and
    a window carrying it makes the unambiguous case - one flag changed, so that
    is the one to put back - report two flags and refuse to act.
    """
    settings = get_settings()
    lookback = timedelta(minutes=settings.flag_change_lookback_minutes)

    return changes_not_made_by(
        settings.unleash_actor,
        get_recent_flag_changes(since=to_iso(utc_now() - lookback)),
    )


def argus_changed_flag_since(
    flag: str,
    since: datetime,
    fetch: FlagChangesSince = get_recent_flag_changes,
) -> bool | None:
    """Whether Argus's own change to `flag` reached the provider after `since`.

    The question a walk asks when it is resumed inside the mitigation node and
    finds an action claimed with nothing recorded against it: the worker that
    claimed it died, and only the provider knows whether the change it was
    making landed. The provider's event log is where that is written down, and
    it is already what tells Argus's changes from a human's - asked here in the
    one direction the rest of Argus never asks it.

    `None` means the provider could not say - it could not be reached, or it
    attributes nothing to Argus because operator and agent share a credential.
    A caller must not read that as "no change was made": the difference between
    an unmade change and an unanswerable question is the difference between
    acting again and escalating.
    """
    try:
        changes = fetch(since=to_iso(since))
    except Exception:
        # Every way the provider can fail to answer arrives here, and they all
        # mean the same thing to the caller: nobody can say. Narrowing this to
        # the transport's own exception would let a change in the client's
        # vocabulary turn "could not ask" into a crash inside a resumed walk.
        return None

    return change_by_actor_to(flag, get_settings().unleash_actor, changes)


def fetch_recent_metrics() -> list[MetricBucket]:
    """The service's metric buckets, over the retention the read tier holds.

    Unanchored deliberately. The verdict asks whether the minutes since the
    action sit at the service's baseline, and the baseline is the incident's
    own quiet stretch - a window narrowed to post-action minutes alone would
    have no departure to contrast with, and would read any steady rate as
    healthy however elevated it was.
    """
    return get_metrics_summary()


def set_flag(flag: str, enabled: bool) -> dict[str, Any]:
    """Sets a flag to a state, returning the undo descriptor for the change.

    One seam for both taking an action and undoing it: undoing is the same call
    with the state reversed. That is not a convenience - it is what lets a
    refuted mitigation be put back in whichever direction it went.
    """
    return set_feature_flag(flag=flag, enabled=enabled)


def utc_now() -> datetime:
    """The clock the verification measures its timeout against, as a seam a
    test can replace with one that does not actually wait."""
    return datetime.now(UTC)
