"""Which kind of stretch an incident's impact was, decided once.

The stored impact, the brief, the summary and every page that reads the stored
impact describe the same stretch - back to normal, ended by a person's report,
never seen back, or not covered by the metrics at all - and a stretch decided
in four places can be four stretches. So it is decided here, by one rule, and
every site that says it matches on the answer.
"""

from __future__ import annotations

from core.models import ImpactExtent

from postmortem_writing.measuring import Measurements


def the_extent(measured: Measurements, disproven: bool) -> ImpactExtent:
    """The stretch `measured` describes, or that there was none.

    Metrics that stopped come first: whatever else is known of the end, the
    stretch is one they did not cover, and they resumed or they did not. Then a
    person's report, which is an end the metrics did not show. Then a service
    never seen back, whose every figure is a lower bound. A disproven alarm has
    no stretch at all.
    """
    if disproven:
        return ImpactExtent.DISPROVEN

    if measured.metrics_stopped_at is not None and measured.metrics_resumed_at is not None:
        return ImpactExtent.METRICS_RESUMED

    if measured.metrics_stopped_at is not None:
        return ImpactExtent.METRICS_MISSING

    if measured.reported_by is not None:
        return ImpactExtent.REPORTED

    if measured.back_to_normal_at is None:
        return ImpactExtent.AT_LEAST

    return ImpactExtent.MEASURED
