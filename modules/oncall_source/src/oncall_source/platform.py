"""The on-call platform, as Argus needs it: the port, in Argus's own words.

Optional, and behind one seam. A deployment may page through PagerDuty, through
something else, or through nothing - Grafana alone is enough to run Argus - so
everything above this port asks it questions without knowing which platform, if
any, answers. Each platform is one adapter named for its vendor, and only that
adapter knows a route, a header, an event name or a field.

What crosses the port is what a platform *said*, already translated: a
delivery is one of the few things Argus acts on or deliberately does not, and
the rule deciding which - only a person's resolution ends an incident - lives in
the adapter that can tell a person from an integration, not above it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol

from argus_core.models import ReportChannel
from pydantic import BaseModel

from oncall_source.engagement import ReportedIncident


class OnCallDeliveryUnverified(Exception):
    """A delivery whose signature does not prove the platform sent it.

    Raised before anything in it is read, because what a delivery can say -
    that a person resolved an incident - ends one, and a forged one would end
    an incident nobody ended.
    """


class ResolvedByAPerson(BaseModel):
    """A person resolved the platform's incident: the one delivery Argus acts on.

    `by` is the person as the platform names them, which is how the account
    credits them.
    """

    platform_incident: str
    by: str


class ResolvedWithoutAPerson(BaseModel):
    """The platform's incident resolved, and nobody decided it.

    The monitor's integration clearing its alert - a metrics signal, and Argus
    reads recovery from the metrics itself - or automation and timeouts, which
    the platform names nobody for. `resolved_by` is what it did name, kept for
    the log; `None` where it named nothing.
    """

    platform_incident: str
    resolved_by: str | None


class Merged(BaseModel):
    """The platform's incident was merged into another.

    Not an ending: the incident moved. Its alerts went with it, so a person
    later resolving `into` is found through them like any other resolution.
    """

    platform_incident: str
    into: str


class Reopened(BaseModel):
    """The platform's incident was reopened."""

    platform_incident: str


class Irrelevant(BaseModel):
    """Anything else the platform said, named by its own event."""

    event: str


# What a delivery turned out to say.
type Delivery = ResolvedByAPerson | ResolvedWithoutAPerson | Merged | Reopened | Irrelevant


class OnCallPlatform(Protocol):
    """The on-call platform, for the questions Argus asks it.

    Every question that reaches the platform's API raises `OnCallUnavailable`
    when it cannot be answered, so a caller can tell "the platform said no"
    from "the platform could not be asked".
    """

    @property
    def channel(self) -> ReportChannel:
        """Where a person's report through this platform reached Argus."""
        ...

    def parse_delivery(self, body: bytes, headers: Mapping[str, str]) -> Delivery:
        """What one delivery says, once its signature proves who sent it."""
        ...

    def keys_of(self, platform_incident: str) -> list[str]:
        """The keys the incident's senders stamped on it."""
        ...

    def incident_for(self, keys: Iterable[str]) -> str | None:
        """The platform's incident carrying any of these keys, or `None`."""
        ...

    def resolution_note(self, platform_incident: str) -> str | None:
        """What the person wrote when they resolved it, or `None`."""
        ...

    def reported_incident(self, platform_incident: str) -> ReportedIncident:
        """The incident as the platform holds it, for engagement."""
        ...
