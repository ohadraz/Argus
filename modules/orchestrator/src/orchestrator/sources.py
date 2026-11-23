"""The real answers to everything the Postmortem asks of the world (spec §7.6).

One module, and one job: build the `Sources` record a postmortem is written
against, from the ports each provider is reached through. Which vendor answers
each - the payment provider, the rate provider, the HR source, the on-call
platform - is the worker's root's to choose (`apps.worker`), and each arrives
here already built; this module names none of them.

These reads used to sit *inside* the functions that gather a postmortem, each
with a note explaining that a unit test of the gathering should not have to
have a payment SDK installed. The note was right about the symptom and wrong
about the cause: the gathering already had a port record to fill, and filling
it with hard-wired adapters hidden behind an import statement made an
untestable function look testable. `gathering.py` names no vendor at all and
takes what it needs as an argument, and so does this.

Each source answers `None` where it could not be read, never zero. A provider
that is down must not become a postmortem reporting that an incident cost
nothing - the document is built to tell the two apart, and can only do so if
what reaches it admits the difference.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial

from core import Settings, to_iso
from core.anomaly import AnomalyThresholds
from core.models import (
    NOTIFICATION_KEY,
    ON_CALL_INCIDENT,
    AlertRuleStanding,
    MetricBucket,
    Reference,
)
from incident_cost import EngagedResponder, MoneySources, PayBand, RateTable
from incident_record.repository import exchange_rates, incidents, references
from oncall_source import OnCallUnavailable, engagement_with
from oncall_source.platform import OnCallPlatform
from pay_band_source import PayBandsRead, PayBandsUnavailable
from postgres import Connections
from postmortem_writing import EngagementAnswer, NotPaged, Sources
from read_mcp_client import ReadTier
from revenue_source import Charges, taken_between

from orchestrator.rates import Published, todays_rates

logger = logging.getLogger(__name__)


def the_real_sources(settings: Settings,
                     connections: Connections,
                     read: ReadTier,
                     thresholds: AnomalyThresholds,
                     *,
                     oncall: OnCallPlatform | None,
                     charges: Charges,
                     published: Published,
                     bands: PayBandsRead) -> Sources:
    """Every port answered by the provider this deployment is configured for.

    Each provider arrives already built and bound to its own vendor's settings
    - `charges` the payment provider's listing, `published` the
    rate provider's latest table, `bands` the HR source's - by the process's
    root, which is the one place that names a vendor. What is read off
    `settings` here is Argus's own: the currency it reports in, the window the
    read tier serves, the working year.

    The read tier arrives as the tier somebody already holds, not as an address
    to dial: a postmortem's metrics are one more question asked over the session
    an investigation has been using all along.

    `connections` rather than a connection: the rates are the one source that
    reaches a table, and it is asked for at most once, while a postmortem is
    being written. Holding a connection open across the whole document for the
    sake of one question would keep it out of the pool for the length of a
    model call.

    `thresholds` is handed in rather than read off `settings`, because there
    must be exactly one of them. The same value went to the Investigator and to
    Mitigation, and the postmortem dating recovery on lines of its own is how
    it would come to report a recovery at a minute Mitigation had refused to
    confirm on.

    `oncall` is the on-call platform, already built - or `None`, since a
    deployment need not have one. Handed in because which vendor it is, is the
    composition root's to decide, and a source that held the port alone would
    be one no test has to stand a vendor in for.
    """
    return Sources(
        thresholds=thresholds,
        money=MoneySources(
            revenue=partial(_the_services_takings, charges=charges),
            rates=partial(_todays_rates,
                          connections,
                          base=settings.reporting_currency,
                          published=published),
            bands=partial(_what_a_title_is_worth, read=bands),
            working_hours_a_year=settings.working_hours_a_year,
            reporting_currency=settings.reporting_currency
        ),
        engagement=partial(_who_responded, platform=oncall, connections=connections),
        metrics=partial(_metrics_between, read=read,
                        served=timedelta(minutes=settings.metrics_window_minutes)),
        alert_rule=partial(_the_alert_rule, read=read),
        metrics_reporting_lag_minutes=settings.metrics_reporting_lag_minutes
    )


def _the_services_takings(started_at: datetime,
                          ended_at: datetime,
                          *,
                          charges: Charges) -> Mapping[str, Decimal] | None:
    """What the service took over the incident, read from the payment provider.

    A provider that cannot be read - or a deployment holding no credential -
    answers `None` rather than zero. The agent already knows what to do with an
    unanswered question, and "the incident cost nothing" is not it.
    """
    takings = taken_between(started_at, ended_at, charges=charges)

    return takings.amounts if takings is not None else None


def _todays_rates(connections: Connections,
                  *,
                  base: str,
                  published: Published) -> RateTable | None:
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
            published=published
        )


def _who_responded(incident_id: str,
                   *,
                   platform: OnCallPlatform | None,
                   connections: Connections) -> EngagementAnswer | NotPaged | None:
    """What human attention the incident took, read from the on-call platform.

    Read on the platform's own incident, never on Argus's id: they are two
    incidents opened by one alert. A platform that cannot be read - or a
    deployment with no platform at all - answers `None` rather than zero. An
    incident nobody acknowledged answers zero, and one no platform incident
    is linked to answers `NotPaged`; both are measurements, and different ones.

    The minutes are person-minutes, already summed across the people who
    responded, and the titles say what those people were rather than who. Both
    cross as the source answered them; nothing here reinterprets either.
    """
    if platform is None:
        # Still "could not say": nobody looked. Said as information, because
        # the platform is optional and a deployment without one chose that.
        logger.info("no on-call platform configured")

        return None

    try:
        platform_incidents = _the_platform_incidents_of(incident_id, platform, connections)
    except OnCallUnavailable:
        logger.warning("engagement could not be read", exc_info=True)

        return None

    if not platform_incidents:
        logger.info("no on-call incident linked")

        return NotPaged()

    if len(platform_incidents) > 1:
        # Nothing here can say which page's minutes were spent on this
        # incident, and summing them would count one response twice.
        logger.warning("several on-call incidents match", extra={
            "platform_incidents": platform_incidents
        })

        return None

    engaged = engagement_with(platform_incidents[0], reported=platform.reported_incident)

    if engaged is None:
        logger.warning("engagement could not be read")

        return None

    return EngagementAnswer(minutes=engaged.minutes,
                            responders=engaged.responders,
                            titles=engaged.titles,
                            engaged=[EngagedResponder(minutes=responder.minutes,
                                                      job_title=responder.job_title)
                                     for responder in engaged.engaged],
                            shared_with=_the_others_paged_under(platform_incidents[0],
                                                                incident_id, connections))


def _the_others_paged_under(platform_incident: str,
                            incident_id: str,
                            connections: Connections) -> int:
    """How many other Argus incidents the platform's incident is linked to.

    Linked is what the record knows: a person's resolution links every
    incident the page was open for, and engagement links the one it found.
    An incident still to come is not counted - nothing can be - which is why
    the one written last is the one that can say most.
    """
    with connections() as conn:
        linked = references.get_incidents_by_values(conn, ON_CALL_INCIDENT, [platform_incident])

    return len([incident for incident in linked if incident.id != incident_id])


def _the_platform_incidents_of(incident_id: str,
                               platform: OnCallPlatform,
                               connections: Connections) -> list[str]:
    """The platform's incidents this one may be: none, one, or - where
    nothing can tell them apart - several.

    The platform's ids where a person's resolution there already linked the
    two. Otherwise the platform incidents carrying a key the monitor paged
    under that were open while this incident was going on: a key is an alert
    group's, and every firing of the group opened a page under it, so a page
    that closed before this incident began was another firing's. One found is
    recorded, so the next question goes straight to it; several are not, since
    recording them would be choosing.
    """
    with connections() as conn:
        linked = references.get_values_for(conn, incident_id, ON_CALL_INCIDENT)
        keys = references.get_values_for(conn, incident_id, NOTIFICATION_KEY)
        incident = incidents.get(conn, incident_id)

    if linked:
        return linked

    if not keys or incident is None:
        return []

    found = [paged.id for paged in platform.incidents_for(keys)
             if paged.lifespan.overlaps(incident.lifespan)]

    if len(found) == 1:
        with connections() as conn:
            references.add(conn, incident_id, [
                Reference(source=platform.name, kind=ON_CALL_INCIDENT, value=found[0])
            ])
            conn.commit()

    return found


def _what_a_title_is_worth(*, read: PayBandsRead) -> Mapping[str, PayBand] | None:
    """What each job title the HR source prices is worth a year.

    Bands rather than anybody's pay: a band belongs to a level that titles are
    assigned to, so the response is priced without any person's compensation
    being read, and this deployment's credential never needs to be able to.

    Answers `None` where the source could not be read - including a deployment
    holding no HR credential at all. A postmortem is written either way; it
    simply publishes no cost and says why.
    """
    try:
        priced = read()
    except PayBandsUnavailable:
        logger.warning("pay bands could not be read", exc_info=True)

        return None

    return {title: PayBand(minimum=band.minimum,
                           midpoint=band.midpoint,
                           maximum=band.maximum,
                           currency=band.currency)
            for title, band in priced.items()}


def _the_alert_rule(rule: str, *, read: ReadTier) -> AlertRuleStanding | None:
    """`rule` as the read tier reads it off its definition - how long it waits
    with its condition holding before it fires, and the series it watches -
    over the session the metrics are read on.

    `None` where the tier could not read the rule, however the read failed -
    a refusal, no server, or an answer that never came back in time - never a
    standing made up: a rule that fires at once and one nobody could read are
    told differently, and a postmortem is written without the rule rather than
    lost for want of it.
    """
    try:
        return read.get_alert_rule(rule)
    except Exception:
        logger.warning("alert rule could not be read", exc_info=True, extra={"rule": rule})

        return None


def _metrics_between(window_start: datetime,
                     window_end: datetime,
                     rule: str | None,
                     *,
                     read: ReadTier,
                     served: timedelta) -> list[MetricBucket]:
    """The metrics channel, asked for a window spanning the whole incident and
    for the rule that paged, so the document's figures are read off the series
    the walk's were.

    In consecutive windows no wider than the tier serves whole. Its ceiling
    bounds what a model is handed, and cuts a wider window down from the start;
    the postmortem is code, and a week-long incident read as its first six hours
    is one whose recovery, and most of whose failing, was never seen.

    A range read answers for both its ends, so the minute two windows share
    comes back from each - and is kept once, or it would weigh double in every
    level the document reports.

    Nothing where any window could not be read, however the read failed - a
    refusal, no server, or an answer that never came back in time - which the
    document already says as no minute of the metrics read. Never raised, for
    `_the_alert_rule`'s reason: raised, a read of the shop that timed out failed
    the run of an incident already over, and nothing was written up. And never
    the windows that answered alone: rows stopping where a failed window begins
    are what a metrics outage looks like, and the document would say the
    service's metrics stopped where only the read did.
    """
    kept: dict[str, MetricBucket] = {}
    start = window_start

    try:
        while start < window_end:
            end = min(start + served, window_end)
            for bucket in read.get_metrics_summary(window_start=to_iso(start),
                                                   window_end=to_iso(end),
                                                   rule=rule):
                kept.setdefault(bucket.bucket_id, bucket)
            start = end
    except Exception:
        logger.warning("metrics could not be read", exc_info=True, extra={"rule": rule})

        return []

    return list(kept.values())
