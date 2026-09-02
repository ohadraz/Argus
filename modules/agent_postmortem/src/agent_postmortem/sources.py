"""The two things the Postmortem needs that Argus cannot yet answer.

Both are stated as the question the agent has, not as anything a provider
offers: *what did the service take between these two times*, and *who
responded to this incident and for how long*. Neither mentions a payment
processor or an on-call tool, and nothing above these names one either.

They are ports rather than clients because no adapter exists yet. Defining
them here rather than in `argus_core` is deliberate: nothing else consumes
them, and a shared abstraction with one consumer is a guess about the second.

`None` from either is "could not be read", never "there was nothing". The
difference is the whole point of the type: a revenue source that is down must
not become a postmortem reporting that the incident cost nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from argus_core.models.metrics import MetricBucket
from pydantic import BaseModel

# What the service took between two instants, or `None` if nobody could say.
type Revenue = Callable[[datetime, datetime], Decimal | None]

# Pre-aggregated service metrics over a window - the same channel the
# Investigator reads, asked for a wider window than it ever had reason to.
type Metrics = Callable[[datetime, datetime], list[MetricBucket]]


class EngagementAnswer(BaseModel):
    """How much human attention an incident took.

    Two numbers rather than one, because they answer different questions: how
    long the incident occupied someone, and how many someones it occupied. An
    exec summary says "three engineers, two hours"; a single total says
    neither.

    A type of its own rather than a member of the port below: a port that is a
    plain callable can be satisfied by any function, and a function carries no
    nested class - so hanging the answer off the port would mean no test double
    could ever be one.
    """

    minutes: int
    responders: int


# Who responded to one incident and for how long, or `None` if nobody could
# say.
type Engagement = Callable[[str], EngagementAnswer | None]
