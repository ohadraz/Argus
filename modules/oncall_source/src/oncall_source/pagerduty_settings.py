"""What it takes to read PagerDuty, and to believe what it delivers."""

from __future__ import annotations

from core import AdapterSettings


class PagerDutySettings(AdapterSettings):
    """What it takes to read PagerDuty.

    Empty credential by default, and empty means the source reports it could not
    answer: a response time nobody can vouch for is worse than one the document
    says it could not obtain, and a default credential would be one nobody chose.

    Beside the adapter rather than in it, because naming what a source needs
    must not cost the SDK that source talks to: a composition root builds these
    settings to decide whether it can read the provider at all, and importing
    them out of `pagerduty_adapter` would import `pagerduty` to ask. Nor in the
    port, which names no vendor.
    """

    pagerduty_api_key: str = ""
    # Where the SDK sends its requests. Empty means the real API. Pointing this
    # at `pagerduty_double` is the only thing that selects it: the seam sits
    # below the SDK, so the vendor's request building and error vocabulary
    # still run.
    pagerduty_base_url: str = ""
    # Whether the provider's certificate is checked. True everywhere that
    # matters: PagerDuty's own certificate is real. False only against the
    # double on this machine, which mints itself a certificate nobody has any
    # reason to trust - and answers TLS at all because the vendor's SDK refuses
    # a base URL that is not `https://`.
    pagerduty_verify_tls: bool = True


class PagerDutyDeliverySettings(PagerDutySettings):
    """What only the process receiving PagerDuty's deliveries may know beside
    the reading credential: the secret they are signed with.

    A class of its own because the worker reads the platform and never hears
    from it, and a process that cannot be told anything has no use for the
    secret that proves who is telling. The web process's root reads this one.
    """

    # Returned once when the subscription is created. A person resolving an
    # incident there is delivered under it, and a delivery that can end an
    # incident must be PagerDuty's. Empty accepts nothing: a digest under an
    # empty key is one anybody can compute.
    pagerduty_webhook_secret: str = ""
