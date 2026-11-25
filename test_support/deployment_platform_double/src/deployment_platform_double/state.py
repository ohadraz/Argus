"""What a deployment platform holds before anybody asks it anything.

The seed both adapters in the port's suite are built from: the double reads it
directly, and the suite's Argo CD stand-in serves it in Argo CD's own shapes.
Every value is frozen and every collection a tuple, so a seed is the same seed
whoever holds it and however many platforms are built from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from deployment_platform import Autoscaler, AutoscalerBounds


@dataclass(frozen=True)
class HistoryEntry:
    """One deployment the platform recorded, as a `DeploymentRecord` says it -
    whose it is aside, which the platform works out from `initiated_by`."""

    history_id: int
    revision: str
    deployed_at: str
    repo_url: str | None = None
    path: str | None = None
    initiated_by: str | None = None


@dataclass(frozen=True)
class Container:
    """One container a Deployment's pods start, and whether it is run before
    the ones serving."""

    name: str
    image: str
    init: bool = False


@dataclass(frozen=True)
class Rendering:
    """What the platform renders the application's Deployment as at one
    revision: the containers its pods start."""

    revision: str
    containers: tuple[Container, ...]


@dataclass(frozen=True)
class Pod:
    """One process serving the application: the node it runs on, `None` where
    it has not been placed, and when it started."""

    name: str
    node: str | None
    started_at: datetime


@dataclass(frozen=True)
class AutoscalerState:
    """The application's autoscaler, as the platform names it, and its bounds."""

    autoscaler: Autoscaler
    bounds: AutoscalerBounds


@dataclass(frozen=True)
class ApplicationState:
    """One application as the platform holds it.

    It runs the revision of its last history entry, and its Deployment starts
    that revision's rendering - unless `running` says otherwise: the
    containers somebody set on the Deployment by hand, which a rollback's sync
    replaces with the rendering it returned to. `serving` and `updated` default
    to `replicas`, a rollout finished.
    """

    name: str
    history: tuple[HistoryEntry, ...]
    renderings: tuple[Rendering, ...]
    replicas: int
    pods: tuple[Pod, ...] = ()
    serving: int | None = None
    updated: int | None = None
    paused: bool = False
    has_failed: bool = False
    autoscaler: AutoscalerState | None = None
    accelerator_pin: str | None = None
    syncs_itself: bool = True
    running: tuple[Container, ...] | None = None


@dataclass(frozen=True)
class Node:
    """A node of the platform's, and the card it carries - `None` where it
    carries none."""

    name: str
    card: str | None = None


@dataclass(frozen=True)
class PlatformState:
    """Everything the platform holds.

    `signed_in_as` is the account the credential Argus uses belongs to, which
    the platform records on a sync Argus asks for - a rollback among them. A
    fact of the platform's, apart from whichever account Argus is configured to
    recognise as its own: the two drifting is what telling them apart is for.
    """

    applications: tuple[ApplicationState, ...]
    nodes: tuple[Node, ...] = ()
    signed_in_as: str | None = None
