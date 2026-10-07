from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from argus_core.models.change_event import ChangeEvent
from argus_core.models.flag_change import FlagChange


@dataclass(frozen=True)
class Circumstances:
    """Everything a round established that an action can be worked out from,
    apart from the candidate the action would answer.

    One value rather than a parameter each, because what a strategy needs grows
    with the modes it answers: each new kind of evidence was one more parameter
    on every strategy, on the lookup and on the walk's three callers, read by one
    strategy and named by all of them. Here it is one more field.

    The candidate stays outside because it is the one thing that varies within a
    round - the walk asks what each of several candidates would be answered with,
    and the rest is the same for all of them.

    `service` is the alert's, because an action addressed to a service is
    addressed to the one the incident is about; a candidate's subject is prose
    and names nothing a platform could be asked to act on.

    `stale_entry_keys` is the one field that is an address rather than an
    account of what happened. A cache key belongs to whoever wrote the cache, so
    nothing in Argus composes one - the evidence that named it carries it here
    as a value, never through a model's conclusion.

    `flag_changes` and `deployments` are what the provider and the platform
    recorded over the round's window. A flag history nobody could read is not an
    empty one, and is never represented here: no circumstances are built for it,
    because nothing is proposed while the provider cannot be read.

    A contract rather than Mitigation's own type, because the walk builds it and
    a shape kept inside the agent is one the Orchestrator installs an agent to
    name.
    """

    service: str
    flag_changes: Sequence[FlagChange]
    # Empty by default, because every mode but one is answered without them -
    # and an alert that mentions no cache says nothing about entries, rather
    # than claiming none is stale.
    stale_entry_keys: Sequence[str] = ()
    # Empty by default for the same reason: one mode reads them, and that mode
    # proposes a rollback only where a deployment was recorded.
    deployments: Sequence[ChangeEvent] = ()
