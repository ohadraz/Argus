from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from argus_core.config import get_settings
from argus_core.models.flag_change import FlagChange
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import to_iso
from read_mcp_client import get_metrics_summary
from write_mcp_client import get_recent_flag_changes, set_feature_flag

FlagChangeFetcher = Callable[[], list[FlagChange]]
MetricsFetcher = Callable[[], list[MetricBucket]]
FlagSetter = Callable[[str, bool], dict[str, Any]]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


def fetch_recent_flag_changes() -> list[FlagChange]:
    """The flag toggles recorded over the configured lookback, oldest first.

    A named function rather than `get_recent_flag_changes` passed directly,
    because the agent needs exactly one of that tool's calling shapes - a
    window ending now - and a seam is only useful if a test can spec against
    the shape the caller actually uses. Deciding the window here also keeps
    `propose_action` free of both configuration and I/O.
    """
    lookback = timedelta(minutes=get_settings().flag_change_lookback_minutes)

    return get_recent_flag_changes(since=to_iso(utc_now() - lookback))


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
