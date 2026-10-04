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

A sandbox is Stripe's own, and charges in it are not money. The key is the one
`STRIPE_API_KEY` holds; `STRIPE_BASE_URL` names the stand-in, as it does for
the demo, and the sandbox half reaches Stripe at the SDK's default. A live key
is refused outright rather than skipped: this test takes a charge.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core import get_settings
from argus_testkit import Assertion, Scenario
from revenue_source import Charge, RevenueSettings
from revenue_source.stripe_adapter import charges_between
from stripe import StripeClient

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


def _a_charge_the_stand_in_lists() -> Charge:
    """One charge from the stand-in's last minute, as the adapter reads it.

    One that arrived and was not refunded, because that is the charge a
    sandbox can be made to take again with one card and one request. The
    stand-in lists the shop's ordinary trade in a window nothing has broken,
    but an earlier case in the session may have left a scenario seeded.
    """
    if not THE_STAND_IN or STRIPES_OWN_HOST in THE_STAND_IN:
        raise AssertionError(
            f"Expected STRIPE_BASE_URL to name the stand-in, it names Stripe itself "
            f"[{THE_STAND_IN or 'the SDK default'}]: the two halves would be one "
            f"service compared with itself."
        )

    now = datetime.now(UTC)
    charges = charges_between(
        now - A_MINUTE, now,
        RevenueSettings(stripe_api_key=ANY_KEY_WILL_DO, stripe_base_url=THE_STAND_IN)
    )
    kept = next((charge for charge in charges if charge.succeeded and not charge.refunded), None)

    if kept is None:
        raise AssertionError("Expected the stand-in to list a charge that arrived, it listed none.")

    return kept


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

    StripeClient(_the_sandbox_key()).v1.payment_intents.create(params={
        "amount": int(charge.amount * MINOR_UNITS_IN_A_MAJOR_ONE),
        "currency": charge.currency,
        "payment_method": A_CARD_THAT_ALWAYS_PAYS,
        "payment_method_types": ["card"],
        "confirm": True
    })

    return taken_at


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
