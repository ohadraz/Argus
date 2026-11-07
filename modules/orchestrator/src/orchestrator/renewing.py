"""Keeping a claimed run's lease alive while its walk goes on.

A lease bounds how long a *stopped* worker's run waits before somebody takes it
back. It is not a budget for the walk, and must not be read as one: the
investigation is allowed 1,800 seconds and Code-Fix 1,100, either of which
outlasts the 720 the lease is set to. So the claim is renewed for as long as
the walk runs, and this is what renews it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Final

from argus_core import Connections, in_real_time
from argus_incidents.repository import runs

logger = logging.getLogger(__name__)

# How often the claim is renewed, as a fraction of the lease. A third, so two
# renewals may be missed - a slow query, a process the operating system paused -
# before anything else is entitled to take the run for abandoned.
RENEWALS_PER_LEASE: Final = 3

# Waits up to the given seconds between renewals, and answers whether renewing
# should stop - `threading.Event.wait`'s shape, which is what the worker hands
# in. Injected so the loop is tested in no time at all.
type Stopped = Callable[[float], bool]


def between_renewals(lease: timedelta) -> float:
    """How many real seconds pass between two renewals of `lease`.

    Postgres measures the lease on the stack's clock and renewing waits on the
    real one, so the interval is converted - or a stack running faster than
    real time would see its lease lapse under a walk still in progress.
    """
    return in_real_time(lease.total_seconds() / RENEWALS_PER_LEASE)


def keep_renewing(held: runs.Run,
                  lease: timedelta,
                  connections: Connections,
                  stopped: Stopped) -> None:
    """Renews `held`'s lease every third of it until `stopped` says to stop, or
    until the run is no longer this claim's.

    A renewal that fails is logged and the next is tried. Stopping at the first
    one let a single blip end renewing for good: the lease then ran out under a
    walk still going, and the run was taken back and walked a second time
    beside it - the double walk renewing exists to prevent. The walk is not
    taken down with it either; a database that stays unreachable fails the
    run's settling soon enough.

    A renewal that finds the run taken back, or settled, ends renewing: the run
    is somebody else's or nobody's, and the claim that lost it has nothing left
    to keep alive.
    """
    every = between_renewals(lease)

    while not stopped(every):
        try:
            with connections() as renewing_conn:
                still_held = runs.renew(renewing_conn, held, lease)
        except Exception:
            # A thread of its own, outside the run's context, so the run is
            # named here rather than stamped.
            logger.warning("claim could not be renewed, renewing again next time",
                           exc_info=True, extra={"run_id": held.id})
            continue

        if not still_held:
            logger.warning("run no longer held by this claim, renewing stopped",
                           extra={"run_id": held.id, "epoch": held.epoch})
            return
