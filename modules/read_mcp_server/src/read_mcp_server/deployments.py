"""What one deployment changed, read as evidence (spec §16).

The fifth retrieval channel, and the only one that answers about a change rather
than about the service. Two sources meet here and neither leaves the tier: the
deployment history says which revision was running before the one being asked
about, and the repository says what differs between the two. A caller names one
revision and learns what landed.

It exists for one distinction nothing else here can make. A bad deployment and a
broken configuration arrive the same way, move the same signals, and are put right
the same way - and what separates them is whether the commit that landed touched
source code or the values it shipped with. The deploy summary cannot say: an
application syncs from one directory for the life of the application, so every
deployment of the shop reports `deploy`, the ones that rewrote source included.
That was tried, and a paid walk read the path exactly as instructed and reached
the wrong answer.

Nothing here decides what a path *means*. Which directories hold configuration
belongs to the repository being read, so a path labelled "code" or "config" would
be this module deciding something it cannot know - wrongly, the first time
somebody keeps their values beside their source. It says what changed and leaves
the reading to whoever weighs causes.

No scope, and the omission is load-bearing. `github_source_paths` narrows what
this tier searches and indexes to the directories holding the service itself,
which is right for reading code and inverting here: the configuration a deployment
ships lives outside the source tree by definition, so a narrowed comparison hides
the one file that answers the question - and hides it as a deployment that changed
nothing, which is not a weaker answer than the truth but its opposite.
"""

from __future__ import annotations

from typing import Final, Protocol

from argus_core.models import ChangeEvent
from repository_source import (
    RepositorySourceSettings,
    SourceDifference,
    the_difference_between,
)

from read_mcp_server.argocd import FetchApplication, the_revisions_deployed
from read_mcp_server.repository import RepositoryReadSettings, the_source_settings

# How many changed files one answer names. A name is one short line and is what
# tells code from configuration, so this is deliberately generous - and it lands
# where the comparison's own listing ceiling does, because a bound this tier holds
# should not depend on the source happening to hold one.
MOST_FILES_NAMED: Final = 300

# How many lines of diff one answer carries, across every file in it. The bound
# that actually protects a turn: names are cheap and diffs are not, so when this
# is spent the diffs stop and the names go on. A reader still learns which files
# changed, which is the whole of the distinction this channel exists for.
MOST_PATCH_LINES_ALL_TOLD: Final = 200

# The channel that answers about a change this one cannot. A feature flag has no
# revision and no repository behind it, so a flag's name arriving here is a caller
# having read one channel's answer into the other's argument.
THE_CHANNEL_THAT_REPORTS_FLAG_CHANGES: Final = "get_change_events"


class SourceComparer(Protocol):
    """How this module asks what differs between two commits.

    A `Protocol` rather than a `Callable` alias for the reason `FetchApplication`
    is one: a test stands it in with `create_autospec`, which needs something
    introspectable. Positional throughout, because the order of the two revisions
    is the whole of what distinguishes making a deployment from undoing it, and a
    keyword would let a caller swap them without looking wrong.
    """

    def __call__(self,
                 base: str,
                 head: str,
                 settings: RepositorySourceSettings, /) -> SourceDifference: ...


