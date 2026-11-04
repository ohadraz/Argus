"""Whether the stand-in still answers as Stripe does.

Every suite that reads what the shop took reads it from the Target Service's
stand-in at `/stripe`, through the real SDK. What none of them can say is
whether Stripe itself answers the adapter's question the way the stand-in
does - the window it filters on, the units it counts in, the words it spells a
currency and a status with. That is checked here against a Stripe sandbox, the
one way it can be: a charge the stand-in lists is taken again in the sandbox,
the adapter reads it back from there, and the two readings are required to be
equal - amount, currency, whether it arrived, and what was refunded.

The stand-in cannot be told to take a charge - it lists the trade the shop
invents - so the sandbox is given the stand-in's charge rather than the other
way round. What is compared is the same either way: one sale, read through the
adapter from both.

The window is checked at its edges as well, since a reading of the whole
window cannot tell a bound kept to the second from one kept to the minute: the
stand-in walked whole minutes, and listed a window's first and last minutes
whole. Each side is asked about one charge of its own, over windows ending at
that charge's second or a second before it, and beginning at it or a second
after it, and the two are required to answer alike. The windows are asked as
the adapter asks them - `created[gte]` and `created[lte]`, paged to the end -
but read by id through the SDK: a `Charge` carries neither an id nor a second,
so, read by value, any other charge of the same amount in the window would
pass for it - and at the stand-in, whose charges come in two amounts, most of
them would.

A sandbox is Stripe's own, and charges in it are not money. The key is the one
`STRIPE_API_KEY` holds; `STRIPE_BASE_URL` names the stand-in, as it does for
the demo, and the sandbox half reaches Stripe at the SDK's default. A live key
is refused outright rather than skipped: this test takes a charge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from argus_core import get_settings
from argus_testkit import Assertion, Scenario
from revenue_source import Charge, RevenueSettings
from revenue_source.stripe_adapter import charges_between
from stripe import PaymentIntent, StripeClient

# Where the stand-in answers - wherever Argus itself is configured to read
# Stripe from - and a key it takes from anybody.
THE_STAND_IN = get_settings().stripe_base_url
ANY_KEY_WILL_DO = "sk_test_the_shop_accepts_anything"

# Empty is the SDK's own default, which is Stripe.
STRIPE_ITSELF = ""

# Stripe's own host, which a stand-in's address never names.
STRIPES_OWN_HOST = "stripe.com"

# The only spelling of a key this test will take a charge with. Stripe still
# names a sandbox's keys after the mode they used to belong to.
A_SANDBOX_KEY = "sk_test_"

# A card Stripe's sandboxes accept and no live account does.
A_CARD_THAT_ALWAYS_PAYS = "pm_card_visa"

# Every currency the shop is paid in has two decimal places - see the adapter.
MINOR_UNITS_IN_A_MAJOR_ONE = 100

# Around a charge, wide enough that a clock a little apart from Stripe's still
# holds it.
A_MINUTE = timedelta(minutes=1)

# Stripe's listing vocabulary: the field a window bounds, its two inclusive
# bounds, the page size, and the address a client is pointed at.
CREATED: Final = "created"
AT_OR_AFTER: Final = "gte"
AT_OR_BEFORE: Final = "lte"
LIMIT: Final = "limit"
THE_API_ADDRESS: Final = "api"

# Stripe's vocabulary for taking a payment there and then: how much, in what,
# with which card, by which kind of method, and confirmed in the same request.
AMOUNT: Final = "amount"
CURRENCY: Final = "currency"
PAYMENT_METHOD: Final = "payment_method"
PAYMENT_METHOD_TYPES: Final = "payment_method_types"
A_CARD: Final = "card"
CONFIRM: Final = "confirm"

# Stripe's own largest page, so a window short enough to hold one charge's
# minute is one request.
A_FULL_PAGE = 100

# The smallest step a bound takes, and the one the stand-in did not keep to.
A_SECOND = 1

# What a charge to take its edges with costs: the smallest sum Stripe takes in
# the shop's home currency.
SOME_AMOUNT_IN_CENTS = 50
SOME_CURRENCY = "usd"

needs_a_sandbox = pytest.mark.skipif(
    not get_settings().stripe_api_key,
    reason="no STRIPE_API_KEY: the real half of the contract cannot be checked"
)


@pytest.mark.contract
@needs_a_sandbox
def test_a_charge_the_stand_in_lists_reads_the_same_when_stripe_took_it() -> None:
    # The whole of the happy path. A charge read wrongly by either side - in
    # minor units, under an upper-case currency, as not having arrived - reads
    # as a different charge from the other side's, whichever side it was.
    Scenario() \
        .given(
            the_charge := _a_charge_the_stand_in_lists(),
            taken_at := _the_same_charge_was_taken_in_the_sandbox(the_charge)
        ) \
        .when(lambda: list(charges_between(
            taken_at - A_MINUTE, taken_at + A_MINUTE,
            RevenueSettings(stripe_api_key=_the_sandbox_key(), stripe_base_url=STRIPE_ITSELF)
        ))) \
        .then(_it_reads_as(the_charge))


@pytest.mark.contract
@needs_a_sandbox
def test_the_stand_in_bounds_a_window_to_the_second_as_stripe_does() -> None:
    # Stripe's `created[gte]` and `created[lte]` are inclusive, in seconds. A
    # stand-in keeping them to the minute listed the last minute of every
    # window whole, and a loss summed from it counted takings from seconds
    # after the window ended.
    Scenario() \
        .given(
            at_the_stand_in := _a_client(ANY_KEY_WILL_DO, THE_STAND_IN),
            at_stripe := _a_client(_the_sandbox_key(), STRIPE_ITSELF),
            its_charge := _a_charge_listed_by(at_the_stand_in),
            stripe_s_charge := _a_charge_taken_by(at_stripe)
        ) \
        .when(lambda: (_what_its_edges_hold(at_the_stand_in, *its_charge),
                       _what_its_edges_hold(at_stripe, *stripe_s_charge))) \
        .then(_the_two_answer_alike())


def _a_charge_the_stand_in_lists() -> Charge:
    """One charge from the stand-in's last minute, as the adapter reads it.

    One that arrived and was not refunded, because that is the charge a
    sandbox can be made to take again with one card and one request. The
    stand-in lists the shop's ordinary trade in a window nothing has broken,
    but an earlier case in the session may have left a scenario seeded.
    """
    _the_stand_in_is_not_stripe()

    now = datetime.now(UTC)
    charges = charges_between(
        now - A_MINUTE, now,
        RevenueSettings(stripe_api_key=ANY_KEY_WILL_DO, stripe_base_url=THE_STAND_IN)
    )
    kept = next((charge for charge in charges if charge.succeeded and not charge.refunded), None)

    if kept is None:
        raise AssertionError("Expected the stand-in to list a charge that arrived, it listed none.")

    return kept


def _the_stand_in_is_not_stripe() -> None:
    if not THE_STAND_IN or STRIPES_OWN_HOST in THE_STAND_IN:
        raise AssertionError(
            f"Expected STRIPE_BASE_URL to name the stand-in, it names Stripe itself "
            f"[{THE_STAND_IN or 'the SDK default'}]: the two halves would be one "
            f"service compared with itself."
        )


def _the_sandbox_key() -> str:
    """The key, refused outright if it is not a sandbox's."""
    key = get_settings().stripe_api_key

    if not key.startswith(A_SANDBOX_KEY):
        raise AssertionError(
            "Expected a sandbox key in STRIPE_API_KEY, it holds some other kind: "
            "this test takes a charge, and never against a live account."
        )

    return key


