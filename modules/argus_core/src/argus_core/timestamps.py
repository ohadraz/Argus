from __future__ import annotations

from datetime import UTC, datetime

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def to_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def to_iso_minute(moment: datetime) -> str:
    """The minute `moment` falls in, in wire format - the instant truncated.
    """
    return to_iso(moment.replace(second=0, microsecond=0))


def parse_iso(value: str) -> datetime:
    """Reads an ISO-8601 instant, treating a naive one as UTC.

    Raises `ValueError` when `value` is not a timestamp at all.
    """
    parsed = datetime.fromisoformat(value)

    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
