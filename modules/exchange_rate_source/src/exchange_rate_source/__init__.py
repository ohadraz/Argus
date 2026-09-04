"""What one unit of money is worth in another, on the day it was published.

Re-exports only. The implementation lives in named modules - `rates.py` for
what a table is, `frankfurter.py` for the one place a provider is known by
name - so that importing the vocabulary never pulls in an HTTP client.
"""

from __future__ import annotations

from exchange_rate_source.frankfurter import rates_published_for
from exchange_rate_source.rates import PublishedRates, RatesUnavailable

__all__ = [
    "PublishedRates",
    "RatesUnavailable",
    "rates_published_for",
]
