"""The one place Stripe is known by name.

The provider is read through its own SDK rather than a hand-built request, so
what the demo exercises is what a real account would: the library's request
building, its paging, its object model. Aiming it is one setting - the seam
sits *below* the SDK, exactly as it does for the Anthropic client - which is
what makes the shop's own endpoint a stand-in rather than a second
implementation.

Nothing above this module imports `stripe`, and nothing above it sees a
`StripeError`: a provider that cannot be read leaves here as
`RevenueUnavailable`, which is the vocabulary the rest of Argus answers in.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from stripe import StripeClient, StripeError

from revenue_source.takings import Charge, RevenueSettings, RevenueUnavailable

# How a client is built. Injected rather than constructed outright so that a
# test can assert the case that matters most here - that a deployment holding
# no credential builds nothing at all - without a network, and without
# monkeypatching a name this module imported.
type ClientOf = Callable[..., StripeClient]

# Stripe's own query vocabulary. `created` bounds the window, and `gte`/`lte`
# make it inclusive at both ends - what a window between two instants means
# everywhere else in Argus.
_CREATED: Final = "created"
_AT_OR_AFTER: Final = "gte"
_AT_OR_BEFORE: Final = "lte"
_LIMIT: Final = "limit"

# How a charge is reported. `status` is the provider's word for whether the
# money arrived, and `succeeded` is the only one of its values that means it
# did - the rest (`failed`, `pending`) are money the shop does not have.
_STATUS: Final = "status"
_SUCCEEDED: Final = "succeeded"
_CURRENCY: Final = "currency"
_AMOUNT: Final = "amount"
_AMOUNT_REFUNDED: Final = "amount_refunded"

# Money is reported in the currency's minor unit - cents, agorot, pence. Every
# currency this shop can be paid in has two decimal places; the ones that do
# not (JPY has none, KWD three) would need the provider's own table rather
# than a second guess here.
_MINOR_UNITS_IN_A_MAJOR_ONE: Final = Decimal(100)

# The most charges to ask for at once. Stripe's own maximum; fewer would mean
# more round trips for the same window and no other difference.
_A_FULL_PAGE: Final = 100

# The address the SDK sends API requests to. One of four the client accepts -
# the others are for Connect, file uploads and meter events, none of which this
# reads - and naming it here keeps the vendor's shape out of the settings.
_THE_API_ADDRESS: Final = "api"


def charges_between(started_at: datetime,
                    ended_at: datetime,
                    settings: RevenueSettings,
                    client_of: ClientOf = StripeClient) -> Iterable[Charge]:
    """Every charge the provider recorded in the window, newest first.

    The provider's own order, not a choice made here: Stripe lists charges with
    the most recent first, and every consumer above sums the whole window, so
    the order is something to state rather than something to rely on. A reader
    that stopped early would be taking the newest and calling it the window.

    Paged to the end rather than to the first hundred: a busy shop's window
    would otherwise be reported as whatever fitted on one page, which is wrong
    in exactly the direction that makes an incident look cheap.

    Drawn rather than collected. The window is the incident's, and an onset an
    alert states can be a week old, so what has to be held at once is a whole
    shop's takings for a week - to produce one per-currency sum. Yielding
    leaves the size of the window a property of the read rather than of the
    reader. It does not reduce the round trips, and nothing here can: the page
    size is already the provider's maximum and the endpoint offers no
    aggregate, so a narrower answer would have to be a narrower question.

    Each charge leaves as a `Charge`, which is Argus's word for one and not
    Stripe's: the vendor's field names, its status vocabulary and its minor
    units all stop here, and what travels on is money with a currency and a
    fact about whether it arrived.

    Raises `RevenueUnavailable` for anything the provider fails to answer, and
    for a deployment holding no credential at all. The distinction the caller
    needs is between "there were no charges" and "nobody could say", and an
    exception is the only way a listing can say the second.
    """
    # Eager, both of them, and that is why the paging sits in a function of its
    # own: a generator defers its whole body to the first draw, and a caller
    # that never drew would neither be told the credential is missing nor be
    # stopped from having a client built under one nobody chose.
    if not settings.stripe_api_key:
        raise RevenueUnavailable(
            "no payment credential is configured, so what the shop took cannot "
            "be read"
        )

    client = client_of(
        settings.stripe_api_key,
        base_addresses=(
            {_THE_API_ADDRESS: settings.stripe_base_url}
            if settings.stripe_base_url
            else None
        )
    )

    return _drawn_from(client, started_at, ended_at)


def _drawn_from(client: StripeClient,
                started_at: datetime,
                ended_at: datetime) -> Iterator[Charge]:
    """The listing itself, one charge at a time.

    A failure mid-listing leaves here in the same vocabulary as one on the
    first page: the provider fetches the next page as it is asked for, so a
    window can be half-read and then unreadable, and the caller that is folding
    it has to hear about that as `RevenueUnavailable` rather than as a vendor's
    error escaping from under a `for`.
    """
    try:
        for charge in client.v1.charges.list(
            params={
                _CREATED: {
                    _AT_OR_AFTER: int(started_at.timestamp()),
                    _AT_OR_BEFORE: int(ended_at.timestamp())
                },
                _LIMIT: _A_FULL_PAGE
            }
        ).auto_paging_iter():
            yield _as_a_charge(charge.to_dict())
    except StripeError as error:
        raise RevenueUnavailable(
            f"the payment provider could not be read: {error}"
        ) from error


def _as_a_charge(reported: Mapping[str, Any]) -> Charge:
    """One charge as Stripe reported it, read into Argus's own object.

    A refund total is absent from a charge nobody refunded, so that one field
    has a default. The rest are required: a listing that failed to say what a
    charge was for, or in which currency, is not a charge with a gap in it -
    it is a listing nothing should be summed from, and refusing it here is
    what stops a silent zero reaching the estimate.
    """
    return Charge(
        succeeded=reported.get(_STATUS) == _SUCCEEDED,
        currency=str(reported[_CURRENCY]),
        amount=_in_major_units(reported[_AMOUNT]),
        refunded=_in_major_units(reported.get(_AMOUNT_REFUNDED, 0))
    )


def _in_major_units(minor_units: Any) -> Decimal:
    return Decimal(int(minor_units)) / _MINOR_UNITS_IN_A_MAJOR_ONE
