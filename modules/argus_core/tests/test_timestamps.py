from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from argus_core.timestamps import parse_iso, to_iso, to_iso_minute


@pytest.mark.unit
def test_to_iso_writes_a_utc_instant_with_a_trailing_z() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 45
    some_instant_on_the_minute = datetime(
        some_year, some_month, some_day, some_hour, some_minute, 0, tzinfo=UTC
    )

    assert to_iso(some_instant_on_the_minute) == (
        f"{some_year}-{some_month:02d}-{some_day:02d}"
        f"T{some_hour:02d}:{some_minute:02d}:00Z"
    )


@pytest.mark.unit
def test_to_iso_converts_an_offset_instant_to_utc() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_local_hour = 14
    some_minute = 45
    some_offset_hours = 3
    some_instant_on_the_minute = datetime(
        some_year,
        some_month,
        some_day,
        some_local_hour,
        some_minute,
        0,
        tzinfo=timezone(timedelta(hours=some_offset_hours)),
    )

    assert to_iso(some_instant_on_the_minute) == (
        f"{some_year}-{some_month:02d}-{some_day:02d}"
        f"T{some_local_hour - some_offset_hours:02d}:{some_minute:02d}:00Z"
    )


@pytest.mark.unit
def test_to_iso_writes_whole_seconds() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 45
    some_second = 37
    some_instant_with_sub_second_precision = datetime(
        some_year, some_month, some_day, some_hour, some_minute, some_second, 123456, tzinfo=UTC
    )

    assert to_iso(some_instant_with_sub_second_precision) == (
        f"{some_year}-{some_month:02d}-{some_day:02d}"
        f"T{some_hour:02d}:{some_minute:02d}:{some_second:02d}Z"
    )


@pytest.mark.unit
def test_parse_iso_reads_what_to_iso_wrote() -> None:
    some_instant = datetime(2026, 8, 20, 11, 45, 37, tzinfo=UTC)

    assert parse_iso(to_iso(some_instant)) == some_instant


@pytest.mark.unit
def test_parse_iso_treats_a_naive_instant_as_utc() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 45
    some_naive_text = (
        f"{some_year}-{some_month:02d}-{some_day:02d}"
        f"T{some_hour:02d}:{some_minute:02d}:00"
    )

    assert parse_iso(some_naive_text) == datetime(
        some_year, some_month, some_day, some_hour, some_minute, 0, tzinfo=UTC
    )


@pytest.mark.unit
def test_parse_iso_reads_an_offset_instant_as_the_same_moment() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_local_hour = 14
    some_minute = 45
    some_offset_hours = 3
    some_offset_text = (
        f"{some_year}-{some_month:02d}-{some_day:02d}"
        f"T{some_local_hour:02d}:{some_minute:02d}:00+{some_offset_hours:02d}:00"
    )

    assert parse_iso(some_offset_text) == datetime(
        some_year,
        some_month,
        some_day,
        some_local_hour - some_offset_hours,
        some_minute,
        0,
        tzinfo=UTC,
    )


@pytest.mark.unit
def test_parse_iso_rejects_text_that_is_not_a_timestamp() -> None:
    some_log_line_without_a_timestamp = "ERROR"

    with pytest.raises(ValueError):
        parse_iso(some_log_line_without_a_timestamp)


@pytest.mark.unit
def test_to_iso_minute_truncates_an_instant_to_its_minute() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_hour = 11
    some_minute = 45
    some_instant_with_sub_second_precision = datetime(
        some_year, some_month, some_day, some_hour, some_minute, 37, 123456, tzinfo=UTC
    )

    assert to_iso_minute(some_instant_with_sub_second_precision) == (
        f"{some_year}-{some_month:02d}-{some_day:02d}"
        f"T{some_hour:02d}:{some_minute:02d}:00Z"
    )


@pytest.mark.unit
def test_to_iso_minute_normalizes_to_utc() -> None:
    some_year = 2026
    some_month = 8
    some_day = 20
    some_local_hour = 14
    some_minute = 45
    some_offset_hours = 3
    some_instant_on_the_minute = datetime(
        some_year,
        some_month,
        some_day,
        some_local_hour,
        some_minute,
        0,
        tzinfo=timezone(timedelta(hours=some_offset_hours)),
    )

    assert to_iso_minute(some_instant_on_the_minute) == (
        f"{some_year}-{some_month:02d}-{some_day:02d}"
        f"T{some_local_hour - some_offset_hours:02d}:{some_minute:02d}:00Z"
    )


@pytest.mark.unit
def test_to_iso_minute_is_the_same_for_any_instant_within_that_minute() -> None:
    some_instant_on_the_minute = datetime(2026, 8, 20, 11, 45, 0, tzinfo=UTC)
    a_later_instant_in_the_same_minute = some_instant_on_the_minute + timedelta(seconds=59)

    assert to_iso_minute(a_later_instant_in_the_same_minute) == to_iso_minute(
        some_instant_on_the_minute
    )
