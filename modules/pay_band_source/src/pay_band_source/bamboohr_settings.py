"""What it takes to read BambooHR's pay bands, and nothing else."""

from __future__ import annotations

from core import AdapterSettings
from pydantic import Field


class BambooHrSettings(AdapterSettings):
    """What it takes to read the HR system's pay bands.

    The credential only ever needs to read pay grades and bands. Compensation
    per person is not read by anything here, so a deployment issuing this
    credential should not grant it - what a *level* pays is all Argus asks.

    Beside the adapter rather than in it, as the other postmortem sources'
    settings are (`oncall_source.pagerduty_settings`,
    `revenue_source.stripe_settings`, `metrics_source.prometheus_settings`), so
    that a composition root naming what the source needs does not import the
    client that talks to it; nor in the port, which names no vendor.
    """

    # Empty by default, for the reason the on-call credential is: a cost nobody
    # can vouch for is worse than one the document says it could not obtain.
    hr_api_key: str = ""
    # The Target Environment's HR-shaped endpoint by default, because that is
    # what a demo has; a real deployment points this at its own account.
    hr_base_url: str = "http://localhost:8080/bamboohr"
    # Short on purpose: the bands are wanted while a postmortem is being
    # written, and a document that waits a minute for a figure it can
    # legitimately report as absent is worse than one without it.
    hr_timeout_seconds: float = Field(default=10.0, gt=0.0)
