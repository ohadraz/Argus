"""The real answers to everything the Postmortem asks of the world (spec §7.6).

One module, and one job: build the `Sources` record a postmortem is written
against. Every vendor this deployment reads is named here, at the top, as an
ordinary import - Stripe, PagerDuty, BambooHR, the rate provider and the read
tier - because this is a composition root, and a process that needs them is the
process that pays for them.

That is the whole reason it exists. These imports used to sit *inside* the
functions that gather a postmortem, each with a note explaining that a unit test
of the gathering should not have to have a payment SDK installed. The note was
right about the symptom and wrong about the cause: the gathering already had a
port record to fill, and filling it with hard-wired adapters hidden behind an
import statement made an untestable function look testable. With the building
moved here, `gathering.py` names no vendor at all and takes what it needs as an
argument.

Each source answers `None` where it could not be read, never zero. A provider
that is down must not become a postmortem reporting that an incident cost
nothing - the document is built to tell the two apart, and can only do so if
what reaches it admits the difference.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from functools import partial

from agent_postmortem import (
    EngagedResponder,
    EngagementAnswer,
    PayBand,
    RateTable,
    Sources,
)
from argus_core import Connections, Settings, to_iso
from argus_core.mcp_transport import McpClient
from argus_core.models import MetricBucket
from argus_incidents.repository import exchange_rates
from exchange_rate_source.frankfurter import (
    ExchangeRateSettings,
    rates_published_for,
)
from oncall_source import OnCallSettings, engagement_with
from oncall_source.pagerduty_adapter import reported_incident
from read_mcp_client import get_metrics_summary
from responder_rate_source import (
    PayBandsUnavailable,
    ResponderRateSettings,
    pay_bands,
)
from revenue_source import RevenueSettings, taken_between
from revenue_source.stripe_adapter import charges_between

from orchestrator.rates import todays_rates


def the_real_sources(settings: Settings,
                     connections: Connections,
                     read: McpClient) -> Sources:
    """Every port answered by the provider this deployment is configured for.

    The configuration is sliced once, here, and each source is handed only its
    own slice. A source that never learns a credential's name cannot leak it
    into a postmortem, and one holding the whole of `Settings` would be able to
    read every credential Argus has in order to ask about money.

    Which is why this one takes the whole of it, and is meant to. It is the
    narrowing itself: four slices come out of here and each goes to the one
    provider it configures. A slice handed *in* would only move the question
    of who may read a payment key one call further up, and split the answer
    across two places.

    The read tier arrives as the connection somebody already holds to it, not as
    an address to dial: a postmortem's metrics are one more question asked over
    the session an investigation has been using all along.

    `connections` rather than a connection: the rates are the one source that
    reaches a table, and it is asked for at most once, while a postmortem is
    being written. Holding a connection open across the whole document for the
    sake of one question would keep it out of the pool for the length of a
    model call.
    """
    return Sources(
        revenue=partial(_the_services_takings,
                        settings=RevenueSettings.of(settings)),
        rates=partial(_todays_rates,
                      connections,
                      base=settings.reporting_currency,
                      settings=ExchangeRateSettings.of(settings)),
        engagement=partial(_who_responded, settings=OnCallSettings.of(settings)),
        bands=partial(_what_a_title_is_worth,
                      settings=ResponderRateSettings.of(settings)),
        metrics=partial(_metrics_between, client=read),
        working_hours_a_year=settings.working_hours_a_year,
        reporting_currency=settings.reporting_currency
    )


def _the_services_takings(started_at: datetime,
                          ended_at: datetime,
                          *,
                          settings: RevenueSettings) -> Mapping[str, Decimal] | None:
    """What the service took over the incident, read from the payment provider.

    A provider that cannot be read - or a deployment holding no credential -
    answers `None` rather than zero. The agent already knows what to do with an
    unanswered question, and "the incident cost nothing" is not it.
    """
    takings = taken_between(
        started_at,
        ended_at,
        charges=partial(charges_between, settings=settings)
    )

    return takings.amounts if takings is not None else None


def _todays_rates(connections: Connections,
                  *,
                  base: str,
                  settings: ExchangeRateSettings) -> RateTable | None:
    """The day's rates, fetched once and held against the day nobody answers.

    Takes its own connection rather than borrowing the one the gathering holds.
    Which rates to use is a decision, and reaching the table that holds them is
    a detail of where they are kept - so the connection is opened around the
    reads and closed again, and the decision happens with none held.
    """
    with connections() as conn:
        return todays_rates(
            base,
            held_rates=partial(exchange_rates.get_latest_for, conn),
            hold_rates=partial(exchange_rates.record, conn),
            published=partial(rates_published_for, settings=settings)
        )


def _who_responded(incident_id: str,
                   *,
                   settings: OnCallSettings) -> EngagementAnswer | None:
    """What human attention the incident took, read from the on-call provider.

    A provider that cannot be read - or a deployment holding no credential -
    answers `None` rather than zero. An incident nobody acknowledged answers
    zero, which is a different thing and is the source's to say.

    The minutes are person-minutes, already summed across the people who
    responded, and the titles say what those people were rather than who. Both
    cross as the source answered them; nothing here reinterprets either.
    """
    engaged = engagement_with(
        incident_id,
        reported=partial(reported_incident, settings=settings)
    )

    if engaged is None:
        return None

    return EngagementAnswer(minutes=engaged.minutes,
                            responders=engaged.responders,
                            titles=engaged.titles,
                            engaged=[EngagedResponder(minutes=responder.minutes,
                                                      job_title=responder.job_title)
                                     for responder in engaged.engaged])


def _what_a_title_is_worth(*,
                           settings: ResponderRateSettings
                           ) -> Mapping[str, PayBand] | None:
    """What each job title the HR source prices is worth a year.

    Bands rather than anybody's pay: a band belongs to a level that titles are
    assigned to, so the response is priced without any person's compensation
    being read, and this deployment's credential never needs to be able to.

    Answers `None` where the source could not be read - including a deployment
    holding no HR credential at all. A postmortem is written either way; it
    simply publishes no cost and says why.
    """
    try:
        read = pay_bands(settings)
    except PayBandsUnavailable:
        return None

    return {title: PayBand(minimum=band.minimum,
                           midpoint=band.midpoint,
                           maximum=band.maximum,
                           currency=band.currency)
            for title, band in read.items()}


def _metrics_between(window_start: datetime,
                     window_end: datetime,
                     *,
                     client: McpClient) -> list[MetricBucket]:
    """The metrics channel, asked for a window spanning the whole incident."""
    return get_metrics_summary(window_start=to_iso(window_start),
                               window_end=to_iso(window_end),
                               client=client)
