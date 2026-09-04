from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg
from exchange_rate_source import PublishedRates

"""Where a day's exchange rates are written down.

Not an incident's table and not the single-writer rule's business: a rate
belongs to a day rather than to an incident, and every postmortem written that
day converts at the same one. Which is the reason it is held at all - the
provider publishes today's, so a document re-derived next month would convert
at a rate that did not exist when it was written.

Rates are never updated, only inserted. A day's reference rate is published
once and does not move, so a second insert for the same day is the same
numbers arriving again - taken as already known rather than as a correction.
"""


def record(conn: psycopg.Connection, rates: PublishedRates) -> None:
    """Writes one day's table, leaving any row already held as it was.

    One statement rather than a row at a time: thirty currencies arrive
    together from one request, and a partial table is a conversion that
    silently finds no rate for the currency the shop actually took.
    """
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO exchange_rate (base, currency, published_on, per_unit) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (base, currency, published_on) DO NOTHING",
            [
                (rates.base, currency, rates.on, per_unit)
                for currency, per_unit in rates.per_unit.items()
            ]
        )
    conn.commit()


def get_latest_for(conn: psycopg.Connection, base: str) -> PublishedRates | None:
    """The most recently published table held for `base`, whole.

    The newest day and only that day: rates from two days mixed into one table
    would be a conversion whose disclosed date is true of some of its figures.
    `None` where nothing has ever been held, which is the caller's cue that
    there is nothing to fall back on.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT currency, per_unit "
            "  FROM exchange_rate "
            " WHERE base = %s "
            "   AND published_on = (SELECT MAX(published_on) "
            "                         FROM exchange_rate WHERE base = %s)",
            (base, base)
        )
        held = cursor.fetchall()

        if not held:
            return None

        cursor.execute(
            "SELECT MAX(published_on) FROM exchange_rate WHERE base = %s", (base,)
        )
        published_on = cursor.fetchone()

    return PublishedRates(
        base=base,
        on=_a_day(published_on),
        per_unit={currency: Decimal(per_unit) for currency, per_unit in held}
    )


def _a_day(row: tuple[date, ...] | None) -> date:
    """The day the rows above belong to.

    Read back rather than carried from the first query, because the two
    statements have to agree on which day was newest and only the database can
    say. A row is certain to exist here - the caller has already found rates
    for that day.
    """
    if row is None:
        raise ValueError("rates were held for this base but no day was recorded")

    return row[0]
