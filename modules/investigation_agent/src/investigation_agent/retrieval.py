from __future__ import annotations

from functools import partial
from typing import Protocol

from core.models import (
    ChangeEvent,
    DeploymentChanges,
    FlagChange,
    MetricBucket,
    PodPlacement,
    RolloutAccount,
    ServiceDependency,
    as_a_change,
)

# What the loop asks of each retrieval channel, said as the shape it calls with
# rather than as the tier that answers today. `Protocol` rather than a
# `Callable` alias throughout: a test stands each of these in with
# `create_autospec`, which needs something introspectable. A composition root
# binds each to the read tier's own method for it - `ReadTier.get_placements`
# satisfies `PlacementFetcher` as it stands - so nothing sits between the two
# to re-spell the call, and this package never names a tier.


class MetricsFetcher(Protocol):
    """The metrics, anchored on the alert and read for the rule that paged.

    The rule rather than the series it watches: what that series is called in
    the metrics backend's own language is the read tier's to work out, and
    nothing on this side of the port speaks it. The rule travels so that each
    minute carries that rule's own series beside the five fixed ones: it is the
    only signal a fault in what the service answers departs in.

    Anchored on the alert, so no window is named. Keyword-only, both, because
    the read tier's own call takes a window beside them, all the same type: a
    positional seam would type-check against it and send the rule as the
    window's start.
    """

    def __call__(self, *, alert_time: str | None, rule: str | None) -> list[MetricBucket]: ...


class LogFetcher(Protocol):
    """One explicit window of log lines, both bounds ISO-8601.

    Always a window, never an alert anchor - by the time the loop reads logs it
    has an onset, and the point of two-phase retrieval is to spend the
    expensive phase around that onset. Keyword-only for `MetricsFetcher`'s
    reason.
    """

    def __call__(self, *, window_start: str, window_end: str) -> list[str]: ...


class ChangeFetcher(Protocol):
    def __call__(self,
                 service: str,
                 window_start: str,
                 window_end: str, /) -> list[ChangeEvent]: ...


class DependencyFetcher(Protocol):
    """The register, asked what one service calls.

    The only channel here with no window in its shape, and the absence is the
    point: what a service calls is a fact about how it is built rather than
    about a stretch of time, so there is nothing to date and nothing to widen.
    """

    def __call__(self, service: str, /) -> list[ServiceDependency]: ...


class DeploymentDiffFetcher(Protocol):
    """One deployment, asked what it changed.

    The second channel with no window, and the only one with a subject. What a
    deployment changed is a fact about one commit, so there is nothing to date;
    but there is more than one deployment, and which one is being asked about is
    the model's to name - so a revision goes in where the others take nothing.

    Answers in lines rather than in a shape of a diff's own. What comes back is a
    diff and the two revisions it is between, which is prose by nature: a model
    reads it, and a type with a `patch` field in it would be a shape three modules
    had to agree on to carry text that is already text. Beside the lines, whether
    they name every file - the one thing about them that is not for the model.
    """

    def __call__(self, service: str, revision: str, /) -> DeploymentChanges: ...


class RolloutFetcher(Protocol):
    """One service, asked whether the deployment it is running has converged.

    The third channel with no window, and the register's shape rather than the
    deployment diff's: whether a rollout finished is a fact about the deployment
    running now, so there is nothing to date - and there is nothing for a model
    to name either, because the service is the incident's.

    Answers with a value - the counts, the revision going out and the one before
    it - rather than in lines, unlike the deployment diff. A diff is said to
    every reader as it was read; a rollout is said by each reader in its own
    words, the model's among them, and they write those from the fields.
    """

    def __call__(self, service: str, /) -> RolloutAccount: ...


class PlacementFetcher(Protocol):
    """One service, asked where each of its replicas runs.

    The rollout's shape, and the one channel here the model never asks for. The
    loop reads it once, after the onset, because a pin to a card is decided
    from it and a model that never asked would leave nothing to decide from.

    Answers in Argus's own values rather than in lines, unlike the two beside
    it: what comes back is read by the walk as well as shown to a model, and
    which pods started at the onset is a comparison, not a sentence.
    """

    def __call__(self, service: str, /) -> list[PodPlacement]: ...


# The two systems that record a change, as this module reaches them. Named types
# for the reason the three above are, and told apart by name rather than by
# position: a deploy history and a flag history are two three-argument callables
# and nothing else would distinguish them.


class DeployHistory(Protocol):
    def __call__(self,
                 *,
                 service: str,
                 window_start: str,
                 window_end: str) -> list[ChangeEvent]: ...


class FlagHistory(Protocol):
    def __call__(self, since: str, /) -> list[FlagChange]: ...


def changes_from(deploys: DeployHistory, flags: FlagHistory) -> ChangeFetcher:
    """The change channel, over the two histories that record a change.

    Handed both rather than a tier, because the two live on two tiers (see
    `fetch_change_events`) and which method of which answers is a composition
    root's to bind - the deploys the read tier's, the flags the write tier's.
    This package never holds the write tier to ask it.
    """
    return partial(fetch_change_events, get_change_events=deploys, get_recent_flag_changes=flags)


def fetch_change_events(service: str,
                        window_start: str,
                        window_end: str,
                        *,
                        get_change_events: DeployHistory,
                        get_recent_flag_changes: FlagHistory
                        ) -> list[ChangeEvent]:
    """The third channel: what changed on the service over one explicit window.

    A separate seam from the log fetcher because it answers a different
    question on a different timescale - *what changed* rather than what the
    service said - over a window far wider than any the widening schedule
    reaches. There are only ever a handful of changes to read where there
    would be millions of log lines.

    Two sources, because two systems record a change to what a service does.
    A deploy has a commit and a pipeline behind it; a feature flag flipped has
    neither, and until it was read here the Investigator could only find one by
    noticing that a log line happened to mention it - a cause found by luck.

    They arrive from different tiers, and that is not an accident to tidy away:
    the flag provider serves its audit log to admin credentials only, and the
    read process holds none by design. Reading history is strictly less than
    the write tier can already do, and the tier split's claim is that the
    *read* process cannot mutate - which is untouched.

    Merged here rather than by either server, so neither has to learn that the
    other exists. What comes back is one history in time order, because that is
    what it is: the things that happened to this service, whoever recorded them.

    Neither source is defaulted. Both are asked over a tier somebody opened, and
    a default would be this module deciding where a deployment's servers are -
    which is a composition root's business.

    Raises rather than reporting nothing when either source cannot be reached.
    "Nothing changed" is a conclusion something acts on, so a source that was
    never read must not arrive looking like one that was read and found empty.
    """
    deploys = get_change_events(
        service=service, window_start=window_start, window_end=window_end
    )
    # The provider is asked what happened *since* a moment - it has no notion of
    # a far end - so the window's close is applied here. Without it a flag
    # flipped after the incident began would be offered as something that might
    # have caused it.
    toggles = [
        as_a_change(toggle)
        for toggle in get_recent_flag_changes(window_start)
        if toggle.occurred_at <= window_end
    ]

    return sorted([*deploys, *toggles], key=lambda change: change.occurred_at)
