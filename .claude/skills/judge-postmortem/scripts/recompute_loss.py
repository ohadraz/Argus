"""The customer loss worked again from the takings Argus read, independently of Argus's code.

Reads a capture's takings.json (every charges request and its answer), db/exchange_rate.json and
db/postmortem.json. For each window: the charges as read (what Argus sums) and the charges whose
`created` lies inside the window's own bounds (Stripe's semantics), each summed as Argus's
takings module does - succeeded only, amount less refunded, minor units over 100 - per currency,
then in the base currency (amount divided by its rate). Then, as `measuring.py` does: the earliest
window is two weeks back, the next one week back, the last the incident; variation is
|week back - two weeks back|, shortfall is week back - incident, loss is the shortfall where it
is larger than the variation, else 0.

usage: python -I -X utf8 recompute_loss.py <capture dir>
"""

import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HUNDRED = Decimal(100)


def window_of(url: str) -> tuple[int, int]:
    query = parse_qs(urlparse(url).query)
    return int(query["created[gte]"][0]), int(query["created[lte]"][0])


def in_base(by_currency: dict[str, Decimal], base: str, rates: dict[str, Decimal]) -> Decimal:
    total = Decimal(0)
    for currency, amount in by_currency.items():
        total += amount if currency == base else amount / rates[currency]
    return total


def when(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%d %H:%M:%S")


def say_the_stored_loss(capture: Path) -> None:
    recomputed = json.loads((capture / "loss_recomputed.json").read_text(encoding="utf-8"))
    print(f"\nloss_recomputed.json says loss {recomputed['loss']}")
    postmortem = json.loads((capture / "db" / "postmortem.json").read_text(encoding="utf-8"))
    for row in postmortem:
        for key in ("loss", "customer_loss", "estimated_loss", "customer_loss_estimate"):
            if key in row:
                print(f"postmortem.json {key}: {row[key]}")


def main(argv: list[str]) -> None:
    capture = Path(argv[1])
    requests = json.loads((capture / "takings.json").read_text(encoding="utf-8"))
    # An incident with no onset has no window to count takings over, so nothing was read.
    if not requests:
        print("no takings were read, so there is no loss to work again")
        say_the_stored_loss(capture)
        return

    rate_rows = json.loads((capture / "db" / "exchange_rate.json").read_text(encoding="utf-8"))
    base = rate_rows[0]["base"]
    rates = {row["currency"]: Decimal(row["per_unit"]) for row in rate_rows}

    read: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    inside: dict[tuple[int, int], dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    seen: dict[tuple[int, int], set[str]] = defaultdict(set)
    outside: dict[tuple[int, int], list[tuple[str, int, str, int]]] = defaultdict(list)
    # Every window asked about, by its request: one whose charges all failed (a payment
    # provider down) is a window of takings 0, not a window nobody read.
    requested: set[tuple[int, int]] = set()
    for request in requests:
        assert request["status"] == 200, request["url"]
        window = window_of(request["url"])
        requested.add(window)
        for charge in request["body"]["data"]:
            assert charge["id"] not in seen[window], f"charge read twice: {charge['id']}"
            seen[window].add(charge["id"])
            if charge["status"] != "succeeded":
                continue
            kept = (Decimal(charge["amount"]) - Decimal(charge.get("amount_refunded", 0))) / HUNDRED
            read[window][charge["currency"]] += kept
            if window[0] <= charge["created"] <= window[1]:
                inside[window][charge["currency"]] += kept
            else:
                outside[window].append((charge["id"], charge["created"], charge["currency"],
                                        charge["amount"]))

    windows = sorted(requested)
    assert len(windows) == 3, windows
    for label, totals in (("as read", read), ("inside the bounds", inside)):
        figures = [in_base(dict(totals[window]), base, rates) for window in windows]
        earlier, before, during = figures
        variation = abs(before - earlier)
        shortfall = before - during
        loss = shortfall if shortfall > variation else Decimal(0)
        print(f"\n{label}:")
        for window, figure in zip(windows, figures, strict=True):
            print(f"  {when(window[0])} to {when(window[1])}: "
                  f"{ {currency: str(amount) for currency, amount in totals[window].items()} } "
                  f"= {figure:.6f} {base}, {len(seen[window])} charges read")
        print(f"  variation {variation:.6f}, shortfall {shortfall:.6f}, loss {loss:.6f} {base}")

    for window in windows:
        for charge_id, created, currency, amount in outside[window]:
            print(f"OUTSIDE {when(window[0])}-{when(window[1])}: {charge_id} created "
                  f"{when(created)} {amount} {currency}")

    say_the_stored_loss(capture)


if __name__ == "__main__":
    main(sys.argv)
