from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

from argus_core import SettingsSlice, to_iso, utc_now
from argus_core.mcp_transport import McpClient
from argus_core.models import (
    FlagChange,
    MetricBucket,
    RestartedService,
    UndoDescriptor,
)
from read_mcp_client import get_metrics_summary
from write_mcp_client import (
    get_recent_flag_changes,
    restart_service,
    set_feature_flag,
)

from agent_mitigation.attribution import change_by_actor_to, changes_not_made_by


class FlagChangeFetcher(Protocol):
    """What `mitigate` needs from whatever reads recent flag changes.

    A `Protocol` for the reason `ActionTaker` is one, and asking nothing for
    the same reason: how far back the window reaches was decided where the
    process started.
    """

    def __call__(self) -> list[FlagChange]: ...
# The same tool asked for a window that starts where the caller says, rather
# than where configuration says. Only the resumed walk needs that: it is asking
# about one particular moment - when an action was claimed - and the configured
# lookback is about something else entirely.
class FlagChangesSince(Protocol):
    def __call__(self, since: str) -> list[FlagChange]: ...
# The service's own account of itself, and the one way to change what it does.
# `Protocol` rather than a `Callable` alias for both, because a test stands each
# in with `create_autospec` and specing against the function that answers them
# would be specing against the wrong shape: those take the connection they are
# asked over, and neither of these knows a server exists.


class MetricsFetcher(Protocol):
    def __call__(self) -> list[MetricBucket]: ...


class FlagSetter(Protocol):
    def __call__(self, flag: str, enabled: bool, /) -> UndoDescriptor: ...


class ServiceRestarter(Protocol):
    """The tier's other write: bringing a service back under a new process.

    It answers with what came up rather than with nothing, because a restart
    that was accepted and never happened is indistinguishable from the symptoms
    alone. No undo descriptor, and no room for one - there is nothing a restart
    leaves behind for anybody to put back.
    """

    def __call__(self, service: str, /) -> RestartedService: ...
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
# Whether the walk waiting on an action is still one anybody wants. Takes
# nothing: which incident this is belongs to the caller, and an agent that had
# to be told would be an agent that could look it up - which is a database this
# module has no business holding an opinion about.
StillWanted = Callable[[], bool]
# Whether somebody other than Argus changed a flag since a given moment, or
# `None` where nobody can say. What an undo consults before it writes: a change
# made after Argus's own is somebody's deliberate decision, and putting the flag
# back would replace it with a state nobody chose.
ChangedFromOutside = Callable[[str, datetime], bool | None]


class MitigationSettings(SettingsSlice):
    """How Mitigation behaves against the provider and the service.

    How far back a window of recent flag changes reaches, whose changes Argus
    recognises as its own, and how long it waits for the service to answer an
    action.

    `unleash_actor` is empty where Argus and its operators share one
    credential. That is a real deployment and not a misconfiguration - the
    attribution rules answer `None` there rather than guessing.
    """

    flag_change_lookback_minutes: int
    unleash_actor: str
    mitigation_verification_timeout_seconds: float
    mitigation_attempts_per_subject: int


def flag_changes_over(client: McpClient) -> FlagChangesSince:
    """The provider's flag history, asked over one connection to the write tier.

    The tier is the write tier because the provider serves its audit log to
    admin credentials only, and `argus-read-mcp` holds none by design. Reading
    history is strictly less than the write tier can already do.
    """
    return partial(_flag_changes_since, client=client)


def recent_metrics_over(client: McpClient) -> MetricsFetcher:
    """The service's metrics, asked over one connection to the read tier."""
    return partial(fetch_recent_metrics, client=client)


def flag_setter_over(client: McpClient) -> FlagSetter:
    """One of the two writes Argus makes, over one connection to the write
    tier."""
    return partial(set_flag, client=client)


def service_restarter_over(client: McpClient) -> ServiceRestarter:
    """The other, over the same connection."""
    return partial(restart_a_service, client=client)


def _flag_changes_since(since: str, *, client: McpClient) -> list[FlagChange]:
    """The write tier's flag history, asked from one moment onwards.

    A named function rather than `get_recent_flag_changes` itself, because the
    agent needs exactly one of that tool's calling shapes and a seam is only
    useful if a test can spec against the shape the caller actually uses.
    """
    return get_recent_flag_changes(since, client=client)


