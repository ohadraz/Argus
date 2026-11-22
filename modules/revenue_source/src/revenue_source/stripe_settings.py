"""What it takes to read Stripe, and nothing else."""

from __future__ import annotations

from core import SettingsSlice


class StripeSettings(SettingsSlice):
    """What it takes to read Stripe, and nothing else.

    Declared in this package rather than in the kernel because this is the only
    package that reads either field: a slice with one consumer belongs to that
    consumer, the way `Charge` does. What travels upwards is money with a
    currency, and a caller that never learns the credential's name cannot leak
    it into a postmortem.

    Beside the adapter rather than in it, because naming what a source needs
    must not cost the SDK that source talks to. A composition root builds this
    slice to decide whether it can read the provider at all, and importing it
    out of `stripe_adapter` would import `stripe` to ask. Nor in the port, which
    names no vendor.
    """

    stripe_api_key: str
    stripe_base_url: str