def what_a_deployment_changed(service: str,
                              revision: str,
                              settings: RepositoryReadSettings,
                              *,
                              fetch: FetchApplication,
                              compare: SourceComparer = the_difference_between
                              ) -> list[str]:
    """What the deployment of `revision` changed, as lines a model reads.

    The revision is the only subject. What it is compared against is found here,
    in the deployment history, and not asked of the caller: the revision deployed
    before this one is in that history and in nothing the caller has seen, so a
    caller supplying it would be supplying a guess - and a comparison against a
    guessed base describes the wrong change in exactly the shape the right one has.

    Three answers come back as prose rather than as a failure, because each is a
    fact about the deployment history rather than a failure to read it, and each
    leaves the caller with a different next move: a revision no deployment has, a
    deployment with nothing before it, and a deployment that changed nothing. The
    last of those is a conclusion something acts on - it rules the deployment out -
    which is exactly why a repository that could not be compared raises instead.
    """
    deployed = the_revisions_deployed(service, fetch=fetch)
    landed = _where_in_the_history(revision, deployed)

    if landed is None:
        return [
            f"No deployment of {service} has revision [{revision}]. The "
            f"deployment history holds "
            f"{[deploy.reference for deploy in deployed] or 'no deployment at all'}"
            f". If [{revision}] names a feature flag rather than a deployment, "
            f"what changed about it is reported by "
            f"{THE_CHANNEL_THAT_REPORTS_FLAG_CHANGES} - a flag has no revision "
            f"and no diff to read."
        ]

    if landed == 0:
        return [
            f"Revision [{revision}] is the earliest deployment of {service} the "
            f"history holds, so there is no earlier deployment to compare it "
            f"against. What it changed cannot be read; what it shipped can, by "
            f"reading the repository at that revision."
        ]

    before = deployed[landed - 1].reference
    difference = compare(before, revision, the_source_settings(settings))

    return _said(service, difference)


def _where_in_the_history(revision: str,
                          deployed: list[ChangeEvent]) -> int | None:
    """Which entry of the history this revision is, or that it is none of them.

    By position rather than by returning the entry itself, because what the caller
    wants is the entry *before* it - and an answer that hands back the match alone
    would have the caller searching the list a second time to find its neighbour.
    """
    for position, deploy in enumerate(deployed):
        if deploy.reference == revision:
            return position

    return None


def _said(service: str, difference: SourceDifference) -> list[str]:
    """One comparison as lines, bounded, with every bound it hit stated.

    The header names both revisions. What reads this is a model rather than the
    caller that asked, and a diff that does not say what it is a diff of is one the
    reader has to trust it was handed correctly.

    Names first and diffs second, per file, so that a budget running out costs the
    diffs and never the names. Which files a deployment touched is the answer to
    the question this channel is for; what changed inside them is how a reader
    becomes sure of it.
    """
    said = [
        f"Deployment of revision {difference.head} to {service}, compared against "
        f"{difference.base} - the revision deployed before it."
    ]

    if not difference.files:
        said.append(
            "It changed no file at all: the two revisions are identical, so "
            "nothing this deployment carried can account for the symptoms."
        )

        return said

    named = difference.files[:MOST_FILES_NAMED]
    lines_left = MOST_PATCH_LINES_ALL_TOLD
    unshown = 0

    for changed in named:
        said.append(f"{changed.status} {changed.path}")

        if changed.patch is None:
            said.append(
                "  (no diff: the comparison carries none for this file - it is "
                "not text, or its change was too large to list)"
            )
            continue

        patch = changed.patch.splitlines()

        if len(patch) > lines_left:
            unshown += 1
            continue

        said.extend(f"  {line}" for line in patch)
        lines_left -= len(patch)

    return said + _whatever_was_left_out(difference, unshown)


def _whatever_was_left_out(difference: SourceDifference,
                           unshown: int) -> list[str]:
    """The notices, which are the half of a bound that makes it honest.

    A short answer and a shortened answer look the same, so every one of these
    says which of the two this is. Without them a deployment that rewrote a
    repository arrives as one that touched the handful of files that happened to
    fit, and a cause gets attributed to the last of them.
    """
    notices = []

    if difference.more_files_than_listed:
        notices.append(
            "... and more, not listed: the comparison reports more changed files "
            "than it will name, so what is above is not all of it - this "
            "deployment changed a great deal."
        )
    elif len(difference.files) > MOST_FILES_NAMED:
        notices.append(
            f"... and {len(difference.files) - MOST_FILES_NAMED} more files, not "
            f"named: this deployment changed more files than one answer carries, "
            f"so what is above is not all of it."
        )

    if unshown:
        notices.append(
            f"... and the changes to {unshown} more files, not shown: the diffs "
            f"above reached the {MOST_PATCH_LINES_ALL_TOLD} lines one answer "
            f"carries. Those files are named above; what changed inside them is "
            f"not here."
        )

    return notices