def _the_same_charge_was_taken_in_the_sandbox(charge: Charge) -> datetime:
    """Takes `charge` in the sandbox - same amount, same currency - and says
    when."""
    taken_at = datetime.now(UTC)

    _a_payment_taken(StripeClient(_the_sandbox_key()),
                     int(charge.amount * MINOR_UNITS_IN_A_MAJOR_ONE), charge.currency)

    return taken_at


def _a_payment_taken(stripe: StripeClient, amount_in_minor_units: int,
                     currency: str) -> PaymentIntent:
    """A payment taken in the sandbox with a card that always pays."""
    return stripe.v1.payment_intents.create(params={
        AMOUNT: amount_in_minor_units,
        CURRENCY: currency,
        PAYMENT_METHOD: A_CARD_THAT_ALWAYS_PAYS,
        PAYMENT_METHOD_TYPES: [A_CARD],
        CONFIRM: True
    })


def _a_client(key: str, address: str) -> StripeClient:
    """A client of the SDK, pointed where the adapter would point it."""
    return StripeClient(key, base_addresses={THE_API_ADDRESS: address} if address else None)


def _a_charge_listed_by(stand_in: StripeClient) -> tuple[str, int]:
    """The id and second of one charge from the stand-in's last minute."""
    _the_stand_in_is_not_stripe()

    now = int(datetime.now(UTC).timestamp())
    listed = stand_in.v1.charges.list(params={
        CREATED: {AT_OR_AFTER: now - int(A_MINUTE.total_seconds()), AT_OR_BEFORE: now},
        LIMIT: A_FULL_PAGE
    }).data

    if not listed:
        raise AssertionError("Expected the stand-in to list a charge in its last minute, "
                             "it listed none.")

    return listed[0].id, listed[0].created


