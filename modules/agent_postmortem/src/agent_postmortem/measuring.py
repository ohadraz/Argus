"""Everything about an incident that is a number, read before anything is asked
of a model.

One function, because the figures are not independent: the loss is the
incident's hours against the same hours whole weeks earlier, beyond how far
those differ from the same hours as far back again; every window is dated from
the same instant,
and the currency the answer is published in is a property of the table that
converted them. Measured separately they could disagree with each other, and a
document whose duration and whose loss describe different incidents is worse
than one carrying neither.

Which is why recovery is found here, once, and every window below is bounded
by what it says. It is a property of the incident like the onset beside it,
and it is a fact about the service rather than about Argus: the walk stays
open through the verification wait, the code-fix attempt and the write-up, so
a figure measured to the close describes a service that was mostly fine. A
duration measured to recovery beside a rise measured to the close would be the
two-incidents-on-one-page failure this function exists to prevent.

Two clocks leave here, named as two. How long the service was broken is a fact
about the fault; how long Argus held the incident is a fact about the
response, and the second never stands in for the first.

Two costs, and they are the same kind of thing: what the outage cost customers,
and what the response cost the business. Both are money, both come from ports,
and both are reported side by side on the page.

Every source is asked once and what it answered is kept, because the sentences
the document discloses are written from the same reads that produced the
figures. A disclosure that went back to the rate table for the rate it is about
could name a rate the figure was not converted at.

`None` is never zero here. A source that could not be read leaves its figure
absent, and the absence carries as far as the page - an unreadable payment
provider must not become a postmortem reporting that the incident cost nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import NamedTuple

from argus_core import parse_iso, to_iso
from argus_core.anomaly import AnomalyThresholds, find_back_to_normal, find_recovery
from argus_core.models import MetricBucket
from pydantic import BaseModel, Field

from agent_postmortem.estimate import (
    BASELINE_WINDOW,
    DemandLevels,
    ErrorRates,
    LatencyLevels,
    RuleSeriesLevels,
    RuleSeriesSpan,
    Unmeasured,
    a_line_was_read,
    beyond_the_variation,
    calm_to_read_for,
    demand_over,
    duration_in_hours,
    error_rates_over,
    first_minute_past_its_line,
    in_the_reporting_currency,
    latency_over,
    rule_held_before_the_onset,
    rule_series_before,
    rule_series_over,
    weeks_back_for,
    why_no_error_rates,
)
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.responder_cost import ResponderCost, responder_cost
from agent_postmortem.sources import (
    EngagementAnswer,
    NotPaged,
    PayBand,
    RateTable,
    Sources,
)


class Measurements(BaseModel):
    """One incident, as far as it can be counted.

    Both the figures and what they were read from. The reads are here because
    nothing downstream may go back to a source: a document is written after the
    incident, sources move, and a second read is a second answer.

    The instant it was dated from travels too. A duration means nothing without
    it - an incident measured from its onset and one measured from its alert
    are different measurements, and only one of them can be compared with
    another incident's.
    """

    # How long the service was broken - onset to back to normal, both read off
    # the metrics. Not how long the walk stayed open: that clock runs through the
    # verification wait, the code-fix attempt and the write-up, and an impact
    # figure measured over it describes a service that was mostly fine.
    duration_in_hours: float
    # Where the service was back inside the range it keeps when nothing is
    # wrong - which is not where Mitigation saw it fall off the incident's
    # level, its recovery - and `None` where it was not back by the last minute
    # of metrics read. `None` is an answer rather than a
    # missing one: every figure above is then a lower bound, and whatever
    # renders them has to say so rather than quietly presenting a bound read
    # as a measurement.
    back_to_normal_at: datetime | None
    # Who reported the incident resolved, where that report is the end above -
    # an end a person's word set rather than one the metrics showed, and said as
    # theirs wherever it is said. `None` wherever anything else ended it.
    reported_by: str | None = None
    # How long Argus held the incident - the alert to the close. The one
    # figure on the page measuring the responder rather than the fault, which
    # is why it is kept and why it never stands in for the duration above. One
    # field answering both questions is the defect all of this came from.
    time_to_close_in_hours: float
    # What the error rate did, at the three levels worth reporting, or `None`
    # where it could not be measured - `error_rates_unmeasured` says why.
    # Nothing rests on it: it is what the
    # model is told about what happened, and no figure is computed from it.
    error_rates: ErrorRates | None
    loss: Decimal | None
    # What the loss is stated in, and `None` wherever there is no loss to
    # state. A currency beside an absent figure is a label for nothing.
    currency: str | None
    # What the shop took over the incident's own hours whole weeks earlier -
    # what the incident is compared with.
    baseline_revenue: Decimal | None
    # How far those hours and the same hours as far back again differ, in the
    # reporting currency: how much the shop varies on its own over them.
    # A shortfall no larger is no loss. `None` where either went unread.
    variation: Decimal | None = None
    # How far the incident's takings fell short of that stretch's, whether or
    # not it was beyond the variation - negative where the shop took more.
    # `None` where either went unread.
    shortfall: Decimal | None = None
    # What the incident's hours took whole weeks earlier, per currency, before
    # any of it was converted.
    # The conversions are disclosed one line each, and a line naming a currency
    # needs the currencies rather than the total.
    baseline_takings: Mapping[str, Decimal] | None
    rates: RateTable | None
    currencies_left_out: list[str]
    onset_at: datetime | None
    engaged: EngagementAnswer | NotPaged | None
    cost: ResponderCost | None
    bands: Mapping[str, PayBand] | None
    # The instant from which the metrics carry no minute at all, where the read
    # answered and its rows stop before the incident began. A different fact from
    # `back_to_normal_at` being `None`: that one measured a service still in trouble at
    # the end of the window, and this one measured nothing after the onset - so
    # the duration above is how long the metrics had been missing by the close,
    # not a stretch of trouble.
    #
    # Also where the rows come back, but only once Argus acted: an action that
    # restores the sight puts rows after the onset, and counted as sight, they
    # answer the question with what the action did about it.
    metrics_stopped_at: datetime | None = None
    # Where the metrics came back after they stopped - the minute their rows
    # resume, or the action that brought them back where they resume in its
    # minute, which describes only the seconds after it - and `None` where they
    # stopped and never resumed, or never stopped. The stretch the metrics did
    # not cover ends here, and so does every figure measured over it.
    metrics_resumed_at: datetime | None = None
    # What the paging rule's own series did, at the error rate's levels, or
    # `None` where the metrics carry no such series. Told to the model beside
    # the error rate and resting no figure, as that does.
    rule_series: RuleSeriesLevels | None = None
    # Why `error_rates` is `None`, and `None` itself wherever they were
    # measured. An absent figure alone was told to the model as metrics that
    # could not be read, about a read that had returned six hours of them.
    error_rates_unmeasured: Unmeasured | None = None
    # That the service was back to normal a whole minute before the action
    # credited with bringing it back - so the action did not. Attribution, said
    # rather than hidden by ending the incident at the action.
    back_before_the_action: bool = False
    # How long the paging rule waits with its condition holding before it
    # fires - part of the time from the onset to the alert. `None` where no rule
    # paged, or where its wait could not be read, which `rule_wait_unread` says:
    # a rule nobody could read is not one that fires at once.
    rule_waits: timedelta | None = None
    rule_wait_unread: bool = False
    # Whether the rule's series was past its line in every minute its wait
    # reaches back to before the onset (`rule_held_before_the_onset`), and
    # `None` where that could not be read - or there was no onset or wait to
    # read it for.
    rule_held_before_the_onset: bool | None = None
    # The query of the series the paging rule watches, which is what names the
    # series: the alert's words are its condition. `None` where no rule paged,
    # where the rule could not be read, or where no one series could be
    # followed in it.
    rule_series_query: str | None = None
    # The unit that series is in, as Grafana names a unit - read off the rule's
    # panel or its metric's name - and `None` where neither said one.
    rule_series_unit: str | None = None
    # Whether that series is the very query the error rate is read by: then what
    # the rule watched is the error rate, already said as one.
    rule_series_is_the_error_rate: bool = False
    # Whether that series is one of the queries a latency is read by: then what
    # the rule watched is how long requests took, already said at its levels.
    rule_series_is_a_latency: bool = False
    # How long requests took at each quantile, over the same stretch as the
    # error rate - empty where either side of it carried no minute. Told to the
    # model where nothing else it is given says what the people using the
    # service felt.
    latency: list[LatencyLevels] = Field(default_factory=list)
    # The load - requests a minute, and the CPU in use against its limit - over
    # the same stretch, and `None` where either side of it carried no minute.
    # Told to the model where the cause confirmed is the load.
    demand: DemandLevels | None = None
    # How far back the paging rule's condition looks - "no sample for 5m" holds
    # only once five minutes have passed with none - which is part of the time
    # from an onset to its alert, as the wait is. Nothing for a check that looks
    # back over no range, and `None` where no rule paged or it went unread.
    rule_looks_back: timedelta | None = None
    # How often the paging rule is evaluated: a condition that comes to hold
    # between two evaluations is seen at the second, so up to this much of the
    # time to the alert is the rule not having looked yet. `None` where no rule
    # paged or it went unread.
    rule_evaluated_every: timedelta | None = None
    # The first minute from the onset to the alert in which the rule's series
    # was past its line - where the time to the alert is weighed from, since a
    # fault that grows reaches the line after the onset - and whether any minute
    # there carried the line at all (`rule_line_read`), which tells a line never
    # passed from one never read. `None` and `False` without an onset.
    rule_past_its_line_at: datetime | None = None
    rule_line_read: bool = False
    # What the paging rule's series read over the minutes the rule looked at
    # before it fired - its wait and how far its condition looks back - on a
    # disproven alarm: the disproof's grounds in figures. `None` on any other
    # ending, where no rule paged or it went unread, or where no minute there
    # carried the series.
    rule_series_before_the_alert: RuleSeriesSpan | None = None


def measure(evidence: IncidentEvidence, sources: Sources) -> Measurements:
    """Read every source once, and count what they said.

    The incident is dated from its onset rather than from the alert. Those two
    differ by however long the alert took to fire, and counting those minutes
    as calm trade would raise the baseline using the very minutes the service
    was already failing in.
    """
    # The alert's own time where nothing measured an onset, as its sender dated
    # it - the instant the brief and the page date such an incident from. It is
    # the wrong instant to cost an incident from - which is why no loss is
    # published without an onset, below - but it is the right one to describe
    # it from, and the duration is the model's context rather than a published
    # figure.
    began = evidence.onset_at or evidence.alerted_at
    # Read once, and every window below bounded by what it says. Computed here
    # rather than per figure because it is a property of the incident, like
    # the onset beside it: a duration measured to recovery and a rise measured
    # to the close would be two incidents on one page, which is the failure
    # this function exists to prevent.
    # Back as far as the error rate's own variation needs, for an incident as
    # long as it can have been - bounded by its close, since how long it was
    # broken is only known once the read is in.
    metrics = sources.metrics(began - calm_to_read_for(evidence.ended_at - began),
                              evidence.ended_at,
                              evidence.rule)
    # Up to the action only from an onset: an incident with none is dated from
    # its alert, and the walk asks this of no window but one from an onset.
    sight = _the_sight_lost(metrics, began,
                            evidence.first_acted_at if evidence.onset_at is not None else None,
                            evidence.ended_at, sources.metrics_reporting_lag_minutes)
    # Where the service came back is judged on the hour before it, as it always
    # was: the readers find their own quiet half in what they are handed, and a
    # noisier stretch hours earlier would move the bar a minute is told apart by.
    recent = [bucket for bucket in metrics
              if parse_iso(bucket.bucket_id) >= began - BASELINE_WINDOW]
    resumed = sight.resumed if sight is not None else None
    if resumed is not None:
        # A stretch the metrics did not cover ends where they resume, whatever
        # the walk recorded later: nothing measured the service inside it, so no
        # figure is read from the minutes after it, and it is back to normal
        # there only where the rows it resumed with say so.
        found_back: datetime | None = resumed.in_minute
        back_to_normal_at = (resumed.at
                             if _back_to_normal_from(resumed.in_minute, recent, sources.thresholds)
                             == resumed.in_minute else None)
        back_before_the_action = False
        measured_until = resumed.at
    else:
        found_back = _when_the_service_came_back(
            evidence.recorded_recovery_at,
            evidence.resolution.at if evidence.resolution is not None else None,
            evidence.watched_and_never_recovered,
            recent,
            sources.thresholds,
            began
        )
        back_to_normal_at, back_before_the_action = _found_back_before(found_back, evidence)
        # The read has to end somewhere even when nothing says the service came
        # back, so it ends at the close - the boundary a query needs. What must
        # not happen is the substitution going unmarked, and `back_to_normal_at` is
        # the mark: absent, and every figure below is a lower bound.
        measured_until = back_to_normal_at or evidence.ended_at
    duration = duration_in_hours(began, measured_until)
    # Like with like: the incident against its own clock hours whole weeks
    # earlier, so a shop's day and week cancel out - and those against the same
    # hours as far back again, for how much the shop varies on its own.
    #
    # Nothing is read without an onset, since no loss is counted from the alert:
    # takings read for nothing were disclosed as converted at a rate no figure
    # was converted at.
    dated = evidence.onset_at is not None
    rates = sources.rates() if dated else None
    back = weeks_back_for(measured_until - began)
    taken_earlier = (sources.revenue(began - 2 * back, measured_until - 2 * back)
                     if dated else None)
    taken_before = sources.revenue(began - back, measured_until - back) if dated else None
    taken_during = sources.revenue(began, measured_until) if dated else None
    earlier_revenue, _ = _as_one_figure(
        taken_earlier, rates, sources.reporting_currency)
    baseline_revenue, left_out = _as_one_figure(
        taken_before, rates, sources.reporting_currency)
    revenue_during, _ = _as_one_figure(
        taken_during, rates, sources.reporting_currency)
    variation = (abs(baseline_revenue - earlier_revenue)
                 if baseline_revenue is not None and earlier_revenue is not None else None)
    shortfall = (baseline_revenue - revenue_during
                 if baseline_revenue is not None and revenue_during is not None else None)
    loss = _loss(shortfall, variation) if dated else None
    engaged = sources.engagement(evidence.incident_id)
    bands = sources.bands()
    alert_rule = sources.alert_rule(evidence.rule) if evidence.rule is not None else None
    waits = alert_rule.pending_seconds if alert_rule is not None else None

    return Measurements(
        duration_in_hours=duration,
        back_to_normal_at=back_to_normal_at,
        reported_by=(evidence.resolution.by
                     if evidence.resolution is not None
                     and back_to_normal_at == evidence.resolution.at else None),
        back_before_the_action=back_before_the_action,
        # From the incident's opening rather than from the onset or the
        # alert. The minutes before Argus had the incident are the fault's, not
        # the responder's - nobody had been told yet - and charging them to the
        # response would price Argus for a delay in somebody else's monitoring.
        time_to_close_in_hours=duration_in_hours(
            evidence.started_at, evidence.ended_at),
        # The end of the harm itself, not the bound the read fell back to. Where
        # the service never came back there is no first well minute to stop at,
        # and every minute read is part of the incident.
        #
        # The first well minute as found, not the end moved to an action inside
        # it: that minute read normal, and stopping at the action counted it as
        # broken - a healthy minute inside the stretch, pulling it towards the
        # baseline.
        error_rates=error_rates_over(metrics, began, found_back),
        loss=loss,
        currency=sources.reporting_currency if loss is not None else None,
        baseline_revenue=baseline_revenue,
        baseline_takings=taken_before,
        variation=variation,
        shortfall=shortfall,
        rates=rates,
        currencies_left_out=left_out,
        onset_at=evidence.onset_at,
        engaged=engaged,
        cost=_what_the_response_cost(engaged, bands, sources.working_hours_a_year),
        bands=bands,
        metrics_stopped_at=sight.stopped_at if sight is not None else None,
        metrics_resumed_at=resumed.at if resumed is not None else None,
        # Over the same stretch as the error rate, for the same reason.
        rule_series=rule_series_over(metrics, began, found_back),
        error_rates_unmeasured=why_no_error_rates(metrics, began, found_back),
        rule_waits=timedelta(seconds=waits) if waits is not None else None,
        rule_looks_back=(timedelta(seconds=alert_rule.range_seconds)
                         if alert_rule is not None else None),
        rule_evaluated_every=(timedelta(seconds=alert_rule.interval_seconds)
                              if alert_rule is not None else None),
        rule_wait_unread=evidence.rule is not None and waits is None,
        rule_series_query=alert_rule.series_query if alert_rule is not None else None,
        rule_series_unit=alert_rule.series_unit if alert_rule is not None else None,
        rule_series_is_the_error_rate=(alert_rule is not None
                                       and alert_rule.series_is_the_error_rate),
        rule_series_is_a_latency=alert_rule is not None and alert_rule.series_is_a_latency,
        # Over the same stretch as the error rate, for the same reason.
        latency=latency_over(metrics, began, found_back),
        demand=demand_over(metrics, began, found_back),
        rule_held_before_the_onset=(
            rule_held_before_the_onset(metrics, evidence.onset_at, evidence.alerted_at,
                                       timedelta(seconds=waits))
            if evidence.onset_at is not None and waits is not None else None),
        rule_past_its_line_at=(
            first_minute_past_its_line(metrics, evidence.onset_at, evidence.alerted_at)
            if evidence.onset_at is not None else None),
        rule_line_read=(evidence.onset_at is not None
                        and a_line_was_read(metrics, evidence.onset_at, evidence.alerted_at)),
        rule_series_before_the_alert=(
            rule_series_before(metrics, evidence.alerted_at,
                               timedelta(seconds=alert_rule.pending_seconds
                                         + alert_rule.range_seconds))
            if evidence.disproven and alert_rule is not None else None)
    )


class _Resumed(NamedTuple):
    """Where the metrics came back: as an instant, and as the minute their
    first row back is, which is what a read is cut at."""
    at: datetime
    in_minute: datetime


class _Sight(NamedTuple):
    """Where the metrics stopped, and where they came back - `None` where they
    never did."""
    stopped_at: datetime
    resumed: _Resumed | None = None


def _the_sight_lost(metrics: list[MetricBucket],
                    began: datetime,
                    first_acted_at: datetime | None,
                    closed_at: datetime,
                    reporting_lag_minutes: int) -> _Sight | None:
    """Where the read answered and holds no minute from `began` up to the
    minute Argus first acted in - or up to the close, where it never acted - and
    where the rows came back after it, if they did.

    Up to the action rather than the close, as the walk asks it of the window it
    judges an action on: an action that restores the sight puts rows after the
    onset, and counted as evidence the sight was there, they answer the question
    with the very thing the action did about it. The minute the action fell in
    is not asked about either: it is aggregated over seconds either side of the
    change, and where the action restores the sight it is the first minute the
    rows come back in. And where they come back in it, they came back after the
    action, which is when they are said to have resumed.

    An empty read is not this. It is a source that could not answer, and it
    says nothing about whether the service was being collected from - where a
    window whose rows simply stop says exactly that.

    Nor is a window that had not arrived. The newest minute a read can hold is
    the close's own minute less the source's lag, so an incident closed before
    its first minute was reported has no row after it however well it was
    watched. Dated from the close rather than from the read, so a postmortem
    written again says the same. Nor, for the same reason, rows back after an
    action taken inside the onset's own minute: there is no whole minute before
    it that a read could have held.
    """
    if not metrics:
        return None

    first_minute = _the_minute_starting_at_or_after(began)
    newest_reported = (closed_at.replace(second=0, microsecond=0)
                       - timedelta(minutes=reporting_lag_minutes))
    if first_minute > newest_reported:
        return None

    after = sorted(minute for bucket in metrics
                   if (minute := parse_iso(bucket.bucket_id)) >= began)
    if not after:
        return _Sight(stopped_at=began)

    if first_acted_at is None or first_acted_at < began:
        return None

    acted_in = first_acted_at.replace(second=0, microsecond=0)
    if first_minute >= acted_in or after[0] < acted_in:
        return None

    return _Sight(stopped_at=began,
                  resumed=_Resumed(at=max(after[0], first_acted_at), in_minute=after[0]))


def _the_minute_starting_at_or_after(instant: datetime) -> datetime:
    minute = instant.replace(second=0, microsecond=0)

    return minute if minute == instant else minute + timedelta(minutes=1)


def _as_one_figure(taken: Mapping[str, Decimal] | None,
                   rates: RateTable | None,
                   reporting_currency: str) -> tuple[Decimal | None, list[str]]:
    """What the service took, stated in the one currency the document reports
    in, and whatever could not be stated there at all.

    A quiet window took nothing, and nothing is a measurement: an empty mapping
    is zero rather than an unanswered question. Only an unread provider leaves
    no figure, because only it leaves no takings to state.

    A table nobody could read is a table with no rates in it, which the
    arithmetic already knows how to answer: whatever needed no conversion is in
    the figure, and every currency that did is named as missing from it. The
    currency this is reported in comes from the configuration either way - it is
    what the table was asked to quote against - so it is not a guess, and losing
    the money that needed no rate at all would be the worse answer.
    """
    if taken is None:
        return None, []

    if rates is None:
        return _only_the_money_needing_no_rate(taken, reporting_currency)

    return in_the_reporting_currency(taken, rates)


def _only_the_money_needing_no_rate(
        taken: Mapping[str, Decimal],
        reporting_currency: str) -> tuple[Decimal, list[str]]:
    """The takings already in the reporting currency, and every other currency.

    The same shape `in_the_reporting_currency` returns for a currency the table
    does not cover, because it is the same finding: money that was taken, and
    no rate to state it with.
    """
    return (
        taken.get(reporting_currency, Decimal(0)),
        [currency for currency in taken if currency != reporting_currency]
    )


def _loss(shortfall: Decimal | None, variation: Decimal | None) -> Decimal | None:
    """The estimate, or nothing when any window went unread.

    Nothing, never zero: an unreadable revenue source and a service that lost
    no money are different findings, and only one of them is a measurement.
    Every window is needed - a loss is the difference between two of them, and
    whether that difference is a loss at all is what the third says.
    """
    if shortfall is None or variation is None:
        return None

    return beyond_the_variation(shortfall, variation)


def _when_the_service_came_back(recorded: datetime | None,
                                reported: datetime | None,
                                watched_and_never_recovered: bool,
                                metrics: list[MetricBucket],
                                thresholds: AnomalyThresholds,
                                began: datetime) -> datetime | None:
    """The instant the incident ended, or `None` where nothing ever said.

    Looked for from the minute Mitigation recorded, where it recorded one: the
    first minute from there the service was back to normal
    (`_back_to_normal_from`), which is a different question from the
    recovery's and is asked here. The recovery itself is not checked against
    the series. That is the correction, and it is about *windows* rather than
    about rules: the rule was always one rule, but
    Mitigation asks it of the window it is polling and this asks it of a window
    bounded by the incident's close, so two evaluations of one rule over two
    spans of minutes could always disagree. They cannot disagree if the question
    is only asked once, and the answer belongs to the party that was watching at
    the time. The onset arrives the same way for the same reason (spec §16).

    Corroborating the recorded minute against the series would put the
    disagreement straight back, with the added defect of resolving it in favour
    of the window that was not there: a service that recovered, was confirmed,
    and relapsed afterwards would have its recovery withdrawn by minutes that
    came after Argus had stopped looking.

    Where a person reported the incident resolved, the report is the end, as
    said: it is the fact (spec §16), and searching the series from it would be
    Argus looking for a level falling to corroborate a claim it does not test.
    Second only to a recorded minute the service is found back to normal from,
    which is an earlier answer to when it was over; a recorded minute it never
    gets back from answers nothing, and the report stands. Over Mitigation
    never having seen the service come back, too - that is Argus's answer, and
    the report is the person's.

    The same holds where the answer was no. Mitigation watched, never saw the
    service come back, and said so on every look - and asking again of this
    window would resolve the same disagreement in favour of the window that was
    not watching. On a service that flaps it finds a lull in one run and none in
    the next, so the incident is not recovered, and every figure a lower bound.

    Falling back to the series where nothing was recorded, which is not a
    degenerate case but three ordinary ones: an incident that escalated before
    it acted, one nobody mitigated, and a recovery confirmed with nothing to
    date it by. None of them has a minute to give, and all get a postmortem.

    Never from the moment an action was applied, and never from the moment a
    verdict was reached. Those say when Argus acted and when it concluded, and a
    service does not recover because somebody acted on it.

    As an instant rather than the `bucket_id` the detector answers with, because
    everything here subtracts it from another instant.

    From `began` on, the instant the incident is dated from, for the reason
    Mitigation dates its own from the onset: a window re-read for where the
    incident started can open on an earlier episode and end that one instead.
    """
    if recorded is not None:
        back = _back_to_normal_from(recorded, metrics, thresholds)
        if back is not None or reported is None:
            return back

    if reported is not None:
        return reported

    if watched_and_never_recovered:
        return None

    recovered = find_recovery(metrics, thresholds, since=to_iso(began))

    return (_back_to_normal_from(parse_iso(recovered), metrics, thresholds)
            if recovered is not None else None)


def _back_to_normal_from(recovered: datetime,
                         metrics: list[MetricBucket],
                         thresholds: AnomalyThresholds) -> datetime | None:
    """Where the service was back inside the range it keeps when nothing is
    wrong, looking from the minute it fell off the incident's level - `None`
    where the minutes read from there never get back.

    A different question from the recovery's, asked once and here: the recovery
    is what a verdict on an action needs, and the end of the harm is what an
    impact needs, and a fix landing mid-minute leaves the minutes between the
    two still broken. The recovery is where looking starts and nothing before
    it is looked at, so a lull before Mitigation saw the service leave the
    incident is not the end of it.

    The recovery itself where the read holds no minute from it on: nothing
    read then says otherwise.
    """
    looking_from = recovered.replace(second=0, microsecond=0)
    if not any(parse_iso(bucket.bucket_id) >= looking_from for bucket in metrics):
        return recovered

    back = find_back_to_normal(metrics, thresholds, since=to_iso(looking_from))

    return parse_iso(back) if back is not None else None


def _found_back_before(back: datetime | None,
                       evidence: IncidentEvidence) -> tuple[datetime | None, bool]:
    """The end of the harm against the action credited with ending it, and
    whether the service was back before that action.

    A minute holding the action reads as normal for its seconds after the
    action, and says nothing of the seconds before - so there the end is the
    action. A whole normal minute ending at or before it says the service was
    back before Argus acted, which is a finding about attribution and is kept
    rather than tidied away by ending the incident at the action.
    """
    credited = evidence.credited_action
    if back is None or credited is None:
        return back, False

    if back <= credited.taken_at < back + timedelta(minutes=1):
        return credited.taken_at, False

    return back, back + timedelta(minutes=1) <= credited.taken_at


def _what_the_response_cost(engaged: EngagementAnswer | NotPaged | None,
                            bands: Mapping[str, PayBand] | None,
                            working_hours_a_year: float) -> ResponderCost | None:
    """What the people on the incident cost, or nothing where either half is
    missing.

    Both halves have to be there: minutes nobody could measure, minutes nobody
    was paged to spend, and bands nobody could read are different absences with
    the same consequence, and each is disclosed separately. The pricing itself
    declines any response it cannot price in full, so nothing here inspects the
    responders.
    """
    if not isinstance(engaged, EngagementAnswer) or bands is None:
        return None

    return responder_cost(engaged.engaged, bands, working_hours_a_year)
