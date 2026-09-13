"""What one unit of money is worth in another, on the day it was published.

Re-exports only, and only the fetching. What a table *is* - `PublishedRates`,
and the `RatesUnavailable` that stands for having none - lives in
`argus_core.models.rates`, because the repository that holds a table and the
walk that chooses between a held one and a fresh one both name it, and neither
should install an HTTP client to say so.
"""

from __future__ import annotations

from exchange_rate_source.frankfurter import rates_published_for

__all__ = [
    "rates_published_for",
]