def _a_charge_taken_by(stripe: StripeClient) -> tuple[str, int]:
    """Takes a charge in the sandbox, and says its id and second."""
    made = _a_payment_taken(stripe, SOME_AMOUNT_IN_CENTS, SOME_CURRENCY).latest_charge

    if not isinstance(made, str):
        raise AssertionError(f"Expected the sandbox to name the charge it made, it named [{made}].")

    charge = stripe.v1.charges.retrieve(made)

    return charge.id, charge.created


def _what_its_edges_hold(client: StripeClient, charge_id: str,
                         created: int) -> dict[str, bool]:
    """Whether a charge is listed by windows ending at its second and a second
    short of it, and beginning at its second and a second past it."""
    a_minute = int(A_MINUTE.total_seconds())
    windows = {
        "ending at its second": (created - a_minute, created),
        "ending a second before it": (created - a_minute, created - A_SECOND),
        "beginning at its second": (created, created + a_minute),
        "beginning a second after it": (created + A_SECOND, created + a_minute)
    }

    return {edge: charge_id in _the_ids_listed(client, *window)
            for edge, window in windows.items()}


def _the_ids_listed(client: StripeClient, at_or_after: int, at_or_before: int) -> set[str]:
    return {charge.id for charge in client.v1.charges.list(params={
        CREATED: {AT_OR_AFTER: at_or_after, AT_OR_BEFORE: at_or_before},
        LIMIT: A_FULL_PAGE
    }).auto_paging_iter()}


def _it_reads_as(at_the_stand_in: Charge) -> Assertion[list[Charge]]:
    """The sandbox's charge, read back equal to the stand-in's - every field."""
    def assertion(from_stripe: list[Charge]) -> bool:
        if at_the_stand_in not in from_stripe:
            raise AssertionError(
                f"Expected Stripe to read back the stand-in's charge {at_the_stand_in!r}, "
                f"the window held {from_stripe!r}."
            )

        return True

    return assertion


def _the_two_answer_alike() -> Assertion[tuple[dict[str, bool], dict[str, bool]]]:
    """Each edge holding its charge at the stand-in exactly where it does at
    Stripe."""
    def assertion(answers: tuple[dict[str, bool], dict[str, bool]]) -> bool:
        at_the_stand_in, at_stripe = answers

        if at_the_stand_in != at_stripe:
            raise AssertionError(
                f"Expected the stand-in's window edges to hold its charge as Stripe's "
                f"hold Stripe's, {at_stripe}, and they held {at_the_stand_in}."
            )

        return True

    return assertion
