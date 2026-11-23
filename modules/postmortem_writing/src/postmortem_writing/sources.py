"""The things the Postmortem needs to be told from outside Argus.

Each is stated as the question the Postmortem Writer has, not as anything a
provider offers - *who responded to this incident and for how long*, *what did
the service's metrics read between these two times* - and none of them names an
on-call tool, a metrics store or any other vendor, nor does anything above
them. The money is asked through `incident_cost`'s own sources, which `Sources`
carries whole.

They are ports rather than clients, so that the question is the Postmortem
Writer's and the answer is a vendor's: each is answered by an adapter in a
package of its own, wired in by the process that writes the document, and
nothing here knows which one answered. Defining them here rather than in `core`
is deliberate: nothing else consumes them, and a shared abstraction with one
consumer is a guess about the second.

`None` from any of them is "could not be read", never "there was nothing". The
difference is the whole point of the type: an on-call platform that is down
must not become a postmortem reporting that nobody responded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from core.anomaly import AnomalyThresholds
from core.models import AlertRuleStanding, MetricBucket
from incident_cost import EngagedResponder, MoneySources
from pydantic import BaseModel

# Pre-aggregated service metrics over a window - the same channel the
# Investigator reads, asked for a wider window than it ever had reason to, and
# for the same rule: the one that paged, whose own series each minute then
# carries beside the five. `None` for an incident paged by no rule. Empty where
# it could not be read, which is what an empty read already says on the page -
# no minute of the metrics read - and never raised.
type Metrics = Callable[[datetime, datetime, str | None], list[MetricBucket]]

# The paging rule as the read tier reads it - how long its condition has to hold
# before it fires, and the query of the series it watches - or `None` if nobody
# could say. The rule as it is defined when the document is written, minutes
# after it paged - the same rule the metrics are read for.
type AlertRule = Callable[[str], AlertRuleStanding | None]


class EngagementAnswer(BaseModel):
    """How much human attention an incident took.

    Two numbers rather than one, because they answer different questions: how
    long the incident occupied someone, and how many someones it occupied. An
    exec summary says "three engineers, two hours"; a single total says
    neither.

    `minutes` is person-minutes - each responder's own engagement, added
    together - so a source answering it has already accounted for how many
    people were on it, and nothing above may multiply by the count again.

    The titles say what those people were, and never who. A document reporting
    that a senior engineer and an SRE spent the night is one a reader can act
    on; the same document with names is about people, and it gets emailed.
    Fewer titles than responders means one could not be read, which is a gap in
    the description rather than in the measurement.

    A type of its own rather than a member of the port below: a port that is a
    plain callable can be satisfied by any function, and a function carries no
    nested class - so hanging the answer off the port would mean no test double
    could ever be one.
    """

    minutes: int
    responders: int
    titles: list[str] = []
    # The same response, held per person rather than summed. Alongside the
    # total rather than instead of it: a reader wants the total, and anything
    # pricing the response cannot use it.
    engaged: list[EngagedResponder] = []
    # How many other incidents the same on-call incident was also about. A
    # page can stay open across two of Argus's incidents - one it said it
    # mitigated while the alarm went on, and the one that followed - and its
    # response is then reported in full on each, which is only honest while
    # each says it was shared.
    shared_with: int = 0


class NotPaged(BaseModel):
    """Nobody was asked to respond: no on-call incident was linked to this one.

    The third answer, distinct from both of the others. Not an incident nobody
    engaged with - zero minutes is a measurement of people who were paged and
    did not come - and not a source that could not be read: the source
    answered, and none of its incidents was this one. A document that said
    either would be wrong about which blank it is leaving.
    """


# Who responded to one incident and for how long; `NotPaged` where nobody was
# asked to; or `None` if nobody could say.
type Engagement = Callable[[str], EngagementAnswer | NotPaged | None]


@dataclass(frozen=True)
class Sources:
    """Everything the Postmortem reads and does not own.

    One value rather than six arguments, because that is what they are: a
    deployment configures them once, they are the same for every incident it
    writes about, and only the incident varies from call to call. Passed
    separately they would be six chances to hand one call a different world
    from the last.

    The money arrives as one value of its own (`MoneySources`), because what it
    is read through and the arithmetic done with it are `incident_cost`'s.
    """

    money: MoneySources
    engagement: Engagement
    metrics: Metrics
    alert_rule: AlertRule
    # Where the algorithm draws its lines, on the same terms as the money's
    # working year: a number rather than a port, read from the
    # deployment at the same moment as the source it is applied to. It decides
    # which minute the service recovered at, and every window this module
    # measures is bounded by that - so thresholds configured apart from the
    # metrics source would be a recovery found under one set of lines and a
    # mitigation confirmed under another.
    thresholds: AnomalyThresholds
    # How many minutes behind the clock the metrics source reports, on the
    # same terms as `thresholds`: a property of the source, read from the same
    # deployment. It decides the newest minute a read could hold, and a minute
    # not yet reported is no evidence that nobody was watching.
    metrics_reporting_lag_minutes: int
