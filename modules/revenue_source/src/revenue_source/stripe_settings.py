"""What it takes to read Stripe, and nothing else."""

from __future__ import annotations

from core import AdapterSettings


class StripeSettings(AdapterSettings):
    """What it takes to read Stripe, and nothing else.

    Declared in this package rather than in the kernel because this is the only
    package that reads either field. What travels upwards is money with a
    currency, and a caller that never learns the credential's name cannot leak
    it into a postmortem.

    Beside the adapter rather than in it, because naming what a source needs
    must not cost the SDK that source talks to. A composition root builds these
    settings to decide whether it can read the provider at all, and importing
    them out of `stripe_adapter` would import `stripe` to ask. Nor in the port,
    which names no vendor.
    """

    # Empty by default, and empty means the source reports that it could not
    # answer: a postmortem resting on money nobody can vouch for is worse than
    # one saying the figure is missing, and a default credential would be one
    # nobody chose.
    stripe_api_key: str = ""
    # Where the SDK sends its requests. Empty means the real API. Pointing this
    # at the shop's own Stripe-shaped endpoint is the only thing that selects
    # it: the seam sits below the SDK, so the vendor's request building, paging
    # and object model all still run.
    stripe_base_url: str = ""
