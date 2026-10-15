"""Deploy history, read from the deployment platform (spec §16).

The change channel's first source. What the platform recorded comes through its
reads port as Argus's own records; this maps each onto a `ChangeEvent` and
applies the window. Everything above sees `ChangeEvent`, and nothing here knows
which vendor answered.

Mapping is ordinary deterministic code - never a model. A hallucinated deploy is
a fabricated cause, and the verdict would then rest on evidence that never
existed.
"""

from __future__ import annotations

from argus_core import parse_iso
from argus_core.models import ChangeEvent, ChangeKind
from deployment_platform import (
    DeploymentPlatformError,
    DeploymentPlatformReads,
    DeploymentRecord,
)
from repository_source import owner_and_name, where_to_read

from read_mcp_server.change_source import ChangeSourceUnavailable


def the_revisions_deployed(application: str,
                           *,
                           platform: DeploymentPlatformReads) -> list[ChangeEvent]:
    """Every deploy of one application, oldest first, with no window applied.

    The whole history, because what one deployment is compared against is the
    revision deployed before it - and that revision is under no obligation to
    fall inside whatever window an investigation happens to be reading. Windowed,
    the comparison would quietly be against the window's oldest entry instead: a
    diff of the wrong thing, in exactly the shape a diff of the right thing has.

    Ordered here rather than taken as the platform served it. Which order its
    history arrives in is the platform's business and not a promise a diagnosis
    may rest on, and "the one before this" is meaningless without one.

    A platform that did not answer becomes `ChangeSourceUnavailable`, whichever
    way it failed. Neither may become "no changes".
    """
    try:
        recorded = platform.deployments_of(application)
    except DeploymentPlatformError as error:
        raise ChangeSourceUnavailable(
            f"could not read deploy history for [{application}]: {error}"
        ) from error

    return sorted(
        (_a_deploy_from(record) for record in recorded),
        key=lambda deploy: parse_iso(deploy.occurred_at)
    )


def fetch_deploys(
    application: str,
    *,
    window_start: str,
    window_end: str,
    platform: DeploymentPlatformReads,
) -> list[ChangeEvent]:
    """The deploys of one application within one window, as `ChangeEvent`s.

    The window is applied here rather than asked of the platform because Argo CD,
    the one behind the port today, takes no time parameters at all - it answers
    with an application's entire revision history.

    The history itself comes from `the_revisions_deployed`, which is the same
    read without the window. Two functions rather than one with an optional
    window: a channel asking about a stretch of time and a channel asking what
    one deployment replaced are different questions, and a defaulted window is
    how the second one silently becomes the first.
    """
    window_opened = parse_iso(window_start)
    window_closed = parse_iso(window_end)

    return [
        deploy
        for deploy in the_revisions_deployed(application, platform=platform)
        if window_opened <= parse_iso(deploy.occurred_at) <= window_closed
    ]


def _a_deploy_from(record: DeploymentRecord) -> ChangeEvent:
    """`deployed_at` anchors the event: a deploy is "at" the moment it landed,
    which is the moment the symptoms could start."""
    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=record.deployed_at,
        reference=record.revision,
        summary=_what_it_shipped(record.revision, record.repo_url, record.path),
        actor=record.initiated_by,
        revision_source=(where_to_read(record.repo_url, record.revision, record.path)
                         if record.repo_url else None),
        source=(
            f"{record.repo_url}/{record.path}"
            if record.repo_url and record.path
            else record.repo_url
        ),
    )


def _what_it_shipped(revision: str, repo_url: str | None, path: str | None) -> str:
    """A deployment said as the facts that locate it: its revision, and the
    repository and directory it was synced from.

    All three are addresses rather than descriptions. The revision is what a
    later channel is asked about - what this deployment changed is answered by
    naming it - and the repository and directory are where the manifests it
    applied live, which is what a person opens. The directory alone is half an
    address, since every repository may have a `deploy/`; the repository is
    named by owner and name, which is what tells two apart, rather than by the
    whole address, which says nothing more to a reader.

    The path is not what the deployment changed, and nothing here should be read
    as saying so. An application syncs from one directory for the life of the
    application: every deployment of the shop reports `deploy`, the ones whose
    commits rewrote source code included. So the path is constant across the one
    distinction a reader of a deployment most needs - code or configuration - and
    a model asked to draw that distinction from it will draw it wrongly, which a
    paid walk duly did.

    Said rather than classified, for the reason it is said rather than
    interpreted. Which directories hold configuration is that repository's
    business and changes between them, so a `path` mapped here to "code" or
    "config" would be this channel deciding something it cannot know - and
    deciding it wrongly the first time somebody keeps their values beside their
    source.
    """
    deployed = f"deployed revision {revision}"
    repository = owner_and_name(repo_url) if repo_url else None
    directory = path.strip("/") if path else None

    if repository is None and not directory:
        return deployed
    if repository is None:
        return f"{deployed} from the {directory}/ directory"
    if not directory:
        return f"{deployed} from the {repository} repository"

    return f"{deployed} from the {repository} repository's {directory}/ directory"
