"""What it takes to read PagerDuty, and nothing else."""

from __future__ import annotations

from core import SettingsSlice


class PagerDutySettings(SettingsSlice):
    """What it takes to read PagerDuty.

    Empty by default in the environment, and empty means the source reports it
    could not answer: a response time nobody can vouch for is worse than one
    the document says it could not obtain, and a default credential would be
    one nobody chose.

    `pagerduty_verify_tls` is here because `pagerduty_double` mints itself a
    certificate nobody has reason to trust - and answers TLS at all because the
    vendor's SDK refuses a base URL that is not `https://`.

    Beside the adapter rather than in it, because naming what a source needs
    must not cost the SDK that source talks to: a composition root builds this
    slice to decide whether it can read the provider at all, and importing it
    out of `pagerduty_adapter` would import `pagerduty` to ask. Nor in the port,
    which names no vendor.
    """

    pagerduty_api_key: str
    pagerduty_base_url: str
    pagerduty_verify_tls: bool
