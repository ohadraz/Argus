"""The day's rates, fetched once and stood in for when nobody answers.

Fetch on first use rather than on a schedule: rates are wanted only when a
postmortem is written, and a nightly job would keep asking on the days nothing
broke. Once fetched they are held, because the European Central Bank publishes
once a working day and does not move again - so a second document written the
same afternoon has nothing to gain from a second request.

The fallback is the reason any of this is stored. An incident written up while
the rate provider is down would otherwise lose its estimate over a number that
was already known yesterday; a day's drift on a reference rate is small beside
the difference between a figure and a blank. What must never happen is the
older rate being reported as today's, which is why the day travels with the
table rather than beside it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import psycopg
from agent_postmortem.sources import RateTable
from exchange_rate_source import PublishedRates, RatesUnavailable
from exchange_rate_source import rates_published_for as from_the_provider

from orchestrator.repository import exchange_rates

# Where a table comes from when one has to be fetched. Injected so a test can
# say what the provider did - answered, or refused - without a network.
type Published = Callable[[str], PublishedRates]


def todays_rates(conn: psycopg.Connection,
                 base: str,
                 published: Published = from_the_provider,
                 today: Callable[[], date] = date.today) -> RateTable | None:
    """The rates to convert with, or `None` if there are none to be had.

    Held rates from today answer immediately. Anything older is a reason to
    ask, and what the provider says then either replaces them or does not
    reach them at all - a provider that cannot be read leaves yesterday's
    table standing rather than emptying the answer.

    `None` only where nothing was fetched and nothing was ever held. The
    document treats that as an unanswered question and publishes no estimate,
    which is the honest end of this channel.
    """
    held = exchange_rates.get_latest_for(conn, base)

    if held is not None and held.on == today():
        return _a_table_of(held)

    try:
        fetched = published(base)
    except RatesUnavailable:
        return _a_table_of(held) if held is not None else None

    exchange_rates.record(conn, fetched)

    return _a_table_of(fetched)


def _a_table_of(rates: PublishedRates) -> RateTable:
    """The same table in the vocabulary the document speaks.

    Two types for one shape, deliberately: the agent states what it needs
    without naming a provider, and this is the one place that knows both.
    """
    return RateTable(base=rates.base, on=rates.on, per_unit=rates.per_unit)