def fetch_recent_flag_changes(
    settings: MitigationSettings,
    fetch: FlagChangesSince,
    now: Clock = utc_now,
) -> list[FlagChange]:
    """The flag toggles recorded over the configured lookback, oldest first -
    excluding the ones Argus itself made.

    A named function rather than `get_recent_flag_changes` passed directly,
    because the agent needs exactly one of that tool's calling shapes - a
    window ending now - and a seam is only useful if a test can spec against
    the shape the caller actually uses. Deciding the window here also keeps
    `propose_action` free of both configuration and I/O.

    `fetch` is not defaulted, here or in the two questions below. It is the
    provider reached over a connection somebody opened, and a default would be
    this module deciding where that provider is - which belongs to whoever
    started the process. The clock still is: a clock is not an address.

    Argus's own changes are dropped here rather than by the caller, because
    every caller wants the same thing: what somebody *else* did. Once Argus can
    act more than once on an incident, its own revert lands in this window, and
    a window carrying it makes the unambiguous case - one flag changed, so that
    is the one to put back - report two flags and refuse to act.
    """
    lookback = timedelta(minutes=settings.flag_change_lookback_minutes)

    return changes_not_made_by(
        settings.unleash_actor,
        fetch(since=to_iso(now() - lookback)),
    )


def argus_changed_flag_since(
    flag: str,
    since: datetime,
    settings: MitigationSettings,
    fetch: FlagChangesSince,
) -> bool | None:
    """Whether Argus's own change to `flag` reached the provider after `since`.

    The question a walk asks when it is resumed inside the mitigation node and
    finds an action claimed with nothing recorded against it: the worker that
    claimed it died, and only the provider knows whether the change it was
    making landed. The provider's event log is where that is written down, and
    it is already what tells Argus's changes from a human's - asked here in the
    one direction the rest of Argus never asks it.

    `None` means the provider could not say - it could not be reached, or it
    attributes nothing to Argus because operator and agent share a credential.
    A caller must not read that as "no change was made": the difference between
    an unmade change and an unanswerable question is the difference between
    acting again and escalating.
    """
    try:
        changes = fetch(since=to_iso(since))
    except Exception:
        # Every way the provider can fail to answer arrives here, and they all
        # mean the same thing to the caller: nobody can say. Narrowing this to
        # the transport's own exception would let a change in the client's
        # vocabulary turn "could not ask" into a crash inside a resumed walk.
        return None

    return change_by_actor_to(flag, settings.unleash_actor, changes)


def somebody_else_changed_flag_since(
    flag: str,
    since: datetime,
    settings: MitigationSettings,
    fetch: FlagChangesSince,
) -> bool | None:
    """Whether anybody but Argus changed `flag` after `since`.

    What an undo consults before it writes, and the mirror of the question
    above: not "did my change land" but "has anybody been in here since it
    did". The provider's event log answers it, and nothing else can - current
    state cannot, because a flag somebody switched and switched back reads
    exactly like one nobody touched, and the provider serves current state from
    a cache that lags the change that matters most.

    `None` means nobody can say: the provider could not be reached. A caller
    must not read it as "nobody has been in here" - the two are the difference
    between putting a change back and overwriting a person.

    A deployment that attributes nothing - operator and agent sharing one
    credential - answers `True`, because `changes_not_made_by` filters nothing
    there and Argus's own write is then indistinguishable from somebody else's.
    That is the safe direction: a flag left as found can be put back by hand,
    and a human's deliberate change overwritten cannot be recovered at all.
    """
    try:
        changes = fetch(since=to_iso(since))
    except Exception:
        return None

    return any(
        change.flag == flag
        for change in changes_not_made_by(settings.unleash_actor, changes)
    )


def fetch_recent_metrics(*, client: McpClient) -> list[MetricBucket]:
    """The service's metric buckets, over the retention the read tier holds.

    Unanchored deliberately. The verdict asks whether the minutes since the
    action sit at the service's baseline, and the baseline is the incident's
    own quiet stretch - a window narrowed to post-action minutes alone would
    have no departure to contrast with, and would read any steady rate as
    healthy however elevated it was.
    """
    return get_metrics_summary(client=client)


def restart_a_service(service: str, *, client: McpClient) -> RestartedService:
    """Restarts a service, answering with the process that came up.

    A named function rather than `restart_service` itself, for the reason
    `_flag_changes_since` is one: the agent needs one of that tool's calling
    shapes, and a seam is only useful if a test can spec against the shape the
    caller actually uses.
    """
    return restart_service(service, client=client)


def set_flag(flag: str, enabled: bool, *, client: McpClient) -> UndoDescriptor:
    """Sets a flag to a state, returning the undo descriptor for the change.

    One seam for both taking an action and undoing it: undoing is the same call
    with the state reversed. That is not a convenience - it is what lets a
    refuted mitigation be put back in whichever direction it went.
    """
    return set_feature_flag(flag, enabled, client=client)
