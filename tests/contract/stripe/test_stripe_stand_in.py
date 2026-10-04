"""Whether the stand-in still answers as Stripe does.

Every suite that reads what the shop took reads it from the Target Service's
stand-in at `/stripe`, through the real SDK. What none of them can say is
whether Stripe itself answers the adapter's question the way the stand-in
does - the window it filters on, the units it counts in, the words it spells a
currency and a status with. That is checked here against a Stripe sandbox: a
charge is taken there, the adapter reads it back, and the stand-in's charges
are required to read the same way.

Read the same rather than equal. The stand-in's charges are the shop's trade,
the sandbox's is the one this test took, and their amounts have nothing to do
with each other. What every caller depends on is that a charge comes back in
the window it was taken in, in major units, and spelled as the stand-in spells
one - a currency the stand-in wrote as `USD` would sum apart from every `usd`
Stripe ever answered.

A sandbox is Stripe's own, and charges in it are not money. The key is the one
`STRIPE_API_KEY` holds; `STRIPE_BASE_URL` is ignored here, since that aims the
demo at the stand-in and this half has to reach Stripe. A live key is refused
outright rather than skipped: this test takes a charge.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from argus_core import get_settings
from argus_testkit import Assertion, Scenario, all_of
from revenue_source import Charge, RevenueSettings
from revenue_source.stripe_adapter import charges_between
from stripe import StripeClient

# Where the stand-in answers, and a key it takes from anybody.
THE_STAND_IN = "http://localhost:8080/stripe"
ANY_KEY_WILL_DO = "sk_test_the_shop_accepts_anything"

# Empty is the SDK's own default, which is Stripe.
STRIPE_ITSELF = ""

# The only spelling of a key this test will take a charge with. Stripe still
# names a sandbox's keys after the mode they used to belong to.
A_SANDBOX_KEY = "sk_test_"

# A card Stripe's sandboxes accept and no live account does.
A_CARD_THAT_ALWAYS_PAYS = "pm_card_visa"

THE_CURRENCY = "usd"

# Around the charge, wide enough that a clock a little apart from Stripe's
# still holds it.
A_MINUTE = timedelta(minutes=1)

needs_a_sandbox = pytest.mark.skipif(
    not get_settings().stripe_api_key,
    reason="no STRIPE_API_KEY: the real half of the contract cannot be checked"
)


@pytest.mark.contract
@needs_a_sandbox
def test_a_charge_the_sandbox_took_reads_as_the_stand_in_reads_one() -> None:
    # The whole of the happy path. An amount nobody else is charging, so the
    # charge found is the one taken; cents that are not a round number, so a
    # reading in the wrong units cannot land on the right figure by accident.
    Scenario() \
        .given(
            the_amount := Decimal(1000 + secrets.randbelow(9000)) / 100,
            taken_at := _a_charge_was_taken_in_the_sandbox(the_amount)
        ) \
        .when(lambda: list(charges_between(
            taken_at - A_MINUTE, taken_at + A_MINUTE,
            RevenueSettings(stripe_api_key=_the_sandbox_key(), stripe_base_url=STRIPE_ITSELF)
        ))) \
        .then(all_of(
            _it_came_back(the_amount),
            _it_reads_as(list(charges_between(
                taken_at - A_MINUTE, taken_at + A_MINUTE,
                RevenueSettings(stripe_api_key=ANY_KEY_WILL_DO, stripe_base_url=THE_STAND_IN)
            )), the_amount)
        ))


def _the_sandbox_key() -> str:
    """The key, refused outright if it is not a sandbox's."""
    key = get_settings().stripe_api_key

    if not key.startswith(A_SANDBOX_KEY):
        raise AssertionError(
            "Expected a sandbox key in STRIPE_API_KEY, it holds some other kind: "
            "this test takes a charge, and never against a live account."
        )

    return key


def _a_charge_was_taken_in_the_sandbox(amount: Decimal) -> datetime:
    """Takes a charge for `amount`, and says when."""
    taken_at = datetime.now(UTC)

    StripeClient(_the_sandbox_key()).v1.payment_intents.create(params={
        "amount": int(amount * 100),
        "currency": THE_CURRENCY,
        "payment_method": A_CARD_THAT_ALWAYS_PAYS,
        "payment_method_types": ["card"],
        "confirm": True
    })

    return taken_at


def _it_came_back(amount: Decimal) -> Assertion[list[Charge]]:
    def assertion(charges: list[Charge]) -> bool:
        if not any(charge.amount == amount for charge in charges):
            raise AssertionError(
                f"Expected the charge taken for [{amount}] read back in its window, "
                f"the window held {[str(charge.amount) for charge in charges]}."
            )

        return True

    return assertion


def _it_reads_as(at_the_stand_in: list[Charge], amount: Decimal) -> Assertion[list[Charge]]:
    """The two answers, as the adapter reads them.

    The charge the sandbox took against the stand-in's in the same currency:
    whether it is money the shop has, how the currency is spelled, and what
    was refunded off it. Not the amount - the two were never the same sale.
    """
    def assertion(from_stripe: list[Charge]) -> bool:
        taken = next((charge for charge in from_stripe if charge.amount == amount), None)

        if taken is None:
            raise AssertionError(
                f"Expected the charge taken for [{amount}] to compare, it never came back."
            )

        stood_in = [charge for charge in at_the_stand_in if charge.currency == taken.currency]

        if not stood_in:
            raise AssertionError(
                f"Expected the stand-in to answer a charge in [{taken.currency}], "
                f"it answered in {sorted({charge.currency for charge in at_the_stand_in})}."
            )

        real = (taken.succeeded, taken.refunded)
        stand_in = (stood_in[0].succeeded, stood_in[0].refunded)

        if real != stand_in:
            raise AssertionError(
                f"Expected the stand-in's charge read as Stripe's was (succeeded, refunded) "
                f"{real}, it read {stand_in}."
            )

        return True

    return assertion
