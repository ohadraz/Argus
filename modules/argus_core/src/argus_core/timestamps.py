from __future__ import annotations

from datetime import UTC, datetime

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def to_iso(moment: datetime) -> str:
    """Writes an instant in the format everything on the wire uses: UTC, whole
    seconds, trailing `Z`.

    One format, in one place, because separate concerns have to produce byte-
    identical strings: a log line's timestamp prefix and a metric bucket's id
    are compared directly, and `bucket_ids` scoping only works while they
    agree.
    """
    return moment.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def to_iso_minute(moment: datetime) -> str:
    """The minute `moment` falls in, in wire format - the instant truncated.

    Neither a metrics concern nor a logs one, which is why it lives here: a
    metric bucket's id and the minute derived from a log line's timestamp are
    compared as strings, so both have to come from this one derivation or the
    two-phase drill-down quietly stops matching anything.
    """
    return to_iso(moment.replace(second=0, microsecond=0))


def parse_iso(value: str) -> datetime:
    """Reads an ISO-8601 instant, treating a naive one as UTC.

    Raises `ValueError` when `value` is not a timestamp at all - callers rely
    on that to tell "this log line has no timestamp" from "this log line has
    one", so it is part of the contract rather than an incidental failure.
    """
    parsed = datetime.fromisoformat(value)

    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
