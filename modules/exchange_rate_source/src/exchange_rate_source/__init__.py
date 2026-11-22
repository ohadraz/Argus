"""What one unit of money is worth in another, on the day it was published.

Nothing at the front door: the package is one adapter, `frankfurter`, and a
process's root imports it by that name, as it imports every adapter. What a
table *is* - `PublishedRates`, and the `RatesUnavailable` that stands for having
none - lives in `core.models.rates`, because the repository that holds a table
and the walk that chooses between a held one and a fresh one both name it, and
neither should install an HTTP client to say so.
"""

from __future__ import annotations

__all__: list[str] = []
