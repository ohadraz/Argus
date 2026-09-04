from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from argus_core.config import Settings
from argus_testkit import Assertion, Kept, Scenario, all_of, attempting
from revenue_source import Charge, RevenueUnavailable
from revenue_source.stripe_adapter import charges_between

"""Reading the provider - what a listing means once it arrives.

Two things belong here. One a stack cannot show: a deployment holding no
credential, which must report that it could not answer rather than sending a
request under a credential nobody chose. The other a stack should not be the
only witness to: the provider's own vocabulary - its status words, its minor
units - read into Argus's object, which is the whole reason anything above
this module never sees either.

What is injected is the client factory, so the SDK's request path stays real
and only its answer is written. Whether that path reaches Stripe correctly -
pagination, the base address, the credential - is proven in the e2e stack.
"""

# The provider's own words for what happened to a charge, spelled out here
# rather than shared with the module under test: the assertion is that Argus
# reads *these* strings, and a constant imported from the reader would agree
# with itself whatever it was renamed to.
SUCCEEDED = "succeeded"
FAILED = "failed"
PENDING = "pending"

SOME_CURRENCY = "usd"

# What the provider counts in. Two decimal places for every currency this shop
# can be paid in.
MINOR_UNITS_IN_A_MAJOR_ONE = 100


@pytest.mark.unit
def test_without_a_credential_the_provider_is_never_asked() -> None:
    # Two things, and the second is the one that matters. Reporting "could not
    # be read" keeps the estimate absent rather than zero; not building a
    # client at all is what stops an unconfigured deployment authenticating as
    # nobody against whatever address it happens to hold.
    some_window_end = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_start = some_window_end - timedelta(hours=1)
    settings_without_a_key = _settings_with(api_key="")
    a_client_was_asked_for: Kept[bool] = Kept()

    Scenario() \
        .when(
            attempting(
                lambda: charges_between(
                    some_window_start, some_window_end,
                    settings=settings_without_a_key,
                    client_of=_a_factory_recording_into(a_client_was_asked_for))
            )
        ) \
        .then(
            all_of(
                _the_source_said_it_could_not_be_read(),
                _no_client_was_built(a_client_was_asked_for)
            )
        )


@pytest.mark.unit
def test_only_money_that_arrived_is_reported_as_having_arrived() -> None:
    # The provider says what happened to a charge in its own words, and only
    # one of them means the shop has the money. Read the other way round - or
    # read as "anything but failed" - a window full of pending charges becomes
    # revenue the shop was never paid, and the incident it is compared against
    # looks cheap in exactly the same proportion.
    some_window_end = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_start = some_window_end - timedelta(hours=1)
    dont_care_amount = 4_000

    Scenario() \
        .given(
            reported := [
                _a_reported_charge(of=dont_care_amount, status=SUCCEEDED),
                _a_reported_charge(of=dont_care_amount, status=FAILED),
                _a_reported_charge(of=dont_care_amount, status=PENDING)
            ]
        ) \
        .when(
            lambda: charges_between(
                some_window_start, some_window_end,
                settings=_settings_with(api_key="dont care"),
                client_of=_a_provider_reporting(*reported))
        ) \
        .then(
            all_of(
                _the_charge_at(0, went_through=True),
                _the_charge_at(1, went_through=False),
                _the_charge_at(2, went_through=False)
            )
        )


@pytest.mark.unit
def test_what_the_provider_counts_in_minor_units_leaves_here_as_money() -> None:
    # Cents in, money out. A hundredfold is not the kind of error a reader
    # notices in a published figure, and everything downstream - the baseline,
    # the loss, the summary - is stated in whatever this returns.
    some_window_end = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_start = some_window_end - timedelta(hours=1)
    some_amount_in_minor_units = 4_000
    some_refund_in_minor_units = 250

    Scenario() \
        .given(
            reported := [
                _a_reported_charge(of=some_amount_in_minor_units,
                                   refunded=some_refund_in_minor_units)
            ]
        ) \
        .when(
            lambda: charges_between(
                some_window_start, some_window_end,
                settings=_settings_with(api_key="dont care"),
                client_of=_a_provider_reporting(*reported))
        ) \
        .then(
            all_of(
                _the_charge_at(0, was_for=_as_money(some_amount_in_minor_units)),
                _the_charge_at(0, had_refunded=_as_money(some_refund_in_minor_units))
            )
        )


@pytest.mark.unit
def test_a_charge_nobody_refunded_is_reported_as_refunding_nothing() -> None:
    # The provider omits the field rather than sending a zero, and a charge
    # read as having no refundable total at all would be one this cannot sum.
    some_window_end = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    some_window_start = some_window_end - timedelta(hours=1)
    dont_care_amount = 4_000

    Scenario() \
        .given(
            reported := [_a_reported_charge(of=dont_care_amount, refunded=None)]
        ) \
        .when(
            lambda: charges_between(
                some_window_start, some_window_end,
                settings=_settings_with(api_key="dont care"),
                client_of=_a_provider_reporting(*reported))
        ) \
        .then(
            _the_charge_at(0, had_refunded=Decimal(0))
        )


def _settings_with(api_key: str) -> Settings:
    return Settings(stripe_api_key=api_key)


def _a_factory_recording_into(kept: Kept[bool]) -> Any:
    def factory(*dont_care_args: Any, **dont_care_kwargs: Any) -> Any:
        kept.take(True)

        raise AssertionError(
            "A client was built for a deployment holding no credential."
        )

    return factory


def _the_source_said_it_could_not_be_read() -> Assertion[Any]:
    def assertion(error: Any) -> bool:
        if not isinstance(error, RevenueUnavailable):
            raise AssertionError(
                f"Expected the source to report that it could not be read, but "
                f"what came back was {error!r}."
            )

        return True

    return assertion


def _no_client_was_built(kept: Kept[bool]) -> Assertion[Any]:
    def assertion(dont_care_error: Any) -> bool:
        if kept.taken:
            raise AssertionError(
                "Expected no request to be prepared without a credential, but a "
                "client was built."
            )

        return True

    return assertion


def _as_money(minor_units: int) -> Decimal:
    return Decimal(minor_units) / MINOR_UNITS_IN_A_MAJOR_ONE


def _a_reported_charge(of: int,
                       status: str = SUCCEEDED,
                       refunded: int | None = 0,
                       currency: str = SOME_CURRENCY) -> Mapping[str, Any]:
    """One charge in the provider's own shape - minor units, a status word, and
    a refunded total the provider leaves out entirely when there is none, which
    `refunded=None` writes."""
    reported: dict[str, Any] = {
        "status": status,
        "currency": currency,
        "amount": of
    }

    if refunded is not None:
        reported["amount_refunded"] = refunded

    return reported


def _a_provider_reporting(*reported: Mapping[str, Any]) -> Any:
    """A client factory whose listing answers exactly these charges.

    Stood in by hand rather than by `create_autospec`: what is stood in for is
    three chained attributes of the vendor's client and a page object yielding
    charges that answer `to_dict`, and a spec deep enough to reach that would
    be a second implementation of the SDK's object model. `to_dict` is what
    the SDK's own objects answer, which is why the charges here answer it too.
    """
    charges = [Mock(to_dict=Mock(return_value=dict(charge))) for charge in reported]
    listing = Mock(auto_paging_iter=Mock(return_value=charges))

    return lambda *dont_care_args, **dont_care_kwargs: SimpleNamespace(
        v1=SimpleNamespace(charges=Mock(list=Mock(return_value=listing)))
    )


def _the_charge_at(position: int,
                   went_through: bool | None = None,
                   was_for: Decimal | None = None,
                   had_refunded: Decimal | None = None) -> Assertion[Any]:
    """One charge out of the listing, checked on whichever facts were named."""
    def assertion(charges: Any) -> bool:
        listing: list[Charge] = list(charges)

        if len(listing) <= position:
            raise AssertionError(
                f"Expected a charge at position [{position}], but the listing "
                f"held {len(listing)}."
            )

        charge = listing[position]

        if went_through is not None and charge.succeeded != went_through:
            raise AssertionError(
                f"Expected the charge at [{position}] to be read as "
                f"{'money that arrived' if went_through else 'money that did not'}, "
                f"but it came back as {charge!r}."
            )

        if was_for is not None and charge.amount != was_for:
            raise AssertionError(
                f"Expected the charge at [{position}] to be for [{was_for}], but "
                f"it came back as [{charge.amount}]."
            )

        if had_refunded is not None and charge.refunded != had_refunded:
            raise AssertionError(
                f"Expected [{had_refunded}] refunded off the charge at "
                f"[{position}], but it came back as [{charge.refunded}]."
            )

        return True

    return assertion
